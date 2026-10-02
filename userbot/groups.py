"""Group chats: noticing when you are called, answering each person who called, and the limits on that."""
import asyncio
import re
import random
import time
from datetime import datetime
from telethon import errors
from telethon.tl.types import ChannelForbidden, ChatForbidden, User
from . import config as C
from . import daylog, judge, lang, media, memory, punct, quirks, rhythm
from . import trace
from . import app
from .app import commander_ids, describe, full_name, group_done, group_names, group_seen, hold_draft, http, log, our_ids, our_texts, pacing_on, rand, state, type_like_a_person
from .drafting import persona, punct_profile, style_block, style_stats
from .replies import DEFER_RE, TEACHER_RE
from .wording import IDENTITY_HINT, PRESSING_RE, clean_reply, identity_question, looks_safe, name_re, split_reply, stale_parts


GROUP_HINT = ("\nThis is a GROUP chat. Below is the recent conversation; lines start with who wrote them ('You' is "
              "you). {sender} just addressed you — by @username, by name, or by replying to you. Their message is:\n"
              "“{message}”\nFirst work out from the conversation what exactly they want from you (a question, an "
              "opinion, a request, a joke at your expense), then answer THAT, clearly and to the point, in one short "
              "message the way you write in a group. If they only called your name, ask what's up in a word or two. "
              "Don't greet everyone, don't address other people, don't repeat their words back, no stickers or GIFs.\n")


def addressed_to_me(msg) -> bool:
    return bool(getattr(msg, "mentioned", False) or name_re().search(msg.raw_text or ""))


group_tasks: dict[tuple[int, int], asyncio.Task] = {}  # (group, message id) -> the answer being written; several at once


def answer_in_group(msg, sender, force: bool = False):
    """Every person who called you gets their own answer, written side by side (each quotes its message)."""
    key = (msg.chat_id, msg.id)
    if key not in group_tasks:
        group_tasks[key] = asyncio.create_task(group_reply_flow(msg, sender, force))


def cancel_group(chat_id: int):
    for key in [k for k in group_tasks if k[0] == chat_id]:
        group_tasks.pop(key).cancel()


mention_log: dict[int, list[tuple[float, int]]] = {}   # group -> (time, who) of mentions that got an answer


def mention_allowed(chat_id: int, sender_id: int, who: str = "") -> bool:
    """A few answers, then silence: someone calling you over and over in a group stops getting replies."""
    now = time.time()
    recent = mention_log[chat_id] = [(t, s) for t, s in mention_log.get(chat_id, []) if now - t < C.GROUP_WINDOW]
    mine = sum(1 for _, s in recent if s == sender_id)
    if mine >= C.GROUP_PER_PERSON or len(recent) >= C.GROUP_PER_GROUP:
        if mine == C.GROUP_PER_PERSON or len(recent) == C.GROUP_PER_GROUP:  # say it once, not on every poke
            trace.emit("decision", who, "Called too many times in this group — ignoring further mentions for a while")
            recent.append((now, sender_id))
        return False
    recent.append((now, sender_id))
    return True


def group_ready(chat_id: int) -> bool:
    return C.GROUPS and not state.is_paused() and chat_id not in state.disabled and not rhythm.asleep()


