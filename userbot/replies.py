"""Private chats: the whole path from "someone wrote" to "a reply was sent" — plus writing first, asking again
when ignored, answering a flood with a flood, and picking up unread chats."""
import asyncio
from collections import deque
import itertools
import random
import re
import time
from datetime import datetime
import httpx
from telethon import errors, functions
from telethon.tl.types import InputDialogPeer, ReactionEmoji, User
from . import config as C
from . import daylog, judge, lang, media, memory, pfp, punct, quirks, rhythm, salam, voice
from . import people, trace
from . import app, lessons, lookup
from .app import TELEGRAM_SERVICE_ID, asked, commander_ids, commanding, contacts, forced, full_name, hold_draft, http, label, log, names, our_ids, our_texts, owner_quiet_in, pacing_on, pending, rand, recent_incoming, revives, send_as_bot, sent_by_us, spam_until, spawn, state, to_chat_messages, type_like_a_person
from .drafting import FORCE_LANG, contact_style_path, generate, persona, punct_profile, style_block, style_stats
from .wording import IDENTITY_HINT, PRESSING_RE, answer_each, clean_reply, identity_ignored, identity_question, is_identity_question, looks_safe, split_reply, stale_parts


# formal Russian, the way a teacher or an official writes (family members have their own style files)
TEACHER_RE = re.compile(r"здравствуйте|\bвы\b|\bвас\b|\bвам\b|\bваш\w*|\b(зайдите|подойдите|передайте|принесите|сдайте|"
                        r"напишите|ответьте|сообщите)\b", re.I)


# what people actually tap a reaction on: laughs, good news, congratulations, compliments, emoji-heavy messages
REACTABLE_RE = re.compile(r"аха|хаха|лол|\blol\b|lmao|ура|поздрав|молодец|красав|круто|класс|супер|выиграл|получил|сдал|"
                          r"\b(nice|congrats|won|yay|let'?s go)\b|zo'?r|tabrik|[\U0001F600-\U0001F64F\U0001F389\U0001F525\u2764]", re.I)


async def remember_later(chat_id: int, who: str, their_messages: list[str]):
    try:
        for note in await memory.remember(http, chat_id, who, their_messages):
            log.info("%s: remembered %r", who, note)
            daylog.record("note", who, note)
            trace.emit("decision", who, f"Noted for later: {note}")
        upcoming = await people.note_upcoming(http, chat_id, who, "\n".join(their_messages))
        if upcoming:
            log.info("%s: will ask about %r after %s", who, upcoming["what"], upcoming["ask_after"])
            trace.emit("decision", who, f"Will ask how “{upcoming['what']}” went (from {upcoming['ask_after']})")
    except Exception:
        log.exception("%s: remembering failed", who)


async def no_text_reply(chat_id: int, who: str, action: str, history):
    """An acknowledgement doesn't need words: leave it, or put a reaction on their message."""
    if action == "skip":
        log.info("%s: no reply needed", who)
        daylog.record("skipped", who)
        trace.emit("decision", who, "Their message doesn't need a reply — leaving it")
        return
    emoji = action.split(":", 1)[1]
    target = next((m for m in history if not m.out), None)
    if not target:
        return
    await asyncio.sleep(rhythm.reading_seconds(history) + random.uniform(0.5, 2.5) if pacing_on() else 0)
    try:
        await app.client(functions.messages.SendReactionRequest(peer=chat_id, msg_id=target.id,
                                                            reaction=[ReactionEmoji(emoticon=emoji)]))
    except errors.RPCError as e:
        log.info("%s: reaction not possible (%s)", who, e.__class__.__name__)
        trace.emit("decision", who, "No reply needed (a reaction wasn't possible here) — leaving it")
        return
    log.info("%s: reacted %s", who, emoji)
    daylog.record("reacted", who, emoji)
    rhythm.online_for_a_bit(app.client)
    trace.emit("sent", who, f"[reaction {emoji}] instead of a text reply")


# "ок щас", "ща гляну", "lemme check": a promise to come back in a moment
DEFER_RE = re.compile(
    r"\b(щас|ща|секунд\w*|сек|минутк\w*|минуту|погоди|подожди)\b|\bсейчас\s*(?:$|[,.!]|скину|гляну|посмотрю|проверю|сделаю|напишу|найду)"
    r"|\b(гляну|посмотрю|проверю|поищу|узнаю|уточню)\b"
    r"|\b(lemme|let\s+me)\s+(check|see|look)\b|\b(one|a|1)\s+sec\b|\bhold\s+on\b|\bbrb\b|\bhozir\b|\bqara(yman|b)\b|\bko'raman\b", re.I)
CAME_BACK = {"ru": ["не, хз если честно", "не нашёл пока", "не, не знаю"], "en": ["nah idk tbh", "couldn't find it"],
             "uz": ["topolmadim hozircha", "bilmadim rosti"]}


async def come_back(chat_id: int, contact: User, who: str, after_id: int, their_text: str, said: str):
    """You said "щас" — so a moment later you come back with something: the answer if it can be found, or a plain
    "couldn't find out". Staying silent after "one sec" is the one thing a person doesn't do."""
    try:
        await asyncio.sleep(rand(C.FOLLOW_UP))
        if state.is_paused() or not state.is_active(chat_id, C.REPLY_MODE) or chat_id in pending or state.handed_off(chat_id):
            return
        history = await app.client.get_messages(chat_id, limit=C.CONTEXT_MESSAGES)
        if not history or history[0].id != after_id:
            return  # they wrote again, or you did: the conversation moved on by itself
        found = await lookup.research(http, history[1:], their_text) if C.LOOKUP_ON else None
        system = persona.format(name=app.me.first_name or full_name(app.me), contact=who,
                                style=style_block(who, their_text, contact),
                                now=datetime.now().strftime("%A %d %B %Y, %H:%M"), status=rhythm.status())
        system += memory.facts_block(full_name(app.me)) + memory.notes_block(chat_id, who) + (found[1] if found else "")
        messages = to_chat_messages(history) + [{"role": "user", "content": (
            f"[A minute ago you told them “{said}” — that you would get back to them. Now do it, in ONE short message "
            "in your style. If what they wanted is something you know or just looked up, give it. If it is something "
            "about your real life that you don't actually know here, or something you'd have to do in person (send a "
            "file, come somewhere, call), say plainly that you can't right now or don't know. Never say \"one sec\" / "
            "\"щас\" / \"later\" again. Output only the message.]")}]
        text = ""
        try:
            resp = await http.post("/complete", json={"messages": messages, "system": system, "models": C.MODELS,
                                                      "max_tokens": 80, "temperature": C.TEMPERATURE})
            lines = clean_reply(resp.json()["reply"]).splitlines() if resp.is_success else []
            text = punct.apply(lines[0].strip(), punct_profile(contact)) if lines else ""
        except Exception:
            log.exception("%s: follow-up could not be written", who)
        grounded = found is not None
        handing_over = re.fullmatch(r"\W*(вот|держи|лови|на|here|there you go|mana)\W*", text, re.I)  # nothing is attached
        if not text or handing_over or not looks_safe(text) or DEFER_RE.search(text) or stale_parts(history, [text]) \
                or (not grounded and judge.overreach(their_text, text, memory.today_note())):
            text = random.choice(CAME_BACK.get(lang.base(lang.detect(their_text)) or "ru", CAME_BACK["ru"]))
        if (await app.client.get_messages(chat_id, limit=1))[0].id != after_id:
            return
        trace.emit("decision", who, f"Said “{said}” a moment ago — coming back with: {text[:80]}")
        await type_like_a_person(chat_id, text)
        await send_as_bot(chat_id, text)
        trace.emit("sent", who, text)
        daylog.record("replied", who, text, them="(following up on your own “" + said[:40] + "”)")
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("%s: follow-up failed", who)


