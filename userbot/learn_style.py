"""Learn how you text from your own sent messages, so the userbot can imitate you.

Reads ONLY messages you sent in private chats. Stats are computed locally; a sample of your own
messages (never other people's) is sent to the backend model to write a style profile.

Outputs (git-ignored, contain your personal messages):
  userbot/style/stats.json     — local statistics
  userbot/style/examples.json  — bank of your real messages used as few-shot examples
  userbot/style/profile.md     — written style guide injected into the persona

Run with the userbot stopped:  .venv/bin/python -m userbot.learn_style
Learn from another logged-in session (see login.py):  .venv/bin/python -m userbot.learn_style main
"""
import asyncio
import json
import random
import re
import sys
from collections import Counter

import httpx
from telethon import TelegramClient
from telethon.tl.types import User

from . import config as C
from .state import State

MAX_DIALOGS = 300            # most recent private chats to scan
MAX_PER_CHAT = 400           # your messages per chat
PROFILE_SAMPLE = 350         # your messages sent to the model to write the profile
EXAMPLE_BANK = 400           # your messages kept for few-shot examples
TELEGRAM_SERVICE_ID = 777000
MIN_MESSAGES = 150           # below this the profile is mostly noise

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F1E6-\U0001F1FF]")
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
URL_RE = re.compile(r"https?://\S+")
# Messages with slurs are left out of learning so the userbot never repeats them to other people.
SLUR_RE = re.compile(r"\bn[i1!]+gg(?:er|a|ah|az|as|ers|uh)s?\b|\bnibba\w*|\bниг+ер\w*|\bниг+а\b", re.I)


def usable(text: str) -> bool:
    return bool(text) and not SLUR_RE.search(text)


def script_of(text: str) -> str:
    cyr = len(re.findall(r"[А-Яа-яЁёЎўҚқҒғҲҳ]", text))
    lat = len(re.findall(r"[A-Za-z]", text))
    return "cyrillic" if cyr > lat else "latin" if lat else "other"


def compute_stats(messages: list[str], per_chat_counts: Counter) -> dict:
    n = len(messages)
    lengths = sorted(len(m) for m in messages)
    letters_start = [m for m in messages if m[0].isalpha()]
    words = Counter(w.lower() for m in messages for w in WORD_RE.findall(m))
    emojis = Counter(e for m in messages for e in EMOJI_RE.findall(m))
    endings = Counter(m[-1] if not m[-1].isalnum() else "<letter/digit>" for m in messages)
    openers = Counter(WORD_RE.findall(m.lower())[0] for m in messages if WORD_RE.findall(m))
    from . import punct
    return {
        "punct": punct.measure(messages),
        "messages_analyzed": n,
        "chats_analyzed": len(per_chat_counts),
        "length_chars": {"median": lengths[n // 2], "p90": lengths[int(n * 0.9)], "max": lengths[-1]},
        "starts_lowercase_pct": round(100 * sum(m[0].islower() for m in letters_start) / max(len(letters_start), 1)),
        "ends_with": {k: round(100 * v / n) for k, v in endings.most_common(8)},
        "with_emoji_pct": round(100 * sum(bool(EMOJI_RE.search(m)) for m in messages) / n),
        "top_emojis": [e for e, _ in emojis.most_common(15)],
        "scripts_pct": {k: round(100 * v / n) for k, v in Counter(script_of(m) for m in messages).items()},
        "top_words": [w for w, _ in words.most_common(80)],
        "top_openers": [w for w, _ in openers.most_common(25)],
        "bracket_smiles_pct": round(100 * sum(bool(re.search(r"\){1,}\s*$", m)) for m in messages) / n),
    }


async def collect(client: TelegramClient) -> tuple[list[str], Counter]:
    me = await client.get_me()
    state = State()
    messages: list[str] = []
    per_chat: Counter = Counter()
    async for dialog in client.iter_dialogs(limit=MAX_DIALOGS):
        entity = dialog.entity
        if not isinstance(entity, User) or entity.bot or entity.id in (me.id, TELEGRAM_SERVICE_ID):
            continue
        async for msg in client.iter_messages(entity, from_user="me", limit=MAX_PER_CHAT):
            text = URL_RE.sub("", msg.raw_text or "").strip()
            if usable(text) and not text.startswith(".ai") and not msg.fwd_from \
                    and not state.sent_by_bot(entity.id, msg.id):
                messages.append(text)
                per_chat[entity.id] += 1
        print(f"  {dialog.name[:30]:30} {per_chat[entity.id]:4} messages", flush=True)
    return messages, per_chat


async def write_profile(messages: list[str], stats: dict) -> str:
    sample = random.sample(messages, min(PROFILE_SAMPLE, len(messages)))
    prompt = (
        "Below are statistics and a random sample of Telegram messages written by ONE person. "
        "Write a precise style guide (in English, as bullet points, max ~350 words) that would let someone "
        "text EXACTLY like this person. Describe each language they use SEPARATELY (Russian, English, Uzbek — whichever appear): how they write in it, "
        "typical words and phrases in it, how formal they are. Then cover: when they switch/mix languages, typical length and "
        "message-splitting, capitalization and punctuation habits, emoji/smiley habits (e.g. ')' smiles), "
        "slang, abbreviations and signature words/phrases (quote them literally), greetings and sign-offs, "
        "how they agree/refuse/laugh, and overall tone. Only describe what the data shows; do not invent, and never "
        "list a word just to say it is absent. Do not include names or nicknames of people.\n\n"
        f"STATISTICS:\n{json.dumps(stats, ensure_ascii=False, indent=1)}\n\n"
        "MESSAGES (one per line):\n" + "\n".join(m.replace("\n", " / ") for m in sample)
    )
    async with httpx.AsyncClient(base_url=C.BACKEND_URL, timeout=600) as http:
        resp = await http.post("/complete", json={"messages": [{"role": "user", "content": prompt}],
                                                  "models": C.MODELS, "max_tokens": 12000,
                                                  "reasoning": True})
    resp.raise_for_status()
    return resp.json()["reply"]


async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    client = TelegramClient(str(C.HERE / name) if name else C.SESSION_PATH, C.API_ID, C.API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit(f"Not logged in. Run once: .venv/bin/python -m userbot.login {name or ''}".strip())

    print("Collecting your sent messages from private chats...")
    messages, per_chat = await collect(client)
    await client.disconnect()
    await build_style(messages, compute_stats(messages, per_chat))


async def build_style(messages: list[str], stats: dict):
    """Shared by live-account learning and export import: saves stats, example bank and profile."""
    if len(messages) < MIN_MESSAGES:
        raise SystemExit(f"Only {len(messages)} of your messages found (need {MIN_MESSAGES}+) — "
                         "not enough to learn a style. Use an account you actually chat from.")
    C.STYLE_DIR.mkdir(exist_ok=True)
    (C.STYLE_DIR / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2))

    # Example bank: favor normal chat messages over very long ones.
    candidates = [m for m in set(messages) if len(m) <= 200]
    bank = random.sample(candidates, min(EXAMPLE_BANK, len(candidates)))
    (C.STYLE_DIR / "examples.json").write_text(json.dumps(bank, ensure_ascii=False, indent=1))

    print(f"\n{stats['messages_analyzed']} messages from {stats['chats_analyzed']} chats. Writing style profile...")
    profile = await write_profile(messages, stats)
    (C.STYLE_DIR / "profile.md").write_text(profile + "\n")
    print(f"\nSaved to {C.STYLE_DIR}/\n\n{profile}")


if __name__ == "__main__":
    asyncio.run(main())
