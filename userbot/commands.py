"""Everything you control the account with: the .ai commands, orders in plain words, orders from your other
account, and the buttons on the dashboard."""
import asyncio
import re
import time
from types import SimpleNamespace
from datetime import datetime
from telethon import errors, events, functions
from telethon.tl.types import User
from . import config as C
from . import daylog, media, memory, pfp, rhythm, salam, toggles
from . import pilot, trace
from . import app
from .app import COMMAND_RE, cancel, commander_ids, commanding, contacts, forced, full_name, group_done, group_names, http, log, names, our_ids, our_texts, pending, pilot_busy, push_history, resolve_name, send_as_bot, set_chat_mode, spawn, state, type_like_a_person
from .groups import answer_in_group, cancel_group
from .replies import reply_flow, reply_to_unread, spam
from .wording import typed_by_bot


@app.client.on(events.NewMessage(outgoing=True, pattern=r"^\.ai(?:\s+(\w+))?(?:\s+(@?[\w.-]+))?\s*$"))
async def on_command(event):
    if typed_by_bot(event):
        return
    arg = (event.pattern_match.group(1) or "status").lower()
    if arg in PROFILE_COMMANDS or arg in ("note", "today", "do"):
        return  # handled by on_profile_command / on_note_command / on_today_command
    tag = (event.pattern_match.group(2) or "").lower()
    chat_id = event.chat_id
    in_saved = chat_id == app.me.id
    replied = await event.get_reply_message() if event.is_reply else None
    await event.delete()

    if arg == "summary":
        await app.client.send_message("me", daylog.summary())
        return
    if arg == "fwd":
        await app.client.send_message("me", await forward_command(tag, replied))
        return
    if arg in ("save", "forget", "clips"):
        await app.client.send_message("me", clip_command(arg, tag, replied, in_saved))
        return
    if arg in ("notes", "forgetnotes"):
        if in_saved or not event.is_private:
            note = f"⚠️ use .ai {arg} inside the private chat with that person"
        elif arg == "notes":
            items = memory.notes(chat_id)
            note = (f"🧠 notes about {await resolve_name(chat_id)}:\n" + "\n".join(f"- {n['text']} ({n['date']})" for n in items)
                    if items else f"🧠 nothing remembered about {await resolve_name(chat_id)} yet")
        else:
            note = f"🗑 erased {memory.clear_notes(chat_id)} note(s) about {await resolve_name(chat_id)}"
        await app.client.send_message("me", note)
        return
    if arg == "pfp":
        if tag != "undo":
            note = "⚠️ usage: .ai pfp undo"
        else:
            note = "↩️ newest profile photo removed" if await pfp.undo(app.client) else "⚠️ there is no profile photo to remove"
        await app.client.send_message("me", note)
        return
    if arg in ("savepack", "salam", "notsalam"):
        if not replied or not replied.sticker:
            note = f"⚠️ reply to a sticker with .ai {arg}"
        elif arg == "savepack":
            pack = await salam.save_pack(app.client, replied)
            note = f"✅ sticker pack '{pack}' added to your account" if pack else "⚠️ that sticker has no pack"
        else:
            state.remember_salam_sticker(str(replied.document.id), arg == "salam")
            note = ("✅ learned: that is an 'Assalomu alaykum' sticker — I'll answer it with the same sticker"
                    if arg == "salam" else "✅ learned: that is not a salam sticker")
        await app.client.send_message("me", note)
        return

    if arg in ("on", "off") and in_saved:
        note = "⚠️ use .ai on/off inside the chat or group you mean"
    elif arg == "on":
        state.enable(chat_id)
        note = "✅ auto-replies ON for {chat}"
    elif arg == "manual":
        if in_saved or not event.is_private:
            note = "⚠️ use .ai manual inside the private chat you mean"
        else:
            state.set_manual(chat_id)
            cancel(chat_id)
            note = "✋ {chat}: I won't answer there — I'll just tell you when they write (.ai on to undo)"
    elif arg == "off":
        state.disable(chat_id)
        cancel(chat_id)
        note = "⛔ auto-replies OFF for {chat}"
    elif arg == "pause":
        duration = re.fullmatch(r"(\d+)([mhd])", tag)
        seconds = int(duration.group(1)) * {"m": 60, "h": 3600, "d": 86400}[duration.group(2)] if duration else 0
        state.set_paused(True, seconds)
        for cid in list(pending):
            cancel(cid)
        note = (f"⏸ auto-replies paused for {tag} (until {datetime.fromtimestamp(state.paused_until):%H:%M %d.%m})"
                if seconds else "⏸ all auto-replies paused until .ai resume")
    elif arg == "awake":
        duration = re.fullmatch(r"(\d+)([mhd])", tag or "2h")
        seconds = int(duration.group(1)) * {"m": 60, "h": 3600, "d": 86400}[duration.group(2)] if duration else 7200
        state.awake_until = rhythm.awake_until = time.time() + seconds if seconds else 0
        state.save()
        note = (f"🌙 staying up until {datetime.fromtimestamp(state.awake_until):%H:%M} — answering as usual"
                if seconds else "😴 back to the normal sleep schedule")
        if seconds:
            spawn(reply_to_unread())
    elif arg == "resume":
        state.set_paused(False)
        note = "▶️ auto-replies resumed"
    elif arg == "unread":
        count = await reply_to_unread()
        note = f"📬 answering {count} unread chat(s)" if count else "📭 no unread private messages to answer"
    else:
        enabled = ", ".join([await resolve_name(cid) for cid in sorted(state.enabled)]) or "none"
        paused = ("yes" if state.paused else f"until {datetime.fromtimestamp(state.paused_until):%H:%M %d.%m}"
                  if state.is_paused() else "no")
        disabled = ", ".join([await resolve_name(cid) for cid in sorted(state.disabled)]) or "none"
        note = (f"🤖 mode: {C.REPLY_MODE} | paused: {paused} | "
                + (f"off in: {disabled}" if C.REPLY_MODE == "all" else f"enabled chats: {enabled}")
                + ("" if in_saved else " | this chat: {active}"))

    if "{chat}" in note or "{active}" in note:
        chat = await event.get_chat()
        note = note.format(chat=full_name(chat) if isinstance(chat, User) else chat_id,
                           active="active" if state.is_active(chat_id, C.REPLY_MODE) else "inactive")
    await app.client.send_message("me", note)


