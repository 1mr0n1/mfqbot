"""A human day: asleep at night, slow during school, sometimes just slow — and only "online" when it makes sense.

Times are this machine's local time. Configure in .env:
  USERBOT_SLEEP=00:00-07:00          no replies; messages stay unread and are answered after waking up
  USERBOT_BUSY=08:30-15:30           weekdays: replies come with a delay (phone checked now and then)
  USERBOT_RHYTHM=false               switches all of this off (always answer right away)
"""
import asyncio
import itertools
import logging
import math
import random
import re
import time
from datetime import datetime, timedelta

from telethon import TelegramClient, functions

from . import config as C

log = logging.getLogger("userbot.rhythm")

_available_at: dict[int, float] = {}   # chat -> when "you" next look at the phone for that chat
_last_reply_at: dict[int, float] = {}  # chat -> when the last reply went out (an active chat gets fast answers)
_offline_task: asyncio.Task | None = None


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _in_window(window: str, now: datetime) -> bool:
    start, end = (_minutes(x) for x in window.split("-"))
    cur = now.hour * 60 + now.minute
    return start <= cur < end if start <= end else cur >= start or cur < end


def _wake_jitter(now: datetime) -> int:
    """Minutes after the alarm before the phone gets picked up — different every day, stable within a day."""
    return random.Random(now.strftime("%Y-%m-%d")).randint(*C.WAKE_JITTER_MIN)


def asleep(now: datetime | None = None) -> bool:
    if not C.RHYTHM:
        return False
    now = now or datetime.now()
    if _in_window(C.SLEEP_WINDOW, now):
        return True
    # still "not up yet" for a few minutes after the window ends
    earlier = now - timedelta(minutes=_wake_jitter(now))
    return _in_window(C.SLEEP_WINDOW, earlier)


def busy(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return C.RHYTHM and now.weekday() < 5 and _in_window(C.BUSY_WINDOW, now)


def status(now: datetime | None = None) -> str:
    """Where you most likely are right now, from your routine — so "ты где?" gets a sane answer, not an invention."""
    now = now or datetime.now()
    if _in_window(C.SLEEP_WINDOW, now):
        return "at home, in bed (it's night)"
    if now.weekday() < 5 and _in_window(C.BUSY_WINDOW, now):
        return "at school (in class or on a break)"
    if now.hour >= 20 or now.hour < 8:
        return "at home"
    return "out of school, free time — you don't say exactly where you are; 'занят', 'гуляю', 'по делам' is enough"


def wait_seconds(chat_id: int) -> float:
    """How long before this chat gets looked at. An ongoing conversation is answered right away."""
    if not C.RHYTHM:
        return 0
    now = time.time()
    if now - _last_reply_at.get(chat_id, 0) < C.ACTIVE_CHAT_SECONDS:
        return 0  # we're mid-conversation
    if _available_at.get(chat_id, 0) > now:
        # They wrote again while waiting: someone who keeps messaging gets looked at soon, not minutes later.
        _available_at[chat_id] = min(_available_at[chat_id], now + random.uniform(5, 20))
        return _available_at[chat_id] - now
    if busy():
        delay = random.uniform(*C.BUSY_DELAY)
    elif random.random() < C.SLOW_CHANCE:
        delay = random.uniform(*C.SLOW_DELAY)
    else:
        delay = 0
    _available_at[chat_id] = now + delay
    return delay


def replied(chat_id: int):
    _last_reply_at[chat_id] = time.time()
    _available_at.pop(chat_id, None)


async def _go_offline(client: TelegramClient, delay: float):
    try:
        await asyncio.sleep(delay)
        await client(functions.account.UpdateStatusRequest(offline=True))
    except asyncio.CancelledError:
        pass
    except Exception:
        log.debug("Could not set offline status", exc_info=True)


def online_for_a_bit(client: TelegramClient):
    """After doing something, stay "online" briefly, then go offline like someone putting the phone down."""
    global _offline_task
    if not C.RHYTHM:
        return
    if _offline_task and not _offline_task.done():
        _offline_task.cancel()
    _offline_task = asyncio.create_task(_go_offline(client, random.uniform(*C.ONLINE_LINGER)))


# ---------- pacing that depends on the message ----------

HARD_RE = re.compile(r"\d+\s*[%+\-*/x×]\s*\d+|сколько\s+будет|посчитай|реши|почему|зачем|объясни|расскажи|как\s+(сделать|это|работает)|"
                     r"что\s+(такое|думаешь)|выбрать|лучше|why|explain|how\s+(do|does|to|much|many)|what\s+(is|do\s+you\s+think)|"
                     r"which|should\s+i|nega|tushuntir|qaysi|qancha\s+bo'ladi", re.I)


def _vary(seconds: float, spread: float = 0.35) -> float:
    """People are never exactly consistent: multiply by a log-normal factor (usually 0.7x–1.4x, sometimes more)."""
    return seconds * math.exp(random.gauss(0, spread))


def reading_seconds(history) -> float:
    """Time to take in what they sent since your last message: text by length, voice by duration, a look at photos."""
    total = 0.0
    for msg in itertools.takewhile(lambda m: not m.out, history):
        text = msg.raw_text or ""
        duration = getattr(getattr(msg, "file", None), "duration", None) or 0
        if (getattr(msg, "voice", None) or getattr(msg, "video_note", None)) and duration:
            total += min(duration * random.uniform(0.7, 1.0), 45)   # you listen to it
        elif text:
            total += 0.4 + len(text) / random.uniform(18, 30)       # reading speed in characters per second
        if getattr(msg, "photo", None):
            total += random.uniform(1.5, 4.5)
        elif getattr(msg, "sticker", None):
            total += random.uniform(0.3, 1.0)
    return min(_vary(total, 0.25), 60)


def thinking_seconds(their_text: str, reply: str, chat_id: int | None = None) -> float:
    """How long before you start typing, depending on what was asked and what you're about to say."""
    words = len(reply.split())
    if HARD_RE.search(their_text):
        base = random.uniform(4, 14)        # needs working out
    elif "?" in their_text and words > 3:
        base = random.uniform(1.5, 5)       # a normal question
    elif words <= 2:
        base = random.uniform(0.3, 1.5)     # "да", "ок", "иду" come out instantly
    else:
        base = random.uniform(0.8, 3.5)
    if chat_id is not None and time.time() - _last_reply_at.get(chat_id, 0) < C.ACTIVE_CHAT_SECONDS:
        base *= 0.6                         # the conversation is flowing
    return min(_vary(base), 30)


def typing_plan(text: str) -> list[tuple[float, float]]:
    """-> [(seconds typing, seconds paused after)], so "typing…" can stop and start like a person hesitating."""
    speed = random.uniform(4.5, 10)         # characters per second; differs from message to message
    total = min(max(_vary(len(text) / speed, 0.25), 0.7), 25)
    if len(text) > 25 and random.random() < 0.25:   # stop mid-way, think, continue
        first = total * random.uniform(0.3, 0.7)
        return [(first, random.uniform(1, 3.5)), (total - first, 0)]
    return [(total, 0)]