async def scan_groups():
    """Groups the account is in → the dashboard list; and mentions the live feed missed get their answer.
    Only groups with something new are opened, and only their latest messages are read."""
    current: dict[int, str] = {}
    async for dialog in app.client.iter_dialogs(limit=60):
        gone = isinstance(dialog.entity, (ChatForbidden, ChannelForbidden)) or getattr(dialog.entity, "left", False) \
            or getattr(dialog.entity, "deactivated", False)
        if not dialog.is_group or gone:  # kicked out, left, or the group was closed: not yours any more
            continue
        current[dialog.id] = dialog.name
        last, since = dialog.message, group_seen.get(dialog.id, 0)
        if not last or last.id <= since:
            continue
        group_seen[dialog.id] = last.id
        if not group_ready(dialog.id):
            continue
        messages = await app.client.get_messages(dialog.id, limit=12, min_id=since)
        answered = {m.reply_to_msg_id for m in messages if m.out and m.reply_to_msg_id}
        for msg in reversed(messages):  # oldest first: everyone who called you and got no answer yet
            if msg.out or (dialog.id, msg.id) in group_done or msg.id in answered or not addressed_to_me(msg):
                continue
            if time.time() - msg.date.timestamp() > C.GROUP_FRESH:
                continue
            sender = await msg.get_sender()
            if isinstance(sender, User) and not sender.bot:
                group_done.add((dialog.id, msg.id))
                if sender.id not in commander_ids and not mention_allowed(dialog.id, sender.id, f"{full_name(sender)} @ {dialog.name}"):
                    continue
                log.info("%s: found a missed mention in the group scan", dialog.name)
                answer_in_group(msg, sender)
    group_names.clear()  # a group you were removed from, or left, drops off the dashboard list
    group_names.update(current)


JOIN_HINT = ("\nThis is a GROUP chat. Below is the recent conversation; lines start with who wrote them ('You' is "
             "you). NOBODY addressed you. Decide the way a real member of this group would whether to write anything:\n"
             "- write if the last message is a question or a remark to everyone that you have a real answer or opinion "
             "on, if they are talking about you, or if it continues an exchange you are already part of;\n"
             "- stay out if the others are talking to each other, if it is not your business, if someone already "
             "answered, or if all you could add is an agreement, a greeting or a filler.\n"
             "Most of the time the right choice is to stay out. If you stay out, answer with exactly SKIP. Otherwise "
             "write ONE short message in the way you write in this group — no greeting, no questions just to keep "
             "talking, no stickers or GIFs.\n")
identity_asked: dict[tuple[int, int], float] = {}   # (group, person) -> when their "are you a bot?" was last ignored
join_log: dict[int, list[float]] = {}        # group -> when the account wrote there without being called
join_tasks: dict[int, asyncio.Task] = {}     # group -> the "should I say something?" that is still settling


def may_join(chat_id: int, msg, history) -> bool:
    """The cheap part of the decision, before any model is asked: is this even a moment to consider speaking?"""
    now = time.time()
    recent = join_log[chat_id] = [t for t in join_log.get(chat_id, []) if now - t < 3600]
    if len(recent) >= C.JOIN_PER_HOUR or (recent and now - recent[-1] < C.JOIN_GAP):
        return False
    text = msg.raw_text or ""
    if not text.strip() or TEACHER_RE.search(text) or re.search(r"@\w{4,}", text):
        return False  # nothing said, an adult speaking formally, or it is addressed to someone by @name
    if getattr(msg, "reply_to_msg_id", None) and not any(m.out and m.id == msg.reply_to_msg_id for m in history):
        return False  # a reply to somebody else's message
    mine = next((m for m in history if m.out), None)
    if len(history) >= 2 and all(m.out for m in history[:2]):
        return False  # you spoke last, twice: wait for someone else
    in_conversation = mine is not None and now - mine.date.timestamp() < C.JOIN_ACTIVE
    return in_conversation or ("?" in text and random.random() < C.JOIN_COLD_CHANCE)


def consider_joining(event, sender):
    """Something was said in a group where the account may join in: think it over once the chat has settled."""
    old = join_tasks.pop(event.chat_id, None)
    if old:
        old.cancel()  # a newer message: decide about the conversation as it is now

    async def settle():
        try:
            await asyncio.sleep(rand(C.JOIN_SETTLE))
            history = await app.client.get_messages(event.chat_id, limit=C.GROUP_CONTEXT)
            if not history or history[0].id != event.id or not may_join(event.chat_id, event.message, history[1:]):
                return
            await group_reply_flow(event, sender, joining=True)
        finally:
            if join_tasks.get(event.chat_id) is asyncio.current_task():
                join_tasks.pop(event.chat_id, None)
    join_tasks[event.chat_id] = asyncio.create_task(settle())


