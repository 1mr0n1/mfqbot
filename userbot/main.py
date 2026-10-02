"""Userbot: replies from your own Telegram account, paced like a human.

Control it by sending these from your account (they're deleted instantly; confirmations go to Saved Messages):
  .ai on / .ai off   — in a private chat: enable/disable auto-replies there
  .ai pause / resume — anywhere: stop/restart all auto-replies
  .ai pause 30m      — pause for a while (m/h/d), then resume automatically
  .ai awake 2h       — stay up: ignore the night-time sleep for that long (.ai awake 0m = back to normal)
  .ai status         — anywhere: show current state
  .ai unread         — anywhere: answer unread private messages now (also done at startup)
  .ai save <tag>     — reply to your own voice/round video in Saved Messages to add it to the clip library
  .ai forget <tag>   — remove a clip;  .ai clips — list clips
  .ai savepack       — reply to a sticker: add its whole pack to your account
  .ai salam / .ai notsalam — reply to a sticker: teach that it is / isn't an "Assalomu alaykum" sticker
  (Saved Messages only)
  .ai name <first name> / .ai surname <last name or -> / .ai bio <text or -> / .ai profile
  .ai photo          — reply to a photo with this to make it your profile photo
  .ai pfp undo       — anywhere: remove the newest profile photo (e.g. one someone asked the bot to set)
  .ai summary        — anywhere: today's digest now (it also arrives every evening)
  .ai fwd <@username or name> — reply to any message with this: forward it to that person or group
  .ai manual         — in a private chat: never answer there, just tell you someone wrote (.ai on undoes it)
  .ai today <text>   — anywhere: tell it something true about today ("сделал домашку", "на теннисе до 7");
                       it answers from that until midnight. `.ai today` alone shows what it knows.
  .ai note <text>    — in a private chat: remember something about that person
  .ai notes / .ai forgetnotes — in a private chat: show / erase what is remembered about that person
"""
import asyncio
import os
import logging
import time
from datetime import datetime, timedelta
import httpx
from telethon import events
from telethon.tl.types import User
from . import config as C
from . import daylog, rhythm, toggles
from . import mood, pilot, trace
from .autoprofile import bio_loop
from . import app
from .app import TELEGRAM_SERVICE_ID, asked, cancel, commander_ids, contacts, describe, forced, full_name, group_done, group_seen, http, label, log, names, our_texts, pending, recent_incoming, resolve_name, spawn, state
from .commands import clip_by_name, command_loop, gather_order, obey, order_queue, own_photo_to_avatar, pin_commanders, save_clip_from_owner, teach
from .groups import addressed_to_me, answer_in_group, consider_joining, group_ready, mention_allowed, scan_groups
from .replies import echo_of, flood_from, initiative_loop, nudge_loop, reply_flow, reply_to_unread, spam
from .wording import name_re

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per dashboard event is just noise


@app.client.on(events.NewMessage(outgoing=True))
async def on_outgoing(event):
    if event.raw_text.startswith(".ai"):
        return
    texts = our_texts.get(event.chat_id)
    if texts and event.raw_text in texts:
        texts.remove(event.raw_text)
        return
    state.clear_handoff(event.chat_id)  # you answered there yourself; normal rules apply again
    asked.pop(event.chat_id, None)
    if event.chat_id in pending:
        log.info("%s: you replied yourself, standing down", label(event.chat_id))
        cancel(event.chat_id)