PROFILE_COMMANDS = {"name", "surname", "bio", "photo", "profile"}


async def operate(order: str, here: int | None = None):
    """An order in plain words → the account carries it out (see pilot.py); the report goes to Saved Messages."""
    async with pilot_busy:
        ctx = SimpleNamespace(client=app.client, http=http, state=state, me=app.me, send=send_as_bot, set_mode=set_chat_mode)
        try:
            report = await pilot.run(ctx, order, here)
        except Exception:
            log.exception("Pilot failed on %r", order)
            report = f"🛠 {order}\n⚠️ that failed (see the userbot log)"
            trace.emit("warning", "Pilot", "The order failed (see the userbot log)")
    await app.client.send_message("me", report)


@app.client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+do\s+(.+)$"))
async def on_do_command(event):
    """`.ai do <anything>`: operate the account in plain words. Typed in a chat, that chat is "here"."""
    if typed_by_bot(event):
        return
    order, here = event.pattern_match.group(1).strip(), event.chat_id
    await event.delete()
    spawn(operate(order, here))


@app.client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+today(?:\s+(.+))?$"))
async def on_today_command(event):
    """`.ai today <text>`: something true about today, so questions like "did you do your homework?" get real answers."""
    if typed_by_bot(event):
        return
    text = (event.pattern_match.group(1) or "").strip()
    await event.delete()
    if text:
        await app.client.send_message("me", f"📅 today: {memory.add_today(text)}")
    else:
        await app.client.send_message("me", f"📅 today: {memory.today_note() or 'nothing yet — tell me with .ai today <text>'}")


