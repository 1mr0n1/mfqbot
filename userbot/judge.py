"""Two judgment calls a person makes before answering: "does this even need a reply?" and "is this one for me?"

- closers: "ok", "👍", a lone sticker after YOUR message don't need a text reply — skip them or just react.
- sensitive: money, emergencies, someone upset, codes/passwords… are not answered by the bot at all;
  the owner is pinged in Saved Messages and the bot stays out of that chat for a while.
"""
import itertools
import logging
import random
import re

import httpx

from . import config as C

log = logging.getLogger("userbot.judge")

# ---------- messages that don't need a reply ----------
ACK_WORDS = set("""ok okay okey oki k kk ок окей оке окк ага угу ладно лан понял поняла понятно ясно хорошо хоп хор норм
 нормально договорились отлично супер круто класс xop hop mayli bo'ldi boldi tushunarli ha yes yep yeah yea sure got it
 alr alright aight bet fine cool nice good да даа ну и all right""".split())
THANKS_WORDS = set("""спс спасибо пасиб спасибки благодарю rahmat raxmat рахмат thx thanks thank you ty tysm большое
 катта katta""".split())
BYE_WORDS = set("""пока покеда пакеда давай до завтра встречи связи свидания увидимся спокойной ночи споки сладких снов
 доброй bye byee goodbye gn night good see you ya cya later ttyl take care xayr hayr ko'rishguncha korishguncha
 yaxshi dam ol oling tun tuning хайр""".split())
LAUGH_RE = re.compile(r"^(lol|lmao|lmfao|п?[ахaxh]{4,}|\)+)$", re.I)
# how people address each other — doesn't change what kind of message it is
VOCATIVE = set("""bro бро брат братан братишка чел друг dude man aka uka opa opajon oyijon dadajon мам мама пап папа
 дядя тётя jigar jiga do'stim dostim""".split())
EMOJI_ONLY_RE = re.compile(r"^[\W\d_]*$")  # no letters at all: emoji, punctuation
REACTIONS = ["👍", "❤"]  # the only reactions the account uses


def _closer_kind(text: str) -> str | None:
    """-> 'thanks' | 'bye' | 'ack' | 'laugh' | 'emoji' if the whole message is just that, else None."""
    text = text.strip()
    if not text or EMOJI_ONLY_RE.match(text):
        return "emoji"
    words = [w for w in re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)*", text.lower()) if w not in VOCATIVE]
    if "?" in text or len(words) > 6:
        return None
    if not words:
        return "ack"
    if all(LAUGH_RE.match(w) for w in words):
        return "laugh"
    if not all(w in ACK_WORDS or w in THANKS_WORDS or w in BYE_WORDS or LAUGH_RE.match(w) for w in words):
        return None
    if any(w in BYE_WORDS for w in words) and not all(w in ACK_WORDS for w in words):
        return "bye"
    if any(w in THANKS_WORDS for w in words):
        return "thanks"
    return "ack"


def closer_action(history) -> str | None:
    """-> 'react:<emoji>' or None (= answer normally). Only when they're closing after YOUR message.

    Someone wrapping up ("ok", "спасибо", "пока", "спокойной ночи") gets a reaction instead of more text."""
    unanswered = list(itertools.takewhile(lambda m: not m.out, history))
    if not unanswered or len(unanswered) > 3 or len(history) == len(unanswered):
        return None  # nothing new, a real burst, or they opened the conversation
    kinds = []
    for msg in unanswered:
        if msg.photo or msg.voice or msg.video or msg.video_note or (msg.document and not msg.sticker):
            return None
        kind = "emoji" if msg.sticker else _closer_kind(msg.raw_text or "")
        if not kind:
            return None
        kinds.append(kind)
    if "thanks" in kinds or "bye" in kinds:
        return "react:❤" if "thanks" in kinds or random.random() < 0.4 else "react:👍"
    return "react:👍"


def may_skip(history) -> bool:
    """Only short non-questions are candidates for "no reply needed"; real messages always get an answer."""
    texts = [m.raw_text or "" for m in itertools.takewhile(lambda m: not m.out, history)]
    joined = " ".join(texts)
    return "?" not in joined and len(joined.split()) <= 4


