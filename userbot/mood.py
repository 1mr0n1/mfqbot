"""A mood for the day, and when the account shows up as online.

Nobody is the same person every day. Each morning one mood is drawn (the same all day, different tomorrow) and it
tints the replies: a tired day is shorter and slower, a good day asks more back. `.ai mood <name>` sets it by
hand for today; `.ai mood` shows it.

Presence: a person's "last seen" follows their day — nothing at night, short appearances in the breaks between
lessons, a look at the phone every so often in free time. Without this the account is only ever "online" in the
seconds around a reply, which is its own kind of tell.
"""
import asyncio
import logging
import random
import time
from datetime import datetime

from telethon import functions

from . import config as C
from . import rhythm

log = logging.getLogger("userbot.mood")

MOODS = {  # name: (weight, what the model is told, reply-delay multiplier)
    "normal": (50, "", 1.0),
    "good": (16, "You are in a good mood today: a bit more talkative and quicker to joke, and you ask things back.", 0.8),
    "tired": (14, "You are tired today: answers even shorter than usual, low energy, no jokes, you don't ask much.", 1.5),
    "lazy": (9, "You can't be bothered today: minimal answers, you put things off, nothing extra.", 1.4),
    "annoyed": (6, "You are a bit irritated today: dry, short, less patient with teasing — never rude to family.", 1.1),
    "busy": (5, "You have a lot going on today: quick, to the point, you wrap conversations up.", 1.2),
}
_forced: tuple[str, str] | None = None   # (date, mood) set by hand


def today() -> str:
    day = time.strftime("%Y-%m-%d")
    if _forced and _forced[0] == day:
        return _forced[1]
    if not C.MOOD_ON:
        return "normal"
    rng = random.Random("mood:" + day)
    names = list(MOODS)
    return rng.choices(names, weights=[MOODS[n][0] for n in names])[0]


def set_today(name: str) -> bool:
    global _forced
    name = name.strip().lower()
    if name not in MOODS:
        return False
    _forced = (time.strftime("%Y-%m-%d"), name)
    return True


def hint() -> str:
    text = MOODS[today()][1]
    return f"\n{text}\n" if text else ""


def slowdown() -> float:
    return MOODS[today()][2]


# ---------- presence ----------
BREAK_EVERY = 50      # a lesson plus its break, in minutes
BREAK_MINUTES = 10


def in_break(now: datetime) -> bool:
    """During school hours: is it one of the breaks between lessons? (lessons start at the top of BUSY_WINDOW)"""
    start = C.BUSY_WINDOW.split("-")[0]
    hour, minute = (int(x) for x in start.split(":"))
    since = (now.hour * 60 + now.minute) - (hour * 60 + minute)
    return since >= 0 and since % BREAK_EVERY >= BREAK_EVERY - BREAK_MINUTES


def next_look(now: datetime | None = None) -> tuple[float, float] | None:
    """-> (seconds until the account next shows up online, seconds it stays) — or None while asleep."""
    now = now or datetime.now()
    if rhythm.asleep(now):
        return None
    if rhythm.busy(now):
        if in_break(now):
            return random.uniform(20, 120), random.uniform(40, 150)   # phone out in the break
        return random.uniform(240, 600), 0                            # in class: check again later, stay offline
    return random.uniform(8 * 60, 35 * 60) * slowdown(), random.uniform(30, 180)   # free time: a look now and then


async def presence_loop(client, is_paused):
    """Show up online the way a person's day would: breaks, free time, never at night."""
    while True:
        try:
            plan = next_look() if C.PRESENCE_ON and C.RHYTHM and not is_paused() else None
            if plan is None:
                await asyncio.sleep(600)
                continue
            wait, stay = plan
            await asyncio.sleep(wait)
            if not stay or not C.PRESENCE_ON or rhythm.asleep() or (rhythm.busy() and not in_break(datetime.now())):
                continue
            await client(functions.account.UpdateStatusRequest(offline=False))
            await asyncio.sleep(stay)
            await client(functions.account.UpdateStatusRequest(offline=True))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("Presence update failed", exc_info=True)
            await asyncio.sleep(300)