@app.client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+note\s+(.+)$"))
async def on_note_command(event):
    """`.ai note <text>` in a private chat: remember something about that person."""
    if typed_by_bot(event):
        return
    text, chat_id = event.pattern_match.group(1).strip(), event.chat_id
    await event.delete()
    if chat_id == app.me.id or not event.is_private:
        await app.client.send_message("me", "⚠️ use .ai note <text> inside the private chat with that person")
        return
    memory.add_note(chat_id, text, source="you", who=await resolve_name(chat_id))
    await app.client.send_message("me", f"🧠 noted about {await resolve_name(chat_id)}: {text}")


@app.client.on(events.NewMessage(outgoing=True, pattern=r"(?s)^\.ai\s+(name|surname|bio|photo|profile)\b\s*(.*)$"))
async def on_profile_command(event):
    """Owner commands for name / surname / bio / photo. (The only thing a chat can trigger is pfp.py.)"""
    if typed_by_bot(event):
        return
    cmd, value = event.pattern_match.group(1).lower(), event.pattern_match.group(2).strip()
    replied = await event.get_reply_message() if event.is_reply else None
    in_saved = event.chat_id == app.me.id
    await event.delete()
    if not in_saved:
        await app.client.send_message("me", "⚠️ profile commands only work here in Saved Messages")
        return
    try:
        note = await profile_command(cmd, value, replied)
    except errors.RPCError as e:
        note = f"⚠️ Telegram refused: {e.__class__.__name__}"
    app.me = await app.client.get_me()  # the persona uses your current name
    await app.client.send_message("me", note)


async def profile_command(cmd: str, value: str, replied) -> str:
    clear = value == "-"
    if cmd == "profile":
        full = await app.client(functions.users.GetFullUserRequest("me"))
        return (f"👤 name: {app.me.first_name or ''}\nsurname: {app.me.last_name or '—'}\n"
                f"bio: {full.full_user.about or '—'}")
    if cmd == "photo":
        if not replied or not replied.photo:
            return "⚠️ reply to a photo with .ai photo"
        data = await replied.download_media(file=bytes)
        await app.client(functions.photos.UploadProfilePhotoRequest(
            file=await app.client.upload_file(data, file_name="profile.jpg")))
        return "🖼 profile photo updated"
    if not value:
        return f"⚠️ usage: .ai {cmd} <text>" + ("" if cmd == "name" else "  (or - to clear)")
    if cmd == "name":
        await app.client(functions.account.UpdateProfileRequest(first_name=value[:64]))
        return f"✅ name → {value[:64]}"
    if cmd == "surname":
        await app.client(functions.account.UpdateProfileRequest(last_name="" if clear else value[:64]))
        return "✅ surname cleared" if clear else f"✅ surname → {value[:64]}"
    try:  # bio
        await app.client(functions.account.UpdateProfileRequest(about="" if clear else value))
    except errors.AboutTooLongError:
        return "⚠️ bio too long (70 characters max, 140 with Premium)"
    return "✅ bio cleared" if clear else f"✅ bio → {value}"


async def forward_command(target: str, replied) -> str:
    """`.ai fwd <who>` as a reply to a message: forward that message. Only you can trigger a forward."""
    if not replied or not target:
        return "⚠️ reply to a message with .ai fwd <@username or name>"
    entity = None
    if target.startswith("@"):
        try:
            entity = await app.client.get_entity(target)
        except Exception:
            return f"⚠️ couldn't find {target}"
    else:
        matches = [d for d in await app.client.get_dialogs(limit=300) if target in (d.name or "").lower()]
        if len(matches) != 1:
            names_found = ", ".join(d.name for d in matches[:6]) or "nobody"
            return f"⚠️ '{target}' matches {len(matches)} chats ({names_found}) — be more specific or use @username"
        entity = matches[0].entity
    await app.client.forward_messages(entity, replied)
    name = getattr(entity, "title", None) or full_name(entity)
    daylog.record("replied", name, "[forwarded a message — your command]")
    return f"↪️ forwarded to {name}"


