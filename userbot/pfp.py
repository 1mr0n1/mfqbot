"""Someone asks you to use a photo as your profile picture -> the account does it, within limits.

Triggered only by an explicit request ("set this as your pfp", "поставь на аву", "avaga qo'y", ...) that comes with
a photo: in the same message, in the message it replies to, or sent just before. Before anything changes a
vision model must call the picture safe (fails closed), and changes are rate-limited. Every change is reported
in Saved Messages; `.ai pfp undo` removes the newest profile photo, which brings back the previous one.
"""
import base64
import itertools
import logging
import re

import httpx
from telethon import TelegramClient, functions, utils

from . import config as C
from .state import State

log = logging.getLogger("userbot.pfp")

# "profile picture" in the ways people say it (English / Russian / Uzbek)
REQUEST_RE = re.compile(
    r"\bpfp\b|\bavatar\w*|\bava\b|\bavaga\b|\bavatarga\b|\bprofil\w*\b.*\b(rasm\w*|photo|pic\w*|foto\w*)|\bprofile\s*(pic\w*|photo|image)"
    r"|\bprofilga\b|\bаватар\w*|\bав[ауы]\b|\bавк[ауи]\b|\bаватарк\w*|\bна\s+профиль\b|\bфото\s+профиля\b|\bпрофилга\b",
    re.I)
# ...and it has to be an actual request, not just a mention of a profile picture.
VERB_RE = re.compile(
    r"\b(set|put|use|make|change|update|switch)\b|постав\w*|смени\w*|поменя\w*|сдела\w*|установ\w*|измени\w*"
    r"|qo['‘’`]?y\w*|almashtir\w*|o['‘’`]?rnat\w*|o['‘’`]?zgartir\w*|қўй\w*|алмаштир\w*", re.I)


def is_request(text: str) -> bool:
    return bool(REQUEST_RE.search(text) and VERB_RE.search(text))


MAX_BYTES = 5_000_000
CHECK = ("Someone wants this image used as a public profile picture. Answer UNSAFE if it shows any of: nudity or "
         "sexual content, gore or graphic violence, hate symbols or extremist imagery, drugs, a document / ID / bank "
         "card / QR code / screenshot with private information, or insulting or obscene text. Otherwise answer SAFE. "
         "Answer with one word.")


async def find_request(history):
    """-> the photo message someone explicitly asked you to use as your profile picture, or None."""
    unanswered = list(itertools.takewhile(lambda m: not m.out, history))  # newest first
    requests = [m for m in unanswered if is_request(m.raw_text or "")]
    if not requests:
        return None
    for msg in requests:
        if msg.photo:  # the photo is attached to the request itself
            return msg
        if msg.is_reply:  # the request is a reply to a photo
            target = await msg.get_reply_message()
            if target and target.photo and not target.out:
                return target
    return next((m for m in unanswered if m.photo), None)  # otherwise the nearest photo they just sent


async def is_safe(http: httpx.AsyncClient, data: bytes) -> bool:
    content = [{"type": "text", "text": CHECK},
               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()}}]
    try:
        resp = await http.post("/complete", json={"messages": [{"role": "user", "content": content}],
                                                  "models": C.VISION_MODELS, "max_tokens": 10})
    except httpx.HTTPError:
        return False
    if resp.is_error:
        return False
    verdict = resp.json()["reply"].strip().lower()
    return verdict.startswith("safe")  # anything else, including no clear answer, counts as unsafe


async def apply(client: TelegramClient, state: State, http: httpx.AsyncClient, photo_msg, who: str) -> str:
    """-> 'changed' | 'limit' | 'unsafe' | 'error'"""
    if not state.pfp_allowed():
        return "limit"
    try:
        data = await photo_msg.download_media(file=bytes)
        if not data or len(data) > MAX_BYTES:
            return "error"
        if not await is_safe(http, data):
            log.info("Profile photo suggested by %s was not judged safe", who)
            return "unsafe"
        await client(functions.photos.UploadProfilePhotoRequest(
            file=await client.upload_file(data, file_name="profile.jpg")))
    except Exception:
        log.exception("Profile photo change failed")
        return "error"
    state.record_pfp()
    await client.send_message("me", f"🖼 profile photo changed — {who} asked for it. Undo with: .ai pfp undo")
    return "changed"


async def undo(client: TelegramClient) -> bool:
    """Delete the newest profile photo (the previous one becomes current again)."""
    photos = await client.get_profile_photos("me", limit=1)
    if not photos:
        return False
    await client(functions.photos.DeletePhotosRequest(id=[utils.get_input_photo(photos[0])]))
    return True


# What the model is told so its reply matches what actually happened.
HINTS = {
    "changed": "\nThey asked you to use their photo as your profile picture and you just did. Acknowledge it in a few words.\n",
    "limit": "\nThey asked you to use their photo as your profile picture. You didn't — you changed it too recently. "
             "Say so casually in a few words (maybe later).\n",
    "unsafe": "\nThey asked you to use their photo as your profile picture. You are not going to use that picture. "
              "Decline casually in a few words, without lecturing.\n",
    "error": "\nThey asked you to use their photo as your profile picture, but it didn't work. Say so in a few words.\n",
}