def parse_model_choice(reply: str) -> str | None:
    """The model may answer [skip] or [react 👍] instead of text."""
    text = reply.strip()
    if re.fullmatch(r"\[skip\]", text, re.I):
        return "skip"
    match = re.fullmatch(r"\[react\s+(\S+)\]", text, re.I)
    if match:
        emoji = match.group(1).replace("️", "")
        return f"react:{emoji if emoji in REACTIONS else '👍'}"
    return None


NO_REPLY_HINT = ("\nNot every message needs a text reply. If theirs is just an acknowledgement or a reaction that ends the "
                 "exchange, answer with exactly [skip] (send nothing) or [react 👍] (put an emoji reaction on their "
                 "message — only 👍 or ❤). Use a normal reply whenever they asked or said something.\n")


# ---------- messages the owner should handle personally ----------
STRONG = [
    ("a verification code or password",
     r"\b(otp|password|passcode)\b|парол\w*|\bparol\w*"
     r"|(sms|смс|verification|login|confirm\w*|подтвержд\w*|tasdiq\w*)\W+(\w+\W+){0,3}(code|код|kod)\b"
     r"|\b(code|код|kod)\b\W+(\w+\W+){0,3}(sms|смс|пришл\w*|прислал\w*|отправ\w*|скин\w*|keldi|yubor\w*|ayt\w*|came|sent)"),
    ("money", r"\b(lend|borrow|loan|owe|debt|pay me|send me \$?\d|transfer|cash ?app|paypal)\b|\$\s?\d{2,}|\d{2,}\s?(\$|usd|сум|sum|so'm|som|руб|k\b)"
              r"|в\s*долг|одолжи\w*|займи\w*|перевед\w*|скинь\s+(деньг|на карт)|на карту|деньг\w*|\bqarz\w*|\bpul\w*\s+(ber|kerak|tashla|o'tkaz)|kartaga"),
    ("an emergency", r"\b(emergency|hospital|ambulance|accident|police|urgent(ly)?|asap|died|passed away)\b|срочно|больниц\w*|скор(ая|ую)"
                     r"|авари\w*|полици\w*|умер(ла)?|kasalxona\w*|tez yordam|avariya|vafot|zudlik|shoshilinch"),
]
CLASSIFY = (
    "Below are the latest messages someone sent to their friend or relative {name} in a private chat. Decide whether "
    "{name} must answer PERSONALLY. Answer PERSONAL only for something clearly serious: the person is in real distress "
    "(crying, panicking, saying they are deeply hurt), a serious fight or breaking off contact, romantic or relationship "
    "talk, illness, injury, death or other bad news, trouble with police, school administration or the law.\n"
    "Everything else is NORMAL — including teasing, banter, jokes, mild complaints or reproaches ('you didn't reply', "
    "'you didn't do it'), embarrassing or silly stories, everyday plans and logistics, favors, questions, greetings. "
    "When in doubt, answer NORMAL.\n"
    "Answer with one word, PERSONAL or NORMAL, then a dash and the reason in at most 6 words.\n\nMESSAGES:\n{messages}"
)


async def sensitive_reason(http: httpx.AsyncClient, name: str, history, keywords_only: bool = False) -> str | None:
    """-> why the owner should take this one, or None. keywords_only skips the model's judgment call."""
    texts = [m.raw_text for m in itertools.takewhile(lambda m: not m.out, history) if m.raw_text]
    joined = "\n".join(reversed(texts))
    if not joined.strip():
        return None
    for reason, pattern in STRONG:
        if re.search(pattern, joined, re.I):
            return reason
    if keywords_only or len(joined.split()) < 4:
        return None  # too short to be worth a model call
    try:
        resp = await http.post("/complete", json={
            "messages": [{"role": "user", "content": CLASSIFY.format(name=name, messages=joined[:1500])}],
            "models": C.MODELS, "max_tokens": 30, "temperature": 0})
    except httpx.HTTPError:
        return None
    if resp.is_error:
        return None
    verdict = resp.json()["reply"].strip()
    if verdict.upper().startswith("PERSONAL"):
        return re.sub(r"^PERSONAL\W*", "", verdict, flags=re.I).strip()[:80] or "needs a personal answer"
    return None