def clip_command(arg: str, tag: str, replied, in_saved: bool) -> str:
    if arg == "clips":
        clips = media.load_clips()
        if not clips:
            return "🎙 no clips yet — record a voice/round video here and reply to it with .ai save <tag>"
        return "🎙 clips:\n" + "\n".join(f"{c['kind']}: {t}" for t, c in sorted(clips.items()))
    if not tag:
        return f"⚠️ usage: .ai {arg} <tag>"
    if arg == "forget":
        return f"🗑 removed clip '{tag}'" if media.remove_clip(tag) else f"⚠️ no clip '{tag}'"
    if not in_saved or not replied:
        return "⚠️ in Saved Messages, reply to your voice/round video with .ai save <tag>"
    kind = media.add_clip(tag, replied)
    return f"✅ saved {kind} clip '{tag}'" if kind else "⚠️ that's not a voice message or round video"


async def pin_commanders():
    """USERBOT_COMMANDERS -> numeric ids. A username is resolved once; after that the id is what counts."""
    for ref in C.COMMANDERS:
        key = ref.lstrip("@").lower()
        if key.lstrip("-").isdigit():
            commander_ids.add(int(key))
            continue
        if key not in state.commanders:
            try:
                entity = await app.client.get_entity(key)
            except Exception as e:
                log.warning("Commander %s could not be looked up (%s) — ignored", ref, e.__class__.__name__)
                continue
            if not isinstance(entity, User) or entity.bot or entity.is_self:
                log.warning("Commander %s is not another person's account — ignored", ref)
                continue
            state.commanders[key] = entity.id
            state.save()
            log.info("Commander @%s pinned to id %s (%s)", key, entity.id, full_name(entity))
        commander_ids.add(state.commanders[key])
    if commander_ids:
        trace.emit("system", "", f"Orders are accepted from {len(commander_ids)} other account(s) of yours, without asking back")


AVATAR_RE = re.compile(  # "put it on the profile photo" — not just any mention of an avatar
    r"\bна\s+ав[ауы]\b|\bна\s+аватар\w*|(постав|смени|поменя|установи|сделай)\w*\b.*(\bав[ауые]\b|аватар|фото\s+профил)"
    r"|\b(set|make|put|use)\b.*(\bpfp\b|avatar|profile\s+(pic|photo|picture))|\bas\s+(ur|your|the|my)\s+(pfp|avatar)", re.I)


NOT_AVATAR_RE = re.compile(r"\b(убери|удали|сними|верни|remove|delete)\b|\?", re.I)


async def own_photo_to_avatar(event) -> bool:
    """Your other account sends a photo and says "на аву": that exact photo becomes the profile photo.
    The photo is taken from the message itself, the message it replies to, or the photo you sent there in the
    last 10 minutes — never from anywhere else."""
    text = event.raw_text or ""
    if not AVATAR_RE.search(text) or NOT_AVATAR_RE.search(text):
        return False
    photo = event.message if event.message.photo else None
    if not photo and event.is_reply:
        replied = await event.get_reply_message()
        photo = replied if replied and replied.photo else None
    if not photo:
        photo = next((m for m in await app.client.get_messages(event.chat_id, limit=12)
                      if m.photo and not m.out and m.sender_id == event.sender_id
                      and event.date.timestamp() - m.date.timestamp() < 600), None)
    if not photo:
        return False  # no photo of yours to use: the order goes on as text ("поставь на аву кота")
    who = names.get(event.chat_id, "your other account")
    try:
        data = await photo.download_media(file=bytes)
        await app.client(functions.photos.UploadProfilePhotoRequest(file=await app.client.upload_file(data, file_name="profile.jpg")))
    except Exception:
        log.exception("Setting the profile photo from the owner's own picture failed")
        trace.emit("warning", who, "Couldn't set that photo as the profile photo (see the userbot log)")
        await send_as_bot(event.chat_id, "не получилось поставить", reply_to=event.id)
        return True
    state.record_pfp()
    trace.emit("system", who, "Profile photo set to the picture you sent from your other account")
    await app.client.send_read_acknowledge(event.chat_id)
    await send_as_bot(event.chat_id, "поставил", reply_to=event.id)
    state.mark_handled(event.chat_id, event.id)
    return True


order_queue: dict[int, list] = {}   # chat -> messages of an order still arriving ("зайди по ссылке" + the link)


