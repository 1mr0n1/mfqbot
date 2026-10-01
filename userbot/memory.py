"""What the account knows: facts about you (a file you write) and notes about each person (kept automatically).

  userbot/facts.md              — you write this: who you are, school, schedule, family, interests…
  userbot/memory/<chat_id>.json — short notes per person, picked up from what THEY say (never from the bot's
                                  own replies, so it can't "remember" things it made up). Also: `.ai note <text>`.
Both are git-ignored and stay on this machine; they are sent to the model as part of the prompt.
"""
import json
import logging
import time

import httpx

from . import config as C

log = logging.getLogger("userbot.memory")

MAX_NOTES = 40
EXTRACT = (
    "Below are messages that {who} sent in a private chat. List anything worth remembering about THEM for future "
    "conversations: lasting facts about them (job, school, family, where they live, what they like), plans or dates "
    "they mentioned, things they asked for or are waiting on. Skip small talk, greetings, jokes and anything "
    "temporary. Each item: one short line in English, starting with '- They ' (never use their name). At most 3 items. "
    "If nothing is worth "
    "remembering, answer exactly NONE.\n{known}\nMESSAGES:\n{messages}"
)


def facts_block(name: str) -> str:
    if not C.FACTS_PATH.exists():
        return ""
    # Skip comments and template lines that were never filled in ("School: …" or "School:").
    lines = [ln.strip() for ln in C.FACTS_PATH.read_text().splitlines()
             if ln.strip() and not ln.lstrip().startswith("#") and "…" not in ln and not ln.rstrip().endswith(":")]
    facts = "\n".join(lines)
    if not facts:
        return ""
    return (f"\nTrue facts about your own life, {name}. These are background knowledge, NOT things to recite: "
            "mention a fact only when they ask about exactly that, and then give only that one thing in a few words "
            "(asked your name → just your first name; asked your school → just the school). Never volunteer other "
            "facts, never introduce yourself. Anything about your life that is NOT listed here you don't know, so "
            f"stay vague about it instead of making it up:\n{facts}\n")


def _path(chat_id: int):
    return C.MEMORY_DIR / f"{chat_id}.json"


def notes(chat_id: int) -> list[dict]:
    path = _path(chat_id)
    return json.loads(path.read_text()) if path.exists() else []


def add_note(chat_id: int, text: str, source: str = "auto") -> bool:
    text = text.strip().lstrip("-• ").strip()
    items = notes(chat_id)
    if not text or any(text.lower() == n["text"].lower() for n in items):
        return False
    items.append({"text": text[:200], "date": time.strftime("%Y-%m-%d"), "source": source})
    C.MEMORY_DIR.mkdir(exist_ok=True)
    _path(chat_id).write_text(json.dumps(items[-MAX_NOTES:], ensure_ascii=False, indent=1))
    return True


def clear_notes(chat_id: int) -> int:
    count = len(notes(chat_id))
    _path(chat_id).unlink(missing_ok=True)
    return count


def notes_block(chat_id: int, who: str) -> str:
    items = notes(chat_id)
    if not items:
        return ""
    lines = []
    for n in items:
        text = n["text"][0].lower() + n["text"][1:] if n["text"].lower().startswith("they ") else n["text"]
        lines.append(f"- {text} ({n['date']})")
    return (f"\nThe person texting you right now is {who}. Things {who} told you earlier — these are about THEM, the "
            f"person you are replying to, not about some third person; use them when relevant, don't recite them:\n"
            + "\n".join(lines) + "\n")


async def remember(http: httpx.AsyncClient, chat_id: int, who: str, their_messages: list[str]) -> list[str]:
    """After a reply went out: note anything durable THEY said. Runs in the background; failures are harmless."""
    text = "\n".join(m.replace("\n", " ")[:300] for m in their_messages if m.strip())
    if len(text.split()) < 6:
        return []
    known = notes(chat_id)
    prompt = EXTRACT.format(
        who=who, messages=text,
        known=("Already known (don't repeat):\n" + "\n".join(f"- {n['text']}" for n in known) + "\n") if known else "")
    try:
        resp = await http.post("/complete", json={"messages": [{"role": "user", "content": prompt}],
                                                  "models": C.MODELS, "max_tokens": 150, "temperature": 0})
    except httpx.HTTPError:
        return []
    if resp.is_error:
        return []
    answer = resp.json()["reply"].strip()
    if answer.upper().startswith("NONE"):
        return []
    added = []
    for line in answer.splitlines()[:3]:
        if line.strip().startswith(("-", "•")) and add_note(chat_id, line):
            added.append(line.strip().lstrip("-• ").strip())
    return added
