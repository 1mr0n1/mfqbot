"""One folder per person: who they are, how close you are, what to ask them about later.

  userbot/memory/people/<name>_<telegram id>/
      profile.json   who this is: the name they gave, their Telegram name, when they first wrote, how close you are
      notes.json     facts they stated about themselves (see memory.py)
      threads.json   things coming up in their life, to ask about afterwards ("экзамен завтра" -> "ну как экзамен?")

Everything stays on this machine (git-ignored). You can edit the files by hand — e.g. set "closeness" in
profile.json to "close", "known" or "stranger" and it is kept.
"""
import json
import logging
import re
import time
from datetime import date, datetime, timedelta

import httpx

from . import config as C

log = logging.getLogger("userbot.people")

CLOSE_AT = 400      # this many messages between you two -> a close friend
KNOWN_AT = 40       # this many -> someone you know
RECOUNT_AFTER = 24 * 3600


def root():
    return C.MEMORY_DIR / "people"


def folder(chat_id: int, name: str = "", create: bool = False):
    """The person's folder; found by the id at the end of its name, so renaming the front part is fine."""
    base = root()
    found = next(iter(base.glob(f"*_{chat_id}")), None) if base.exists() else None
    if found or not create:
        return found
    slug = re.sub(r"[^\w]+", "-", name, flags=re.U).strip("-")[:30] or "person"
    path = base / f"{slug}_{chat_id}"
    path.mkdir(parents=True, exist_ok=True)
    old = C.MEMORY_DIR / f"{chat_id}.json"  # notes from before people had folders
    if old.exists():
        old.rename(path / "notes.json")
    return path


def _read(chat_id: int, file: str, default):
    path = folder(chat_id)
    if not path or not (path / file).exists():
        return default
    try:
        return json.loads((path / file).read_text())
    except ValueError:
        return default


def _write(chat_id: int, name: str, file: str, data):
    (folder(chat_id, name, create=True) / file).write_text(json.dumps(data, ensure_ascii=False, indent=1))


def profile(chat_id: int) -> dict:
    return _read(chat_id, "profile.json", {})


def save_profile(chat_id: int, name: str, **fields) -> dict:
    data = profile(chat_id)
    data.setdefault("id", chat_id)
    data.setdefault("first_seen", time.strftime("%Y-%m-%d"))
    data.update({k: v for k, v in fields.items() if v is not None})
    _write(chat_id, name, "profile.json", data)
    return data


# ---------- who is this? ----------
INTRO_RE = re.compile(r"\b(это|я|меня\s+зовут|зовут|this\s+is|i'?m|i\s+am|my\s+name\s+is|it'?s|men|ismim|man)\b", re.I)
WHO = ('Someone you didn\'t know was asked "who is this?" (or introduced themselves). Their messages:\n{text}\n\n'
       'If they say who they are, answer with one JSON object: {{"name": "<their first name, exactly as they wrote '
       'it>", "about": "<how they described themselves in a few of their own words: class, where you know them '
       'from — or empty>"}}. If they did not say who they are, answer exactly NONE.')
ASK_HINT = ("\nYou don't know who this is: the number isn't in your contacts and you have never talked. Answer what "
            "they wrote in a word or two, and ask who it is — one short casual line in their language (\"а кто это?\", "
            "\"who's this?\", \"kim bu?\"). Nothing else.\n")


async def introduced(http: httpx.AsyncClient, text: str) -> dict | None:
    """-> {"name", "about"} if these messages say who the person is. The name must be a word they really wrote."""
    if not text.strip() or len(text.split()) > 60:
        return None
    if len(text.split()) > 3 and not INTRO_RE.search(text):
        return None  # a longer message with no "я / это / I'm": not an introduction, don't spend a model call
    try:
        resp = await http.post("/complete", json={"messages": [{"role": "user", "content": WHO.format(text=text[:600])}],
                                                  "models": C.JUDGE_MODELS, "max_tokens": 60, "temperature": 0})
    except httpx.HTTPError:
        return None
    if resp.is_error:
        return None
    answer = resp.json()["reply"]
    start = answer.find("{")
    if start == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(answer[start:])
    except ValueError:
        return None
    name = str(data.get("name") or "").strip()
    if not (2 <= len(name) <= 30) or name.lower() not in text.lower() or not re.fullmatch(r"[^\W\d_][\w .'ʻ’-]*", name):
        return None
    if name.lower() in ("я", "это", "me", "i", "man", "men", "бот", "bot", "друг", "friend"):
        return None
    about = str(data.get("about") or "").strip()
    return {"name": name[:1].upper() + name[1:], "about": about[:40] if about.lower() in text.lower() else ""}


ASKS_WHO_RE = re.compile(r"\bкто\b|\bwho\b|\bkim\b|\bкак\s+(тебя|вас)\s+зовут|your\s+name", re.I)
WHO_LINES = {"ru": "а кто это?", "en": "who's this?", "uz": "kim bu?"}


# ---------- how close ----------
FAMILY = r"mom|mother|dad|father|sister|brother|uncle|aunt|grandma|grandpa|cousin|мам\w*|пап\w*|сестр\w*|брат\w*|дяд\w*|т[её]т\w*"


def family_role(username: str | None) -> str | None:
    """ "@x is my mom" in facts.md -> "mom"."""
    if not username or not C.FACTS_PATH.exists():
        return None
    match = re.search(rf"@{re.escape(username)}\b\s*(?:is|=|-|—)?\s*(?:is\s+)?my\s+(?:\w+\s+)?({FAMILY})\b",
                      C.FACTS_PATH.read_text(), re.I)
    return match.group(1).lower() if match else None