async def who_is_this(chat_id: int, contact: User, who: str, history, their_text: str) -> str:
    """Someone you don't know writes: find out who it is. -> a hint for the reply ("ask who this is"), or "".
    The question is asked ONCE, and only in a chat where you have never written anything. Once they say who they
    are, they get a folder (people.py) and are saved to your Telegram contacts."""
    if not C.INTRO_ON or contact.contact or contact_style_path(contact) or chat_id in commander_ids:
        return ""
    prof = people.profile(chat_id)
    if prof.get("who") in ("known", "unknown", "before"):
        return ""
    if prof.get("who") is None and any(m.out for m in history):
        people.save_profile(chat_id, who, who="before")  # you have written here before: you know who this is
        return ""
    info = await people.introduced(http, their_text)
    if info:
        about = info["about"]
        relative = bool(info.get("relative"))
        name = info["name"] or who                      # a relative says who they are to you, not their name
        people.save_profile(chat_id, name, who="known", given_name=info["name"] or None, about=about, telegram_name=who,
                            username=contact.username, met=time.strftime("%Y-%m-%d"))
        memory.add_note(chat_id, f"представился: {about if relative else name}" + (f" ({about})" if about and not relative else ""),
                        source="intro", who=name)
        first, last = (who, f"({about})") if relative else (name, about[:30])
        saved = ""
        if C.ADD_CONTACTS:
            try:
                await app.client(functions.contacts.AddContactRequest(id=contact, first_name=first[:60], last_name=last[:60],
                                                                       phone="", add_phone_privacy_exception=False))
                saved = f" and saved to your contacts as “{first} {last}”".rstrip()
            except Exception as e:
                log.warning("%s: could not add to contacts (%s: %s)", who, e.__class__.__name__, e)
                trace.emit("warning", who, f"Couldn't save them to your contacts ({e.__class__.__name__})")
        names[chat_id] = f"{first} {last}".strip()
        log.info("%s said who they are: %s", who, about if relative else name)
        trace.emit("system", who, f"Now known as {name}" + (f" — {about}" if about else "") + saved)
        spawn(app.client.send_message("me", f"👤 {who} says who they are: " + (about if relative else name + (f" — {about}" if about else ""))
                                      + (f" (@{contact.username})" if contact.username else "") + f".\nNoted{saved}."
                                      + ("\nIf that really is family, tell me and I'll treat them as family." if relative else "")))
        return (f"\nThey just told you who they are: {about if relative else name}"
                + (f" ({about})" if about and not relative else "") + ". Take it in naturally, in a word or two; don't "
                "repeat it back and don't ask again.\n")
    tries = prof.get("asked", 0)
    if tries >= 1:  # the question was asked once already; it is never asked a second time
        people.save_profile(chat_id, who, who="unknown" if tries >= 3 else "asked", asked=tries + 1)
        return ""
    people.save_profile(chat_id, who, who="asked", asked=1, telegram_name=who, username=contact.username)
    trace.emit("decision", who, "Not in your contacts and you never wrote here — asking who it is (once)")
    return people.ASK_HINT


async def write_first():
    """Now and then, open a chat yourself: ask how the thing they told you about went, or just what's up."""
    now = datetime.now()
    if not C.INITIATE_ON or state.is_paused() or state.approve or rhythm.asleep() or rhythm.busy() \
            or not C.INITIATE_HOURS[0] <= now.hour < C.INITIATE_HOURS[1]:
        return
    record = state.initiated
    if record.get("date") != now.strftime("%Y-%m-%d"):
        record.update(date=now.strftime("%Y-%m-%d"), count=0)
    if record["count"] >= C.INITIATE_MAX:
        return
    with_reason, friends = [], []
    for prof in people.everyone():
        cid = prof.get("id")
        if not isinstance(cid, int) or cid in pending or cid in commander_ids or cid in state.manual \
                or not state.is_active(cid, C.REPLY_MODE) or state.handed_off(cid) \
                or time.time() - record.get("last", {}).get(str(cid), 0) < C.INITIATE_GAP:
            continue
        thread = people.due_thread(cid) if C.REMEMBER else None
        if thread:
            with_reason.append((cid, thread))
        elif prof.get("closeness") == "close":
            friends.append((cid, None))
    if not with_reason and (not friends or random.random() > C.INITIATE_CHANCE):
        return
    chat_id, thread = random.choice(with_reason or friends)
    history = await app.client.get_messages(chat_id, limit=C.CONTEXT_MESSAGES)
    if not history:
        return
    quiet = time.time() - history[0].date.timestamp()
    if not history[0].out and quiet < C.RECENT_UNANSWERED:
        return  # they are waiting for an answer anyway; that is the reply flow's job
    if quiet < C.INITIATE_QUIET[0] and not thread or quiet > C.INITIATE_QUIET[1]:
        return
    contact = await app.client.get_entity(chat_id)
    if not isinstance(contact, User) or contact.bot:
        return
    who = names.setdefault(chat_id, full_name(contact))
    ask = (f"ask how “{thread['what']}” went — they told you about it on {thread['noted']}" if thread
           else "ask what they are up to, or how the day is going")
    system = persona.format(name=app.me.first_name or full_name(app.me), contact=who, style=style_block(who, "", contact),
                            now=now.strftime("%A %d %B %Y, %H:%M"), status=rhythm.status())
    system += memory.facts_block(full_name(app.me)) + memory.notes_block(chat_id, who)
    messages = to_chat_messages(history) + [{"role": "user", "content": (
        "[No new message from them. You decide to text them first, after a pause in the conversation. Write ONE short "
        f"opening line the way you text this person out of the blue: {ask}. In the language you two use. No formal "
        "greeting, no news about yourself, no emoji, nothing that was already said above. Output only the line.]")}]
    try:
        resp = await http.post("/complete", json={"messages": messages, "system": system, "models": C.MODELS,
                                                  "max_tokens": 60, "temperature": C.TEMPERATURE})
    except httpx.HTTPError:
        return
    if resp.is_error:
        return
    lines = clean_reply(resp.json()["reply"]).splitlines()
    opener = punct.apply(lines[0].strip(), punct_profile(contact)) if lines else ""
    if not opener or len(opener) > 70 or not looks_safe(opener) or media.MEDIA_LINE_RE.match(opener) \
            or stale_parts(history, [opener]) or judge.overreach("", opener, memory.today_note()):
        trace.emit("decision", who, f"Thought of writing first, but the line wasn't good — skipped: {opener[:60]}")
        return
    trace.emit("decision", who, "Writing first" + (f" — to ask about “{thread['what']}”" if thread else ""))
    await type_like_a_person(chat_id, opener)
    await send_as_bot(chat_id, opener)
    record["count"] += 1
    record.setdefault("last", {})[str(chat_id)] = time.time()
    state.save()
    if thread:
        people.mark_asked(chat_id, who, thread["what"])
    trace.emit("sent", who, opener)
    daylog.record("replied", who, opener, them="(you wrote first)")
    log.info("%s: wrote first (%d chars)", who, len(opener))