async def gather_order(event) -> str | None:
    """Messages from your other account that belong together arrive a moment apart: wait briefly and take them as
    one. -> the order text, or None if this message was absorbed into one that is already waiting."""
    queue = order_queue.setdefault(event.chat_id, [])
    queue.append(event)
    if len(queue) > 1:
        return None
    await asyncio.sleep(4)
    texts = [e.raw_text.strip() for e in order_queue.pop(event.chat_id, []) if (e.raw_text or "").strip()]
    return "\n".join(texts)


async def obey(event, order: str) -> bool:
    """A message from your other account: if it is an order, carry it out and answer with the result.
    -> False if it was just conversation (then it is answered like any other message)."""
    chat_id = event.chat_id
    if not pilot.is_order(order):
        return False  # a question, an opinion, banter: never treated as a command
    commanding.add(chat_id)
    try:
        async with pilot_busy:
            ctx = SimpleNamespace(client=app.client, http=http, state=state, me=app.me, send=send_as_bot, set_mode=set_chat_mode)
            try:
                earlier = [m for m in await app.client.get_messages(chat_id, limit=8) if m.id < event.id and (m.raw_text or "").strip()]
                context = "\n".join(f"{'You (the account)' if m.out else 'Owner' if m.sender_id in commander_ids else 'Someone'}: "
                                    f"{m.raw_text.strip()[:200]}" for m in reversed(earlier[:6]))
                report = await pilot.run(ctx, order, chat_id, trusted=True, may_chat=True, context=context)
            except Exception:
                log.exception("Order from a commander failed: %r", order)
                report = "не получилось, что-то сломалось"
        if report is None:
            return False
        if COMMAND_RE.search(report):
            report = report.replace(".ai", "ai")
        await app.client.send_read_acknowledge(chat_id)
        await send_as_bot(chat_id, report, reply_to=event.id)
        state.mark_handled(chat_id, event.id)
        trace.emit("sent", names.get(chat_id, "your other account"), report[:300])
        return True
    finally:
        commanding.discard(chat_id)


def chat_by_name(name: str) -> int | None:
    return next((cid for cid, n in names.items() if n == name), None)