async def closeness(client, chat_id: int, contact, has_style: bool) -> str:
    """-> "family" | "close" | "known" | "stranger". Counted from how much you two have written; a value you put
    into profile.json yourself ("closeness_by": "you") is never overwritten."""
    data = profile(chat_id)
    if data.get("closeness_by") == "you" and data.get("closeness"):
        return data["closeness"]
    if data.get("closeness") and time.time() - data.get("counted_at", 0) < RECOUNT_AFTER:
        return data["closeness"]
    if family_role(getattr(contact, "username", None)):
        level, total = "family", None
    else:
        try:
            total = (await client.get_messages(chat_id, limit=0)).total
        except Exception:
            total = None
        level = ("close" if has_style or (total or 0) >= CLOSE_AT
                 else "known" if getattr(contact, "contact", False) or (total or 0) >= KNOWN_AT else "stranger")
    name = " ".join(x for x in (getattr(contact, "first_name", ""), getattr(contact, "last_name", "")) if x)
    save_profile(chat_id, name, closeness=level, closeness_by="count", counted_at=time.time(), messages=total,
                 telegram_name=name, username=getattr(contact, "username", None))
    return level


CLOSENESS_HINT = {
    "family": "\nThis is your family. Be yourself but respectful: short and warm, no swearing, no teasing back.\n",
    "close": "\nThis is a close friend. You joke, tease back and use your slang freely with them.\n",
    "known": "\nYou know this person, but you are not close: friendly and short, little slang, no teasing.\n",
    "stranger": "\nYou barely know this person: polite, short and dry. No jokes, no slang, nothing personal about "
                "yourself beyond what they ask.\n",
}


# ---------- things to ask about later ----------
UPCOMING_RE = re.compile(
    r"завтра|послезавтра|сегодня\s+(вечером|ночью|после)|на\s+выходных|в\s+(понедельник|вторник|среду|четверг|пятницу|"
    r"субботу|воскресенье)|через\s+(\d+|пару|несколько)\s+(дн|недел)|экзамен|контрольн|зач[её]т|соревнован|матч|турнир|"
    r"врач|больниц|операци|день\s+рождения|\bдр\b|поездк|уезжа|улета|собеседован|олимпиад|"
    r"tomorrow|tonight|this\s+weekend|next\s+week|on\s+(mon|tues|wednes|thurs|fri|satur|sun)day|exam|test|tournament|"
    r"interview|doctor|birthday|trip|flight|ertaga|indinga|imtihon|musobaqa|tug'ilgan", re.I)
THREAD = ('Today is {today}. A friend wrote this in a chat:\n{text}\n\nIs there ONE specific thing coming up in THEIR '
          'life that a friend would ask about afterwards (an exam, a match, a trip, a doctor visit, a birthday, an '
          'interview)? Answer with one JSON object: {{"what": "<the thing, in their own words, 2-5 words>", '
          '"when": "<YYYY-MM-DD: the day it happens>"}} — or exactly NONE.')


def threads(chat_id: int) -> list[dict]:
    return _read(chat_id, "threads.json", [])


async def note_upcoming(http: httpx.AsyncClient, chat_id: int, who: str, text: str) -> dict | None:
    """They mentioned something coming up: remember it, with the day from which asking about it makes sense."""
    if not UPCOMING_RE.search(text) or len(text.split()) < 3:
        return None
    try:
        resp = await http.post("/complete", json={"messages": [{"role": "user", "content": THREAD.format(
            today=datetime.now().strftime("%A %Y-%m-%d"), text=text[:800])}],
            "models": C.JUDGE_MODELS, "max_tokens": 60, "temperature": 0})
    except httpx.HTTPError:
        return None
    if resp.is_error:
        return None
    answer = resp.json()["reply"]
    start = answer.find("{")
    if start == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(answer[start:])
        due = date.fromisoformat(str(data.get("when", ""))[:10]) + timedelta(days=1)  # ask once it is over
    except ValueError:
        return None
    what = str(data.get("what") or "").strip()
    said = {w[:5] for w in re.findall(r"[^\W\d_]{4,}", text.lower())}
    words = [w[:5] for w in re.findall(r"[^\W\d_]{4,}", what.lower())]
    if not what or not words or not any(w in said for w in words):
        return None  # not their words: the model made it up
    if not (date.today() < due <= date.today() + timedelta(days=22)):
        return None
    items = threads(chat_id)
    if any(t["what"].lower() == what.lower() for t in items):
        return None
    item = {"what": what[:60], "ask_after": due.isoformat(), "noted": time.strftime("%Y-%m-%d"), "asked": False}
    _write(chat_id, who, "threads.json", (items + [item])[-12:])
    return item


def due_thread(chat_id: int) -> dict | None:
    """Something they told you about that has happened by now and you haven't asked about (not older than 4 days)."""
    today = date.today()
    for item in threads(chat_id):
        try:
            due = date.fromisoformat(item["ask_after"])
        except (KeyError, ValueError):
            continue
        if not item.get("asked") and due <= today <= due + timedelta(days=4):
            return item
    return None


def mark_asked(chat_id: int, who: str, what: str):
    items = threads(chat_id)
    for item in items:
        if item["what"] == what:
            item["asked"] = True
    _write(chat_id, who, "threads.json", items)


def thread_hint(item: dict) -> str:
    return (f"\nEarlier they told you about this in their life: “{item['what']}” — it has happened by now. If it fits "
            "the conversation, ask how it went, in a few words. Don't force it in if they are talking about something "
            "else entirely.\n")


def everyone() -> list[dict]:
    """All profiles (for picking someone to write to first)."""
    out = []
    if root().exists():
        for path in root().iterdir():
            file = path / "profile.json"
            if file.exists():
                try:
                    out.append(json.loads(file.read_text()))
                except ValueError:
                    pass
    return out
