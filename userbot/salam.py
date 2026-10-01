"""The Islamic greeting gets a fixed, correct answer — never left to the model.

Text  "Assalomu alaykum (va rahmatullohi va barokatuh)" in Latin / Cyrillic / Arabic script
      -> "Va alaykum assalom (va rahmatullohi va barokatuh)" in the same script and length.
Sticker showing that greeting -> the very same sticker is sent back, and its pack is saved to your account.

A sticker has no text, so it is recognized by (in order): what you taught it (`.ai salam` / `.ai notsalam`
as a reply to a sticker), the pack's name, or one look by a vision model. The verdict is remembered per sticker.
"""
import base64
import io
import itertools
import logging
import re
from dataclasses import dataclass

import httpx
from telethon import TelegramClient, functions
from telethon.tl.types import DocumentAttributeSticker, InputStickerSetEmpty

from . import config as C
from .state import State

log = logging.getLogger("userbot.salam")

# as-salamu alaykum, in the spellings people actually type
LATIN = r"\b(?:as+|es+)?[\s\-']*sal[ao]+m[ui]?n?[\s\-']*(?:u[\s\-']*)?[ao]l[aeo]y?i?k[uo]m\b"
CYRILLIC = r"\b(?:ас+|эс+)?[\s\-]*сал[аоя]+м[уи]?[\s\-]*[ауо]?[\s\-]*[ао]л[аеэ]йк[уо]м\b|\bас[\s\-]*саляму[\s\-]*[ау]лейкум\b"
ARABIC = r"السلام\s*عليكم"
SALAM_RE = re.compile(f"{LATIN}|{CYRILLIC}|{ARABIC}", re.I)
FULL_RE = re.compile(r"ra[hx]mat|ра[ҳхx]мат|رحمة|barak|barok|барак|барок|بركات", re.I)
TAIL_RE = re.compile(r"\b(va|wa|ва|و)\b|ra[hx]matul+o[hx]\w*|ра[ҳх]матул+о[ҳх]\w*|barak\w*|barok\w*|барак\w*|барок\w*"
                     r"|رحمة\s*الله|وبركاته|و", re.I)
PACK_RE = re.compile(r"sal[ao]m|салом|салям|салам|islam|ислам|muslim|мусулм|муслим|سلام", re.I)

REPLIES = {
    ("latin", True): "Va alaykum assalom va rahmatullohi va barokatuh",
    ("latin", False): "Va alaykum assalom",
    ("cyrillic", True): "Ва алайкум ассалом ва раҳматуллоҳи ва барокатуҳ",
    ("cyrillic", False): "Ва алайкум ассалом",
    ("arabic", True): "وعليكم السلام ورحمة الله وبركاته",
    ("arabic", False): "وعليكم السلام",
}


@dataclass
class Greeting:
    sticker: object = None    # incoming salam sticker message -> answer with the same sticker
    reply: str | None = None  # fixed text answer to a written salam
    rest: bool = False        # they also wrote something else that still needs a real answer


RESPONSE_RE = re.compile(r"\b(va|wa|ва|уа)\s*[’'`]?\s*a?[lл]?\w*[йy]?[кk][уu][мm]\b|^\W*(va|wa|ва)\s+[аa]l\w+|وعليكم", re.I)


def is_response(text: str) -> bool:
    """ "Va alaykum assalom" — they are answering your greeting."""
    return bool(RESPONSE_RE.search(text))


def text_reply(text: str) -> str | None:
    match = SALAM_RE.search(text)
    if not match or is_response(text):
        return None
    found = match.group(0)
    script = "arabic" if re.search("[؀-ۿ]", found) else "cyrillic" if re.search("[а-яё]", found, re.I) else "latin"
    return REPLIES[(script, bool(FULL_RE.search(text)))]


def remainder(text: str) -> str:
    """What's left of a message once the greeting itself is removed."""
    rest = TAIL_RE.sub(" ", SALAM_RE.sub(" ", text))
    return re.sub(r"[\s,.!:;\-–—]+", " ", rest).strip()