async def run_command(cmd: dict):
    """Something you clicked on the dashboard."""
    kind, name = cmd.get("type"), cmd.get("chat", "")
    chat_id = chat_by_name(name) if name else None
    if kind == "pause":
        state.set_paused(True)
        for cid in list(pending):
            cancel(cid)
        trace.emit("system", "", "Paused from the dashboard — no replies until you resume")
    elif kind == "resume":
        state.set_paused(False)
        trace.emit("system", "", "Resumed from the dashboard")
        spawn(reply_to_unread())
    elif kind == "toggle":
        key, on = cmd.get("value"), cmd.get("text") == "on"
        if key in toggles.TOGGLES:
            state.settings[key] = on
            state.save()
            toggles.apply(state.settings)
            trace.emit("system", "", f"{toggles.TOGGLES[key][1]}: {'ON' if on else 'off'} (set from the dashboard)")
            if on is False and key in ("sleep", "school"):
                spawn(reply_to_unread())  # woke up / left school early: look at what's waiting
    elif kind == "approve":
        state.set_approve(cmd.get("value") == "on")
        trace.emit("system", "", "Approve-before-sending is ON: every draft waits for you" if state.approve
                   else "Approve-before-sending is OFF: drafts send by themselves")
    elif kind == "group" and str(cmd.get("chat", "")).lstrip("-").isdigit():  # the switch next to a group
        gid, on = int(cmd["chat"]), cmd.get("value") == "on"
        if on:
            state.disabled.discard(gid)
            state.save()
        else:
            state.disable(gid)
            cancel_group(gid)
        trace.emit("system", group_names.get(gid, str(gid)), f"Group replies {'ON' if on else 'off'} (set from the dashboard)")
    elif kind in ("gsay", "ganswer") and str(cmd.get("chat", "")).lstrip("-").isdigit():  # a group row
        gid = int(cmd["chat"])
        gname = group_names.get(gid, str(gid))
        if kind == "gsay" and cmd.get("text", "").strip():  # your own words into the group
            text = cmd["text"].strip()
            cancel_group(gid)
            trace.emit("decision", gname, "Sending the text you wrote on the dashboard")
            await type_like_a_person(gid, text)
            await send_as_bot(gid, text)
            trace.emit("sent", gname, text)
            daylog.record("replied", gname, text, them="(you wrote this on the dashboard)")
        elif kind == "ganswer":  # answer the latest message there, called by name or not
            last = next((m for m in await app.client.get_messages(gid, limit=15) if not m.out and (m.raw_text or m.media)), None)
            sender = await last.get_sender() if last else None
            if not last or not isinstance(sender, User):
                trace.emit("warning", gname, "Nothing in that group to answer")
            else:
                cancel_group(gid)
                group_done.add((gid, last.id))
                trace.emit("decision", gname, "You asked for an answer in the group — writing one now")
                answer_in_group(last, sender, force=True)
    elif kind == "do" and cmd.get("text", "").strip():
        spawn(operate(cmd["text"].strip()))
    elif chat_id is None:
        trace.emit("warning", name, "Dashboard action ignored — I don't know that chat yet")
    elif kind == "history":
        await push_history(chat_id)
    elif kind == "mode":
        mode = cmd.get("value")
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
        trace.emit("system", name, f"Chat mode set to {mode} from the dashboard")
    elif kind == "answer":  # overrule a hand-off / ignored question / skipped message
        contact = contacts.get(chat_id)
        if not contact:
            contact = await app.client.get_entity(chat_id)
        state.clear_handoff(chat_id)
        forced.add(chat_id)
        cancel(chat_id)
        trace.emit("decision", name, "You asked for an answer — writing one now")
        pending[chat_id] = asyncio.create_task(reply_flow(chat_id, contact))
    elif kind == "spam" and cmd.get("text", "").strip():  # value = how many times
        count = min(int(cmd.get("value") or 10), C.SPAM_MAX)
        cancel(chat_id)
        trace.emit("decision", name, f"Spamming on your order: “{cmd['text'].strip()}” × {count}")
        await spam(chat_id, name, [cmd["text"].strip()] * count)
    elif kind == "say" and cmd.get("text", "").strip():  # your own words, sent with normal typing
        text = cmd["text"].strip()
        cancel(chat_id)
        state.clear_handoff(chat_id)
        trace.emit("decision", name, "Sending the text you wrote on the dashboard")
        await app.client.send_read_acknowledge(chat_id)
        await type_like_a_person(chat_id, text)
        our_texts.setdefault(chat_id, []).append(text)
        sent = await app.client.send_message(chat_id, text)
        our_ids.add(sent.id)
        state.record_sent(chat_id, sent.id)
        state.mark_handled(chat_id, (await app.client.get_messages(chat_id, limit=1))[0].id)
        trace.emit("sent", name, text)
        daylog.record("replied", name, text, them="(you wrote this on the dashboard)")


async def command_loop():
    """Poll the dashboard for clicks, and tell it what state the account is in."""
    last, _ = await trace.commands(10**9)  # start from "now": don't replay old commands
    beat = 0
    while True:
        await asyncio.sleep(1)
        latest, new = await trace.commands(last)
        if latest < last:  # the backend restarted and its ids started over
            last = 0
            continue
        for cmd in new:
            last = max(last, cmd["id"])
            try:
                await run_command(cmd)
            except Exception:
                log.exception("Dashboard command failed: %r", cmd)
                trace.emit("warning", cmd.get("chat", ""), "That dashboard action failed (see the userbot log)")
        beat += 1
        if beat % 3 == 0 or new:
            known = set(names) | state.disabled | state.manual
            await trace.report_status({
                "account": full_name(app.me), "paused": state.is_paused(), "approve": state.approve,
                "asleep": rhythm.asleep(), "busy": rhythm.busy(), "models": C.MODELS, "mode": C.REPLY_MODE,
                "toggles": toggles.snapshot(),
                "groups": sorted(({"id": gid, "name": name, "on": gid not in state.disabled}
                                  for gid, name in group_names.items()), key=lambda g: g["name"].lower()),
                "chats": sorted(({"name": names.get(cid, str(cid)), "mode": state.mode_of(cid),
                                  "waiting": cid in pending, "held": state.handed_off(cid)}
                                 for cid in known if cid in names), key=lambda c: c["name"].lower())})
