"""Userbot: replies from your own Telegram account, paced like a human.

Control it by sending these from your account (they're deleted instantly; confirmations go to Saved Messages):
  .ai on / .ai off   — in a private chat: enable/disable auto-replies there
  .ai pause / resume — anywhere: stop/restart all auto-replies
  .ai status         — anywhere: show current state
"""
import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime

import httpx
from telethon import TelegramClient, events
from telethon.tl.types import User

from . import config as C
from .state import State

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("userbot")

TELEGRAM_SERVICE_ID = 777000  # login codes etc. — never auto-reply or send these to a model

client = TelegramClient(C.SESSION_PATH, C.API_ID, C.API_HASH)
state = State()
http = httpx.AsyncClient(base_url=C.BACKEND_URL, timeout=300)
persona = C.PERSONA_PATH.read_text()

pending: dict[int, asyncio.Task] = {}   # chat_id -> reply in progress
our_texts: dict[int, list[str]] = {}    # texts we're about to send, to recognize our own outgoing events
our_ids: set[int] = set()               # message ids sent by the userbot (vs. typed by you)
me: User | None = None


def rand(bounds: tuple[float, float]) -> float:
    return random.uniform(*bounds)


def typing_time(text: str) -> float:
    return min(max(len(text) / rand(C.TYPING_CHARS_PER_SEC), C.TYPING_LIMITS[0]), C.TYPING_LIMITS[1])


def cancel(chat_id: int):
    task = pending.pop(chat_id, None)
    if task:
        task.cancel()


def full_name(user: User) -> str:
    return " ".join(filter(None, [user.first_name, user.last_name])) or user.username or "someone"


def describe(msg) -> str:
    text = msg.raw_text or ""
    if msg.sticker:
        media = f"[sticker {getattr(msg.file, 'emoji', '') or ''}]".replace(" ]", "]")
    elif msg.voice:
        media = "[voice message]"
    elif msg.video_note or msg.video or msg.gif:
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


def owner_quiet_in(history) -> float:
    """Seconds until you've been silent in this chat for OWNER_ACTIVE_WINDOW (0 = you're not active)."""
    now = time.time()
    last_manual = max((m.date.timestamp() for m in history if m.out and m.id not in our_ids), default=0)
    return max(last_manual + C.OWNER_ACTIVE_WINDOW - now, 0)


# Last line of defense: never send something that looks like the model's reasoning or instructions.
LEAK_RE = re.compile(r"\b(the user|we need to|we must|the instruction|system prompt|as an ai|language model)\b"
                     r"|\{(name|contact|style|now)\}", re.I)
MAX_REPLY_CHARS = 700


def looks_safe(reply: str) -> bool:
    return len(reply) <= MAX_REPLY_CHARS and not LEAK_RE.search(reply)


# Lines that make it sound like a customer-support bot get dropped.
ASSISTANT_RE = re.compile(r"\b(assist|let me know if you need|anything else|how can i help|feel free|happy to help)\b",
                          re.I)

# Asking whether they're talking to a bot/AI gets an honest fixed answer — never left to the model.
BOT_QUESTION_RE = re.compile(r"\b(bot|robot|ai|a\.i\.|chat ?gpt|gpt|neural|автоответчик|бот|робот|ии|нейросеть|"
                             r"нейронка|чатгпт)\b", re.I)
ADDRESSED_RE = re.compile(r"\?|\b(u|you|ur|r u|are|is this|ты|вы|тебя|это)\b", re.I)
HONEST_REPLY = {
    "cyrillic": "Я сейчас занят, это автоответ. Отвечу лично чуть позже",
    "latin": "im busy rn, this is an auto-reply. ill answer personally later",
}


def asks_if_bot(history) -> bool:
    """True if the other person's latest messages (since your last one) ask about a bot/AI."""
    for msg in history:  # newest first
        if msg.out:
            return False
        text = msg.raw_text or ""
        if BOT_QUESTION_RE.search(text) and ADDRESSED_RE.search(text):
            return True
    return False