@app.client.on(events.NewMessage(incoming=True))
async def on_incoming(event):
    if not event.is_private or time.time() - event.date.timestamp() > C.IGNORE_OLDER_THAN:
        return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot or sender.is_self or sender.id == TELEGRAM_SERVICE_ID:
        return
    who = names[event.chat_id] = full_name(sender)
    asked.pop(event.chat_id, None)  # they answered (or at least wrote): nothing to ask again
    trace.emit("incoming", who, describe(event.message)[:300])
    if sender.id in commander_ids:
        if await teach(event) or await save_clip_from_owner(event) or await own_photo_to_avatar(event) \
                or await clip_by_name(event, event.raw_text):
            return
        answering = pilot.asked_back and pilot.asked_back["chat"] == event.chat_id and time.time() - pilot.asked_back["at"] < 180
        if pilot.is_order(event.raw_text or "") or event.chat_id in order_queue or answering:
            order = await gather_order(event)
            if order is None or await obey(event, order):
                return
        forced.add(event.chat_id)  # just talking: answered normally, but nothing is withheld from yourself
    if not state.is_active(event.chat_id, C.REPLY_MODE):
        trace.emit("decision", who, "Not replying — auto-replies are paused" if state.is_paused()
                   else "Not replying — auto-replies are off for this chat")
        return
    if rhythm.asleep():
        trace.emit("decision", who, "Asleep — this stays unread until the morning")
        return
    if state.handed_off(event.chat_id):
        trace.emit("decision", who, "Still leaving this chat to you (handed off earlier)")
        return
    contacts[event.chat_id] = sender
    flood = flood_from(event.chat_id, event.message)
    if flood and event.chat_id not in state.manual:
        cancel(event.chat_id)
        recent_incoming.pop(event.chat_id, None)
        trace.emit("decision", who, f"{len(flood)} messages in a few seconds — spamming back")
        daylog.record("replied", who, f"[spammed back, {len(flood)} messages]", them=describe(event.message)[:100])
        spawn(spam(event.chat_id, who, [echo_of(m) for m in flood]))
        return
    cancel(event.chat_id)  # a new message restarts the wait, so bursts get one reply
    pending[event.chat_id] = asyncio.create_task(reply_flow(event.chat_id, sender))


@app.client.on(events.NewMessage(incoming=True))
async def on_group_mention(event):
    """Groups: when someone @mentions you, replies to one of your messages, or calls you by name — and, in groups
    you allowed it in, when the account itself judges that it has something to say."""
    if not event.is_group:
        return
    if not addressed_to_me(event.message):
        if C.GROUP_JOIN_ON and event.chat_id in state.chatty and group_ready(event.chat_id) \
                and time.time() - event.date.timestamp() <= C.IGNORE_OLDER_THAN and not state.approve:
            sender = await event.get_sender()
            if isinstance(sender, User) and not sender.bot:
                consider_joining(event, sender)
        return
    if time.time() - event.date.timestamp() > C.IGNORE_OLDER_THAN or not group_ready(event.chat_id):
        return
    if (event.chat_id, event.id) in group_done:
        return
    group_done.add((event.chat_id, event.id))
    group_seen[event.chat_id] = max(group_seen.get(event.chat_id, 0), event.id)
    if event.sender_id in commander_ids and (event.raw_text or "").strip():
        order = name_re().sub(" ", event.raw_text).strip(" ,:")  # in a group: only a message that opens with the order
        if await clip_by_name(event, order):
            return
        if order and pilot.ORDER_RE.match(order) and await obey(event, order):
            return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot:
        return
    if sender.id not in commander_ids and not mention_allowed(event.chat_id, sender.id, full_name(sender)):
        return
    answer_in_group(event.message, sender)


async def model_cost() -> str:
    """What the paid models cost since the last report (OpenRouter), and what is left."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return ""
    try:
        async with httpx.AsyncClient(timeout=15) as web:
            data = (await web.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"})).json()["data"]
    except Exception:
        return ""
    used, total = float(data.get("total_usage", 0)), float(data.get("total_credits", 0))
    since = f"${used - state.spent:.2f} since the last report, " if state.spent >= 0 else ""
    state.spent = used
    state.save()
    return f"Models: {since}${used:.2f} used in total, ${total - used:.2f} left"


async def cost_loop():
    """Keep the dashboard's "what the models cost" line fresh."""
    key = os.environ.get("OPENROUTER_API_KEY")
    while key:
        try:
            async with httpx.AsyncClient(timeout=15) as web:
                data = (await web.get("https://openrouter.ai/api/v1/credits", headers={"Authorization": f"Bearer {key}"})).json()["data"]
            used, total = float(data.get("total_usage", 0)), float(data.get("total_credits", 0))
            app.dashboard["cost"] = {"used": round(used, 2), "left": round(total - used, 2),
                                     "since_report": round(used - state.spent, 2) if state.spent >= 0 else None}
        except Exception:
            pass
        await asyncio.sleep(600)


async def morning_report(day: datetime | None = None) -> str:
    return daylog.report(day, await model_cost())