def strip_greeting_line(reply: str) -> str:
    """Drop a greeting the model added on its own — the fixed answer is already being sent."""
    lines = [line for line in reply.splitlines() if not (SALAM_RE.search(line) and len(remainder(line).split()) < 2)]
    return "\n".join(lines).strip()


def sticker_set_of(msg):
    for attr in msg.document.attributes:
        if isinstance(attr, DocumentAttributeSticker) and not isinstance(attr.stickerset, InputStickerSetEmpty):
            return attr.stickerset
    return None


async def save_pack(client: TelegramClient, msg) -> str | None:
    """Add the sticker's pack to your account. Returns the pack title, or None if it has no pack."""
    stickerset = sticker_set_of(msg)
    if not stickerset:
        return None
    pack = await client(functions.messages.GetStickerSetRequest(stickerset=stickerset, hash=0))
    await client(functions.messages.InstallStickerSetRequest(stickerset=stickerset, archived=False))
    return pack.set.title


async def _looks_like_salam(http: httpx.AsyncClient, msg) -> bool:
    """One look by a vision model at the sticker's preview image."""
    from PIL import Image

    raw = await msg.download_media(file=bytes, thumb=-1) or await msg.download_media(file=bytes)
    if not raw:
        return False
    try:
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return False  # animated/video sticker without a usable preview
    canvas = Image.new("RGB", image.size, (255, 255, 255))
    canvas.paste(image, mask=image.split()[3])
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=90)
    question = ('This is a Telegram sticker. Does it show the Islamic greeting "Assalomu alaykum" / "As-salamu alaykum" '
                '/ "Ассалому алайкум" / "السلام عليكم" (any spelling or script, with or without "va rahmatullohi va '
                'barokatuh")? Answer with one word: YES or NO.')
    content = [{"type": "text", "text": question},
               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}]
    try:
        resp = await http.post("/complete", json={"messages": [{"role": "user", "content": content}],
                                                  "models": C.VISION_MODELS, "max_tokens": 10})
    except httpx.HTTPError:
        return False
    return resp.is_success and resp.json()["reply"].strip().lower().startswith("yes")


async def is_salam_sticker(client: TelegramClient, state: State, http: httpx.AsyncClient, msg) -> bool:
    key = str(msg.document.id)
    if key in state.salam_stickers:
        return state.salam_stickers[key]
    verdict, why = False, "vision"
    stickerset = sticker_set_of(msg)
    if stickerset:
        try:
            pack = await client(functions.messages.GetStickerSetRequest(stickerset=stickerset, hash=0))
            if PACK_RE.search(f"{pack.set.title} {pack.set.short_name}"):
                # A salam-themed pack still has other stickers in it, so the picture decides.
                why = f"pack '{pack.set.title}' + vision"
        except Exception:
            log.exception("Could not read sticker pack")
    verdict = await _looks_like_salam(http, msg)
    log.info("Sticker %s: salam=%s (%s)", key, verdict, why)
    state.remember_salam_sticker(key, verdict)
    return verdict


async def check(client: TelegramClient, state: State, http: httpx.AsyncClient, history) -> Greeting:
    """Look at what the other person sent since your last message."""
    greeting = Greeting()
    for msg in itertools.takewhile(lambda m: not m.out, history):  # newest first
        text = msg.raw_text or ""
        if msg.sticker:
            if not greeting.sticker and await is_salam_sticker(client, state, http, msg):
                greeting.sticker = msg
            continue
        if SALAM_RE.search(text) and not is_response(text):
            greeting.reply = greeting.reply or text_reply(text)
            text = remainder(text)
        if len(text.split()) >= 2 or "?" in text or (msg.media and not msg.sticker):
            greeting.rest = True
    if greeting.sticker:
        greeting.reply = None  # the sticker is the answer
    return greeting
