"""Keeps the account's bio alive on its own, the way a person occasionally updates theirs.

Every BIO_INTERVAL hours (random, never at night) it writes a new bio in the learned style. Chat content
is never used — a bio is public, so nothing from private conversations may leak into it. Changes are
noted in Saved Messages. It can't be triggered from chats, and it pauses with `.ai pause`.
Name, surname and photo are never changed automatically.
"""
import asyncio
import logging
import random
import re
import time
from datetime import datetime

import httpx
from telethon import TelegramClient, errors, functions
from telethon.tl.types import User

from . import config as C
from . import daylog, trace

GREETING_RE = re.compile(r"^(yo|hi|hey|hello|privet|привет|салам|salom)\b", re.I)
from .learn_style import SLUR_RE
from .state import State

log = logging.getLogger("userbot.autoprofile")

BAD_BIO_RE = re.compile(r"https?://|www\.|\bt\.me\b|\w\.(com|ru|uz|me|org|net|io)\b|@\w|#\w|\+?\d[\d\s-]{6,}"
                        r"|\b(bot|ai|assistant|auto-?reply)\b", re.I)


QUOTES = '"“”«»\'`'
# What the bio is about and which language it's in are picked in code, so bios actually vary.
THEMES = ["current mood", "energy / sleep level", "something you're hooked on lately", "a dry sarcastic status",
          "school or work grind", "gaming", "music", "food", "the time of day or the weather", "a single word",
          "being unbothered", "a tiny life motto"]
LANGUAGES = ["English"] * 3 + ["Russian"]


def clean_bio(text: str) -> str:
    bio = text.strip().splitlines()[0] if text.strip() else ""
    bio = re.sub(r"^(bio|new bio|mood)\s*:\s*", "", bio.strip().strip(QUOTES), flags=re.I)
    bio = re.sub(r"\s*[—–(\[-]\s*\d+\s*(chars?|characters|символ\w*)\s*[)\]]?\s*$", "", bio, flags=re.I)
    return bio.strip().strip(QUOTES).strip()


def _key(bio: str) -> str:
    return "".join(ch for ch in bio.lower() if ch.isalnum())


def too_similar(bio: str, history: list[str]) -> bool:
    key = _key(bio)
    return any(key in _key(old) or _key(old) in key for old in history if _key(old))


def acceptable(bio: str, history: list[str]) -> bool:
    return (0 < len(bio) <= C.BIO_MAX_CHARS and bool(_key(bio))
            and not BAD_BIO_RE.search(bio) and not SLUR_RE.search(bio) and not GREETING_RE.search(bio)
            and not re.search(r"[()\[\]—–:]", bio)  # commentary like "(but different) — not allowed"
            and not too_similar(bio, history))


async def write_bio(client: TelegramClient, http: httpx.AsyncClient, me: User, history: list[str]) -> str | None:
    profile = (C.STYLE_DIR / "profile.md").read_text() if (C.STYLE_DIR / "profile.md").exists() else ""
    # Deliberately NOT fed with chat content: a bio is public, private conversations must not leak into it.
    prompt = (
        f"You are {me.first_name}. Write your new Telegram bio — the short line under your name. "
        "A bio is a mood or a vibe, NOT a message to anyone: no greetings (no 'yo', 'hi', 'привет'), "
        "nothing addressed to a person, nothing about specific plans, people or events. "
        "1 to 5 words is ideal, 40 characters at most; lowercase is fine; at most one emoji, often none. "
        "No links, @mentions, phone numbers, hashtags, brackets or explanations.\n"
        f"This time make it about: {random.choice(THEMES)}. Write it in {random.choice(LANGUAGES)}.\n"
        f"Now: {datetime.now():%A, %H:%M}.\n"
        + (f"Already used, so use different words entirely: {' | '.join(history[-8:])}\n" if history else "")
        + (f"\nYour texting style, for word choice and language only:\n{profile}\n" if profile else "")
        + "\nReply with the bio text only, nothing else."
    )
    for _ in range(4):
        try:
            resp = await http.post("/complete", json={"messages": [{"role": "user", "content": prompt}],
                                                      "models": C.MODELS, "max_tokens": 60})
        except httpx.HTTPError as e:
            log.warning("Backend unreachable: %r", e)
            return None
        if resp.is_error:
            log.warning("Backend error %s", resp.status_code)
            return None
        bio = clean_bio(resp.json()["reply"])
        if acceptable(bio, history):
            return bio
        log.info("Rejected bio candidate %r", bio)
    return None


def next_change_at(state: State) -> float:
    if not state.last_bio_at:
        return time.time() + random.uniform(5, 15) * 60  # first one soon after setup
    return state.last_bio_at + random.uniform(*C.BIO_INTERVAL_HOURS) * 3600


async def bio_loop(client: TelegramClient, state: State):
    if not C.AUTO_BIO:
        return
    http = httpx.AsyncClient(base_url=C.BACKEND_URL, timeout=120)
    due = next_change_at(state)
    log.info("Auto-bio on; next change around %s", datetime.fromtimestamp(due).strftime("%H:%M %d.%m"))
    while True:
        await asyncio.sleep(max(due - time.time(), 0) + 1)
        hour = datetime.now().hour
        if state.is_paused() or C.BIO_QUIET_HOURS[0] <= hour < C.BIO_QUIET_HOURS[1]:
            due = time.time() + random.uniform(20, 60) * 60  # look again later
            continue
        try:
            me = await client.get_me()
            bio = await write_bio(client, http, me, state.bio_history)
            if bio:
                await client(functions.account.UpdateProfileRequest(about=bio))
                state.record_bio(bio)
                log.info("Bio changed to %r", bio)
                trace.emit("system", "", f"Changed my bio to: {bio}")
                daylog.record("profile", "", f"bio → {bio}")
                await client.send_message("me", f"✏️ bio updated: {bio}")
        except errors.RPCError as e:
            log.warning("Bio update refused: %s", e.__class__.__name__)
        except Exception:
            log.exception("Bio update failed")
        due = next_change_at(state) if state.last_bio_at > time.time() - 60 else time.time() + 3600