# ---------- a second look at the draft before it is sent ----------
REVIEW = (
    "A person is about to send this reply in a private chat. Check it only for real mistakes.\n"
    "THEIR MESSAGE:\n{them}\n\nDRAFT REPLY:\n{draft}\n\n"
    "Answer BAD only if the draft clearly has one of these problems: (1) made-up or nonsense words, random letters, or "
    "words from a third language mixed in; (2) it is written in a different language than their message{lang}; "
    "(3) it contains notes about itself, instructions, or commentary in brackets; (4) it just repeats their message "
    "back. Everything else is OK: short or one-word answers, vague or non-committal answers ('I'll check and tell "
    "you'), a plain 'no', slang, informal spelling, typos, answering a question with a question.\n"
    "Answer with one word, OK or BAD, then a dash and the reason in at most 8 words."
)


_english: set[str] | None = None
CHAT_ENGLISH = {
    "ok", "okay", "lol", "lmao", "bruh", "bro", "chill", "chillin", "vibe", "vibing", "gonna", "wanna", "gotta", "nah",
    "yeah", "yep", "nope", "idk", "btw", "omg", "wtf", "imo", "rn", "pls", "plz", "thx", "ty", "sry", "cuz", "tho", "fr",
    "ngl", "sus", "cringe", "nice", "cool", "wow", "yo", "hey", "hi", "bye", "aight", "wsg", "gg", "ez", "noob", "skill",
    "iphone", "ipad", "macbook", "airpods", "telegram", "youtube", "tiktok", "instagram", "whatsapp", "discord", "steam",
    "google", "chatgpt", "xiaomi", "samsung", "android", "windows", "wifi", "bluetooth", "online", "offline", "stream",
    "pubg", "minecraft", "roblox", "fortnite", "valorant", "csgo", "python", "olx", "uzum", "yandex", "click", "payme",
}


def foreign_word(them: str, draft: str) -> str | None:
    """In a Cyrillic reply: a Latin-letter word that isn't English, chat slang, a brand, or something they wrote."""
    global _english
    if not re.search("[а-яё]", draft, re.I):
        return None
    if _english is None:
        try:
            with open("/usr/share/dict/words") as f:
                _english = {w.strip().lower() for w in f}
        except OSError:
            _english = set()
    if not _english:
        return None
    theirs = set(re.findall(r"[a-z']+", them.lower()))
    for word in re.findall(r"[A-Za-z][A-Za-z']{3,}", draft):
        w = word.lower().strip("'")
        stems = {w, w.rstrip("s"), w[:-2] if w.endswith("ed") else w, w[:-3] if w.endswith("ing") else w,
                 w[:-3] + "e" if w.endswith("ing") else w}
        if not (stems & _english or w in CHAT_ENGLISH or w in theirs):
            return word
    return None


async def review(http: httpx.AsyncClient, them: str, draft: str, expected: str | None = None) -> str | None:
    """-> None if the draft may be sent, otherwise why not. If the check itself fails, the draft passes."""
    from . import lang

    text = "\n".join(line for line in draft.splitlines() if not re.match(r"^\[(sticker|gif|voice|video)\s", line.strip(), re.I))
    if not text.strip():
        return None  # only media
    their_lang, draft_lang = lang.base(lang.detect(them)), lang.base(lang.detect(text))
    known = {"uz", "ru", "en"}
    if expected is None and their_lang in known and draft_lang in known and their_lang != draft_lang \
            and len(them.split()) >= 3 and len(text.split()) >= 3:
        return f"wrong language ({draft_lang} instead of {their_lang})"
    odd = foreign_word(them, text)
    if odd:
        return f"strange word '{odd}'"
    hint = f" (expected: {expected})" if expected else ""
    try:
        resp = await http.post("/complete", json={
            "messages": [{"role": "user", "content": REVIEW.format(them=them[:800] or "(a photo or sticker)",
                                                                   draft=text[:800], lang=hint)}],
            "models": C.MODELS, "max_tokens": 30, "temperature": 0})
    except httpx.HTTPError:
        return None
    if resp.is_error:
        return None
    verdict = resp.json()["reply"].strip()
    if verdict.upper().startswith("BAD"):
        return re.sub(r"^BAD\W*", "", verdict, flags=re.I).strip()[:80] or "didn't pass the check"
    return None