def clean_reply(reply: str) -> str:
    return "\n".join(line for line in reply.splitlines() if not ASSISTANT_RE.search(line)).strip()


def split_reply(reply: str) -> list[str]:
    parts = [p.strip() for p in reply.splitlines() if p.strip()]
    if len(parts) > C.MAX_PARTS:
        parts = parts[:C.MAX_PARTS - 1] + ["\n".join(parts[C.MAX_PARTS - 1:])]
    return parts


def style_block() -> str:
    """Learned style (see learn_style.py). Re-read every time so re-learning needs no restart."""
    profile_path, examples_path = C.STYLE_DIR / "profile.md", C.STYLE_DIR / "examples.json"
    if not profile_path.exists():
        return ""
    block = f"How {full_name(me)} texts — follow this closely, it matters more than the generic rules above:\n"
    block += profile_path.read_text().strip() + "\n"
    if examples_path.exists():
        examples = json.loads(examples_path.read_text())
        picks = random.sample(examples, min(C.STYLE_EXAMPLES, len(examples)))
        block += ("\nReal messages they've sent (for style only — don't reuse their content):\n"
                  + "\n".join(f"- {m.replace(chr(10), ' / ')}" for m in picks) + "\n")
    return block


async def generate(history, contact: User) -> str | None:
    messages = to_chat_messages(history)
    if not messages or messages[-1]["role"] != "user":
        return ""  # nothing to answer (None means the backend failed)
    system = persona.format(name=full_name(me), contact=full_name(contact), style=style_block(),
                            now=datetime.now().strftime("%A %d %B %Y, %H:%M"))
    try:
        resp = await http.post("/complete", json={"messages": messages, "system": system, "models": C.MODELS})
    except httpx.HTTPError as e:
        log.warning("Backend unreachable: %r", e)
        return None
    if resp.is_error:
        log.warning("Backend error %s: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    log.info("Reply generated by %s", data["model"])
    return data["reply"]


async def reply_flow(chat_id: int, contact: User):
    try:
        await asyncio.sleep(rand(C.DEBOUNCE) + rand(C.READ_DELAY))

        # If you've been chatting here yourself, hold off until you've gone quiet, then re-check.
        # (Your own new message in the chat cancels this task entirely.)
        while True:
            history = await client.get_messages(chat_id, limit=C.CONTEXT_MESSAGES)
            wait = owner_quiet_in(history)
            if not wait:
                break
            log.info("Chat %s: you're active here, holding off %.0fs", chat_id, wait)
            await asyncio.sleep(wait + rand(C.READ_DELAY))
        await client.send_read_acknowledge(chat_id)
        await asyncio.sleep(rand(C.THINK_DELAY))

        started = time.monotonic()
        if asks_if_bot(history):
            last = next((m.raw_text for m in history if not m.out and m.raw_text), "")
            reply = HONEST_REPLY["cyrillic" if re.search("[А-Яа-я]", last) else "latin"]
            await client.send_message("me", f"🤖 {full_name(contact)} asked if they're talking to a bot — "
                                            f"sent the honest auto-reply. You may want to answer yourself.")
        else:
            for attempt in range(C.GENERATE_RETRIES + 1):
                if attempt:  # every model failed — come back later, like a busy person would
                    delay = rand(C.RETRY_DELAY)
                    log.info("Chat %s: models unavailable, retrying in %.0fs (%d/%d)",
                             chat_id, delay, attempt, C.GENERATE_RETRIES)
                    await asyncio.sleep(delay)
                async with client.action(chat_id, "typing"):
                    reply = await generate(history, contact)
                if reply is not None:
                    break
            else:
                log.warning("Chat %s: giving up, no model answered", chat_id)
            reply = clean_reply(reply or "")
        if not reply:
            return
        if not looks_safe(reply):
            log.warning("Chat %s: blocked suspicious reply (%d chars): %r", chat_id, len(reply), reply[:200])
            return
        elapsed = time.monotonic() - started  # typing was already shown while generating

        for i, part in enumerate(split_reply(reply)):
            if i:
                await asyncio.sleep(rand(C.BETWEEN_MESSAGES))
            async with client.action(chat_id, "typing"):
                await asyncio.sleep(max(typing_time(part) - (elapsed if i == 0 else 0), 0.5))
            our_texts.setdefault(chat_id, []).append(part)
            sent = await client.send_message(chat_id, part)
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
        log.info("Chat %s: replied (%d chars)", chat_id, len(reply))
    except asyncio.CancelledError:
        log.info("Chat %s: reply cancelled", chat_id)
        raise
    except Exception:
        log.exception("Chat %s: reply failed", chat_id)
    finally:
        if pending.get(chat_id) is asyncio.current_task():
            pending.pop(chat_id)


@client.on(events.NewMessage(outgoing=True, pattern=r"^\.ai(?:\s+(\w+))?\s*$"))
async def on_command(event):
    arg = (event.pattern_match.group(1) or "status").lower()
    chat_id = event.chat_id
    in_saved = chat_id == me.id
    await event.delete()

    if arg in ("on", "off") and (in_saved or not event.is_private):
        note = "⚠️ .ai on/off only works inside a private chat"
    elif arg == "on":
        state.enable(chat_id)
        note = "✅ auto-replies ON for {chat}"
    elif arg == "off":
        state.disable(chat_id)
        cancel(chat_id)
        note = "⛔ auto-replies OFF for {chat}"
    elif arg == "pause":
        state.set_paused(True)
        for cid in list(pending):
            cancel(cid)
        note = "⏸ all auto-replies paused"
    elif arg == "resume":
        state.set_paused(False)
        note = "▶️ auto-replies resumed"
    else:
        note = (f"🤖 mode: {C.REPLY_MODE} | paused: {state.paused} | enabled chats: {len(state.enabled)}"
                + ("" if in_saved else " | this chat: {active}"))

    if "{chat}" in note or "{active}" in note:
        chat = await event.get_chat()
        note = note.format(chat=full_name(chat) if isinstance(chat, User) else chat_id,
                           active="active" if state.is_active(chat_id, C.REPLY_MODE) else "inactive")
    await client.send_message("me", note)


@client.on(events.NewMessage(outgoing=True))
async def on_outgoing(event):
    if event.raw_text.startswith(".ai"):
        return
    texts = our_texts.get(event.chat_id)
    if texts and event.raw_text in texts:
        texts.remove(event.raw_text)
        return
    if event.chat_id in pending:
        log.info("Chat %s: you replied yourself, standing down", event.chat_id)
        cancel(event.chat_id)


@client.on(events.NewMessage(incoming=True))
async def on_incoming(event):
    if not event.is_private or time.time() - event.date.timestamp() > C.IGNORE_OLDER_THAN:
        return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot or sender.is_self or sender.id == TELEGRAM_SERVICE_ID:
        return
    if not state.is_active(event.chat_id, C.REPLY_MODE):
        return
    cancel(event.chat_id)  # a new message restarts the wait, so bursts get one reply
    pending[event.chat_id] = asyncio.create_task(reply_flow(event.chat_id, sender))


async def catch_up():
    """On startup, answer recent unanswered messages in enabled chats (e.g. ones sent during a restart)."""
    for chat_id in list(state.enabled):
        if not state.is_active(chat_id, C.REPLY_MODE):
            continue
        last = (await client.get_messages(chat_id, limit=1) or [None])[0]
        if last and not last.out and time.time() - last.date.timestamp() < C.IGNORE_OLDER_THAN:
            contact = await last.get_sender()
            if isinstance(contact, User) and not contact.bot:
                log.info("Chat %s: catching up on unanswered message", chat_id)
                pending[chat_id] = asyncio.create_task(reply_flow(chat_id, contact))


async def main():
    global me
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Not logged in. Run once: .venv/bin/python -m userbot.login")
    me = await client.get_me()
    log.info("Running as %s (@%s) | mode=%s | models=%s | paused=%s | enabled chats=%d",
             full_name(me), me.username, C.REPLY_MODE, C.MODELS, state.paused, len(state.enabled))
    await catch_up()
    try:
        await client.run_until_disconnected()
    finally:
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
