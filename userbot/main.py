"""Userbot: replies from your own Telegram account, paced like a human.

Control it by sending these from your account (they're deleted instantly; confirmations go to Saved Messages):
  .ai on / .ai off   — in a private chat: enable/disable auto-replies there
  .ai pause / resume — anywhere: stop/restart all auto-replies
  .ai pause 30m      — pause for a while (m/h/d), then resume automatically
  .ai status         — anywhere: show current state
  .ai unread         — anywhere: answer unread private messages now (also done at startup)
  .ai save <tag>     — reply to your own voice/round video in Saved Messages to add it to the clip library
  .ai forget <tag>   — remove a clip;  .ai clips — list clips
  .ai savepack       — reply to a sticker: add its whole pack to your account
  .ai salam / .ai notsalam — reply to a sticker: teach that it is / isn't an "Assalomu alaykum" sticker
  (Saved Messages only)
  .ai name <first name> / .ai surname <last name or -> / .ai bio <text or -> / .ai profile
  .ai photo          — reply to a photo with this to make it your profile photo
"""
import asyncio
from collections import Counter
import base64
import itertools
import json
import logging
import random
import re
import time
from datetime import datetime

import httpx
from telethon import TelegramClient, errors, events, functions
from telethon.tl.types import User

from . import config as C
from . import lang, media, salam
from . import trace
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
me: User | None = None


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


def looks_safe(reply: str) -> bool:
    return len(reply) <= MAX_REPLY_CHARS and not LEAK_RE.search(reply)


# Lines that make it sound like a customer-support bot get dropped.
ASSISTANT_RE = re.compile(r"\b(assist|let me know if you need|anything else|how can i help|feel free|happy to help)\b",
                          re.I)

# Asking whether they're talking to a bot/AI gets an honest fixed answer — never left to the model.
BOT_QUESTION_RE = re.compile(r"\b(bot|robot|ai|a\.i\.|chat ?gpt|gpt|neural|автоответчик|бот|робот|ии|нейросеть|"
                             r"нейронка|чатгпт)\b", re.I)
ADDRESSED_RE = re.compile(r"\?|\b(u|you|ur|r u|are|is this|ты|вы|тебя|это)\b", re.I)
HONEST_REPLY = {
    "cyrillic": "Я сейчас занят, это автоответ. Отвечу лично чуть позже",
    "latin": "im busy rn, this is an auto-reply. ill answer personally later",
}


def asks_if_bot(history) -> bool:
    """True if the other person's latest messages (since your last one) ask about a bot/AI."""
    for msg in history:  # newest first
        if msg.out:
            return False
        text = msg.raw_text or ""
        if BOT_QUESTION_RE.search(text) and ADDRESSED_RE.search(text):
            return True
    return False


FAKE_TAG_RE = re.compile(r"\[(?!(?:sticker|gif|voice|video)\s)[^\]]*\]", re.I)  # e.g. echoed "[photo]"
REPEAT_RE = re.compile(r"(.)\1{12,}")  # "YOOOOOOOOOOOOOO…" -> capped


