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
CLOSER_RE = re.compile(
    r"^(ok+(ay)?|k+|kk|okey|oki|ок+|окей|ага|угу|ладно|понял[а]?|ясно|хорошо|хоп|хор|норм|давай|спс|спасибо|пасиб"
    r"|xop|hop|mayli|bo'?ldi|rahmat|raxmat|tushunarli|ha+|yes|yep|yeah|sure|thx|thanks|ty|got it|alr(ight)?|bet|lol"
    r"|lmao|haha+|ahah+|хаха+|ахах+|аха+|\)+|👍|👌|🙏|❤️?|😂|🤣|😅|😁|🔥|💯)[\s.!)]*$", re.I)
EMOJI_ONLY_RE = re.compile(r"^[\W\d_]*$")  # no letters at all: emoji, punctuation
REACTIONS = ["👍", "❤", "🔥", "😁", "👌", "🙏", "🤝", "😢", "🤣", "💯", "😭", "🥰", "👏", "🤔"]  # standard Telegram reactions


def closer_action(history) -> str | None:
    """-> 'skip', 'react:<emoji>' or None (= answer normally). Only when they're closing after YOUR message."""
    unanswered = list(itertools.takewhile(lambda m: not m.out, history))
    if not unanswered or len(unanswered) > 2 or len(history) == len(unanswered):
        return None  # nothing new, a burst, or they opened the conversation
    for msg in unanswered:
        text = (msg.raw_text or "").strip()
        if msg.photo or msg.voice or msg.video or msg.video_note or msg.document and not msg.sticker:
            return None
        if text and not (CLOSER_RE.match(text) or EMOJI_ONLY_RE.match(text)):
            return None
        if "?" in text:
            return None
    last = (unanswered[0].raw_text or "").strip().lower()
    if re.match(r"^(спс|спасибо|пасиб|rahmat|raxmat|thx|thanks|ty)", last):
        return random.choice(["react:🙏", "react:👍", "react:❤", "skip"])
    if re.match(r"^(lol|lmao|haha|ahah|хаха|ахах|аха|😂|🤣)", last):
        return random.choice(["react:😁", "react:🤣", "skip", "skip"])
    return random.choice(["skip", "skip", "react:👍", "react:👌"])


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
                 "message — one of 👍 ❤ 🔥 😁 👌 🙏 🤣 😢). Use a normal reply whenever they asked or said something.\n")


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
    "Below are the latest messages someone sent to their friend or relative {name} in a private chat. Should {name} "
    "answer these PERSONALLY instead of sending a casual quick reply? Answer PERSONAL only if it is clearly one of: "
    "they are upset, angry, hurt, crying or want a serious talk; a fight or accusation; romantic or relationship matters; "
    "health problems or bad news; trouble at school, work or with the law; a request for a real decision or commitment "
    "that matters (not small everyday things); anything where a careless answer could hurt them. "
    "Everyday chat, jokes, simple questions, greetings, homework or factual questions, small favors: NORMAL.\n"
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
            "models": C.MODELS, "max_tokens": 30})
    except httpx.HTTPError:
        return None
    if resp.is_error:
        return None
    verdict = resp.json()["reply"].strip()
    if verdict.upper().startswith("PERSONAL"):
        return re.sub(r"^PERSONAL\W*", "", verdict, flags=re.I).strip()[:80] or "needs a personal answer"
    return None
