"""Userbot: replies from your own Telegram account, paced like a human.

Control it by sending these from your account (they're deleted instantly; confirmations go to Saved Messages):
  .ai on / .ai off   — in a private chat: enable/disable auto-replies there
  .ai pause / resume — anywhere: stop/restart all auto-replies
  .ai pause 30m      — pause for a while (m/h/d), then resume automatically
  .ai awake 2h       — stay up: ignore the night-time sleep for that long (.ai awake 0m = back to normal)
  .ai status         — anywhere: show current state
  .ai unread         — anywhere: answer unread private messages now (also done at startup)
  .ai save <tag>     — reply to your own voice/round video in Saved Messages to add it to the clip library
  .ai forget <tag>   — remove a clip;  .ai clips — list clips
  .ai savepack       — reply to a sticker: add its whole pack to your account
  .ai salam / .ai notsalam — reply to a sticker: teach that it is / isn't an "Assalomu alaykum" sticker
  (Saved Messages only)
  .ai name <first name> / .ai surname <last name or -> / .ai bio <text or -> / .ai profile
  .ai photo          — reply to a photo with this to make it your profile photo
  .ai pfp undo       — anywhere: remove the newest profile photo (e.g. one someone asked the bot to set)
  .ai summary        — anywhere: today's digest now (it also arrives every evening)
  .ai fwd <@username or name> — reply to any message with this: forward it to that person or group
  .ai manual         — in a private chat: never answer there, just tell you someone wrote (.ai on undoes it)
  .ai today <text>   — anywhere: tell it something true about today ("сделал домашку", "на теннисе до 7");
                       it answers from that until midnight. `.ai today` alone shows what it knows.
  .ai note <text>    — in a private chat: remember something about that person
  .ai notes / .ai forgetnotes — in a private chat: show / erase what is remembered about that person
"""
import asyncio
from collections import Counter, deque
import base64
import itertools
import json
import logging
import random
import re
import time
from types import SimpleNamespace
from datetime import datetime, timedelta

import httpx
from telethon import TelegramClient, errors, events, functions
from telethon.tl.types import ReactionEmoji, User

from . import config as C
from . import daylog, judge, lang, media, memory, pfp, punct, quirks, recall, rhythm, salam, toggles, voice
from . import pilot, trace
from .autoprofile import bio_loop
from .state import State

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("userbot")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per dashboard event is just noise

TELEGRAM_SERVICE_ID = 777000  # login codes etc. — never auto-reply or send these to a model

client = TelegramClient(C.SESSION_PATH, C.API_ID, C.API_HASH)
state = State()
http = httpx.AsyncClient(base_url=C.BACKEND_URL, timeout=300)
persona = C.PERSONA_PATH.read_text()

pending: dict[int, asyncio.Task] = {}   # chat_id -> reply in progress
our_texts: dict[int, list[str]] = {}    # texts we're about to send, to recognize our own outgoing events
our_ids: set[int] = set()               # message ids sent by the userbot (vs. typed by you)
names: dict[int, str] = {}              # chat_id -> person's name, for logs
background_tasks: set[asyncio.Task] = set()
forced: set[int] = set()                # chats where you clicked "Answer now": skip hand-off / ignore / skip rules once
contacts: dict[int, User] = {}          # chat_id -> the person, for dashboard actions
me: User | None = None


revives: dict[int, int] = {}            # chat_id -> how many times in a row you tried to restart a dying chat
recent_incoming: dict[int, deque] = {}  # chat_id -> their latest messages, to notice a flood
spam_until: dict[int, float] = {}       # chat_id -> no spamming back before this time


def rand(bounds: tuple[float, float]) -> float:
    return random.uniform(*bounds)


def typing_time(text: str) -> float:
    return min(max(len(text) / rand(C.TYPING_CHARS_PER_SEC), C.TYPING_LIMITS[0]), C.TYPING_LIMITS[1])


def cancel(chat_id: int):
    task = pending.pop(chat_id, None)
    if task:
        task.cancel()


def full_name(user: User) -> str:
    return " ".join(filter(None, [user.first_name, user.last_name])) or user.username or "someone"


def label(chat_id: int) -> str:
    return names.get(chat_id, str(chat_id))


async def resolve_name(chat_id: int) -> str:
    if chat_id not in names:
        try:
            entity = await client.get_entity(chat_id)
            names[chat_id] = full_name(entity) if isinstance(entity, User) else getattr(entity, "title", str(chat_id))
        except Exception:
            return str(chat_id)
    return names[chat_id]


def describe(msg) -> str:  # noqa: C901
    text = msg.raw_text or ""
    if msg.sticker:
        media = f"[sticker {getattr(msg.file, 'emoji', '') or ''}]".replace(" ]", "]")
    elif msg.voice:
        media = "[voice message]"
    elif msg.video_note:
        media = "[round video message]"
    elif msg.gif:
        media = "[gif]"
    elif msg.video:
        media = "[video]"
    elif msg.photo:
        media = "[photo]"
    elif msg.media:
        media = "[file]"
    else:
        media = ""
    return " ".join(filter(None, [media, text]))


def to_chat_messages(history) -> list[dict]:
    """Telegram history (newest first) -> OpenAI-style messages, merging consecutive same-role messages."""
    messages: list[dict] = []
    for msg in reversed(history):
        content = describe(msg)
        if not content:
            continue
        role = "assistant" if msg.out else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + content
        else:
            messages.append({"role": role, "content": content})
    return messages


def sent_by_us(chat_id: int, msg) -> bool:
    # our_ids covers this run; state.bot_sent survives restarts
    return msg.id in our_ids or state.sent_by_bot(chat_id, msg.id)


def owner_quiet_in(chat_id: int, history) -> float:
    """Seconds until you've been silent in this chat for OWNER_ACTIVE_WINDOW (0 = you're not active)."""
    now = time.time()
    last_manual = max((m.date.timestamp() for m in history if m.out and not sent_by_us(chat_id, m)), default=0)
    return max(last_manual + C.OWNER_ACTIVE_WINDOW - now, 0)


# Last line of defense: never send something that looks like the model's reasoning or instructions.
LEAK_RE = re.compile(r"\b(the user|we need to|we must|the instruction|system prompt|as an ai|language model"
                     r"|impossible to infer|adhering to|rule \d|final check)\b"
                     r"|\{(name|contact|style|now)\}", re.I)
MAX_REPLY_CHARS = 700


COMMAND_RE = re.compile(r"(?m)^\s*\.ai\b")  # a line that this account would read as one of your commands


def looks_safe(reply: str) -> bool:
    # A text that starts with ".ai" would be executed as YOUR command the moment the account sends it, so nothing
    # written by a model or copied from another person may ever look like one.
    return (len(reply) <= MAX_REPLY_CHARS and not LEAK_RE.search(reply) and not re.search(r"@[A-Za-z]\w{3,}", reply)
            and not re.search(r"\+?\d[\d\s\-()]{7,}\d", reply)  # no phone / card / code-like numbers, ever
            and not COMMAND_RE.search(reply))


def typed_by_bot(event) -> bool:
    """An outgoing message the account sent on its own (not typed by you): never a command."""
    return (event.raw_text in our_texts.get(event.chat_id, []) or event.id in our_ids
            or bool(getattr(event.message, "fwd_from", None)))  # a forwarded ".ai …" is someone else's text


# Lines that make it sound like a customer-support bot get dropped.
ASSISTANT_RE = re.compile(
    r"\b(assist|let me know if you need|anything else|how can i help|feel free|happy to help)\b"
    r"|чем\s+(я\s+)?(могу|можно)\s+помочь|обращай(ся|тесь)|если\s+что[-\s]*то\s+нужно|буду\s+ждать,?\s+когда\s+появится"
    r"|yordam\s+bera\s+ola|qanday\s+yordam|доступ\s+к\s+просмотру"
    r"|спасибо\s+за\s+(рассказ|совет|напоминание|информаци\w+|понимание|вопрос|ответ|помощь\s+в|то,?\s+что)"
    r"|thanks?\s+for\s+(sharing|letting\s+me\s+know|the\s+(info|reminder|advice|update))|рад\s+(был\s+)?помочь|"
    r"хорошего\s+(дня|вечера)|have\s+a\s+(nice|great|good)\s+(day|night|one)", re.I)

# Questions about who or what is answering ("are you a bot?", "who are you?", "is this really you?") are ignored:
# no confirmation, no denial. Lines where the model claims to be human are dropped, so ignoring never becomes lying.
BOT_QUESTION_RE = re.compile(r"\b(bot|robot|ai|a\.i\.|chat ?gpt|gpt|neural|автоответчик|бот|робот|ии|нейросеть|"
                             r"нейронка|чатгпт)\b", re.I)
ADDRESSED_RE = re.compile(r"\?|\b(u|you|ur|you'?re|youre|r u|are|is this|ты|вы|тебя|это|sen|san|siz)\b", re.I)
WHO_RE = re.compile(
    r"\bwho\s+(are|r)\s+(you|u)\b|\bis\s+(this|that|it)\s+(really\s+|actually\s+)?(you|u)\b|\bare\s+(you|u)\s+(even\s+)?(real|human|a\s+(real\s+)?person)\b"
    r"|\bты\s+кто\b|\bкто\s+ты\b|\bэто\s+(точно\s+|правда\s+|реально\s+|вообще\s+)?ты\b|\bты\s+(настоящий|реальный|человек|живой)\b"
    r"|\b(sen\s+)?kimsan\b|\b(rostdan|haqiqatan)\s+(ham\s+)?senmi\b|\bsenmisan\b|\bodammisan\b", re.I)
# "who is this?" is only about identity when it stands alone (otherwise it's about a photo, a person, a video…)
WHO_ALONE_RE = re.compile(r"^\W*(who(['’]s|\s+is)\s+this|кто\s+это|а?\s*это\s+кто|bu\s+kim)\W*$", re.I)
IDENTITY_CLAIM_RE = re.compile(
    r"\b(i['’]?m|i\s+am|im)\s+(a\s+|an\s+)?(real|human|person|not\s+a\s+bot|no\s+bot|not\s+an?\s+ai)\b|\bnot\s+a\s+bot\b"
    r"|\bя\s+(не\s+бот|настоящий|реальный|живой|человек|не\s+ии)\b|\bне\s+бот\b|\bbot\s+emasman\b|\bodamman\b"
    r"|auto-?reply|автоответ", re.I)
