"""What the account knows: facts about you (a file you write) and notes about each person (kept automatically).

  userbot/facts.md              — you write this: who you are, school, schedule, family, interests…
  userbot/memory/people/<name>_<id>/notes.json — short notes per person, picked up from what THEY say (never
                                  from the bot's own replies, so it can't "remember" things it made up). Also:
                                  `.ai note <text>`. The rest of a person's folder is described in people.py.
Both are git-ignored and stay on this machine; they are sent to the model as part of the prompt.
"""
import json
import logging
import re
import time

import httpx

from . import config as C

log = logging.getLogger("userbot.memory")

MAX_NOTES = 40
EXTRACT = (
    "Below are messages that {who} sent in a private chat. Copy out only concrete facts they stated about themselves "
    "that will still matter in a week: where they live, study or work, family, birthdays and dates, plans with a "
    "date, things they asked you for and are waiting on. Write each fact in the SAME language they used, with "
    "their own words, as a short line starting with '- '. At most 3.\n"
    "Do NOT interpret, guess feelings or intentions, describe the conversation, or note questions, greetings, "
    "jokes, opinions or anything about AI or bots. If there is no such fact, answer exactly NONE.\n"
    "{known}\nMESSAGES:\n{messages}"
)
# things a model writes when it is interpreting instead of quoting a fact
SPECULATION_RE = re.compile(
    r"\b(may|might|seems?|appears?|possibly|probably|likely|suggest\w*|indicat\w*|seeking|questioning|skeptic\w*|"
    r"wants? to|needs? (a|to)|waiting for|validation|reassurance|conversation|message|asked (about|if|whether)|"
    r"возможно|видимо|похоже|кажется|наверное|хочет узнать|сомнева\w*|интересу\w*)\b|\b(ai|bot|ии|бот\w*)\b", re.I)


def grounded(note: str, their_text: str) -> bool:
    """A note is kept only if it reuses their own words and doesn't read like an interpretation."""
    if SPECULATION_RE.search(note):
        return False
    said = {w[:5] for w in re.findall(r"[^\W\d_]{4,}", their_text.lower())}
    words = [w[:5] for w in re.findall(r"[^\W\d_]{4,}", note.lower())]
    return bool(words) and sum(w in said for w in words) >= max(1, len(words) // 2)


def facts_block(name: str) -> str:
    if not C.FACTS_PATH.exists():
        return ""
    # Skip comments and template lines that were never filled in ("School: …" or "School:").
    lines = [ln.strip() for ln in C.FACTS_PATH.read_text().splitlines()
             if ln.strip() and not ln.lstrip().startswith("#") and "…" not in ln and not ln.rstrip().endswith(":")]
    facts = "\n".join(lines)
    if not facts:
        return ""
    # "what do you have tomorrow?" — a model gets the weekday wrong, so the right timetable lines are spelled out
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    table = {d: m.group(1).strip() for d in days if (m := re.search(rf"(?im)^Timetable {d}:\s*(.+)$", facts))}
    if table:
        now = time.localtime()
        for label, offset in (("TODAY", 0), ("TOMORROW", 1), ("THE DAY AFTER TOMORROW", 2), ("YESTERDAY", -1)):
            day = days[(now.tm_wday + offset) % 7]
            facts += f"\n{label} is {day}; lessons: {table.get(day, 'none — no school')}"
    today = today_note()
    if today:
        facts += f"\nToday ({time.strftime('%A')}): {today}"
    from . import lessons
    return lessons.block() + (f"\nTrue facts about your own life, {name}. They may be written in English, but you say them in the "
            "language of the chat (the school is «Лидер» in Russian) and you never write @usernames — use first "
            "names. These are background knowledge, NOT things to recite: "
            "mention a fact only when they ask about exactly that, and then give only that one thing in a few words "
            "(asked your name → just your first name; asked your school → just the school). Never volunteer other "
            "facts, never introduce yourself. Anything about your life that is NOT listed here you don't know, so "
            f"stay vague about it instead of making it up:\n{facts}\n")


def today_note() -> str:
    """What you told the account about today (`.ai today <text>`); forgotten when the day ends."""
    if not C.TODAY_PATH.exists():
        return ""
    try:
        data = json.loads(C.TODAY_PATH.read_text())
    except ValueError:
        return ""
    return "; ".join(data.get("notes", [])) if data.get("date") == time.strftime("%Y-%m-%d") else ""


def add_today(text: str) -> str:
    notes = today_note().split("; ") if today_note() else []
    notes.append(text.strip())
    C.TODAY_PATH.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "notes": notes}, ensure_ascii=False))
    return "; ".join(notes)


def _path(chat_id: int, who: str = "", create: bool = False):
    """notes.json inside the person's folder (see people.py); notes from before folders existed are moved in."""
    from . import people
    old = C.MEMORY_DIR / f"{chat_id}.json"
    path = people.folder(chat_id, who, create=create or old.exists())
    return path / "notes.json" if path else None


def notes(chat_id: int) -> list[dict]:
    path = _path(chat_id)
    return json.loads(path.read_text()) if path and path.exists() else []


def add_note(chat_id: int, text: str, source: str = "auto", who: str = "") -> bool:
    text = text.strip().lstrip("-• ").strip()
    items = notes(chat_id)
    if not text or any(text.lower() == n["text"].lower() for n in items):
        return False
    items.append({"text": text[:200], "date": time.strftime("%Y-%m-%d"), "source": source})
    _path(chat_id, who, create=True).write_text(json.dumps(items[-MAX_NOTES:], ensure_ascii=False, indent=1))
    return True


def clear_notes(chat_id: int) -> int:
    count, path = len(notes(chat_id)), _path(chat_id)
    if path:
        path.unlink(missing_ok=True)
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
                                                  "models": C.JUDGE_MODELS, "max_tokens": 150, "temperature": 0})
    except httpx.HTTPError:
        return []
    if resp.is_error:
        return []
    answer = resp.json()["reply"].strip()
    if answer.upper().startswith("NONE"):
        return []
    added = []
    for line in answer.splitlines()[:3]:
        if line.strip().startswith(("-", "•")) and grounded(line, text) and add_note(chat_id, line, who=who):
            added.append(line.strip().lstrip("-• ").strip())
    return added