async def group_reply_flow(event, sender: User, force: bool = False, joining: bool = False):  # event: Message or NewMessage event
    """Someone mentioned you or replied to you in a group: answer that message, quoting it."""
    chat_id = event.chat_id
    message = getattr(event, "message", None)
    message = event if isinstance(message, str) or message is None else message  # a NewMessage event wraps the Message
    chat = await event.get_chat()
    who = f"{full_name(sender)} @ {getattr(chat, 'title', 'group')}"
    try:
        await asyncio.sleep(0 if force else rhythm.wait_seconds(chat_id) + rand(C.DEBOUNCE))
        text = event.raw_text or ""
        plain = name_re().sub(" ", text).strip(" ,:")   # what they said, without your name
        pressed = identity_asked.get((chat_id, sender.id), 0) > time.time() - 600 and bool(PRESSING_RE.match(plain))
        if not force and (identity_question([message]) == "only" or pressed):
            identity_asked[(chat_id, sender.id)] = time.time()  # insisting right after ("признавайся") is ignored too
            trace.emit("decision", who, "They asked who/what is answering — ignoring it, no reply")
            daylog.record("ignored", who, text)
            return
        if not force and C.HANDOFF and await judge.sensitive_reason(http, full_name(app.me), [message], keywords_only=True):
            trace.emit("warning", who, "Sensitive topic in a group — not replying")
            return
        if not force and TEACHER_RE.search(text):  # a teacher or another adult speaking formally, in front of everyone
            trace.emit("incoming", who, text[:300])
            trace.emit("warning", who, "Formal message to you in a group (a teacher?) — not answering, telling you instead")
            daylog.record("handoff", who, f"formal message in a group: {text[:200]}")
            await app.client.send_message("me", f"🚨 {who} addressed you formally in the group:\n“{text[:300]}”\n"
                                            "I did not answer — that one is yours.")
            return
        history = await app.client.get_messages(chat_id, limit=C.GROUP_CONTEXT)
        lines = []
        for msg in reversed(history):
            content = describe(msg)
            if content:
                author = "You" if msg.out else (full_name(msg.sender) if isinstance(msg.sender, User) else "Someone")
                lines.append(f"{author}: {content}")
        system = persona.format(name=app.me.first_name or full_name(app.me),
                                contact=f"{full_name(sender)} (in the group “{getattr(chat, 'title', '')}”)",
                                style=style_block(full_name(sender), text),
                                now=datetime.now().strftime("%A %d %B %Y, %H:%M"),
                                status=rhythm.status())
        system += memory.facts_block(full_name(app.me)) + (
            JOIN_HINT if joining else GROUP_HINT.format(sender=full_name(sender), message=text[:500]))
        if identity_question([message]) == "mixed":
            system += IDENTITY_HINT
        if not joining:  # a message nobody addressed to you is logged only if you decide to answer it
            trace.emit("incoming", who, text[:300])
            trace.emit("decision", who, "They called you in a group — writing a reply")
        ask = ("\n".join(lines) + f"\n\n---\nYou are “You” in this conversation. Write the one message You send now in "
               f"reply to {full_name(sender)}'s last message. Output only the text of that message.")

        async def write(extra: str = "") -> str:
            resp = await http.post("/complete", json={"messages": [{"role": "user", "content": ask}],
                                                      "system": system + extra, "models": C.MODELS, "max_tokens": 300})
            return "" if resp.is_error else clean_reply(resp.json()["reply"])

        reply = await write()
        if joining:
            if not reply or re.match(r"\W*SKIP\b", reply, re.I) or "SKIP" in reply:
                log.info("%s: not called, decided to stay out", who)
                return
            trace.emit("incoming", who, text[:300])
            trace.emit("decision", who, "Not called, but decided to say something")
            join_log.setdefault(chat_id, []).append(time.time())
        if not reply:
            trace.emit("warning", who, "No model answered — staying quiet in the group")
            return
        # the same limits as in private chats: no promises, no made-up facts about your day, no repeated lines
        over = judge.overreach(text, reply, memory.today_note())
        if over:
            trace.emit("decision", who, f"Draft made a {over} I can't back up (“{reply[:60]}”) — rewriting")
            again = await write(judge.NOT_KNOWN_HINT if over == "situation" else
                                "\nYour draft agreed to something or said yes/no about what you did, but you don't know "
                                "that. Put it off in a few words without agreeing or confirming.\n")
            reply = again if again and not judge.overreach(text, again, memory.today_note()) \
                else judge.dodge(over, lang.base(lang.detect(name_re().sub(' ', text))), text)
        if reply and DEFER_RE.search(reply):  # in a group nobody waits for "ща гляну": answer now, or say you can't
            again = await write("\nDon't say that you'll look, check or send something in a moment. Either answer now "
                                "or say in a few words that you don't know / can't.\n")
            reply = again if again and not DEFER_RE.search(again) and not judge.overreach(text, again, memory.today_note()) \
                else judge.dodge("commitment", lang.base(lang.detect(name_re().sub(" ", text))))
        if stale_parts(history, split_reply(reply)):
            again = await write("\nDon't repeat a line that is already in the conversation — not theirs, not yours.\n")
            reply = again if again and not stale_parts(history, split_reply(again)) else ""
        limit, _ = quirks.length_limits(style_stats(sender), text)
        parts = [quirks.shorten(p, limit) for p in split_reply(reply) if not media.MEDIA_LINE_RE.match(p)]
        habits = punct_profile(sender)  # no textbook full stops in a group either
        reply = "\n".join(p for p in (punct.apply(p, habits) for p in parts[:2]) if p)
        if not reply or not looks_safe(reply) or (C.REVIEW and await judge.review(http, plain or text, reply)):
            trace.emit("warning", who, f"Draft for the group wasn't good enough — staying quiet: {reply[:120]}")
            return
        draft_id = trace.new_draft_id()
        hold = max(rhythm.thinking_seconds(text, reply, chat_id), C.MIN_HOLD) if pacing_on() else 0
        trace.emit("draft", who, reply, draft_id=draft_id, parts=[reply], hold=hold, approve=state.approve)
        verdict, edited = await hold_draft(draft_id, hold)
        if verdict != "send":
            trace.emit("cancelled", who, "Draft cancelled or not approved", draft_id=draft_id)
            return
        if edited:
            reply = "\n".join(edited)
        trace.emit("decision", who, "Typing…", draft_id=draft_id, phase="typing", index=0)
        await type_like_a_person(chat_id, reply)
        our_texts.setdefault(chat_id, []).append(reply)
        sent = await app.client.send_message(chat_id, reply, reply_to=None if joining else event.id)
        our_ids.add(sent.id)
        trace.emit("sent", who, reply, draft_id=draft_id, index=0, final=True)
        log.info("%s: replied in group (%d chars)", who, len(reply))
        daylog.record("replied", who, reply, them=text[:200])
        rhythm.replied(chat_id)
        rhythm.online_for_a_bit(app.client)
    except asyncio.CancelledError:
        raise
    except (errors.ChannelPrivateError, errors.ChatWriteForbiddenError, errors.UserBannedInChannelError) as e:
        log.info("%s: can't write there any more (%s)", who, e.__class__.__name__)
        trace.emit("warning", who, "Can't write in this group any more (removed, banned or muted) — taking it off the list")
        group_names.pop(chat_id, None)
    except Exception:
        log.exception("%s: group reply failed", who)
    finally:
        group_tasks.pop((chat_id, event.id), None)
