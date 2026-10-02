"""What every part of the userbot shares: the Telegram client, the saved state, the backend connection, who
is being answered right now — and the small helpers for names, typing and sending."""
import asyncio
from collections import deque
import logging
import random
import re
import time
import httpx
from telethon import TelegramClient
from telethon.tl.types import User
from . import config as C
from . import rhythm
from . import trace
from .state import State


log = logging.getLogger("userbot")


TELEGRAM_SERVICE_ID = 777000  # login codes etc. — never auto-reply or send these to a model


client = TelegramClient(C.SESSION_PATH, C.API_ID, C.API_HASH)


state = State()


http = httpx.AsyncClient(base_url=C.BACKEND_URL, timeout=300)


pending: dict[int, asyncio.Task] = {}   # chat_id -> reply in progress


our_texts: dict[int, list[str]] = {}    # texts we're about to send, to recognize our own outgoing events


our_ids: set[int] = set()               # message ids sent by the userbot (vs. typed by you)


names: dict[int, str] = {}              # chat_id -> person's name, for logs


background_tasks: set[asyncio.Task] = set()


forced: set[int] = set()                # chats where you clicked "Answer now": skip hand-off / ignore / skip rules once


contacts: dict[int, User] = {}          # chat_id -> the person, for dashboard actions


me: User | None = None


revives: dict[int, int] = {}            # chat_id -> how many times in a row you tried to restart a dying chat


group_names: dict[int, str] = {}        # groups the account is in, for the dashboard list


group_seen: dict[int, int] = {}         # chat_id -> newest message id already looked at


group_done: set[tuple[int, int]] = set()  # (chat_id, message id) mentions that already got their answer


asked: dict[int, dict] = {}             # chat_id -> your question that is still waiting for an answer


commander_ids: set[int] = set()         # your own other accounts: what they write is an order


commanding: set[int] = set()            # chats where such an order is being carried out right now


recent_incoming: dict[int, deque] = {}  # chat_id -> their latest messages, to notice a flood


spam_until: dict[int, float] = {}       # chat_id -> no spamming back before this time


def rand(bounds: tuple[float, float]) -> float:
    return random.uniform(*bounds)


def cancel(chat_id: int):
    task = pending.pop(chat_id, None)
    if task:
        task.cancel()


def full_name(user: User) -> str:
    return " ".join(filter(None, [user.first_name, user.last_name])) or user.username or "someone"


def label(chat_id: int) -> str:
    return names.get(chat_id, str(chat_id))


async def resolve_name(chat_id: int) -> str:
    if chat_id not in names:
        try:
            entity = await client.get_entity(chat_id)
            names[chat_id] = full_name(entity) if isinstance(entity, User) else getattr(entity, "title", str(chat_id))
        except Exception:
            return str(chat_id)
    return names[chat_id]


def describe(msg) -> str:  # noqa: C901
    text = msg.raw_text or ""
    if msg.sticker:
        media = f"[sticker {getattr(msg.file, 'emoji', '') or ''}]".replace(" ]", "]")
    elif msg.voice:
        media = "[voice message]"
    elif msg.video_note:
        media = "[round video message]"
    elif msg.gif:
        media = "[gif]"
    elif msg.video:
        media = "[video]"
    elif msg.photo:
        media = "[photo]"
    elif msg.media:
        media = "[file]"
    else:
        media = ""
    return " ".join(filter(None, [media, text]))


def to_chat_messages(history) -> list[dict]:
    """Telegram history (newest first) -> OpenAI-style messages, merging consecutive same-role messages."""
    messages: list[dict] = []
    for msg in reversed(history):
        content = describe(msg)
        if not content:
            continue
        role = "assistant" if msg.out else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + content
        else:
            messages.append({"role": role, "content": content})
    return messages


def sent_by_us(chat_id: int, msg) -> bool:
    # our_ids covers this run; state.bot_sent survives restarts
    return msg.id in our_ids or state.sent_by_bot(chat_id, msg.id)


def owner_quiet_in(chat_id: int, history) -> float:
    """Seconds until you've been silent in this chat for OWNER_ACTIVE_WINDOW (0 = you're not active)."""
    now = time.time()
    last_manual = max((m.date.timestamp() for m in history if m.out and not sent_by_us(chat_id, m)), default=0)
    return max(last_manual + C.OWNER_ACTIVE_WINDOW - now, 0)


COMMAND_RE = re.compile(r"(?m)^\s*\.ai\b")  # a line that this account would read as one of your commands


def spawn(coro):
    task = asyncio.create_task(coro)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


async def hold_draft(draft_id: str, hold: float) -> tuple[str, list[str] | None]:
    """Keep the draft on the dashboard for `hold` seconds — or, in approve mode, until you decide.

    -> ("send", edited parts or None) | ("cancelled", None) | ("expired", None)"""
    started = time.monotonic()
    while True:
        st = await trace.draft_state(draft_id)
        if st.get("cancelled"):
            return "cancelled", None
        if st.get("send_now"):
            return "send", st.get("parts")
        waiting_for_you = state.approve or st.get("editing")  # you're deciding: don't send on a timer
        if time.monotonic() - started >= (C.APPROVE_TIMEOUT if waiting_for_you else hold):
            return ("expired", None) if waiting_for_you else ("send", st.get("parts"))
        await asyncio.sleep(0.4)


def pacing_on() -> bool:
    return C.PACING and bool(C.TYPING_LIMITS[1])  # the dashboard switch, and USERBOT_HUMAN_PACING


async def type_like_a_person(chat_id: int, text: str) -> float:
    """Show "typing…" for as long as this text would take — at a speed that varies, sometimes with a pause."""
    if not pacing_on():
        return 0
    plan = rhythm.typing_plan(text)
    for typing, pause in plan:
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(typing)
        if pause:
            await asyncio.sleep(pause)  # stopped typing for a moment
    return sum(a + b for a, b in plan)


async def send_as_bot(chat_id: int, text: str, **kwargs):
    """A text sent by the account itself (not typed by you): recorded so it isn't mistaken for you stepping in."""
    if COMMAND_RE.search(text):
        raise ValueError("a message that looks like an .ai command is never sent")
    our_texts.setdefault(chat_id, []).append(text)
    msg = await client.send_message(chat_id, text, **kwargs)
    our_ids.add(msg.id)
    state.record_sent(chat_id, msg.id)
    return msg


def set_chat_mode(chat_id: int, mode: str):
    if mode == "off":
        state.disable(chat_id)
        state.manual.discard(chat_id)
        state.save()
        cancel(chat_id)
    elif mode == "manual":
        state.set_manual(chat_id)
        cancel(chat_id)
    else:
        state.disabled.discard(chat_id)
        state.manual.discard(chat_id)
        state.save()


pilot_busy = asyncio.Lock()