async def report_loop():
    """Every morning: what happened yesterday, in Saved Messages."""
    if not C.REPORT_TIME:
        return
    hour, minute = (int(x) for x in C.REPORT_TIME.split(":"))
    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await app.client.send_message("me", await morning_report())
        except Exception:
            log.exception("Morning report failed")


async def summary_loop():
    """Every evening: a digest of the day in Saved Messages."""
    if not C.SUMMARY_TIME:
        return
    hour, minute = (int(x) for x in C.SUMMARY_TIME.split(":"))
    while True:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        try:
            await app.client.send_message("me", daylog.summary())
        except Exception:
            log.exception("Evening summary failed")


async def unread_loop():
    """Safety net: Telegram's live update feed can go quiet (e.g. when another connection uses the same
    login), so re-scan the most recent chats for unread DMs on a timer."""
    while True:
        await asyncio.sleep(C.UNREAD_RESCAN_SECONDS)
        try:
            await reply_to_unread(limit=30)
        except Exception:
            log.exception("Unread re-scan failed")
        try:
            await scan_groups()
        except Exception:
            log.exception("Group scan failed")


ALIVE = C.HERE / ".alive"   # the time this process was last seen running (git-ignored)


async def heartbeat():
    while True:
        ALIVE.write_text(str(time.time()))
        await asyncio.sleep(30)


async def report_downtime():
    """If the account was not running for a while, say so in Saved Messages when it comes back."""
    try:
        last = float(ALIVE.read_text())
    except (OSError, ValueError):
        return
    gap = time.time() - last
    if gap < 180:
        return  # an ordinary restart
    was = (f"{gap / 3600:.1f} h" if gap >= 5400 else f"{gap / 60:.0f} min")
    note = (f"🔌 I was not running for {was} — from {datetime.fromtimestamp(last):%H:%M %d.%m} until now. "
            "Back, and going through the chats that are waiting.")
    log.warning("Was down for %s", was)
    trace.emit("warning", "", f"The userbot was not running for {was} (since {datetime.fromtimestamp(last):%H:%M %d.%m})")
    await app.client.send_message("me", note)


async def main():
    await app.client.connect()
    if not await app.client.is_user_authorized():
        raise SystemExit("Not logged in. Run once: .venv/bin/python -m userbot.login")
    app.me = await app.client.get_me()
    rhythm.awake_until = state.awake_until
    toggles.apply(state.settings)
    log.info("Running as %s (@%s) | mode=%s | models=%s | paused=%s",
             full_name(app.me), app.me.username, C.REPLY_MODE, C.MODELS, state.is_paused())
    if C.REPLY_MODE == "all":
        off = [await resolve_name(cid) for cid in sorted(state.disabled)]
        log.info("Replying in every private chat; off in: %s", ", ".join(off) or "none")
    else:
        enabled = [await resolve_name(cid) for cid in sorted(state.enabled)]
        log.info("Enabled chats: %s", ", ".join(enabled) or "none (type .ai on in a chat)")
    async for dialog in app.client.iter_dialogs(limit=40):  # so the dashboard can act on recent chats right away
        if isinstance(dialog.entity, User) and not dialog.entity.bot and not dialog.entity.is_self \
                and dialog.entity.id != TELEGRAM_SERVICE_ID:
            names[dialog.id] = full_name(dialog.entity)
            contacts[dialog.id] = dialog.entity
    await pin_commanders()
    trace.emit("system", "", f"Userbot started as {full_name(app.me)} — mode: {C.REPLY_MODE}, models: {', '.join(C.MODELS)}")
    await report_downtime()
    await reply_to_unread()
    spawn(scan_groups())
    background = [asyncio.create_task(bio_loop(app.client, state)), asyncio.create_task(unread_loop()),
                  asyncio.create_task(summary_loop()), asyncio.create_task(command_loop()),
                  asyncio.create_task(nudge_loop()), asyncio.create_task(initiative_loop()),
                  asyncio.create_task(heartbeat()), asyncio.create_task(report_loop()),
                  asyncio.create_task(mood.presence_loop(app.client, state.is_paused)), asyncio.create_task(cost_loop())]
    try:
        await app.client.run_until_disconnected()
    finally:
        for task in background:
            task.cancel()
        await http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
