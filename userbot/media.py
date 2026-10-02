"""Stickers, GIFs and your own pre-recorded voice/round-video clips.

The model asks for media with a line of its own:
  [sticker 😭]        -> a sticker for that emoji (your favorites/recents first, then installed packs)
  [gif bro what]      -> first results from Telegram's @gif search
  [voice <tag>]       -> one of YOUR recorded voice messages from the clip library
  [video <tag>]       -> one of YOUR recorded round video messages from the clip library

Clip library: record a voice/round video in Saved Messages, reply to it with ".ai save <tag>".
Only a reference is stored (userbot/clips.json); the clip itself stays in your Saved Messages.
"""
import json
import logging
import random
import re

from telethon import TelegramClient, functions
from telethon.tl.types import DocumentAttributeSticker

from . import config as C

log = logging.getLogger("userbot.media")

MEDIA_LINE_RE = re.compile(r"^\[(sticker|gif|voice|video)\s+([^\]]+)\]$", re.I)
VARIATION = "️"


# ---------- clip library ----------

def load_clips() -> dict[str, dict]:
    return json.loads(C.CLIPS_PATH.read_text()) if C.CLIPS_PATH.exists() else {}


def save_clips(clips: dict[str, dict]):
    C.CLIPS_PATH.write_text(json.dumps(clips, ensure_ascii=False, indent=2))


def clip_kind(msg) -> str | None:
    if msg is None:
        return None
    if msg.voice:
        return "voice"
    if msg.video_note:
        return "video"
    return None


def add_clip(tag: str, msg) -> str | None:
    kind = clip_kind(msg)
    if kind:
        clips = load_clips()
        clips[tag.lower()] = {"kind": kind, "msg_id": msg.id}
        save_clips(clips)
    return kind


def remove_clip(tag: str) -> bool:
    clips = load_clips()
    if clips.pop(tag.lower(), None) is None:
        return False
    save_clips(clips)
    return True


# ---------- prompt ----------

def media_block(name: str) -> str:
    if not C.MEDIA_ENABLED:
        return ""
    clips = load_clips() if C.CLIPS_AUTO else {}   # your recorded clips are offered only if you allowed that
    voice = sorted(t for t, c in clips.items() if c["kind"] == "voice")
    video = sorted(t for t, c in clips.items() if c["kind"] == "video")
    lines = [
        f"\nYou can also send media the way {name} does — occasionally, not every reply. "
        "Put each on its own line, alone, exactly in this format:",
        "[sticker 😂] — a sticker for that one emoji",
        "[gif 2-3 search words] — a GIF",
    ]
    if voice:
        lines.append(f"[voice TAG] — one of {name}'s own voice messages. Available tags: {', '.join(voice)}")
    if video:
        lines.append(f"[video TAG] — one of {name}'s own round video messages. Available tags: {', '.join(video)}")
    lines.append("Never put anything else in square brackets.")
    return "\n".join(lines) + "\n"


# ---------- sending ----------

def _emoji_of(doc) -> str:
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeSticker):
            return (attr.alt or "").replace(VARIATION, "")
    return ""


async def find_sticker(client: TelegramClient, emoji: str):
    emoji = emoji.strip().replace(VARIATION, "")
    # Stickers you actually use first, so it feels like you.
    faved = await client(functions.messages.GetFavedStickersRequest(hash=0))
    recent = await client(functions.messages.GetRecentStickersRequest(hash=0, attached=False))
    yours = [d for d in getattr(faved, "stickers", []) + getattr(recent, "stickers", []) if _emoji_of(d) == emoji]
    if yours:
        return random.choice(yours[:5])
    found = await client(functions.messages.GetStickersRequest(emoticon=emoji, hash=0))
    stickers = getattr(found, "stickers", [])
    return random.choice(stickers[:8]) if stickers else None


async def send_media_line(client: TelegramClient, chat_id: int, kind: str, arg: str):
    """Send one media item. Returns the sent Message, or None if nothing suitable was found."""
    kind, arg = kind.lower(), arg.strip()
    if kind == "sticker":
        doc = await find_sticker(client, arg)
        if doc:
            return await client.send_file(chat_id, doc)
        # No sticker for that emoji: just send the emoji, like a person would.
        return await client.send_message(chat_id, arg) if len(arg) <= 4 else None
    if kind == "gif":
        results = await client.inline_query("gif", arg)
        if results:
            return await results[random.randrange(min(5, len(results)))].click(chat_id)
        return None
    clip = load_clips().get(arg.lower())
    if not clip or clip["kind"] != kind:
        log.info("No %s clip tagged %r", kind, arg)
        return None
    original = await client.get_messages("me", ids=clip["msg_id"])
    if not original or not original.media:
        log.warning("Clip %r is gone from Saved Messages — remove it with .ai forget %s", arg, arg)
        return None
    return await client.send_file(chat_id, original.media, voice_note=kind == "voice", video_note=kind == "video")
