"""A human day: asleep at night, slow during school, sometimes just slow — and only "online" when it makes sense.

Times are this machine's local time. Configure in .env:
  USERBOT_SLEEP=00:00-07:00          no replies; messages stay unread and are answered after waking up
  USERBOT_BUSY=08:30-15:30           weekdays: replies come with a delay (phone checked now and then)
  USERBOT_RHYTHM=false               switches all of this off (always answer right away)
"""
import asyncio
import logging
import random
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


def wait_seconds(chat_id: int) -> float:
    """How long before this chat gets looked at. An ongoing conversation is answered right away."""
    if not C.RHYTHM:
        return 0
    now = time.time()
    if now - _last_reply_at.get(chat_id, 0) < C.ACTIVE_CHAT_SECONDS:
        return 0  # we're mid-conversation
    if _available_at.get(chat_id, 0) > now:
        return _available_at[chat_id] - now  # already decided when; new messages don't push it back
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