async def initiative_loop():
    while True:
        await asyncio.sleep(600)
        try:
            await write_first()
        except Exception:
            log.exception("Writing first failed")


async def reply_flow(chat_id: int, contact: User):
    who = names[chat_id] = full_name(contact)
    contacts[chat_id] = contact
    force = chat_id in forced  # you clicked "Answer now": answer even what would be handed off, ignored or skipped
    forced.discard(chat_id)
    draft_id, history, failed = None, None, False
    try:
        app.me = await app.client.get_me()  # profile may have been changed from outside (userbot.profile)
        wait = rhythm.wait_seconds(chat_id)
        if wait > 30:
            trace.emit("decision", who, ("At school — " if rhythm.busy() else "Not on the phone right now — ")
                       + f"will look at this in about {wait / 60:.0f} min")
        await asyncio.sleep(wait + rand(C.DEBOUNCE) + rand(C.READ_DELAY))

        # If you've been chatting here yourself, hold off until you've gone quiet, then re-check.
        # (Your own new message in the chat cancels this task entirely.)
        while True:
            history = await app.client.get_messages(chat_id, limit=C.CONTEXT_MESSAGES)
            wait = owner_quiet_in(chat_id, history)
            if not wait:
                break
            log.info("%s: you're active here, holding off %.0fs", who, wait)
            trace.emit("decision", who, f"You wrote in this chat recently — holding off {wait:.0f}s so I don't interrupt")
            await asyncio.sleep(wait + rand(C.READ_DELAY))
        # Listen to voice / round-video messages: from here on their transcript counts as the message text.
        heard = 0
        for msg in itertools.takewhile(lambda m: not m.out, history):
            if (msg.voice or msg.video_note) and not msg.raw_text:
                spoken = await voice.transcript(msg)
                if spoken:
                    msg.message = spoken
                    heard += 1
        if heard:
            trace.emit("decision", who, f"Listened to {heard} voice message(s)")
        fresh = [m for m in itertools.takewhile(lambda m: not m.out, history) if m.id > state.handled.get(str(chat_id), 0)]
        if fresh and C.SMART_SKIP and not force and C.VOICE_TRANSCRIBE \
                and all((m.voice or m.video_note) and not m.raw_text for m in fresh):
            # only voice messages, and nothing in them that could be understood (a laugh, noise): a reaction, not words
            trace.emit("decision", who, "A voice message with no words in it — reacting instead of guessing what it said")
            await app.client.send_read_acknowledge(chat_id)
            await no_text_reply(chat_id, who, "react:👍", history)
            return
        their_text = "\n".join(m.raw_text for m in reversed(list(itertools.takewhile(lambda m: not m.out, history)))
                               if m.raw_text)

        # Questions about who/what is answering are simply ignored — they are not a reason to hand the chat over.
        identity = None if force else identity_question(history, identity_ignored.get(chat_id, 0))
        reason = (await judge.sensitive_reason(http, full_name(app.me), history, keywords_only=identity is not None)
                  if C.HANDOFF and not force else None)
        if not reason and not force and judge.crisis(history):
            reason = "someone in real trouble — this needs you, now"  # regardless of the hand-off switch
        if not reason and chat_id in state.manual and not force:
            reason = "this chat is set to manual (.ai on to change)"
        if not reason and C.HANDOFF and not force and not contact_style_path(contact) \
                and TEACHER_RE.search(their_text) and not judge.closer_action(history, state.handled.get(str(chat_id), 0)):
            reason = "a formal message (teacher / official) — better answered by you"
        if reason:  # this one is yours: don't answer, don't even mark it read
            state.hand_off(chat_id, C.HANDOFF_HOLD)
            snippet = " / ".join(m.raw_text for m in reversed(list(itertools.takewhile(lambda m: not m.out, history)))
                                 if m.raw_text)[:300]
            log.info("%s: handed to owner (%s)", who, reason)
            daylog.record("handoff", who, f"{reason}: {snippet}")
            trace.emit("warning", who, f"Leaving this one to you ({reason}) — not replying, staying out for "
                                       f"{C.HANDOFF_HOLD // 60} min or until you answer")
            await app.client.send_message("me", f"🚨 {who} needs YOU — {reason}.\n“{snippet}”\n"
                                            f"I'm not replying and I'll stay out of that chat for "
                                            f"{C.HANDOFF_HOLD // 60} min (or until you write there).")
            return
        await app.client.send_read_acknowledge(chat_id)
        opened_at = time.monotonic()  # the moment the chat was opened; reading and thinking count from here
        await asyncio.sleep(rand(C.THINK_DELAY))

        hint, pfp_failed = "", False
        if C.CLOSENESS_ON:
            level = await people.closeness(app.client, chat_id, contact, bool(contact_style_path(contact)))
            if not contact_style_path(contact) or level == "family":  # a learned per-person style already carries the tone
                hint += people.CLOSENESS_HINT[level]
        intro = await who_is_this(chat_id, contact, who, history, their_text)
        asking_who = intro == people.ASK_HINT
        hint += intro
        researched = None
        if C.LOOKUP_ON and not asking_who:
            researched = await lookup.research(http, history, their_text)
            if researched:
                hint += researched[1]
                trace.emit("decision", who, f"Looked it up before answering: {researched[0]}")
        due = people.due_thread(chat_id) if C.REMEMBER else None
        if due:
            hint += people.thread_hint(due)
        photo_msg = await pfp.find_request(history) if C.PFP_FROM_CHATS else None
        if photo_msg:
            trace.emit("decision", who, "They asked me to use their photo as the profile picture — checking it")
            outcome = await pfp.apply(app.client, state, http, photo_msg, who)
            trace.emit("system" if outcome == "changed" else "warning", who, {
                "changed": "Profile photo changed to the one they sent (undo: .ai pfp undo)",
                "limit": "Not changing the profile photo — it was changed too recently (rate limit)",
                "unsafe": "Not using that photo — the safety look didn't clear it",
                "error": "Couldn't change the profile photo (download/upload failed)"}[outcome])
            log.info("%s: profile photo request -> %s", who, outcome)
            if outcome == "changed":
                daylog.record("profile", who, f"photo changed on {who}'s request")
            hint = pfp.HINTS[outcome]
            pfp_failed = outcome != "changed"

        greeting = await salam.check(app.client, state, http, history)
        if greeting.sticker:  # a salam sticker is answered with the very same sticker
            trace.emit("decision", who, "They sent an 'Assalomu alaykum' sticker → answering with the same sticker")
            await asyncio.sleep(random.uniform(1.5, 4) if pacing_on() else 0)
            our_texts.setdefault(chat_id, []).append("")
            sent = await app.client.send_file(chat_id, greeting.sticker.media)
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
            trace.emit("sent", who, "[the same salam sticker]")
            log.info("%s: answered salam sticker with the same sticker", who)
            try:
                pack = await salam.save_pack(app.client, greeting.sticker)
                if pack:
                    trace.emit("decision", who, f"Saved sticker pack '{pack}' to the account")
            except Exception:
                log.exception("Could not save sticker pack")
            if not greeting.rest:
                return

        # Dry answers in a live conversation: come up with a topic instead of a 👍 (a couple of tries, then let it go)
        is_dry = judge.dry(history, state.handled.get(str(chat_id), 0))
        ours = next((m for m in history if m.out), None)
        # "Answer now" overrules everything; your own other account only skips the hand-off and identity rules,
        # it still gets 👍 / ❤ like anyone else.
        pushed = force and chat_id not in commander_ids
        # A dry word is a dead end only when it answers YOUR question ("как дела?" — "норм"). After a statement,
        # "ок" / "ладно" just closes the exchange, and that gets a 👍, not a new topic.
        answered_dryly = ours is not None and (ours.raw_text or "").rstrip().endswith("?")
        keep_going = (C.KEEP_TALKING and is_dry and answered_dryly and not pushed and not greeting.reply
                      and not greeting.sticker and not photo_msg and identity is None and not quirks.is_formal(history)
                      and time.time() - ours.date.timestamp() <= C.REVIVE_WINDOW
                      and revives.get(chat_id, 0) < C.REVIVE_MAX)
        if not is_dry:
            revives.pop(chat_id, None)
        if keep_going:
            revives[chat_id] = revives.get(chat_id, 0) + 1
            now = time.localtime()
            hint += judge.KEEP_GOING_HINT.format(clock=time.strftime("%H:%M", now), weekday=time.strftime("%A", now))
            trace.emit("decision", who, f"Dry answer — keeping the chat going with a question or a topic "
                                        f"(try {revives[chat_id]}/{C.REVIVE_MAX})")

        action = (judge.closer_action(history, state.handled.get(str(chat_id), 0))
                  if C.SMART_SKIP and not pushed and not greeting.reply and not greeting.sticker and not photo_msg
                  and not keep_going else None)
        if action and quirks.is_formal(history) and re.search(r"до\s+свидания|всего\s+доброго|xayr", their_text, re.I):
            our_texts.setdefault(chat_id, []).append("До свидания")
            sent = await app.client.send_message(chat_id, "До свидания")
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
            trace.emit("sent", who, "До свидания")
            daylog.record("replied", who, "До свидания", them=their_text[:200])
            return
        if action:
            await no_text_reply(chat_id, who, action, history)
            return

        from_model, several = False, []
        if greeting.reply and not greeting.rest:
            reply = greeting.reply  # fixed text, never written by the model
            trace.emit("decision", who, "They wrote the salam greeting → sending the fixed proper answer (model not used)")
        elif identity == "only":
            identity_ignored[chat_id] = history[0].id
            log.info("%s: identity question ignored", who)
            daylog.record("ignored", who, their_text)
            trace.emit("decision", who, "They asked who/what is answering — ignoring it, no reply")
            return
        else:
            if identity == "mixed":
                trace.emit("decision", who, "Their message also asks who/what is answering — ignoring that part")
                hint += IDENTITY_HINT
            several = [] if identity else quirks.questions_in(
                history, after_id=max(identity_ignored.get(chat_id, 0), state.handled.get(str(chat_id), 0)),
                skip=lambda t: is_identity_question(t) or bool(PRESSING_RE.match(t)))
            if several:  # more than one question: each gets its own answer, quoted
                hint += quirks.MULTI_HINT.format(n=len(several), listing="\n".join(
                    f"{n}. {m.raw_text.strip()[:200]}" for n, m in enumerate(several, 1)))
                trace.emit("decision", who, f"{len(several)} questions — answering each one as a reply to it")
            trace.emit("decision", who, "Read the chat — writing a reply")
            from_model = True
            for attempt in range(C.GENERATE_RETRIES + 1):
                if attempt:  # every model failed — come back later, like a busy person would
                    delay = rand(C.RETRY_DELAY)
                    log.info("%s: models unavailable, retrying in %.0fs (%d/%d)", who, delay, attempt, C.GENERATE_RETRIES)
                    trace.emit("warning", who, f"No model answered — trying again in {delay:.0f}s "
                                               f"(attempt {attempt}/{C.GENERATE_RETRIES})")
                    await asyncio.sleep(delay)
                reply = await generate(history, contact, hint)
                if reply is not None:
                    break
            else:
                log.warning("%s: giving up, no model answered", who)
                trace.emit("warning", who, "Giving up — no model answered")
            action = judge.parse_model_choice(reply or "") if C.SMART_SKIP and not greeting.reply else None
            if keep_going and not action and "?" not in (reply or ""):
                # one more try, said more plainly, before settling for a reaction
                reply = await generate(history, contact, hint + (
                    "\nYour line has to END WITH A QUESTION for them — one short question, nothing else.\n")) or ""
            if keep_going and not action and "?" not in (reply or ""):
                # the point was to give them something to answer; a filler line doesn't, so close like a person would
                trace.emit("decision", who, "No good question came to mind — leaving it at a reaction")
                action = judge.closer_action(history, state.handled.get(str(chat_id), 0)) if C.SMART_SKIP else None
                if not action:
                    return
            if action:  # the model decided this needs no text
                await no_text_reply(chat_id, who, action, history)
                return
            reply = clean_reply(reply or "")
            if greeting.reply:  # salam + something else: fixed greeting first, then the model's answer
                rest = salam.strip_greeting_line(reply)
                rest = "\n".join(salam.TAIL_RE.sub(" ", salam.SALAM_RE.sub(" ", ln)).strip(" ,.!") if salam.SALAM_RE.search(ln)
                                 else ln for ln in rest.splitlines())
                reply = (greeting.reply + "\n" + rest).strip()
        if identity == "mixed" and re.fullmatch(r"\W*(да|нет|неа|ага|угу|yes|no|nah|nope|yeah|yep|[12]|ha|yo'?q|бот|bot)\W*", reply or "", re.I):
            # a bare yes / no / "2" to a message that also asked what is answering IS an answer to that: not sent
            trace.emit("decision", who, "The draft answered the who-is-answering part with a yes/no — not sending it")
            identity_ignored[chat_id] = history[0].id
            return
        if not reply:
            # the model answered with nothing usable (often just an emoji, which is stripped): a 👍 says the same
            if C.SMART_SKIP and from_model and "?" not in their_text and their_text.strip():
                trace.emit("decision", who, "Nothing worth writing — a reaction instead")
                await no_text_reply(chat_id, who, "react:👍", history)
                return
            trace.emit("decision", who, "Nothing to send — staying quiet")
            return
        if not looks_safe(reply):
            log.warning("%s: blocked suspicious reply (%d chars): %r — retrying once", who, len(reply), reply[:200])
            trace.emit("warning", who, f"Blocked a suspicious draft ({len(reply)} chars), writing another: {reply[:160]}")
            reply = clean_reply(await generate(history, contact, hint) or "")
            if not reply or not looks_safe(reply):
                log.warning("%s: second reply also unusable, staying quiet", who)
                trace.emit("warning", who, "Second draft was unusable too — staying quiet")
                return

        # no sticker on top of a sticker, and none when the point is to get them talking
        media_just_sent = any(m.out and (getattr(m, "sticker", None) or getattr(m, "gif", None)) for m in history[:4])
        allow_media = C.MEDIA_ENABLED and not contact_style_path(contact) and not keep_going and not media_just_sent
        parts = [p for p in split_reply(reply, len(several)) if allow_media or not media.MEDIA_LINE_RE.match(p)]
        formal = quirks.is_formal(history)
        fixed = greeting.reply if greeting.reply else None  # the fixed salam line is never rewritten
        if from_model:
            # It must not agree to plans or claim what you did or didn't do: rewrite once, then use a neutral phrase.
            said = " ".join(p for p in parts if p != fixed and not media.MEDIA_LINE_RE.match(p))
            over = None if answer_each(several, parts, fixed) else judge.overreach(their_text, said, memory.today_note())
            if researched and over in ("situation", "claim"):
                over = None  # "Белл получил патент в 1876" is the looked-up fact, not something about your own day
            if photo_msg and not pfp_failed and over == "claim":
                over = None  # the profile photo really was changed just now: "готово" is true
            if over:
                trace.emit("decision", who, f"Draft made a {over} I can't back up (“{said[:60]}”) — rewriting")
                again = clean_reply(await generate(history, contact, hint + (
                    "\nYour draft agreed to a plan or promised something. You don't know yet whether you can — say so, "
                    "briefly, without agreeing.\n" if over == "commitment" else judge.NOT_KNOWN_HINT if over == "situation" else
                    "\nYour draft said yes or no about something you did today, but you don't know that. Don't answer "
                    "yes or no — put it off briefly.\n")) or "")
                again_parts = [p for p in split_reply(again, len(several)) if allow_media or not media.MEDIA_LINE_RE.match(p)]
                again_said = " ".join(p for p in again_parts if not media.MEDIA_LINE_RE.match(p))
                if again_said and looks_safe(again) and not judge.overreach(their_text, again_said, memory.today_note()):
                    reply, parts = again, ([fixed] if fixed else []) + again_parts
                else:
                    neutral = judge.dodge(over, lang.base(lang.detect(their_text)))
                    reply, parts = neutral, ([fixed] if fixed else []) + [neutral]
                if over == "situation":  # only you know the answer: tell you, and how to tell the account
                    spawn(app.client.send_message("me", f"❓ {who} asked something only you know:\n“{their_text[:300]}”\n"
                                                    f"I answered: “{' / '.join(parts)[:200]}”. If it matters, answer "
                                                    "them yourself — or tell me with  .ai today <what's going on>."))
            parts = [p if media.MEDIA_LINE_RE.match(p) or p == fixed else quirks.fix_greeting(p, their_text, formal) if i == 0 else p
                     for i, p in enumerate(parts)]
            # Saying the exact same thing as a moment ago is what bots do: ask for a different wording once.
            recent_own = {re.sub(r"[\W_]+", " ", (m.raw_text or "").lower()).strip() for m in history[:8] if m.out}
            said = re.sub(r"[\W_]+", " ", " ".join(parts).lower()).strip()
            if said and said in recent_own and len(said.split()) >= 2:
                trace.emit("decision", who, "Same wording as a moment ago — rewriting it differently")
                again = clean_reply(await generate(history, contact, hint + (
                    f"\nYou already wrote exactly “{' '.join(parts)}” a moment ago. Answer what they said now, "
                    "in different words.\n")) or "")
                if again and looks_safe(again):
                    reply = again
                    parts = [p for p in split_reply(reply, len(several)) if allow_media or not media.MEDIA_LINE_RE.match(p)]
        if from_model:
            # You text short. A rambling draft is rewritten once, then cut down if it's still too long.
            limit, max_parts = quirks.length_limits(style_stats(contact), their_text)
            max_parts = max(max_parts, len(several))
            if researched:
                limit = max(limit * 2, 160)  # a fact with its backing needs a little more room
            text_parts = [p for p in parts if not media.MEDIA_LINE_RE.match(p)]
            if any(len(p) > limit for p in text_parts) or len(text_parts) > max_parts + 1:
                trace.emit("decision", who, f"Draft too long ({max(map(len, text_parts))} chars) — rewriting it shorter")
                words = max(4, limit // 7)
                shorter = clean_reply(await generate(history, contact, hint + (
                    f"\nYour draft was far too long. You text in very short messages: answer in at most {words} "
                    "words, one message, no explanations and no story.\n")) or "")
                if shorter and looks_safe(shorter):
                    reply = shorter
                    parts = [p for p in split_reply(reply, len(several)) if allow_media or not media.MEDIA_LINE_RE.match(p)]
                text_seen, kept = 0, []
                for p in parts:  # whatever is left: at most max_parts short messages
                    if media.MEDIA_LINE_RE.match(p):
                        kept.append(p)
                    elif text_seen < max_parts:
                        kept.append(quirks.shorten(p, limit))
                        text_seen += 1
                parts = kept
            # the model punctuates like a textbook; you don't
            habits = punct_profile(contact)
            parts = [p if media.MEDIA_LINE_RE.match(p) or p == fixed else punct.apply(p, habits) for p in parts]
            parts = [p for p in parts if p]
        if not parts:
            return

        # Never the same line again: a draft that repeats what was already said gets rewritten, then trimmed.
        stale = stale_parts(history, [p for p in parts if p != fixed]) if from_model else []
        if stale:
            log.info("%s: draft repeats earlier messages: %r", who, stale)
            trace.emit("warning", who, "Draft repeats what was already said (" + " / ".join(stale)[:120] + ") — rewriting")
            again = clean_reply(await generate(history, contact, hint + (
                "\nYou have ALREADY sent these exact lines in this chat: " + " | ".join(f"“{p}”" for p in stale) +
                ". Do not write them again, and do not copy any of your earlier messages or theirs. React to what "
                "they just wrote with different words.\n")) or "")
            habits = punct_profile(contact)
            fresh = [p if media.MEDIA_LINE_RE.match(p) else punct.apply(p, habits)
                     for p in split_reply(again, len(several)) if allow_media or not media.MEDIA_LINE_RE.match(p)] if looks_safe(again) else []
            fresh = [p for p in fresh if p and p not in stale_parts(history, fresh)]
            parts = ([fixed] if fixed else []) + (fresh or [p for p in parts if p != fixed and p not in stale])
            reply = "\n".join(parts)
            if not parts:
                trace.emit("decision", who, "Nothing new to say — not sending the same line again")
                daylog.record("skipped", who)
                return

        # A second look before anything is sent: wrong language, nonsense words, a missed question…
        if C.REVIEW and from_model:
            expected = "the language these two normally use with each other" if contact_style_path(contact) else None
            # a sticker, a GIF or one word says nothing about the language: go by how this chat has been going
            basis = their_text if len(their_text.split()) >= 2 else "\n".join(
                [their_text] + [m.raw_text for m in history if m.raw_text][:6])
            problem = await judge.review(http, basis, "\n".join(parts), expected)
            if problem and problem.startswith("Uzbek word") and contact_style_path(contact):
                FORCE_LANG[str(contact_style_path(contact))] = "ru"  # the model's Uzbek failed: answer in Russian
            if problem:
                log.info("%s: draft rejected (%s): %r", who, problem, reply[:120])
                trace.emit("warning", who, f"Second look rejected the draft ({problem}) — rewriting: {reply[:140]}")
                retry_hint = hint + f"\nYour previous draft was rejected: {problem}. Write a better, simpler reply.\n"
                if problem.startswith(("Uzbek word", "wrong language (uz")):
                    retry_hint += "Write this reply in Russian.\n"
                elif problem.startswith("wrong language"):
                    retry_hint += ("Write in the language this chat is in. If you meant to send a GIF, write a normal "
                                   "short text reply instead.\n")
                reply = clean_reply(await generate(history, contact, retry_hint) or "")
                parts = [p if media.MEDIA_LINE_RE.match(p) else punct.apply(p, habits)
                         for p in split_reply(reply, len(several)) if allow_media or not media.MEDIA_LINE_RE.match(p)]
                problem = (await judge.review(http, basis, "\n".join(parts), expected)
                           if parts and looks_safe(reply) else "no usable second draft")
                if problem:
                    log.warning("%s: second draft rejected too (%s) — leaving it to the owner", who, problem)
                    trace.emit("warning", who, f"Couldn't write a good reply ({problem}) — leaving this one to you")
                    daylog.record("failed", who, their_text)
                    await app.client.send_message("me", f"🤷 I couldn't write a good reply to {who} ({problem}).\n"
                                                    f"“{their_text[:300]}”\nThat one is yours.")
                    return

        # The photo was NOT changed: a reply must not say it was.
        if pfp_failed:
            parts = [p for p in parts if not re.search(r"готово|обновл|поставил|поменял|сменил|установил|done|changed|updated|set\b", p, re.I)]
            if not parts:
                return

        if from_model:
            parts = [p if media.MEDIA_LINE_RE.match(p) else memory.right_age(their_text, p) for p in parts]

        # They asked for proof and something was found: the source goes along, as its own message.
        if from_model and researched and researched[2] and lookup.PROOF_RE.search(their_text) \
                and not any("http" in p for p in parts):
            parts = parts[:1] + [researched[2]]
            reply = "\n".join(parts)

        # An unknown person must actually be asked who they are, even if the model forgot to.
        if from_model and asking_who and not any(people.ASKS_WHO_RE.search(p) for p in parts):
            parts = parts[:1] + [people.WHO_LINES.get(lang.base(lang.detect(their_text)), people.WHO_LINES["ru"])]
            reply = "\n".join(parts)

        # Two thoughts, two messages — the way people text.
        if from_model and C.SPLIT_ON and not formal and not several and random.random() < C.SPLIT_CHANCE:
            texts = [p for p in parts if p != fixed and not media.MEDIA_LINE_RE.match(p)]
            if len(texts) == 1:
                halves = [punct.apply(h, punct_profile(contact)) for h in quirks.split_two(texts[0])]
                if len(halves) == 2 and all(halves):
                    at = parts.index(texts[0])
                    parts[at:at + 1] = halves
                    reply = "\n".join(parts)

        # Last gate: whatever the rewrites above produced, it still may not promise or claim things for you.
        if from_model:
            said = " ".join(p for p in parts if p != fixed and not media.MEDIA_LINE_RE.match(p))
            late = None if answer_each(several, parts, fixed) or not said \
                else judge.overreach(their_text, said, memory.today_note())
            if (researched and late in ("situation", "claim")) or (photo_msg and not pfp_failed and late == "claim"):
                late = None
            if late:
                neutral = judge.dodge(late, lang.base(lang.detect(their_text)))
                trace.emit("decision", who, f"A rewrite still made a {late} (“{said[:50]}”) — sending “{neutral}” instead")
                parts = ([fixed] if fixed else []) + [neutral]
                reply = "\n".join(parts)

        # Show the draft on the dashboard for a moment; Cancel there stops it.
        draft_id = trace.new_draft_id()
        if pacing_on():
            # How long a person would take before starting to type: read what came in, then think —
            # barely at all for "ок", noticeably for a calculation or a decision.
            read = rhythm.reading_seconds(history)
            think = rhythm.thinking_seconds(their_text, "\n".join(parts), chat_id) if from_model else random.uniform(0.5, 2)
            hold = max(read + think - (time.monotonic() - opened_at), C.MIN_HOLD)
            trace.emit("decision", who, f"Reading ~{read:.0f}s, thinking ~{think:.0f}s before typing")
        else:
            hold = 0
        trace.emit("draft", who, "\n".join(parts), draft_id=draft_id, parts=parts, hold=hold, approve=state.approve)
        verdict, edited = await hold_draft(draft_id, hold)
        if verdict == "cancelled":
            log.info("%s: draft cancelled from the dashboard", who)
            trace.emit("cancelled", who, "You cancelled this draft on the dashboard", draft_id=draft_id)
            return
        if verdict == "expired":
            log.info("%s: draft not approved in time, dropped", who)
            trace.emit("cancelled", who, f"Nobody approved this draft within {C.APPROVE_TIMEOUT // 60} min — dropped",
                       draft_id=draft_id)
            failed = True  # still unanswered: it stays yours
            return
        if edited:  # you rewrote it on the dashboard: send exactly that — and learn from the correction
            if from_model and edited != parts:
                lessons.add_fix(their_text, "\n".join(parts), "\n".join(edited))
                trace.emit("system", who, "Learned from your correction of this draft")
            parts, from_model = edited, False
            trace.emit("decision", who, "Sending your edited version", draft_id=draft_id)

        quote = quirks.reply_target(history)          # swipe-reply to a specific message when that's natural
        # several questions: line 1 answers question 1, line 2 answers question 2… each sent as a reply to its own
        lines = [i for i, p in enumerate(parts) if not media.MEDIA_LINE_RE.match(p) and p != fixed]
        quotes = dict(zip(lines, several)) if from_model and len(several) >= 2 and len(lines) >= 2 else {}
        slips = from_model and not quirks.is_formal(history)  # typos only in casual chats, never in fixed replies
        sent_count = 0
        for i, part in enumerate(parts):
            if await trace.draft_cancelled(draft_id):
                log.info("%s: draft cancelled from the dashboard", who)
                trace.emit("cancelled", who, "You cancelled this draft on the dashboard", draft_id=draft_id)
                return
            if i:
                await asyncio.sleep(rand(C.BETWEEN_MESSAGES))
            media_line = media.MEDIA_LINE_RE.match(part)
            if media_line:
                kind, arg = media_line.groups()
                action = {"voice": "record-audio", "video": "record-round"}.get(kind.lower(), "typing")
                trace.emit("decision", who, f"Picking {kind.lower()}: {arg}", draft_id=draft_id, phase="typing", index=i)
                if C.TYPING_LIMITS[1]:  # human pacing: "record" / "choose" for a moment
                    async with app.client.action(chat_id, action):
                        await asyncio.sleep(rand((2, 5)))
                our_texts.setdefault(chat_id, []).append("")  # media has no text; recognize our own send
                try:
                    sent = await media.send_media_line(app.client, chat_id, kind, arg)
                except Exception:
                    log.exception("%s: failed to send %s %r", who, kind, arg)
                    sent = None
                if not sent:
                    our_texts[chat_id].remove("")
                    trace.emit("warning", who, f"Couldn't find a {kind.lower()} for '{arg}' — skipped", draft_id=draft_id)
                    continue
                log.info("%s: sent %s %s", who, kind, arg)
            else:
                trace.emit("decision", who, "Typing…", draft_id=draft_id, phase="typing", index=i)
                await type_like_a_person(chat_id, part)
                slip = quirks.typo(part) if slips else None
                text = slip[0] if slip else part
                our_texts.setdefault(chat_id, []).append(text)
                target = quotes.get(i) or (None if quotes else quote)
                sent = await app.client.send_message(chat_id, text, reply_to=target.id if target else None)
                quote = None  # without separate questions, only the first message quotes
                if slip:  # notice the typo a moment later and fix it, by editing or with a "*word"
                    await asyncio.sleep(rand((1.5, 4)))
                    if random.random() < 0.5:
                        await app.client.edit_message(chat_id, sent.id, part)
                        trace.emit("decision", who, f"Sent it with a typo ('{slip[1]}'), then edited the message")
                    else:
                        fix = "*" + slip[1]
                        our_texts[chat_id].append(fix)
                        fixed = await app.client.send_message(chat_id, fix)
                        our_ids.add(fixed.id)
                        state.record_sent(chat_id, fixed.id)
                        trace.emit("sent", who, fix)
            our_ids.add(sent.id)
            state.record_sent(chat_id, sent.id)
            sent_count += 1
            trace.emit("sent", who, part, draft_id=draft_id, index=i)
        trace.emit("decision", who, f"Done — {sent_count} message(s) sent", draft_id=draft_id, final=True)
        question = next((p for p in reversed(parts) if not media.MEDIA_LINE_RE.match(p) and p.rstrip().endswith("?")), None)
        if question and sent_count and from_model and not formal and sent is not None:
            asked[chat_id] = {"msg_id": sent.id, "text": question, "at": time.time(), "nudges": 0, "who": who,
                              "due": rand(C.NUDGE_AFTER_READ), "read_at": None}
        else:
            asked.pop(chat_id, None)
        said_wait = next((p for p in parts if not media.MEDIA_LINE_RE.match(p) and DEFER_RE.search(p)), None)
        if said_wait and sent_count and sent is not None and not formal:
            spawn(come_back(chat_id, contact, who, sent.id, their_text, said_wait))  # "щас" means: and then something follows
        rhythm.replied(chat_id)
        rhythm.online_for_a_bit(app.client)
        if sent_count:
            daylog.record("replied", who, " / ".join(parts), them=their_text[:200])
        target = next((m for m in history if not m.out), None)
        worth_it = bool(target) and "?" not in (target.raw_text or "") and (
            getattr(target, "photo", None) or REACTABLE_RE.search(target.raw_text or ""))
        if sent_count and from_model and not formal and worth_it and random.random() < C.EXTRA_REACTION_CHANCE:
            if target:  # people also just tap a reaction on a photo, a joke, good news
                emoji = "❤" if getattr(target, "photo", None) or random.random() < 0.3 else "👍"
                try:
                    await app.client(functions.messages.SendReactionRequest(peer=chat_id, msg_id=target.id,
                                                                        reaction=[ReactionEmoji(emoticon=emoji)]))
                    trace.emit("sent", who, f"[reaction {emoji}] on their message")
                except errors.RPCError:
                    pass
        if due and sent_count and any(w[:5] in " ".join(parts).lower() for w in re.findall(r"[^\W\d_]{4,}", due["what"].lower())):
            people.mark_asked(chat_id, who, due["what"])  # the follow-up was asked; not again
        if C.REMEMBER:
            theirs = [m.raw_text for m in itertools.takewhile(lambda m: not m.out, history) if m.raw_text]
            spawn(remember_later(chat_id, who, theirs[::-1]))
        log.info("%s: replied (%d chars)", who, len(reply))
    except asyncio.CancelledError:
        log.info("%s: reply cancelled", who)
        failed = True  # not dealt with: a newer run (or you) takes over
        trace.emit("cancelled", who, "Dropped this reply — a new message arrived or you answered yourself",
                   draft_id=draft_id)
        raise
    except Exception:
        failed = True  # leave it unhandled so the periodic re-scan tries again
        log.exception("%s: reply failed", who)
        trace.emit("warning", who, "Reply failed with an error (see userbot log)", draft_id=draft_id, final=True)
    finally:
        if history and not failed:  # answered, reacted, skipped or handed to you: don't pick it up again
            state.mark_handled(chat_id, history[0].id)
        if pending.get(chat_id) is asyncio.current_task():
            pending.pop(chat_id)


def flood_from(chat_id: int, msg) -> list:
    """Their messages of the last few seconds, if there are enough of them to call it spam."""
    burst = recent_incoming.setdefault(chat_id, deque(maxlen=C.SPAM_MAX))
    burst.append(msg)
    now = time.time()
    if not C.SPAM_BACK or state.approve or now < spam_until.get(chat_id, 0):
        return []
    fresh = [m for m in burst if now - m.date.timestamp() <= C.SPAM_WINDOW]
    return fresh if len(fresh) >= C.SPAM_TRIGGER else []


def echo_of(msg):
    """What goes back for one of their messages: the same sticker, the same short text, or a "?"."""
    if msg.sticker:
        return msg
    text = (msg.raw_text or "").strip()
    plain = not re.search(r"https?://|www\.|t\.me/|\w\.[a-z]{2,}(/|\b)", text, re.I)  # no links sent in your name
    return text if text and len(text) <= C.SPAM_ECHO_CHARS and plain and looks_safe(text) else "?"


async def spam(chat_id: int, who: str, items: list) -> int:
    """Send texts / stickers one right after another, without the usual reading and typing."""
    sent = 0
    spam_until[chat_id] = time.time() + C.SPAM_COOLDOWN
    try:
        await app.client.send_read_acknowledge(chat_id)
        for item in items[:C.SPAM_MAX]:
            our_texts.setdefault(chat_id, []).append(item if isinstance(item, str) else "")
            msg = (await app.client.send_message(chat_id, item) if isinstance(item, str)
                   else await app.client.send_file(chat_id, item.media))
            our_ids.add(msg.id)
            state.record_sent(chat_id, msg.id)
            sent += 1
            await asyncio.sleep(rand(C.SPAM_GAP))
    except errors.FloodWaitError as e:
        trace.emit("warning", who, f"Telegram asked to slow down for {e.seconds}s — stopped after {sent} message(s)")
    except Exception:
        log.exception("Spam to %s failed", who)
        trace.emit("warning", who, f"Could not finish — stopped after {sent} message(s)")
    finally:
        spam_until[chat_id] = time.time() + C.SPAM_COOLDOWN
    if sent:
        state.mark_handled(chat_id, (await app.client.get_messages(chat_id, limit=1))[0].id)
        trace.emit("sent", who, f"[{sent} messages in a row]")
    return sent


def nudge_due(entry: dict, now: float, read: bool) -> str:
    """-> "nudge" | "wait" | "drop" for a question that is still unanswered."""
    if now - entry["at"] > C.NUDGE_GIVE_UP or entry["nudges"] >= C.NUDGE_MAX:
        return "drop"
    if read:
        entry["read_at"] = entry["read_at"] or now
        return "nudge" if now - entry["read_at"] >= entry["due"] and now - entry["at"] >= entry["due"] else "wait"
    return "nudge" if entry["nudges"] == 0 and now - entry["at"] >= entry.setdefault("unread_due", rand(C.NUDGE_AFTER_UNREAD)) else "wait"


async def nudge(chat_id: int, entry: dict):
    """Ask again, quoting your own unanswered message: first just "?", then the question in other words."""
    who = entry["who"]
    history = await app.client.get_messages(chat_id, limit=6)
    if not history or not history[0].out or history[0].id != entry.get("last_id", entry["msg_id"]) \
            or not sent_by_us(chat_id, history[0]):
        asked.pop(chat_id, None)  # something happened in the chat since: it is not "ignored" any more
        return
    text = "?"
    if entry["nudges"] >= 1:
        try:
            resp = await http.post("/complete", json={"messages": [{"role": "user", "content": (
                "You texted a friend this question and got no answer:\n" + entry["text"] + "\n\nAsk the same thing "
                "again in other words: one very short casual line, same language, no greeting, no emoji, no "
                "complaining that they didn't answer. Output only the line.")}],
                "models": C.MODELS, "max_tokens": 40, "temperature": 0.8})
            again = clean_reply(resp.json()["reply"]).splitlines()[0].strip() if resp.is_success else ""
        except Exception:
            again = ""
        if again and looks_safe(again) and len(again) <= 80 and judge._norm(again) != judge._norm(entry["text"]):
            text = again
        else:
            text = "??"
    trace.emit("decision", who, f"No answer to “{entry['text'][:60]}” — asking again: {text}")
    if pacing_on():
        await type_like_a_person(chat_id, text)
    sent = await send_as_bot(chat_id, text, reply_to=entry["msg_id"])
    trace.emit("sent", who, f"↩ {text}")
    daylog.record("replied", who, text, them="(no answer to your question)")
    entry.update(nudges=entry["nudges"] + 1, msg_id=entry["msg_id"], read_at=None, at=time.time(),
                 due=rand(C.NUDGE_AFTER_READ) * 2)
    entry["last_id"] = sent.id


async def nudge_loop():
    """Questions you asked that nobody answered: look at them now and then."""
    while True:
        await asyncio.sleep(20)
        if not C.NUDGE_ON or state.is_paused() or rhythm.asleep() or state.approve:
            continue
        for chat_id, entry in list(asked.items()):
            try:
                if chat_id in pending or not state.is_active(chat_id, C.REPLY_MODE) or state.handed_off(chat_id) \
                        or chat_id in state.manual:
                    continue
                peer = await app.client.get_input_entity(chat_id)
                dialog = (await app.client(functions.messages.GetPeerDialogsRequest(peers=[InputDialogPeer(peer)]))).dialogs[0]
                verdict = nudge_due(entry, time.time(), dialog.read_outbox_max_id >= entry.get("last_id", entry["msg_id"]))
                if verdict == "drop":
                    asked.pop(chat_id, None)
                elif verdict == "nudge":
                    await nudge(chat_id, entry)
            except Exception:
                log.exception("Nudge check failed for %s", chat_id)
                asked.pop(chat_id, None)


async def reply_to_unread(limit: int = 0) -> int:
    """Answer private chats that are waiting on you: unread DMs (up to UNREAD_MAX_AGE old), plus unanswered ones
    you have already opened yourself (up to RECENT_UNANSWERED old) — seeing a message doesn't answer it.
    Anything already answered, reacted to, skipped or handed to you is left alone. No groups, channels or bots."""
    count = 0
    if rhythm.asleep():
        return count  # nobody answers at night; these get picked up after waking
    async for dialog in app.client.iter_dialogs(limit=limit or C.UNREAD_SCAN_DIALOGS):
        contact, last = dialog.entity, dialog.message
        if not isinstance(contact, User) or contact.bot or contact.is_self or contact.deleted \
                or contact.id == TELEGRAM_SERVICE_ID:
            continue
        if not last or last.out or dialog.id in pending or dialog.id in commanding \
                or not state.is_active(dialog.id, C.REPLY_MODE):
            continue
        if state.is_handled(dialog.id, last.id) or state.handed_off(dialog.id):
            continue  # already answered, skipped, reacted to, or handed to you
        age = time.time() - last.date.timestamp()
        if not ((dialog.unread_count and age < C.UNREAD_MAX_AGE) or age < C.RECENT_UNANSWERED):
            continue
        names[dialog.id] = full_name(contact)
        what = f"{dialog.unread_count} unread message(s)" if dialog.unread_count else "a recent unanswered message"
        log.info("%s: answering %s", label(dialog.id), what)
        trace.emit("decision", label(dialog.id), f"Found {what} while scanning private chats")
        if count:
            await asyncio.sleep(rand((2, 5)))  # don't fire replies into many chats at the same instant
        pending[dialog.id] = asyncio.create_task(reply_flow(dialog.id, contact))
        count += 1
    return count