def clean_reply(reply: str) -> str:
    first = (me.first_name or "").strip() if me else ""
    lines = []
    for line in reply.splitlines():
        if ASSISTANT_RE.search(line):
            continue
        line = FAKE_TAG_RE.sub("", line)
        if first:  # drop a "Name:" speaker label
            line = re.sub(rf"^\s*{re.escape(first)}\s*:\s*", "", line, flags=re.I)
        line = REPEAT_RE.sub(lambda m: m.group(1) * 8, line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


MEDIA_SPLIT_RE = re.compile(r"(\[(?:sticker|gif|voice|video)\s+[^\]]+\])", re.I)


def split_reply(reply: str) -> list[str]:
    # one part per line, and media tags always become their own part
    parts = [p.strip() for line in reply.splitlines() for p in MEDIA_SPLIT_RE.split(line) if p.strip()]
    if len(parts) > C.MAX_PARTS:
        # merge overflow text into one message, but never glue a media tag to text (keep one media item)
        rest = parts[C.MAX_PARTS - 1:]
        rest_text = [p for p in rest if not media.MEDIA_LINE_RE.match(p)]
        rest_media = [p for p in rest if media.MEDIA_LINE_RE.match(p)]
        parts = parts[:C.MAX_PARTS - 1] + (["\n".join(rest_text)] if rest_text else []) + rest_media[:1]
    return parts


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


def contact_style_block(path, incoming: str) -> str:
    """Style for one specific person, built only from your real chat with them."""
    data = json.loads(path.read_text())
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
    reply_lang = Counter(p["lang"] for p in relevant).most_common(1)[0][0] if relevant else wanted
    in_lang = [m for m in data["examples"] if lang.base(lang.detect(m)) == reply_lang] or data["examples"]
    examples = random.sample(in_lang, min(C.STYLE_EXAMPLES, len(in_lang)))
    block += "\nReal messages you sent them:\n" + "\n".join(f"- {m.replace(chr(10), ' / ')}" for m in examples) + "\n"
    same = [p for p in relevant if p["lang"] == reply_lang]
    pairs = random.sample(same, min(C.CONTACT_PAIRS, len(same)))
    if pairs:
        block += ("\nReal exchanges with them — what they wrote and what you actually answered "
                  "(copy the manner and the language choice, never the content):\n"
                  + "\n".join(f"THEM: {p['them'].replace(chr(10), ' / ')}\nYOU: {p['me'].replace(chr(10), ' / ')}"
                              for p in pairs) + "\n")
    name = {"uz": "Uzbek (Latin letters, exactly the everyday forms shown above)", "ru": "Russian",
            "en": "English"}.get(reply_lang, "the language of the examples above")
    block += (f"\nLanguage note: write your whole reply in {name}. Use only words and forms that appear in your "
              "real messages above; if unsure, answer with something very short.\n")
    return block


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
        examples = json.loads(examples_path.read_text())
        # Mostly messages in the language of this conversation, so the right register gets copied.
        picks = _prefer(examples, wanted, lambda m: lang.base(lang.detect(m)), C.STYLE_EXAMPLES)
        block += ("\nReal messages they've sent (for style only — don't reuse their content):\n"
                  + "\n".join(f"- {m.replace(chr(10), ' / ')}" for m in picks) + "\n")
    if pairs_path.exists():
        pairs = json.loads(pairs_path.read_text())
        same_person = [p for p in pairs if p["with"] == contact_name]
        picks = (random.sample(same_person, min(C.STYLE_PAIRS, len(same_person))) if same_person
                 else _prefer(pairs, wanted, lambda p: lang.base(p.get("lang")), C.STYLE_PAIRS))
        if picks:
            block += ("\nReal exchanges — what someone wrote and what they actually answered "
                      "(copy the manner, never the content):\n"
                      + "\n".join(f"THEM: {p['them'].replace(chr(10), ' / ')}\nYOU: {p['me'].replace(chr(10), ' / ')}"
                                  for p in picks) + "\n")
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


async def generate(history, contact: User) -> str | None:
    messages = to_chat_messages(history)
    if not messages or messages[-1]["role"] != "user":
        return ""  # nothing to answer (None means the backend failed)
    photos = await attach_photos(history, messages) if C.VISION else 0
    incoming = " ".join(m.raw_text for m in itertools.takewhile(lambda m: not m.out, history) if m.raw_text)
    if len(incoming.split()) < 3:  # "ok", an emoji, a photo: go by how this person has been writing lately
        incoming = " ".join([m.raw_text for m in history if not m.out and m.raw_text][:8])
    system = persona.format(name=full_name(me), contact=full_name(contact),
                            style=style_block(full_name(contact), incoming, contact),
                            now=datetime.now().strftime("%A %d %B %Y, %H:%M"))
    if not contact_style_path(contact):
        system += media.media_block(full_name(me))
    if photos:
        system += PHOTO_HINT
    try:
        resp = await http.post("/complete", json={"messages": messages, "system": system, "models": C.MODELS,
                                                  "max_tokens": 300})
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


async def reply_flow(chat_id: int, contact: User):
    global me
    who = names[chat_id] = full_name(contact)
    draft_id = None
    try:
        me = await client.get_me()  # profile may have been changed from outside (userbot.profile)
        await asyncio.sleep(rand(C.DEBOUNCE) + rand(C.READ_DELAY))

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
        await client.send_read_acknowledge(chat_id)
        await asyncio.sleep(rand(C.THINK_DELAY))

        greeting = await salam.check(client, state, http, history)
        if greeting.sticker:  # a salam sticker is answered with the very same sticker
            trace.emit("decision", who, "They sent an 'Assalomu alaykum' sticker → answering with the same sticker")
            await asyncio.sleep(rand(C.DRAFT_HOLD))
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

        if greeting.reply and not greeting.rest:
            reply = greeting.reply  # fixed text, never written by the model
            trace.emit("decision", who, "They wrote the salam greeting → sending the fixed proper answer (model not used)")
        elif asks_if_bot(history):
            last = next((m.raw_text for m in history if not m.out and m.raw_text), "")
            reply = HONEST_REPLY["cyrillic" if re.search("[А-Яа-я]", last) else "latin"]
            trace.emit("decision", who, "They asked if this is a bot → sending the fixed honest auto-reply (model not used)")
            await client.send_message("me", f"🤖 {who} asked if they're talking to a bot — "
                                            f"sent the honest auto-reply. You may want to answer yourself.")
        else:
            trace.emit("decision", who, "Read the chat — writing a reply")
            for attempt in range(C.GENERATE_RETRIES + 1):
                if attempt:  # every model failed — come back later, like a busy person would
                    delay = rand(C.RETRY_DELAY)
                    log.info("%s: models unavailable, retrying in %.0fs (%d/%d)", who, delay, attempt, C.GENERATE_RETRIES)
                    trace.emit("warning", who, f"No model answered — trying again in {delay:.0f}s "
                                               f"(attempt {attempt}/{C.GENERATE_RETRIES})")
                    await asyncio.sleep(delay)
                reply = await generate(history, contact)
                if reply is not None:
                    break
            else:
                log.warning("%s: giving up, no model answered", who)
                trace.emit("warning", who, "Giving up — no model answered")
            reply = clean_reply(reply or "")
            if greeting.reply:  # salam + something else: fixed greeting first, then the model's answer
                reply = (greeting.reply + "\n" + salam.strip_greeting_line(reply)).strip()
        if not reply:
            trace.emit("decision", who, "Nothing to send — staying quiet")
            return
        if not looks_safe(reply):
            log.warning("%s: blocked suspicious reply (%d chars): %r — retrying once", who, len(reply), reply[:200])
            trace.emit("warning", who, f"Blocked a suspicious draft ({len(reply)} chars), writing another: {reply[:160]}")
            reply = clean_reply(await generate(history, contact) or "")
            if not reply or not looks_safe(reply):
                log.warning("%s: second reply also unusable, staying quiet", who)
                trace.emit("warning", who, "Second draft was unusable too — staying quiet")
                return

        allow_media = C.MEDIA_ENABLED and not contact_style_path(contact)
        parts = [p for p in split_reply(reply) if allow_media or not media.MEDIA_LINE_RE.match(p)]
        if not parts:
            return

        # Show the draft on the dashboard for a moment; Cancel there stops it.
        draft_id = trace.new_draft_id()
        hold = rand(C.DRAFT_HOLD)
        trace.emit("draft", who, "\n".join(parts), draft_id=draft_id, parts=parts, hold=hold)
        await asyncio.sleep(hold)

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
                seconds = typing_time(part)
                trace.emit("decision", who, f"Typing for {seconds:.1f}s…", draft_id=draft_id, phase="typing", index=i)
                if seconds:
                    async with client.action(chat_id, "typing"):
                        await asyncio.sleep(seconds)
                our_texts.setdefault(chat_id, []).append(part)
                sent = await client.send_message(chat_id, part)
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
            sent_count += 1
            trace.emit("sent", who, part, draft_id=draft_id, index=i)
        trace.emit("decision", who, f"Done — {sent_count} message(s) sent", draft_id=draft_id, final=True)
        log.info("%s: replied (%d chars)", who, len(reply))
    except asyncio.CancelledError:
        log.info("%s: reply cancelled", who)
        trace.emit("cancelled", who, "Dropped this reply — a new message arrived or you answered yourself",
                   draft_id=draft_id)
        raise
    except Exception:
        log.exception("%s: reply failed", who)
        trace.emit("warning", who, "Reply failed with an error (see userbot log)", draft_id=draft_id, final=True)
    finally:
        if pending.get(chat_id) is asyncio.current_task():
            pending.pop(chat_id)


@client.on(events.NewMessage(outgoing=True, pattern=r"^\.ai(?:\s+(\w+))?(?:\s+([\w-]+))?\s*$"))
async def on_command(event):
    arg = (event.pattern_match.group(1) or "status").lower()
    if arg in PROFILE_COMMANDS:
        return  # handled by on_profile_command
    tag = (event.pattern_match.group(2) or "").lower()
    chat_id = event.chat_id
    in_saved = chat_id == me.id
    replied = await event.get_reply_message() if event.is_reply else None
    await event.delete()

    if arg in ("save", "forget", "clips"):
        await client.send_message("me", clip_command(arg, tag, replied, in_saved))
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

    if arg in ("on", "off") and (in_saved or not event.is_private):
        note = "⚠️ .ai on/off only works inside a private chat"
    elif arg == "on":
        state.enable(chat_id)
        note = "✅ auto-replies ON for {chat}"
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


@client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+(name|surname|bio|photo|profile)\b\s*(.*)$"))
async def on_profile_command(event):
    """Profile changes are owner-only commands — the AI itself can never change your profile."""
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
    if event.chat_id in pending:
        log.info("%s: you replied yourself, standing down", label(event.chat_id))
        cancel(event.chat_id)


@client.on(events.NewMessage(incoming=True))
async def on_incoming(event):
    if not event.is_private or time.time() - event.date.timestamp() > C.IGNORE_OLDER_THAN:
        return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot or sender.is_self or sender.id == TELEGRAM_SERVICE_ID:
        return
    who = names[event.chat_id] = full_name(sender)
    trace.emit("incoming", who, describe(event.message)[:300])
    if not state.is_active(event.chat_id, C.REPLY_MODE):
        trace.emit("decision", who, "Not replying — auto-replies are paused" if state.is_paused()
                   else "Not replying — auto-replies are off for this chat")
        return
    cancel(event.chat_id)  # a new message restarts the wait, so bursts get one reply
    pending[event.chat_id] = asyncio.create_task(reply_flow(event.chat_id, sender))


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
    """Answer private chats that are waiting on you: unread DMs (up to UNREAD_MAX_AGE old), plus very
    recent unanswered ones (e.g. sent during a restart). Groups, channels and bots are never touched."""
    count = 0
    async for dialog in client.iter_dialogs(limit=limit or C.UNREAD_SCAN_DIALOGS):
        contact, last = dialog.entity, dialog.message
        if not isinstance(contact, User) or contact.bot or contact.is_self or contact.deleted \
                or contact.id == TELEGRAM_SERVICE_ID:
            continue
        if not last or last.out or dialog.id in pending or not state.is_active(dialog.id, C.REPLY_MODE):
            continue
        age = time.time() - last.date.timestamp()
        if not ((dialog.unread_count and age < C.UNREAD_MAX_AGE) or age < C.IGNORE_OLDER_THAN):
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
    log.info("Running as %s (@%s) | mode=%s | models=%s | paused=%s",
             full_name(me), me.username, C.REPLY_MODE, C.MODELS, state.is_paused())
    if C.REPLY_MODE == "all":
        off = [await resolve_name(cid) for cid in sorted(state.disabled)]
        log.info("Replying in every private chat; off in: %s", ", ".join(off) or "none")
    else:
        enabled = [await resolve_name(cid) for cid in sorted(state.enabled)]
        log.info("Enabled chats: %s", ", ".join(enabled) or "none (type .ai on in a chat)")
    trace.emit("system", "", f"Userbot started as {full_name(me)} — mode: {C.REPLY_MODE}, models: {', '.join(C.MODELS)}")
    await reply_to_unread()
    background = [asyncio.create_task(bio_loop(client, state)), asyncio.create_task(unread_loop())]
    try:
        await client.run_until_disconnected()
    finally:
        for task in background:
            task.cancel()
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