# refusing out loud ("I won't answer that") sounds like a bot too — such lines are dropped
REFUSAL_RE = re.compile(
    r"не\s+буду\s+(отвечать|обсуждать|говорить)|не\s+хочу\s+(отвечать|обсуждать|вступать|говорить об этом)|без\s+комментариев"
    r"|(won'?t|not\s+going\s+to|refuse\s+to|rather\s+not)\s+(answer|say|discuss|talk)|no\s+comment|javob\s+bermayman", re.I)
# words that belong to the accusation itself ("I know you're a bot, admit it") — not something else to answer
ACCUSE_RE = re.compile(
    r"\b(знаю|признай\w*|признавай\w*|честно|правд\w*|серь[её]зно|точно|докажи\w*|скажи|колись|окей|ок|ладно|ну"
    r"|know|admit|confess|honest\w*|seriously|really|prove|tell|truth|ok|okay|bilaman|tan\s+ol|rostini|ayt)\b|\bа\s+не\s+\w+|\bnot\s+\w+", re.I)
IDENTITY_HINT = ("\nPart of their message is about who or what you are (a bot, an AI, a real person, whether it's really "
                 "you). Act as if that part wasn't written: don't confirm, don't deny, don't mention it, and don't say "
                 "that you won't answer. Reply only to the rest of what they wrote.\n")


def is_identity_question(sentence: str) -> bool:
    return bool((BOT_QUESTION_RE.search(sentence) and ADDRESSED_RE.search(sentence))
                or WHO_RE.search(sentence) or WHO_ALONE_RE.match(sentence))


def identity_question(history) -> str | None:
    """-> 'only' (nothing else was said), 'mixed' (there is also something to answer) or None."""
    found, rest_words = False, 0
    for msg in itertools.takewhile(lambda m: not m.out, history):
        if getattr(msg, "photo", None) or getattr(msg, "voice", None):
            rest_words += 3  # media counts as something to answer
        for sentence in re.split(r"(?<=[.?!,;\n])\s*", msg.raw_text or ""):
            if not sentence.strip():
                continue
            if is_identity_question(sentence):
                found = True
            else:  # count only words that say something beyond the accusation itself
                rest_words += len(re.findall(r"[^\W\d_]{2,}", ACCUSE_RE.sub(" ", sentence)))
    if not found:
        return None
    return "mixed" if rest_words >= 3 else "only"


HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]{0,40}>|\*\*|__|`")  # leftover markup: <b>, </blockquote>, **bold**
FAKE_TAG_RE = re.compile(r"\[(?!(?:sticker|gif|voice|video)\s)[^\]]*\]", re.I)  # e.g. echoed "[photo]"
REPEAT_RE = re.compile(r"(.)\1{12,}")  # "YOOOOOOOOOOOOOO…" -> capped


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\uFE0F\u200D\u2764]+")


def strip_emoji(line: str, keep_one: bool) -> str:
    """Almost no emoji: remove them all, or (rarely) keep just the first one."""
    if media.MEDIA_LINE_RE.match(line.strip()) or judge.parse_model_choice(line):
        return line  # [sticker 😂] / [react 👍] are commands, not text
    first = EMOJI_RE.search(line)
    cleaned = EMOJI_RE.sub("", line)
    if keep_one and first:
        cleaned = cleaned.rstrip() + " " + first.group(0)[0]
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def clean_reply(reply: str) -> str:
    first = (me.first_name or "").strip() if me else ""
    keep_one = random.random() < C.EMOJI_KEEP_CHANCE
    lines = []
    reply = re.sub(r"\s+/\s+|\s+⏎\s+", "\n", reply)  # the examples' line-break marker, copied into the answer
    for line in reply.splitlines():
        line = line.strip().lstrip("/|").strip()
        if ASSISTANT_RE.search(line) or IDENTITY_CLAIM_RE.search(line) or REFUSAL_RE.search(line):
            continue
        line = FAKE_TAG_RE.sub("", HTML_TAG_RE.sub("", line))
        if first:  # drop a "Name:" speaker label
            line = re.sub(rf"^\s*{re.escape(first)}\s*:\s*", "", line, flags=re.I)
        line = REPEAT_RE.sub(lambda m: m.group(1) * 8, line).strip()
        line = strip_emoji(line, keep_one)
        if line:
            lines.append(line)
    return "\n".join(lines)


MEDIA_SPLIT_RE = re.compile(r"(\[(?:sticker|gif|voice|video)\s+[^\]]+\])", re.I)


def split_reply(reply: str) -> list[str]:
    """One part per line (media tags on their own). Text beyond MAX_PARTS messages is dropped, not glued together:
    when the model emits a pile of short lines it is imitating bursts badly, and only the start makes sense."""
    parts = [p.strip() for line in reply.splitlines() for p in MEDIA_SPLIT_RE.split(line) if p.strip()]
    kept, texts = [], 0
    for p in parts:
        if media.MEDIA_LINE_RE.match(p):
            if not any(media.MEDIA_LINE_RE.match(k) for k in kept):
                kept.append(p)  # at most one media item
        elif texts < C.MAX_PARTS:
            kept.append(p)
            texts += 1
    return kept


HOLDOUT: set[str] = set()  # replies hidden from the examples (the simulator's answer key); empty in production


def holdout_key(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def visible(items: list, text_of) -> list:
    if not HOLDOUT:
        return items
    return [i for i in items if not any(holdout_key(line) in HOLDOUT for line in text_of(i).splitlines())]


def _prefer(items: list, wanted, key, count: int) -> list:
    """Up to `count` random items, taking the ones where key(item) == wanted first."""
    matching = [i for i in items if key(i) == wanted] if wanted else []
    others = [i for i in items if i not in matching]
    picks = random.sample(matching, min(count, len(matching)))
    return picks + random.sample(others, min(count - len(picks), len(others)))


def contact_style_path(contact: User):
    """Per-person style file (see import_contact.py), or None if this person has none."""
    path = C.STYLE_DIR / "contacts" / f"{(contact.username or '').lower()}.json"
    return path if contact.username and path.exists() else None


FORCE_LANG: dict[str, str] = {}  # style file -> language for the next draft (set when an Uzbek draft was rejected)


def contact_style_block(path, incoming: str) -> str:
    """Style for one specific person, built only from your real chat with them."""
    data = json.loads(path.read_text())
    data["pairs"] = visible(data["pairs"], lambda p: p["me"])
    data["examples"] = visible(data["examples"], lambda m: m)
    st, wanted = data["stats"], lang.base(lang.detect(incoming))
    turns = ", ".join(f"{k} message(s) in a row {v}%" for k, v in st.get("messages_per_turn_pct", {}).items())
    block = (
        f"You are talking to {data['name']} — someone you know very well. Write to them ONLY the way your real "
        "messages to them below show: same languages, same words and forms of address, same politeness, same "
        "length. Do not use slang, greetings or jokes that don't appear in these examples.\n"
        f"Facts from your real chat with them: languages you use (share of your messages): {st.get('languages_pct')}; "
        f"typical message is about {st['length_chars']['median']} characters; {turns}; "
        f"emoji in {st.get('with_emoji_pct', 0)}% of messages"
        + (f" (mostly {' '.join(st['top_emojis'][:5])})" if st.get("top_emojis") else "") + ".\n"
    )
    # Pick ONE reply language in code — the one you most often answer in when they write in this language —
    # and show only examples in it. Mixed-language examples make the model produce mixed-up text.
    relevant = [p for p in data["pairs"] if p.get("them_lang") == wanted and p.get("lang")] or \
               [p for p in data["pairs"] if p.get("lang")]
    # Which language do you answer in when they write like this? Not always the same one: pick with the same odds
    # as in your real chat (with your mom, Russian about as often as Uzbek) — unless one is forced for a rewrite.
    odds = Counter(p["lang"] for p in relevant if p["lang"] in ("ru", "uz", "en"))
    real = {k: v for k, v in odds.items() if k != "en" or v > sum(odds.values()) * 0.5}  # "ok"/"da" look English
    reply_lang = (FORCE_LANG.pop(str(path), None)
                  or (random.choices(list(real), weights=list(real.values()))[0] if real else wanted))
    in_lang = [m for m in data["examples"] if lang.base(lang.detect(m)) == reply_lang] or data["examples"]
    examples = random.sample(in_lang, min(C.STYLE_EXAMPLES, len(in_lang)))
    block += "\nReal messages you sent them:\n" + "\n".join(f"- {m.replace(chr(10), ' / ')}" for m in examples) + "\n"
    recalled, used = recall.block(recall.index_for((str(path), path.stat().st_mtime), data["pairs"]),
                                  incoming, C.RECALL_PAIRS)
    same = [p for p in relevant if p["lang"] == reply_lang and p not in used]
    pairs = random.sample(same, min(C.CONTACT_PAIRS, len(same)))
    if pairs:
        block += ("\nReal exchanges with them — what they wrote and what you actually answered "
                  "(copy the manner and the language choice, never the content):\n"
                  + "\n".join(f"THEM: {p['them'].replace(chr(10), ' / ')}\nYOU: {p['me'].replace(chr(10), ' / ')}"
                              for p in pairs) + "\n")
    block += recalled
    name = {"uz": "Uzbek (Latin letters, exactly the everyday forms shown above)", "ru": "Russian",
            "en": "English"}.get(reply_lang, "the language of the examples above")
    block += (f"\nLanguage note: write your whole reply in {name}. Use only words and forms that appear in your "
              "real messages above; if unsure, answer with something very short.\n")
    return block


def unsure_phrases(incoming: str) -> str:
    """Your own ways of saying "don't know yet", in the language of this conversation."""
    try:
        bank = json.loads((C.STYLE_DIR / "phrases.json").read_text())
    except (OSError, ValueError):
        bank = {}
    code = lang.base(lang.detect(incoming)) or "ru"
    phrases = bank.get(code) or {"ru": ["не знаю", "хз", "посмотрим"], "en": ["idk", "not sure"],
                                 "uz": ["bilmasam", "bilmadim"]}.get(code) or ["(say it in their language)"]
    return ", ".join(f'"{p}"' for p in phrases)


def style_stats(contact: User) -> dict:
    """Your measured habits (lengths, punctuation): with this person if they have a style file, else in general."""
    try:
        path = contact_style_path(contact)
        return json.loads(path.read_text())["stats"] if path else json.loads((C.STYLE_DIR / "stats.json").read_text())
    except (OSError, ValueError, KeyError):
        return {}


def punct_profile(contact: User) -> dict:
    return style_stats(contact).get("punct") or punct.DEFAULT


def style_block(contact_name: str = "", incoming: str = "", contact: User | None = None) -> str:
    """Learned style (see learn_style.py). Re-read every time so re-learning needs no restart."""
    path = contact_style_path(contact) if contact else None
    if path:
        return contact_style_block(path, incoming)
    profile_path = C.STYLE_DIR / "profile.md"
    examples_path, pairs_path = C.STYLE_DIR / "examples.json", C.STYLE_DIR / "pairs.json"
    if not profile_path.exists():
        return ""
    code = lang.detect(incoming)
    wanted = lang.base(code)
    block = f"How {full_name(me)} texts — follow this closely, it matters more than the generic rules above:\n"
    block += profile_path.read_text().strip() + "\n"
    if examples_path.exists():
        examples = visible(json.loads(examples_path.read_text()), lambda m: m)
        # Mostly messages in the language of this conversation, so the right register gets copied.
        picks = _prefer(examples, wanted, lambda m: lang.base(lang.detect(m)), C.STYLE_EXAMPLES)
        block += ("\nReal messages they've sent (for style only — don't reuse their content):\n"
                  + "\n".join(f"- {m.replace(chr(10), ' / ')}" for m in picks) + "\n")
    if pairs_path.exists():
        pairs = visible(json.loads(pairs_path.read_text()), lambda p: p["me"])
        recalled, used = recall.block(recall.index_for((str(pairs_path), pairs_path.stat().st_mtime), pairs),
                                      incoming, C.RECALL_PAIRS)
        rest = [p for p in pairs if p not in used]
        picks = _prefer(rest, wanted, lambda p: lang.base(p.get("lang")), C.STYLE_PAIRS)
        if picks:
            block += ("\nReal exchanges — what someone wrote and what they actually answered "
                      "(copy the manner, never the content):\n"
                      + "\n".join(f"THEM: {p['them'].replace(chr(10), ' / ')}\nYOU: {p['me'].replace(chr(10), ' / ')}"
                                  for p in picks) + "\n")
        block += recalled
    if code:
        block += (f"\nLanguage note: their latest message is in {lang.NAMES[code]}. Write your whole reply in "
                  "that language and script.\n")
    return block


PHOTO_HINT = ("\nThe other person sent you photo(s) — they are attached to their last message and you can see "
              "them. React to what is actually in the picture (name something specific you see), in your usual "
              "short style. Never repeat their own words back to them.\n")


async def attach_photos(history, messages: list[dict]) -> int:
    """Give the model the newest photos the other person sent since your last message. Returns how many."""
    photos = []
    for msg in history:  # newest first
        if msg.out:
            break
        if msg.photo:
            photos.append(msg)
    parts = [{"type": "text", "text": messages[-1]["content"]}]
    for msg in reversed(photos[:C.MAX_IMAGES]):
        try:
            data = await msg.download_media(file=bytes)
        except Exception:
            log.exception("Could not download photo")
            continue
        if data and len(data) <= 4_000_000:
            parts.append({"type": "image_url",
                          "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()}})
    if len(parts) > 1:
        messages[-1]["content"] = parts
        log.info("Attached %d photo(s) for the model", len(parts) - 1)
    return len(parts) - 1


async def generate(history, contact: User, extra: str = "") -> str | None:
    messages = to_chat_messages(history)
    if not messages or messages[-1]["role"] != "user":
        return ""  # nothing to answer (None means the backend failed)
    photos = await attach_photos(history, messages) if C.VISION else 0
    incoming = " ".join(m.raw_text for m in itertools.takewhile(lambda m: not m.out, history) if m.raw_text)
    if len(incoming.split()) < 3:  # "ok", an emoji, a photo: go by how this person has been writing lately
        incoming = " ".join([m.raw_text for m in history if not m.out and m.raw_text][:8])
    system = persona.format(name=me.first_name or full_name(me), contact=full_name(contact),
                            style=style_block(full_name(contact), incoming, contact),
                            now=datetime.now().strftime("%A %d %B %Y, %H:%M"),
                            status=rhythm.status())
    if not contact_style_path(contact):
        system += media.media_block(full_name(me))
    if photos:
        system += PHOTO_HINT
    system += memory.facts_block(full_name(me)) + memory.notes_block(contact.id, full_name(contact))
    if C.SMART_SKIP:
        system += judge.REACT_HINT
    system += extra  # what just happened outside the conversation (e.g. a profile photo change)
    try:
        body = {"messages": messages, "system": system, "max_tokens": 200, "temperature": C.TEMPERATURE,
                "models": C.PHOTO_MODELS if photos else C.MODELS}
        if not photos:
            body["hedge_after"] = C.HEDGE_AFTER  # the second model joins if the first is slow or rate-limited
        resp = await http.post("/complete", json=body)
    except httpx.HTTPError as e:
        log.warning("Backend unreachable: %r", e)
        return None
    if resp.is_error:
        log.warning("Backend error %s: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    log.info("Reply generated by %s", data["model"])
    trace.emit("decision", full_name(contact),
               f"Model used: {data['model']}" + (f" — looked at {photos} photo(s)" if photos else ""))
    return data["reply"]


# formal Russian, the way a teacher or an official writes (family members have their own style files)
TEACHER_RE = re.compile(r"здравствуйте|\bвы\b|\bвас\b|\bвам\b|\bваш\w*|\b(зайдите|подойдите|передайте|принесите|сдайте|"
                        r"напишите|ответьте|сообщите)\b", re.I)


# what people actually tap a reaction on: laughs, good news, congratulations, compliments, emoji-heavy messages
REACTABLE_RE = re.compile(r"аха|хаха|лол|\blol\b|lmao|ура|поздрав|молодец|красав|круто|класс|супер|выиграл|получил|сдал|"
                          r"\b(nice|congrats|won|yay|let'?s go)\b|zo'?r|tabrik|[\U0001F600-\U0001F64F\U0001F389\U0001F525\u2764]", re.I)


def spawn(coro):
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def remember_later(chat_id: int, who: str, their_messages: list[str]):
    try:
        for note in await memory.remember(http, chat_id, who, their_messages):
            log.info("%s: remembered %r", who, note)
            daylog.record("note", who, note)
            trace.emit("decision", who, f"Noted for later: {note}")
    except Exception:
        log.exception("%s: remembering failed", who)


async def hold_draft(draft_id: str, hold: float) -> tuple[str, list[str] | None]:
    """Keep the draft on the dashboard for `hold` seconds — or, in approve mode, until you decide.

    -> ("send", edited parts or None) | ("cancelled", None) | ("expired", None)"""
    started = time.monotonic()
    while True:
        st = await trace.draft_state(draft_id)
        if st.get("cancelled"):
            return "cancelled", None
        if st.get("send_now"):
            return "send", st.get("parts")
        waiting_for_you = state.approve or st.get("editing")  # you're deciding: don't send on a timer
        if time.monotonic() - started >= (C.APPROVE_TIMEOUT if waiting_for_you else hold):
            return ("expired", None) if waiting_for_you else ("send", st.get("parts"))
        await asyncio.sleep(0.4)


def pacing_on() -> bool:
    return C.PACING and bool(C.TYPING_LIMITS[1])  # the dashboard switch, and USERBOT_HUMAN_PACING


async def type_like_a_person(chat_id: int, text: str) -> float:
    """Show "typing…" for as long as this text would take — at a speed that varies, sometimes with a pause."""
    if not pacing_on():
        return 0
    plan = rhythm.typing_plan(text)
    for typing, pause in plan:
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(typing)
        if pause:
            await asyncio.sleep(pause)  # stopped typing for a moment
    return sum(a + b for a, b in plan)


async def no_text_reply(chat_id: int, who: str, action: str, history):
    """An acknowledgement doesn't need words: leave it, or put a reaction on their message."""
    if action == "skip":
        log.info("%s: no reply needed", who)
        daylog.record("skipped", who)
        trace.emit("decision", who, "Their message doesn't need a reply — leaving it")
        return
    emoji = action.split(":", 1)[1]
    target = next((m for m in history if not m.out), None)
    if not target:
        return
    await asyncio.sleep(rhythm.reading_seconds(history) + random.uniform(0.5, 2.5) if pacing_on() else 0)
    try:
        await client(functions.messages.SendReactionRequest(peer=chat_id, msg_id=target.id,
                                                            reaction=[ReactionEmoji(emoticon=emoji)]))
    except errors.RPCError as e:
        log.info("%s: reaction not possible (%s)", who, e.__class__.__name__)
        trace.emit("decision", who, "No reply needed (a reaction wasn't possible here) — leaving it")
        return
    log.info("%s: reacted %s", who, emoji)
    daylog.record("reacted", who, emoji)
    rhythm.online_for_a_bit(client)
    trace.emit("sent", who, f"[reaction {emoji}] instead of a text reply")


def stale_parts(history, parts: list[str]) -> list[str]:
    """Lines of a draft that were already said in this chat: by you (the model copies its own earlier
    messages from the history and gets stuck on them) or just now by them (parroting)."""
    recent = [m.raw_text for m in history if m.raw_text][:C.REPEAT_LOOKBACK]
    said = {judge._norm(t) for t in recent} | {judge._norm(line) for t in recent for line in t.splitlines()}
    return [p for p in parts if not media.MEDIA_LINE_RE.match(p)
            and len(judge._norm(p).split()) >= 2 and judge._norm(p) in said]


async def reply_flow(chat_id: int, contact: User):
    global me
    who = names[chat_id] = full_name(contact)
    contacts[chat_id] = contact
    force = chat_id in forced  # you clicked "Answer now": answer even what would be handed off, ignored or skipped
    forced.discard(chat_id)
    draft_id, history, failed = None, None, False
    try:
        me = await client.get_me()  # profile may have been changed from outside (userbot.profile)
        wait = rhythm.wait_seconds(chat_id)
        if wait > 30:
            trace.emit("decision", who, ("At school — " if rhythm.busy() else "Not on the phone right now — ")
                       + f"will look at this in about {wait / 60:.0f} min")
        await asyncio.sleep(wait + rand(C.DEBOUNCE) + rand(C.READ_DELAY))

        # If you've been chatting here yourself, hold off until you've gone quiet, then re-check.
        # (Your own new message in the chat cancels this task entirely.)
        while True:
            history = await client.get_messages(chat_id, limit=C.CONTEXT_MESSAGES)
            wait = owner_quiet_in(chat_id, history)
            if not wait:
                break
            log.info("%s: you're active here, holding off %.0fs", who, wait)
            trace.emit("decision", who, f"You wrote in this chat recently — holding off {wait:.0f}s so I don't interrupt")
            await asyncio.sleep(wait + rand(C.READ_DELAY))
        # Listen to voice / round-video messages: from here on their transcript counts as the message text.
        heard = 0
        for msg in itertools.takewhile(lambda m: not m.out, history):
            if (msg.voice or msg.video_note) and not msg.raw_text:
                spoken = await voice.transcript(msg)
                if spoken:
                    msg.message = spoken
                    heard += 1
        if heard:
            trace.emit("decision", who, f"Listened to {heard} voice message(s)")
        their_text = "\n".join(m.raw_text for m in reversed(list(itertools.takewhile(lambda m: not m.out, history)))
                               if m.raw_text)

        # Questions about who/what is answering are simply ignored — they are not a reason to hand the chat over.
        identity = None if force else identity_question(history)
        reason = (await judge.sensitive_reason(http, full_name(me), history, keywords_only=identity is not None)
                  if C.HANDOFF and not force else None)
        if not reason and chat_id in state.manual and not force:
            reason = "this chat is set to manual (.ai on to change)"
        if not reason and C.HANDOFF and not force and not contact_style_path(contact) \
                and TEACHER_RE.search(their_text) and not judge.closer_action(history):
            reason = "a formal message (teacher / official) — better answered by you"
        if reason:  # this one is yours: don't answer, don't even mark it read
            state.hand_off(chat_id, C.HANDOFF_HOLD)
            snippet = " / ".join(m.raw_text for m in reversed(list(itertools.takewhile(lambda m: not m.out, history)))
                                 if m.raw_text)[:300]
            log.info("%s: handed to owner (%s)", who, reason)
            daylog.record("handoff", who, f"{reason}: {snippet}")
            trace.emit("warning", who, f"Leaving this one to you ({reason}) — not replying, staying out for "
                                       f"{C.HANDOFF_HOLD // 60} min or until you answer")
            await client.send_message("me", f"🚨 {who} needs YOU — {reason}.\n“{snippet}”\n"
                                            f"I'm not replying and I'll stay out of that chat for "
                                            f"{C.HANDOFF_HOLD // 60} min (or until you write there).")
            return
        await client.send_read_acknowledge(chat_id)
        opened_at = time.monotonic()  # the moment the chat was opened; reading and thinking count from here
        await asyncio.sleep(rand(C.THINK_DELAY))

        hint = ""
        photo_msg = await pfp.find_request(history) if C.PFP_FROM_CHATS else None
        if photo_msg:
            trace.emit("decision", who, "They asked me to use their photo as the profile picture — checking it")
            outcome = await pfp.apply(client, state, http, photo_msg, who)
            trace.emit("system" if outcome == "changed" else "warning", who, {
                "changed": "Profile photo changed to the one they sent (undo: .ai pfp undo)",
                "limit": "Not changing the profile photo — it was changed too recently (rate limit)",
                "unsafe": "Not using that photo — the safety look didn't clear it",
                "error": "Couldn't change the profile photo (download/upload failed)"}[outcome])
            log.info("%s: profile photo request -> %s", who, outcome)
            if outcome == "changed":
                daylog.record("profile", who, f"photo changed on {who}'s request")
            hint = pfp.HINTS[outcome]

        greeting = await salam.check(client, state, http, history)
        if greeting.sticker:  # a salam sticker is answered with the very same sticker
            trace.emit("decision", who, "They sent an 'Assalomu alaykum' sticker → answering with the same sticker")
            await asyncio.sleep(random.uniform(1.5, 4) if pacing_on() else 0)
            our_texts.setdefault(chat_id, []).append("")
            sent = await client.send_file(chat_id, greeting.sticker.media)
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
            trace.emit("sent", who, "[the same salam sticker]")
            log.info("%s: answered salam sticker with the same sticker", who)
            try:
                pack = await salam.save_pack(client, greeting.sticker)
                if pack:
                    trace.emit("decision", who, f"Saved sticker pack '{pack}' to the account")
            except Exception:
                log.exception("Could not save sticker pack")
            if not greeting.rest:
                return

        # Dry answers in a live conversation: come up with a topic instead of a 👍 (a couple of tries, then let it go)
        is_dry = judge.dry(history)
        ours = next((m for m in history if m.out), None)
        keep_going = (C.KEEP_TALKING and is_dry and not force and not greeting.reply and not greeting.sticker
                      and not photo_msg and identity is None and not quirks.is_formal(history)
                      and ours is not None and time.time() - ours.date.timestamp() <= C.REVIVE_WINDOW
                      and revives.get(chat_id, 0) < C.REVIVE_MAX)
        if not is_dry:
            revives.pop(chat_id, None)
        if keep_going:
            revives[chat_id] = revives.get(chat_id, 0) + 1
            now = time.localtime()
            hint += judge.KEEP_GOING_HINT.format(clock=time.strftime("%H:%M", now), weekday=time.strftime("%A", now))
            trace.emit("decision", who, f"Dry answer — keeping the chat going with a question or a topic "
                                        f"(try {revives[chat_id]}/{C.REVIVE_MAX})")

        action = (judge.closer_action(history)
                  if C.SMART_SKIP and not force and not greeting.reply and not greeting.sticker and not photo_msg
                  and not keep_going else None)
        if action and quirks.is_formal(history) and re.search(r"до\s+свидания|всего\s+доброго|xayr", their_text, re.I):
            our_texts.setdefault(chat_id, []).append("До свидания")
            sent = await client.send_message(chat_id, "До свидания")
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
            trace.emit("sent", who, "До свидания")
            daylog.record("replied", who, "До свидания", them=their_text[:200])
            return
        if action:
            await no_text_reply(chat_id, who, action, history)
            return

        from_model = False
        if greeting.reply and not greeting.rest:
            reply = greeting.reply  # fixed text, never written by the model
            trace.emit("decision", who, "They wrote the salam greeting → sending the fixed proper answer (model not used)")
        elif identity == "only":
            log.info("%s: identity question ignored", who)
            daylog.record("ignored", who, their_text)
            trace.emit("decision", who, "They asked who/what is answering — ignoring it, no reply")
            return
        else:
            if identity == "mixed":
                trace.emit("decision", who, "Their message also asks who/what is answering — ignoring that part")
                hint += IDENTITY_HINT
            trace.emit("decision", who, "Read the chat — writing a reply")
            from_model = True
            for attempt in range(C.GENERATE_RETRIES + 1):
                if attempt:  # every model failed — come back later, like a busy person would
                    delay = rand(C.RETRY_DELAY)
                    log.info("%s: models unavailable, retrying in %.0fs (%d/%d)", who, delay, attempt, C.GENERATE_RETRIES)
                    trace.emit("warning", who, f"No model answered — trying again in {delay:.0f}s "
                                               f"(attempt {attempt}/{C.GENERATE_RETRIES})")
                    await asyncio.sleep(delay)
                reply = await generate(history, contact, hint)
                if reply is not None:
                    break
            else:
                log.warning("%s: giving up, no model answered", who)
                trace.emit("warning", who, "Giving up — no model answered")
            action = judge.parse_model_choice(reply or "") if C.SMART_SKIP and not greeting.reply else None
            if action:  # the model decided this needs no text
                await no_text_reply(chat_id, who, action, history)
                return
            reply = clean_reply(reply or "")
            if greeting.reply:  # salam + something else: fixed greeting first, then the model's answer
                rest = salam.strip_greeting_line(reply)
                rest = "\n".join(salam.TAIL_RE.sub(" ", salam.SALAM_RE.sub(" ", ln)).strip(" ,.!") if salam.SALAM_RE.search(ln)
                                 else ln for ln in rest.splitlines())
                reply = (greeting.reply + "\n" + rest).strip()
        if not reply:
            trace.emit("decision", who, "Nothing to send — staying quiet")
            return
        if not looks_safe(reply):
            log.warning("%s: blocked suspicious reply (%d chars): %r — retrying once", who, len(reply), reply[:200])
            trace.emit("warning", who, f"Blocked a suspicious draft ({len(reply)} chars), writing another: {reply[:160]}")
            reply = clean_reply(await generate(history, contact, hint) or "")
            if not reply or not looks_safe(reply):
                log.warning("%s: second reply also unusable, staying quiet", who)
                trace.emit("warning", who, "Second draft was unusable too — staying quiet")
                return

        allow_media = C.MEDIA_ENABLED and not contact_style_path(contact)
        parts = [p for p in split_reply(reply) if allow_media or not media.MEDIA_LINE_RE.match(p)]
        formal = quirks.is_formal(history)
        fixed = greeting.reply if greeting.reply else None  # the fixed salam line is never rewritten
        if from_model:
            # It must not agree to plans or claim what you did or didn't do: rewrite once, then use a neutral phrase.
            said = " ".join(p for p in parts if p != fixed and not media.MEDIA_LINE_RE.match(p))
            over = judge.overreach(their_text, said, memory.today_note())
            if over:
                trace.emit("decision", who, f"Draft made a {over} I can't back up (“{said[:60]}”) — rewriting")
                again = clean_reply(await generate(history, contact, hint + (
                    "\nYour draft agreed to a plan or promised something. You don't know yet whether you can — say so, "
                    "briefly, without agreeing.\n" if over == "commitment" else
                    "\nYour draft said yes or no about something you did today, but you don't know that. Don't answer "
                    "yes or no — put it off briefly.\n")) or "")
                again_parts = [p for p in split_reply(again) if allow_media or not media.MEDIA_LINE_RE.match(p)]
                again_said = " ".join(p for p in again_parts if not media.MEDIA_LINE_RE.match(p))
                if again_said and looks_safe(again) and not judge.overreach(their_text, again_said, memory.today_note()):
                    reply, parts = again, ([fixed] if fixed else []) + again_parts
                else:
                    neutral = judge.dodge(over, lang.base(lang.detect(their_text)))
                    reply, parts = neutral, ([fixed] if fixed else []) + [neutral]
            parts = [p if media.MEDIA_LINE_RE.match(p) or p == fixed else quirks.fix_greeting(p, their_text, formal) if i == 0 else p
                     for i, p in enumerate(parts)]
            # Saying the exact same thing as a moment ago is what bots do: ask for a different wording once.
            recent_own = {re.sub(r"[\W_]+", " ", (m.raw_text or "").lower()).strip() for m in history[:8] if m.out}
            said = re.sub(r"[\W_]+", " ", " ".join(parts).lower()).strip()
            if said and said in recent_own and len(said.split()) >= 2:
                trace.emit("decision", who, "Same wording as a moment ago — rewriting it differently")
                again = clean_reply(await generate(history, contact, hint + (
                    f"\nYou already wrote exactly “{' '.join(parts)}” a moment ago. Answer what they said now, "
                    "in different words.\n")) or "")
                if again and looks_safe(again):
                    reply = again
                    parts = [p for p in split_reply(reply) if allow_media or not media.MEDIA_LINE_RE.match(p)]
        if from_model:
            # You text short. A rambling draft is rewritten once, then cut down if it's still too long.
            limit, max_parts = quirks.length_limits(style_stats(contact), their_text)
            text_parts = [p for p in parts if not media.MEDIA_LINE_RE.match(p)]
            if any(len(p) > limit for p in text_parts) or len(text_parts) > max_parts + 1:
                trace.emit("decision", who, f"Draft too long ({max(map(len, text_parts))} chars) — rewriting it shorter")
                words = max(4, limit // 7)
                shorter = clean_reply(await generate(history, contact, hint + (
                    f"\nYour draft was far too long. You text in very short messages: answer in at most {words} "
                    "words, one message, no explanations and no story.\n")) or "")
                if shorter and looks_safe(shorter):
                    reply = shorter
                    parts = [p for p in split_reply(reply) if allow_media or not media.MEDIA_LINE_RE.match(p)]
                text_seen, kept = 0, []
                for p in parts:  # whatever is left: at most max_parts short messages
                    if media.MEDIA_LINE_RE.match(p):
                        kept.append(p)
                    elif text_seen < max_parts:
                        kept.append(quirks.shorten(p, limit))
                        text_seen += 1
                parts = kept
            # the model punctuates like a textbook; you don't
            habits = punct_profile(contact)
            parts = [p if media.MEDIA_LINE_RE.match(p) or p == fixed else punct.apply(p, habits) for p in parts]
            parts = [p for p in parts if p]
        if not parts:
            return

        # Never the same line again: a draft that repeats what was already said gets rewritten, then trimmed.
        stale = stale_parts(history, [p for p in parts if p != fixed]) if from_model else []
        if stale:
            log.info("%s: draft repeats earlier messages: %r", who, stale)
            trace.emit("warning", who, "Draft repeats what was already said (" + " / ".join(stale)[:120] + ") — rewriting")
            again = clean_reply(await generate(history, contact, hint + (
                "\nYou have ALREADY sent these exact lines in this chat: " + " | ".join(f"“{p}”" for p in stale) +
                ". Do not write them again, and do not copy any of your earlier messages or theirs. React to what "
                "they just wrote with different words.\n")) or "")
            habits = punct_profile(contact)
            fresh = [p if media.MEDIA_LINE_RE.match(p) else punct.apply(p, habits)
                     for p in split_reply(again) if allow_media or not media.MEDIA_LINE_RE.match(p)] if looks_safe(again) else []
            fresh = [p for p in fresh if p and p not in stale_parts(history, fresh)]
            parts = ([fixed] if fixed else []) + (fresh or [p for p in parts if p != fixed and p not in stale])
            reply = "\n".join(parts)
            if not parts:
                trace.emit("decision", who, "Nothing new to say — not sending the same line again")
                daylog.record("skipped", who)
                return

        # A second look before anything is sent: wrong language, nonsense words, a missed question…
        if C.REVIEW and from_model:
            expected = "the language these two normally use with each other" if contact_style_path(contact) else None
            problem = await judge.review(http, their_text, "\n".join(parts), expected)
            if problem and problem.startswith("Uzbek word") and contact_style_path(contact):
                FORCE_LANG[str(contact_style_path(contact))] = "ru"  # the model's Uzbek failed: answer in Russian
            if problem:
                log.info("%s: draft rejected (%s): %r", who, problem, reply[:120])
                trace.emit("warning", who, f"Second look rejected the draft ({problem}) — rewriting: {reply[:140]}")
                retry_hint = hint + f"\nYour previous draft was rejected: {problem}. Write a better, simpler reply.\n"
                if problem.startswith(("Uzbek word", "wrong language (uz")):
                    retry_hint += "Write this reply in Russian.\n"
                reply = clean_reply(await generate(history, contact, retry_hint) or "")
                parts = [p if media.MEDIA_LINE_RE.match(p) else punct.apply(p, habits)
                         for p in split_reply(reply) if allow_media or not media.MEDIA_LINE_RE.match(p)]
                problem = (await judge.review(http, their_text, "\n".join(parts), expected)
                           if parts and looks_safe(reply) else "no usable second draft")
                if problem:
                    log.warning("%s: second draft rejected too (%s) — leaving it to the owner", who, problem)
                    trace.emit("warning", who, f"Couldn't write a good reply ({problem}) — leaving this one to you")
                    daylog.record("failed", who, their_text)
                    await client.send_message("me", f"🤷 I couldn't write a good reply to {who} ({problem}).\n"
                                                    f"“{their_text[:300]}”\nThat one is yours.")
                    return

        # Show the draft on the dashboard for a moment; Cancel there stops it.
        draft_id = trace.new_draft_id()
        if pacing_on():
            # How long a person would take before starting to type: read what came in, then think —
            # barely at all for "ок", noticeably for a calculation or a decision.
            read = rhythm.reading_seconds(history)
            think = rhythm.thinking_seconds(their_text, "\n".join(parts), chat_id) if from_model else random.uniform(0.5, 2)
            hold = max(read + think - (time.monotonic() - opened_at), C.MIN_HOLD)
            trace.emit("decision", who, f"Reading ~{read:.0f}s, thinking ~{think:.0f}s before typing")
        else:
            hold = 0
        trace.emit("draft", who, "\n".join(parts), draft_id=draft_id, parts=parts, hold=hold, approve=state.approve)
        verdict, edited = await hold_draft(draft_id, hold)
        if verdict == "cancelled":
            log.info("%s: draft cancelled from the dashboard", who)
            trace.emit("cancelled", who, "You cancelled this draft on the dashboard", draft_id=draft_id)
            return
        if verdict == "expired":
            log.info("%s: draft not approved in time, dropped", who)
            trace.emit("cancelled", who, f"Nobody approved this draft within {C.APPROVE_TIMEOUT // 60} min — dropped",
                       draft_id=draft_id)
            failed = True  # still unanswered: it stays yours
            return
        if edited:  # you rewrote it on the dashboard: send exactly that
            parts, from_model = edited, False
            trace.emit("decision", who, "Sending your edited version", draft_id=draft_id)

        quote = quirks.reply_target(history)          # swipe-reply to a specific message when that's natural
        slips = from_model and not quirks.is_formal(history)  # typos only in casual chats, never in fixed replies
        sent_count = 0
        for i, part in enumerate(parts):
            if await trace.draft_cancelled(draft_id):
                log.info("%s: draft cancelled from the dashboard", who)
                trace.emit("cancelled", who, "You cancelled this draft on the dashboard", draft_id=draft_id)
                return
            if i:
                await asyncio.sleep(rand(C.BETWEEN_MESSAGES))
            media_line = media.MEDIA_LINE_RE.match(part)
            if media_line:
                kind, arg = media_line.groups()
                action = {"voice": "record-audio", "video": "record-round"}.get(kind.lower(), "typing")
                trace.emit("decision", who, f"Picking {kind.lower()}: {arg}", draft_id=draft_id, phase="typing", index=i)
                if C.TYPING_LIMITS[1]:  # human pacing: "record" / "choose" for a moment
                    async with client.action(chat_id, action):
                        await asyncio.sleep(rand((2, 5)))
                our_texts.setdefault(chat_id, []).append("")  # media has no text; recognize our own send
                try:
                    sent = await media.send_media_line(client, chat_id, kind, arg)
                except Exception:
                    log.exception("%s: failed to send %s %r", who, kind, arg)
                    sent = None
                if not sent:
                    our_texts[chat_id].remove("")
                    trace.emit("warning", who, f"Couldn't find a {kind.lower()} for '{arg}' — skipped", draft_id=draft_id)
                    continue
                log.info("%s: sent %s %s", who, kind, arg)
            else:
                trace.emit("decision", who, "Typing…", draft_id=draft_id, phase="typing", index=i)
                await type_like_a_person(chat_id, part)
                slip = quirks.typo(part) if slips else None
                text = slip[0] if slip else part
                our_texts.setdefault(chat_id, []).append(text)
                sent = await client.send_message(chat_id, text, reply_to=quote.id if quote else None)
                quote = None  # only the first message quotes
                if slip:  # notice the typo a moment later and fix it, by editing or with a "*word"
                    await asyncio.sleep(rand((1.5, 4)))
                    if random.random() < 0.5:
                        await client.edit_message(chat_id, sent.id, part)
                        trace.emit("decision", who, f"Sent it with a typo ('{slip[1]}'), then edited the message")
                    else:
                        fix = "*" + slip[1]
                        our_texts[chat_id].append(fix)
                        fixed = await client.send_message(chat_id, fix)
                        our_ids.add(fixed.id)
                        state.record_sent(chat_id, fixed.id)
                        trace.emit("sent", who, fix)
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
            sent_count += 1
            trace.emit("sent", who, part, draft_id=draft_id, index=i)
        trace.emit("decision", who, f"Done — {sent_count} message(s) sent", draft_id=draft_id, final=True)
        rhythm.replied(chat_id)
        rhythm.online_for_a_bit(client)
        if sent_count:
            daylog.record("replied", who, " / ".join(parts), them=their_text[:200])
        target = next((m for m in history if not m.out), None)
        worth_it = bool(target) and "?" not in (target.raw_text or "") and (
            getattr(target, "photo", None) or REACTABLE_RE.search(target.raw_text or ""))
        if sent_count and from_model and not formal and worth_it and random.random() < C.EXTRA_REACTION_CHANCE:
            if target:  # people also just tap a reaction on a photo, a joke, good news
                emoji = "❤" if getattr(target, "photo", None) or random.random() < 0.3 else "👍"
                try:
                    await client(functions.messages.SendReactionRequest(peer=chat_id, msg_id=target.id,
                                                                        reaction=[ReactionEmoji(emoticon=emoji)]))
                    trace.emit("sent", who, f"[reaction {emoji}] on their message")
                except errors.RPCError:
                    pass
        if C.REMEMBER:
            theirs = [m.raw_text for m in itertools.takewhile(lambda m: not m.out, history) if m.raw_text]
            spawn(remember_later(chat_id, who, theirs[::-1]))
        log.info("%s: replied (%d chars)", who, len(reply))
    except asyncio.CancelledError:
        log.info("%s: reply cancelled", who)
        failed = True  # not dealt with: a newer run (or you) takes over
        trace.emit("cancelled", who, "Dropped this reply — a new message arrived or you answered yourself",
                   draft_id=draft_id)
        raise
    except Exception:
        failed = True  # leave it unhandled so the periodic re-scan tries again
        log.exception("%s: reply failed", who)
        trace.emit("warning", who, "Reply failed with an error (see userbot log)", draft_id=draft_id, final=True)
    finally:
        spawn(push_history(chat_id))
        if history and not failed:  # answered, reacted, skipped or handed to you: don't pick it up again
            state.mark_handled(chat_id, history[0].id)
        if pending.get(chat_id) is asyncio.current_task():
            pending.pop(chat_id)


@client.on(events.NewMessage(outgoing=True, pattern=r"^\.ai(?:\s+(\w+))?(?:\s+(@?[\w.-]+))?\s*$"))
async def on_command(event):
    if typed_by_bot(event):
        return
    arg = (event.pattern_match.group(1) or "status").lower()
    if arg in PROFILE_COMMANDS or arg in ("note", "today", "do"):
        return  # handled by on_profile_command / on_note_command / on_today_command
    tag = (event.pattern_match.group(2) or "").lower()
    chat_id = event.chat_id
    in_saved = chat_id == me.id
    replied = await event.get_reply_message() if event.is_reply else None
    await event.delete()

    if arg == "summary":
        await client.send_message("me", daylog.summary())
        return
    if arg == "fwd":
        await client.send_message("me", await forward_command(tag, replied))
        return
    if arg in ("save", "forget", "clips"):
        await client.send_message("me", clip_command(arg, tag, replied, in_saved))
        return
    if arg in ("notes", "forgetnotes"):
        if in_saved or not event.is_private:
            note = f"⚠️ use .ai {arg} inside the private chat with that person"
        elif arg == "notes":
            items = memory.notes(chat_id)
            note = (f"🧠 notes about {await resolve_name(chat_id)}:\n" + "\n".join(f"- {n['text']} ({n['date']})" for n in items)
                    if items else f"🧠 nothing remembered about {await resolve_name(chat_id)} yet")
        else:
            note = f"🗑 erased {memory.clear_notes(chat_id)} note(s) about {await resolve_name(chat_id)}"
        await client.send_message("me", note)
        return
    if arg == "pfp":
        if tag != "undo":
            note = "⚠️ usage: .ai pfp undo"
        else:
            note = "↩️ newest profile photo removed" if await pfp.undo(client) else "⚠️ there is no profile photo to remove"
        await client.send_message("me", note)
        return
    if arg in ("savepack", "salam", "notsalam"):
        if not replied or not replied.sticker:
            note = f"⚠️ reply to a sticker with .ai {arg}"
        elif arg == "savepack":
            pack = await salam.save_pack(client, replied)
            note = f"✅ sticker pack '{pack}' added to your account" if pack else "⚠️ that sticker has no pack"
        else:
            state.remember_salam_sticker(str(replied.document.id), arg == "salam")
            note = ("✅ learned: that is an 'Assalomu alaykum' sticker — I'll answer it with the same sticker"
                    if arg == "salam" else "✅ learned: that is not a salam sticker")
        await client.send_message("me", note)
        return

    if arg in ("on", "off") and in_saved:
        note = "⚠️ use .ai on/off inside the chat or group you mean"
    elif arg == "on":
        state.enable(chat_id)
        note = "✅ auto-replies ON for {chat}"
    elif arg == "manual":
        if in_saved or not event.is_private:
            note = "⚠️ use .ai manual inside the private chat you mean"
        else:
            state.set_manual(chat_id)
            cancel(chat_id)
            note = "✋ {chat}: I won't answer there — I'll just tell you when they write (.ai on to undo)"
    elif arg == "off":
        state.disable(chat_id)
        cancel(chat_id)
        note = "⛔ auto-replies OFF for {chat}"
    elif arg == "pause":
        duration = re.fullmatch(r"(\d+)([mhd])", tag)
        seconds = int(duration.group(1)) * {"m": 60, "h": 3600, "d": 86400}[duration.group(2)] if duration else 0
        state.set_paused(True, seconds)
        for cid in list(pending):
            cancel(cid)
        note = (f"⏸ auto-replies paused for {tag} (until {datetime.fromtimestamp(state.paused_until):%H:%M %d.%m})"
                if seconds else "⏸ all auto-replies paused until .ai resume")
    elif arg == "awake":
        duration = re.fullmatch(r"(\d+)([mhd])", tag or "2h")
        seconds = int(duration.group(1)) * {"m": 60, "h": 3600, "d": 86400}[duration.group(2)] if duration else 7200
        state.awake_until = rhythm.awake_until = time.time() + seconds if seconds else 0
        state.save()
        note = (f"🌙 staying up until {datetime.fromtimestamp(state.awake_until):%H:%M} — answering as usual"
                if seconds else "😴 back to the normal sleep schedule")
        if seconds:
            spawn(reply_to_unread())
    elif arg == "resume":
        state.set_paused(False)
        note = "▶️ auto-replies resumed"
    elif arg == "unread":
        count = await reply_to_unread()
        note = f"📬 answering {count} unread chat(s)" if count else "📭 no unread private messages to answer"
    else:
        enabled = ", ".join([await resolve_name(cid) for cid in sorted(state.enabled)]) or "none"
        paused = ("yes" if state.paused else f"until {datetime.fromtimestamp(state.paused_until):%H:%M %d.%m}"
                  if state.is_paused() else "no")
        disabled = ", ".join([await resolve_name(cid) for cid in sorted(state.disabled)]) or "none"
        note = (f"🤖 mode: {C.REPLY_MODE} | paused: {paused} | "
                + (f"off in: {disabled}" if C.REPLY_MODE == "all" else f"enabled chats: {enabled}")
                + ("" if in_saved else " | this chat: {active}"))

    if "{chat}" in note or "{active}" in note:
        chat = await event.get_chat()
        note = note.format(chat=full_name(chat) if isinstance(chat, User) else chat_id,
                           active="active" if state.is_active(chat_id, C.REPLY_MODE) else "inactive")
    await client.send_message("me", note)


PROFILE_COMMANDS = {"name", "surname", "bio", "photo", "profile"}


async def send_as_bot(chat_id: int, text: str, **kwargs):
    """A text sent by the account itself (not typed by you): recorded so it isn't mistaken for you stepping in."""
    if COMMAND_RE.search(text):
        raise ValueError("a message that looks like an .ai command is never sent")
    our_texts.setdefault(chat_id, []).append(text)
    msg = await client.send_message(chat_id, text, **kwargs)
    our_ids.add(msg.id)
    state.record_sent(chat_id, msg.id)
    return msg


def set_chat_mode(chat_id: int, mode: str):
    if mode == "off":
        state.disable(chat_id)
        state.manual.discard(chat_id)
        state.save()
        cancel(chat_id)
    elif mode == "manual":
        state.set_manual(chat_id)
        cancel(chat_id)
    else:
        state.disabled.discard(chat_id)
        state.manual.discard(chat_id)
        state.save()


pilot_busy = asyncio.Lock()


async def operate(order: str, here: int | None = None):
    """An order in plain words → the account carries it out (see pilot.py); the report goes to Saved Messages."""
    async with pilot_busy:
        ctx = SimpleNamespace(client=client, http=http, state=state, me=me, send=send_as_bot, set_mode=set_chat_mode)
        try:
            report = await pilot.run(ctx, order, here)
        except Exception:
            log.exception("Pilot failed on %r", order)
            report = f"🛠 {order}\n⚠️ that failed (see the userbot log)"
            trace.emit("warning", "Pilot", "The order failed (see the userbot log)")
    await client.send_message("me", report)


@client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+do\s+(.+)$"))
async def on_do_command(event):
    """`.ai do <anything>`: operate the account in plain words. Typed in a chat, that chat is "here"."""
    if typed_by_bot(event):
        return
    order, here = event.pattern_match.group(1).strip(), event.chat_id
    await event.delete()
    spawn(operate(order, here))


@client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+today(?:\s+(.+))?$"))
async def on_today_command(event):
    """`.ai today <text>`: something true about today, so questions like "did you do your homework?" get real answers."""
    if typed_by_bot(event):
        return
    text = (event.pattern_match.group(1) or "").strip()
    await event.delete()
    if text:
        await client.send_message("me", f"📅 today: {memory.add_today(text)}")
    else:
        await client.send_message("me", f"📅 today: {memory.today_note() or 'nothing yet — tell me with .ai today <text>'}")


@client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+note\s+(.+)$"))
async def on_note_command(event):
    """`.ai note <text>` in a private chat: remember something about that person."""
    if typed_by_bot(event):
        return
    text, chat_id = event.pattern_match.group(1).strip(), event.chat_id
    await event.delete()
    if chat_id == me.id or not event.is_private:
        await client.send_message("me", "⚠️ use .ai note <text> inside the private chat with that person")
        return
    memory.add_note(chat_id, text, source="you")
    await client.send_message("me", f"🧠 noted about {await resolve_name(chat_id)}: {text}")


@client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+(name|surname|bio|photo|profile)\b\s*(.*)$"))
async def on_profile_command(event):
    """Owner commands for name / surname / bio / photo. (The only thing a chat can trigger is pfp.py.)"""
    if typed_by_bot(event):
        return
    global me
    cmd, value = event.pattern_match.group(1).lower(), event.pattern_match.group(2).strip()
    replied = await event.get_reply_message() if event.is_reply else None
    in_saved = event.chat_id == me.id
    await event.delete()
    if not in_saved:
        await client.send_message("me", "⚠️ profile commands only work here in Saved Messages")
        return
    try:
        note = await profile_command(cmd, value, replied)
    except errors.RPCError as e:
        note = f"⚠️ Telegram refused: {e.__class__.__name__}"
    me = await client.get_me()  # the persona uses your current name
    await client.send_message("me", note)


async def profile_command(cmd: str, value: str, replied) -> str:
    clear = value == "-"
    if cmd == "profile":
        full = await client(functions.users.GetFullUserRequest("me"))
        return (f"👤 name: {me.first_name or ''}\nsurname: {me.last_name or '—'}\n"
                f"bio: {full.full_user.about or '—'}")
    if cmd == "photo":
        if not replied or not replied.photo:
            return "⚠️ reply to a photo with .ai photo"
        data = await replied.download_media(file=bytes)
        await client(functions.photos.UploadProfilePhotoRequest(
            file=await client.upload_file(data, file_name="profile.jpg")))
        return "🖼 profile photo updated"
    if not value:
        return f"⚠️ usage: .ai {cmd} <text>" + ("" if cmd == "name" else "  (or - to clear)")
    if cmd == "name":
        await client(functions.account.UpdateProfileRequest(first_name=value[:64]))
        return f"✅ name → {value[:64]}"
    if cmd == "surname":
        await client(functions.account.UpdateProfileRequest(last_name="" if clear else value[:64]))
        return "✅ surname cleared" if clear else f"✅ surname → {value[:64]}"
    try:  # bio
        await client(functions.account.UpdateProfileRequest(about="" if clear else value))
    except errors.AboutTooLongError:
        return "⚠️ bio too long (70 characters max, 140 with Premium)"
    return "✅ bio cleared" if clear else f"✅ bio → {value}"


async def forward_command(target: str, replied) -> str:
    """`.ai fwd <who>` as a reply to a message: forward that message. Only you can trigger a forward."""
    if not replied or not target:
        return "⚠️ reply to a message with .ai fwd <@username or name>"
    entity = None
    if target.startswith("@"):
        try:
            entity = await client.get_entity(target)
        except Exception:
            return f"⚠️ couldn't find {target}"
    else:
        matches = [d for d in await client.get_dialogs(limit=300) if target in (d.name or "").lower()]
        if len(matches) != 1:
            names_found = ", ".join(d.name for d in matches[:6]) or "nobody"
            return f"⚠️ '{target}' matches {len(matches)} chats ({names_found}) — be more specific or use @username"
        entity = matches[0].entity
    await client.forward_messages(entity, replied)
    name = getattr(entity, "title", None) or full_name(entity)
    daylog.record("replied", name, "[forwarded a message — your command]")
    return f"↪️ forwarded to {name}"


def clip_command(arg: str, tag: str, replied, in_saved: bool) -> str:
    if arg == "clips":
        clips = media.load_clips()
        if not clips:
            return "🎙 no clips yet — record a voice/round video here and reply to it with .ai save <tag>"
        return "🎙 clips:\n" + "\n".join(f"{c['kind']}: {t}" for t, c in sorted(clips.items()))
    if not tag:
        return f"⚠️ usage: .ai {arg} <tag>"
    if arg == "forget":
        return f"🗑 removed clip '{tag}'" if media.remove_clip(tag) else f"⚠️ no clip '{tag}'"
    if not in_saved or not replied:
        return "⚠️ in Saved Messages, reply to your voice/round video with .ai save <tag>"
    kind = media.add_clip(tag, replied)
    return f"✅ saved {kind} clip '{tag}'" if kind else "⚠️ that's not a voice message or round video"


@client.on(events.NewMessage(outgoing=True))
async def on_outgoing(event):
    if event.raw_text.startswith(".ai"):
        return
    texts = our_texts.get(event.chat_id)
    if texts and event.raw_text in texts:
        texts.remove(event.raw_text)
        return
    state.clear_handoff(event.chat_id)  # you answered there yourself; normal rules apply again
    if event.is_private:
        spawn(push_history(event.chat_id))
    if event.chat_id in pending:
        log.info("%s: you replied yourself, standing down", label(event.chat_id))
        cancel(event.chat_id)


def flood_from(chat_id: int, msg) -> list:
    """Their messages of the last few seconds, if there are enough of them to call it spam."""
    burst = recent_incoming.setdefault(chat_id, deque(maxlen=C.SPAM_MAX))
    burst.append(msg)
    now = time.time()
    if not C.SPAM_BACK or state.approve or now < spam_until.get(chat_id, 0):
        return []
    fresh = [m for m in burst if now - m.date.timestamp() <= C.SPAM_WINDOW]
    return fresh if len(fresh) >= C.SPAM_TRIGGER else []


def echo_of(msg):
    """What goes back for one of their messages: the same sticker, the same short text, or a "?"."""
    if msg.sticker:
        return msg
    text = (msg.raw_text or "").strip()
    plain = not re.search(r"https?://|www\.|t\.me/|\w\.[a-z]{2,}(/|\b)", text, re.I)  # no links sent in your name
    return text if text and len(text) <= C.SPAM_ECHO_CHARS and plain and looks_safe(text) else "?"


async def spam(chat_id: int, who: str, items: list) -> int:
    """Send texts / stickers one right after another, without the usual reading and typing."""
    sent = 0
    spam_until[chat_id] = time.time() + C.SPAM_COOLDOWN
    try:
        await client.send_read_acknowledge(chat_id)
        for item in items[:C.SPAM_MAX]:
            our_texts.setdefault(chat_id, []).append(item if isinstance(item, str) else "")
            msg = (await client.send_message(chat_id, item) if isinstance(item, str)
                   else await client.send_file(chat_id, item.media))
            our_ids.add(msg.id)
            state.record_sent(chat_id, msg.id)
            sent += 1
            await asyncio.sleep(rand(C.SPAM_GAP))
    except errors.FloodWaitError as e:
        trace.emit("warning", who, f"Telegram asked to slow down for {e.seconds}s — stopped after {sent} message(s)")
    except Exception:
        log.exception("Spam to %s failed", who)
        trace.emit("warning", who, f"Could not finish — stopped after {sent} message(s)")
    finally:
        spam_until[chat_id] = time.time() + C.SPAM_COOLDOWN
    if sent:
        state.mark_handled(chat_id, (await client.get_messages(chat_id, limit=1))[0].id)
        trace.emit("sent", who, f"[{sent} messages in a row]")
        spawn(push_history(chat_id))
    return sent


@client.on(events.NewMessage(incoming=True))
async def on_incoming(event):
    if not event.is_private or time.time() - event.date.timestamp() > C.IGNORE_OLDER_THAN:
        return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot or sender.is_self or sender.id == TELEGRAM_SERVICE_ID:
        return
    who = names[event.chat_id] = full_name(sender)
    trace.emit("incoming", who, describe(event.message)[:300])
    spawn(push_history(event.chat_id))
    if not state.is_active(event.chat_id, C.REPLY_MODE):
        trace.emit("decision", who, "Not replying — auto-replies are paused" if state.is_paused()
                   else "Not replying — auto-replies are off for this chat")
        return
    if rhythm.asleep():
        trace.emit("decision", who, "Asleep — this stays unread until the morning")
        return
    if state.handed_off(event.chat_id):
        trace.emit("decision", who, "Still leaving this chat to you (handed off earlier)")
        return
    contacts[event.chat_id] = sender
    flood = flood_from(event.chat_id, event.message)
    if flood and event.chat_id not in state.manual:
        cancel(event.chat_id)
        recent_incoming.pop(event.chat_id, None)
        trace.emit("decision", who, f"{len(flood)} messages in a few seconds — spamming back")
        daylog.record("replied", who, f"[spammed back, {len(flood)} messages]", them=describe(event.message)[:100])
        spawn(spam(event.chat_id, who, [echo_of(m) for m in flood]))
        return
    cancel(event.chat_id)  # a new message restarts the wait, so bursts get one reply
    pending[event.chat_id] = asyncio.create_task(reply_flow(event.chat_id, sender))


GROUP_HINT = ("\nThis is a GROUP chat. Below is the recent conversation; lines start with who wrote them ('You' is "
              "you). {sender} just mentioned you or replied to you — answer that message only, briefly, the way you "
              "would in a group. Don't greet everyone, don't address other people, no stickers or GIFs.\n")


async def group_reply_flow(event, sender: User):
    """Someone mentioned you or replied to you in a group: answer that message, quoting it."""
    chat_id = event.chat_id
    chat = await event.get_chat()
    who = f"{full_name(sender)} @ {getattr(chat, 'title', 'group')}"
    try:
        await asyncio.sleep(rhythm.wait_seconds(chat_id) + rand(C.DEBOUNCE))
        text = event.raw_text or ""
        if identity_question([event.message]) == "only":
            trace.emit("decision", who, "They asked who/what is answering — ignoring it, no reply")
            daylog.record("ignored", who, text)
            return
        if C.HANDOFF and await judge.sensitive_reason(http, full_name(me), [event.message], keywords_only=True):
            trace.emit("warning", who, "Sensitive topic in a group — not replying")
            return
        history = await client.get_messages(chat_id, limit=C.GROUP_CONTEXT)
        lines = []
        for msg in reversed(history):
            content = describe(msg)
            if content:
                author = "You" if msg.out else (full_name(msg.sender) if isinstance(msg.sender, User) else "Someone")
                lines.append(f"{author}: {content}")
        system = persona.format(name=me.first_name or full_name(me),
                                contact=f"{full_name(sender)} (in the group “{getattr(chat, 'title', '')}”)",
                                style=style_block(full_name(sender), text),
                                now=datetime.now().strftime("%A %d %B %Y, %H:%M"),
                                status=rhythm.status())
        system += memory.facts_block(full_name(me)) + GROUP_HINT.format(sender=full_name(sender))
        if identity_question([event.message]) == "mixed":
            system += IDENTITY_HINT
        trace.emit("incoming", who, text[:300])
        trace.emit("decision", who, "Mentioned in a group — writing a reply")
        resp = await http.post("/complete", json={"messages": [{"role": "user", "content": "\n".join(lines)}],
                                                  "system": system, "models": C.MODELS, "max_tokens": 300})
        if resp.is_error:
            trace.emit("warning", who, "No model answered — staying quiet in the group")
            return
        reply = clean_reply(resp.json()["reply"])
        parts = [p for p in split_reply(reply) if not media.MEDIA_LINE_RE.match(p)]
        reply = "\n".join(parts[:2])
        if not reply or not looks_safe(reply) or (C.REVIEW and await judge.review(http, text, reply)):
            trace.emit("warning", who, f"Draft for the group wasn't good enough — staying quiet: {reply[:120]}")
            return
        draft_id = trace.new_draft_id()
        hold = max(rhythm.thinking_seconds(text, reply, chat_id), C.MIN_HOLD) if pacing_on() else 0
        trace.emit("draft", who, reply, draft_id=draft_id, parts=[reply], hold=hold, approve=state.approve)
        verdict, edited = await hold_draft(draft_id, hold)
        if verdict != "send":
            trace.emit("cancelled", who, "Draft cancelled or not approved", draft_id=draft_id)
            return
        if edited:
            reply = "\n".join(edited)
        trace.emit("decision", who, "Typing…", draft_id=draft_id, phase="typing", index=0)
        await type_like_a_person(chat_id, reply)
        our_texts.setdefault(chat_id, []).append(reply)
        sent = await client.send_message(chat_id, reply, reply_to=event.id)
        our_ids.add(sent.id)
        trace.emit("sent", who, reply, draft_id=draft_id, index=0, final=True)
        log.info("%s: replied in group (%d chars)", who, len(reply))
        daylog.record("replied", who, reply, them=text[:200])
        rhythm.replied(chat_id)
        rhythm.online_for_a_bit(client)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("%s: group reply failed", who)
    finally:
        if pending.get(chat_id) is asyncio.current_task():
            pending.pop(chat_id)


@client.on(events.NewMessage(incoming=True))
async def on_group_mention(event):
    """Groups: only when someone @mentions you or replies to one of your messages."""
    if not C.GROUPS or not event.is_group or not event.mentioned:
        return
    if time.time() - event.date.timestamp() > C.IGNORE_OLDER_THAN or rhythm.asleep():
        return
    if state.is_paused() or event.chat_id in state.disabled:
        return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot:
        return
    cancel(event.chat_id)
    pending[event.chat_id] = asyncio.create_task(group_reply_flow(event, sender))


async def push_history(chat_id: int):
    """Send the dashboard the recent conversation with this person (for the dialog view)."""
    try:
        messages = await client.get_messages(chat_id, limit=C.DASHBOARD_HISTORY)
        await trace.report_history(label(chat_id), [
            {"id": m.id, "out": bool(m.out), "bot": bool(m.out and sent_by_us(chat_id, m)),
             "text": describe(m) or "[message]", "ts": m.date.timestamp()} for m in reversed(messages)])
    except Exception:
        log.debug("Could not push history for %s", chat_id, exc_info=True)


def chat_by_name(name: str) -> int | None:
    return next((cid for cid, n in names.items() if n == name), None)


async def run_command(cmd: dict):
    """Something you clicked on the dashboard."""
    kind, name = cmd.get("type"), cmd.get("chat", "")
    chat_id = chat_by_name(name) if name else None
    if kind == "pause":
        state.set_paused(True)
        for cid in list(pending):
            cancel(cid)
        trace.emit("system", "", "Paused from the dashboard — no replies until you resume")
    elif kind == "resume":
        state.set_paused(False)
        trace.emit("system", "", "Resumed from the dashboard")
        spawn(reply_to_unread())
    elif kind == "toggle":
        key, on = cmd.get("value"), cmd.get("text") == "on"
        if key in toggles.TOGGLES:
            state.settings[key] = on
            state.save()
            toggles.apply(state.settings)
            trace.emit("system", "", f"{toggles.TOGGLES[key][1]}: {'ON' if on else 'off'} (set from the dashboard)")
            if on is False and key in ("sleep", "school"):
                spawn(reply_to_unread())  # woke up / left school early: look at what's waiting
    elif kind == "approve":
        state.set_approve(cmd.get("value") == "on")
        trace.emit("system", "", "Approve-before-sending is ON: every draft waits for you" if state.approve
                   else "Approve-before-sending is OFF: drafts send by themselves")
    elif kind == "do" and cmd.get("text", "").strip():
        spawn(operate(cmd["text"].strip()))
    elif chat_id is None:
        trace.emit("warning", name, "Dashboard action ignored — I don't know that chat yet")
    elif kind == "history":
        await push_history(chat_id)
    elif kind == "mode":
        mode = cmd.get("value")
        if mode == "off":
            state.disable(chat_id)
            state.manual.discard(chat_id)
            state.save()
            cancel(chat_id)
        elif mode == "manual":
            state.set_manual(chat_id)
            cancel(chat_id)
        else:
            state.disabled.discard(chat_id)
            state.manual.discard(chat_id)
            state.save()
        trace.emit("system", name, f"Chat mode set to {mode} from the dashboard")
    elif kind == "answer":  # overrule a hand-off / ignored question / skipped message
        contact = contacts.get(chat_id)
        if not contact:
            contact = await client.get_entity(chat_id)
        state.clear_handoff(chat_id)
        forced.add(chat_id)
        cancel(chat_id)
        trace.emit("decision", name, "You asked for an answer — writing one now")
        pending[chat_id] = asyncio.create_task(reply_flow(chat_id, contact))
    elif kind == "spam" and cmd.get("text", "").strip():  # value = how many times
        count = min(int(cmd.get("value") or 10), C.SPAM_MAX)
        cancel(chat_id)
        trace.emit("decision", name, f"Spamming on your order: “{cmd['text'].strip()}” × {count}")
        await spam(chat_id, name, [cmd["text"].strip()] * count)
    elif kind == "say" and cmd.get("text", "").strip():  # your own words, sent with normal typing
        text = cmd["text"].strip()
        cancel(chat_id)
        state.clear_handoff(chat_id)
        trace.emit("decision", name, "Sending the text you wrote on the dashboard")
        await client.send_read_acknowledge(chat_id)
        await type_like_a_person(chat_id, text)
        our_texts.setdefault(chat_id, []).append(text)
        sent = await client.send_message(chat_id, text)
        our_ids.add(sent.id)
        state.record_sent(chat_id, sent.id)
        state.mark_handled(chat_id, (await client.get_messages(chat_id, limit=1))[0].id)
        trace.emit("sent", name, text)
        daylog.record("replied", name, text, them="(you wrote this on the dashboard)")


async def command_loop():
    """Poll the dashboard for clicks, and tell it what state the account is in."""
    last, _ = await trace.commands(10**9)  # start from "now": don't replay old commands
    beat = 0
    while True:
        await asyncio.sleep(1)
        latest, new = await trace.commands(last)
        if latest < last:  # the backend restarted and its ids started over
            last = 0
            continue
        for cmd in new:
            last = max(last, cmd["id"])
            try:
                await run_command(cmd)
            except Exception:
                log.exception("Dashboard command failed: %r", cmd)
                trace.emit("warning", cmd.get("chat", ""), "That dashboard action failed (see the userbot log)")
        beat += 1
        if beat % 3 == 0 or new:
            known = set(names) | state.disabled | state.manual
            await trace.report_status({
                "account": full_name(me), "paused": state.is_paused(), "approve": state.approve,
                "asleep": rhythm.asleep(), "busy": rhythm.busy(), "models": C.MODELS, "mode": C.REPLY_MODE,
                "toggles": toggles.snapshot(),
                "chats": sorted(({"name": names.get(cid, str(cid)), "mode": state.mode_of(cid),
                                  "waiting": cid in pending, "held": state.handed_off(cid)}
                                 for cid in known if cid in names), key=lambda c: c["name"].lower())})


async def summary_loop():
    """Every evening: a digest of the day in Saved Messages."""
    if not C.SUMMARY_TIME:
        return
    hour, minute = (int(x) for x in C.SUMMARY_TIME.split(":"))
    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await client.send_message("me", daylog.summary())
        except Exception:
            log.exception("Evening summary failed")


async def unread_loop():
    """Safety net: Telegram's live update feed can go quiet (e.g. when another connection uses the same
    login), so re-scan the most recent chats for unread DMs on a timer."""
    while True:
        await asyncio.sleep(C.UNREAD_RESCAN_SECONDS)
        try:
            await reply_to_unread(limit=30)
        except Exception:
            log.exception("Unread re-scan failed")


async def reply_to_unread(limit: int = 0) -> int:
    """Answer private chats that are waiting on you: unread DMs (up to UNREAD_MAX_AGE old), plus unanswered ones
    you have already opened yourself (up to RECENT_UNANSWERED old) — seeing a message doesn't answer it.
    Anything already answered, reacted to, skipped or handed to you is left alone. No groups, channels or bots."""
    count = 0
    if rhythm.asleep():
        return count  # nobody answers at night; these get picked up after waking
    async for dialog in client.iter_dialogs(limit=limit or C.UNREAD_SCAN_DIALOGS):
        contact, last = dialog.entity, dialog.message
        if not isinstance(contact, User) or contact.bot or contact.is_self or contact.deleted \
                or contact.id == TELEGRAM_SERVICE_ID:
            continue
        if not last or last.out or dialog.id in pending or not state.is_active(dialog.id, C.REPLY_MODE):
            continue
        if state.is_handled(dialog.id, last.id) or state.handed_off(dialog.id):
            continue  # already answered, skipped, reacted to, or handed to you
        age = time.time() - last.date.timestamp()
        if not ((dialog.unread_count and age < C.UNREAD_MAX_AGE) or age < C.RECENT_UNANSWERED):
            continue
        names[dialog.id] = full_name(contact)
        what = f"{dialog.unread_count} unread message(s)" if dialog.unread_count else "a recent unanswered message"
        log.info("%s: answering %s", label(dialog.id), what)
        trace.emit("incoming", label(dialog.id), f"Found {what} while scanning private chats")
        if count:
            await asyncio.sleep(rand((2, 5)))  # don't fire replies into many chats at the same instant
        pending[dialog.id] = asyncio.create_task(reply_flow(dialog.id, contact))
        count += 1
    return count


async def main():
    global me
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Not logged in. Run once: .venv/bin/python -m userbot.login")
    me = await client.get_me()
    rhythm.awake_until = state.awake_until
    toggles.apply(state.settings)
    log.info("Running as %s (@%s) | mode=%s | models=%s | paused=%s",
             full_name(me), me.username, C.REPLY_MODE, C.MODELS, state.is_paused())
    if C.REPLY_MODE == "all":
        off = [await resolve_name(cid) for cid in sorted(state.disabled)]
        log.info("Replying in every private chat; off in: %s", ", ".join(off) or "none")
    else:
        enabled = [await resolve_name(cid) for cid in sorted(state.enabled)]
        log.info("Enabled chats: %s", ", ".join(enabled) or "none (type .ai on in a chat)")
    async for dialog in client.iter_dialogs(limit=40):  # so the dashboard can act on recent chats right away
        if isinstance(dialog.entity, User) and not dialog.entity.bot and not dialog.entity.is_self \
                and dialog.entity.id != TELEGRAM_SERVICE_ID:
            names[dialog.id] = full_name(dialog.entity)
            contacts[dialog.id] = dialog.entity
    trace.emit("system", "", f"Userbot started as {full_name(me)} — mode: {C.REPLY_MODE}, models: {', '.join(C.MODELS)}")
    await reply_to_unread()
    background = [asyncio.create_task(bio_loop(client, state)), asyncio.create_task(unread_loop()),
                  asyncio.create_task(summary_loop()), asyncio.create_task(command_loop())]
    try:
        await client.run_until_disconnected()
    finally:
        for task in background:
            task.cancel()
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
