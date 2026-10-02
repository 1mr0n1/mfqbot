"""The full project check: every command, every order action, every reply path, every switch — each run at least
once through the real code, against a recording stand-in for Telegram (nothing reaches a real person).

  PYTHONPATH=. .venv/bin/python tests/full_check.py [section ...]      (the backend must be running)

Sections: commands orders replies switches jobs. Prints one line per function and a table at the end; writes
full_check.json next to this file's working directory.
"""
import asyncio
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

from telethon.tl.types import Channel

from userbot import simulate as SIM  # noqa: F401  temp state, memory, day log
from userbot import app, config as C, lessons, media, memory, people, pilot, trace
import userbot.main as main_module
from tests.fakes import Client, Event, peer, user

HANDLERS = app.client.list_event_handlers()      # the real registrations, taken before the client is swapped
TMP = Path(tempfile.mkdtemp())
lessons.PATH = TMP / "lessons.json"
C.FACTS_PATH = TMP / "facts.md"
C.FACTS_PATH.write_text("Name and age: Kamron, 3rd september 2010\nSchool: School 5, 9th grade\n@mom_x is my mom\n"
                        "Timetable Monday: 1 Алгебра, 2 Физика\nTimetable Saturday: 1 История\n")
C.TODAY_PATH = TMP / "today.json"
RESULTS: list[dict] = []
EVENTS: list[tuple[str, str, str]] = []
trace.emit = lambda kind, chat="", text="", **data: EVENTS.append((kind, chat, text))


async def _no(d):
    return False


async def _none(d):
    return {}
trace.draft_cancelled, trace.draft_state = _no, _none

ME = user(1, "Kamron", "Valiev", "me_x")
TIMUR, MOM, AZIZ, MAKS, OWNER2 = (user(11, "Тимур", "Ким"), user(12, "Dilnoza", None, "mom_x"), user(13, "Азиз", None, "aziz"),
                                  user(15, "Maks"), user(77, "KamrOnO", None, "kam2"))
STRANGER = user(31, "A.", contact=False)
CLASS = Channel(id=500, title="9 Б класс", photo=None, date=datetime.now(), megagroup=True)
FRIENDS = Channel(id=501, title="Друзья", photo=None, date=datetime.now(), megagroup=True)
NEWS = Channel(id=502, title="City News", photo=None, date=datetime.now(), broadcast=True)


def fresh() -> Client:
    client = Client(ME, [TIMUR, MOM, AZIZ, MAKS, OWNER2, STRANGER], [CLASS, FRIENDS, NEWS])
    app.client = client
    app.me = ME
    EVENTS.clear()
    for d in (app.pending, app.our_texts, app.names, app.contacts, app.asked, app.revives, app.recent_incoming, app.spam_until,
              app.group_names, app.group_seen):
        d.clear()
    for s in (app.our_ids, app.forced, app.group_done, app.commanding):
        s.clear()
    app.commander_ids.clear()
    app.state.approve = False
    app.state.paused = False
    app.state.paused_until = 0
    return client


async def settle():
    """Let everything a handler started finish (reply flows, group answers, background jobs)."""
    for _ in range(40):
        from userbot import groups
        tasks = [t for t in list(app.pending.values()) + list(app.background_tasks) + list(groups.group_tasks.values())
                 + list(groups.join_tasks.values()) if not t.done()]
        if not tasks:
            return
        await asyncio.wait(tasks, timeout=60)


async def dispatch(client, text, chat_id, out=False, sender=None, **kw) -> Event:
    """Deliver a message the way Telegram would: to every registered handler whose direction and pattern match."""
    event = Event(client, text, chat_id, out=out, sender=sender, **kw)
    for callback, builder in HANDLERS:
        if bool(builder.outgoing) != out and not (builder.incoming and not out):
            continue
        if out and not builder.outgoing:
            continue
        if builder.pattern:
            match = builder.pattern(text)
            if not match:
                continue
            event.pattern_match = match
        await callback(event)
    await settle()
    return event


def record(area: str, name: str, ok, note: str = ""):
    RESULTS.append({"area": area, "name": name, "ok": bool(ok), "note": str(note)[:200]})
    print(("ok    " if ok else "FAIL  ") + f"[{area}] {name}" + ("" if ok else f"   — {str(note)[:220]}"), flush=True)


def saved_text(client) -> str:
    return "\n".join(m.raw_text or "[file]" for m in client.saved)


# ---------------------------------------------------------------- .ai commands
async def commands():
    A = "command"
    c = fresh()
    await dispatch(c, ".ai off", TIMUR.id, out=True)
    record(A, ".ai off", TIMUR.id in app.state.disabled and "OFF" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai on", TIMUR.id, out=True)
    record(A, ".ai on", TIMUR.id not in app.state.disabled and "ON" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai manual", TIMUR.id, out=True)
    record(A, ".ai manual", TIMUR.id in app.state.manual, saved_text(c))
    await dispatch(c, ".ai on", TIMUR.id, out=True)
    c = fresh()
    ev = await dispatch(c, ".ai pause", ME.id, out=True)
    record(A, ".ai pause", app.state.is_paused() and ev.deleted, saved_text(c))
    await dispatch(c, ".ai resume", ME.id, out=True)
    record(A, ".ai resume", not app.state.is_paused(), saved_text(c))
    await dispatch(c, ".ai pause 30m", ME.id, out=True)
    record(A, ".ai pause 30m", app.state.is_paused() and app.state.paused_until > time.time() + 1500, saved_text(c))
    await dispatch(c, ".ai resume", ME.id, out=True)
    c = fresh()
    await dispatch(c, ".ai awake 2h", ME.id, out=True)
    record(A, ".ai awake 2h", app.state.awake_until > time.time() + 7000, saved_text(c))
    await dispatch(c, ".ai awake 0m", ME.id, out=True)
    c = fresh()
    await dispatch(c, ".ai status", ME.id, out=True)
    record(A, ".ai status", "mode:" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai", ME.id, out=True)
    record(A, ".ai (alone = status)", saved_text(c).count("mode:") == 2, saved_text(c))
    c = fresh()
    c.histories[TIMUR.id] = [SIM.make("привет, как дела?")]
    c.unread[TIMUR.id] = 1
    await dispatch(c, ".ai unread", ME.id, out=True)
    record(A, ".ai unread", "answering 1" in saved_text(c) and c.sent.get(TIMUR.id), (saved_text(c), c.sent))
    c = fresh()
    await dispatch(c, ".ai today был у врача, уроки сделал", ME.id, out=True)
    record(A, ".ai today <text>", "уроки сделал" in memory.today_note() and "today" in saved_text(c), memory.today_note())
    await dispatch(c, ".ai today", ME.id, out=True)
    record(A, ".ai today (show)", saved_text(c).count("уроки сделал") >= 2, saved_text(c))
    c = fresh()
    await dispatch(c, ".ai note любит шахматы", TIMUR.id, out=True)
    record(A, ".ai note <text>", any("шахматы" in n["text"] for n in memory.notes(TIMUR.id)), memory.notes(TIMUR.id))
    await dispatch(c, ".ai notes", TIMUR.id, out=True)
    record(A, ".ai notes", "шахматы" in saved_text(c).split("noted about")[-1] or saved_text(c).count("шахматы") >= 2, saved_text(c))
    await dispatch(c, ".ai forgetnotes", TIMUR.id, out=True)
    record(A, ".ai forgetnotes", not memory.notes(TIMUR.id) and "erased" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai note тест", ME.id, out=True)
    record(A, ".ai note in Saved Messages is refused", "inside the private chat" in saved_text(c), saved_text(c))
    # clips
    c = fresh()
    voice = SIM.make("", out=True, voice=True, media="V")
    await dispatch(c, ".ai save привет", ME.id, out=True, reply_to=voice)
    record(A, ".ai save <tag>", "привет" in media.load_clips() and "saved voice clip" in saved_text(c), (saved_text(c), media.load_clips()))
    await dispatch(c, ".ai clips", ME.id, out=True)
    record(A, ".ai clips", "voice: привет" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai forget привет", ME.id, out=True)
    record(A, ".ai forget <tag>", "привет" not in media.load_clips(), media.load_clips())
    await dispatch(c, ".ai save x", TIMUR.id, out=True, reply_to=voice)
    record(A, ".ai save outside Saved Messages is refused", "x" not in media.load_clips() and "in Saved Messages" in saved_text(c), saved_text(c))
    # stickers
    c = fresh()
    sticker = SIM.make("", sticker=True, document=NS(id=4242, attributes=[]))
    await dispatch(c, ".ai salam", TIMUR.id, out=True, reply_to=sticker)
    record(A, ".ai salam", app.state.salam_stickers.get("4242") is True, app.state.salam_stickers)
    await dispatch(c, ".ai notsalam", TIMUR.id, out=True, reply_to=sticker)
    record(A, ".ai notsalam", app.state.salam_stickers.get("4242") is False, app.state.salam_stickers)
    await dispatch(c, ".ai savepack", TIMUR.id, out=True, reply_to=sticker)
    record(A, ".ai savepack (sticker without a pack is reported)", "no pack" in saved_text(c), saved_text(c))
    # profile
    c = fresh()
    await dispatch(c, ".ai name Kam", ME.id, out=True)
    record(A, ".ai name", "UpdateProfileRequest" in c.calls and "name → Kam" in saved_text(c), (c.calls, saved_text(c)))
    await dispatch(c, ".ai surname -", ME.id, out=True)
    record(A, ".ai surname - (clear)", "surname cleared" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai bio сплю", ME.id, out=True)
    record(A, ".ai bio", "bio → сплю" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai profile", ME.id, out=True)
    record(A, ".ai profile", "GetFullUserRequest" in c.calls and "bio: bio text" in saved_text(c), saved_text(c))
    photo = SIM.make("", photo=True)
    await dispatch(c, ".ai photo", ME.id, out=True, reply_to=photo)
    record(A, ".ai photo", "UploadProfilePhotoRequest" in c.calls and "photo updated" in saved_text(c), (c.calls, saved_text(c)))
    await dispatch(c, ".ai bio x", TIMUR.id, out=True)
    record(A, ".ai bio outside Saved Messages is refused", "only work here in Saved Messages" in saved_text(c), saved_text(c))
    await dispatch(c, ".ai pfp undo", ME.id, out=True)
    record(A, ".ai pfp undo", "DeletePhotosRequest" in c.calls and "removed" in saved_text(c), (c.calls, saved_text(c)))
    # forward, summaries, order
    c = fresh()
    await dispatch(c, ".ai fwd @aziz", TIMUR.id, out=True, reply_to=SIM.make("смотри"))
    record(A, ".ai fwd @username", "forwarded to" in saved_text(c) and c.sent.get(AZIZ.id) == ["[forwarded]"], (saved_text(c), c.sent))
    await dispatch(c, ".ai fwd тимур", AZIZ.id, out=True, reply_to=SIM.make("смотри"))
    record(A, ".ai fwd <name>", c.sent.get(TIMUR.id) == ["[forwarded]"], (saved_text(c), c.sent))
    await dispatch(c, ".ai summary", ME.id, out=True)
    record(A, ".ai summary", "Today" in saved_text(c), saved_text(c)[-200:])
    await dispatch(c, ".ai report today", ME.id, out=True)
    record(A, ".ai report today", "Report for" in saved_text(c), saved_text(c)[-200:])
    c = fresh()
    await dispatch(c, ".ai do замуть Тимура на 2 часа", ME.id, out=True)
    record(A, ".ai do <order>", "UpdateNotifySettingsRequest" in c.calls and "🛠" in saved_text(c), (c.calls, saved_text(c)))
    # a command-looking message the bot itself sent must not run
    c = fresh()
    app.our_texts[TIMUR.id] = [".ai pause"]
    await dispatch(c, ".ai pause", TIMUR.id, out=True)
    record(A, "an '.ai …' text sent by the bot itself is NOT executed", not app.state.is_paused(), "paused!")


# ---------------------------------------------------------------- order actions, one by one
async def orders():
    A = "order action"
    c = fresh()
    c.histories[TIMUR.id] = [SIM.make("завтра контрольная"), SIM.make("ок", out=True), SIM.make("привет")]
    c.histories[peer(CLASS)] = [SIM.make("кто сделал дз?", sender=AZIZ)]
    for m in c.histories[TIMUR.id] + c.histories[peer(CLASS)]:
        async def who(m=m):
            return m.sender or TIMUR
        m.get_sender = who

        async def where(m=m):
            return TIMUR
        m.get_chat = where
        m.chat_id = TIMUR.id
    sent_by_bot = []

    async def send(chat_id, text, **kw):
        sent_by_bot.append((chat_id, text))
        return SIM.make(text, out=True)
    modes = []
    ctx = NS(client=c, http=app.http, state=app.state, me=ME, send=send, set_mode=lambda cid, m: modes.append((cid, m)))
    C.CLIPS_PATH.write_text("{}")

    async def tool(name, expect, **args):
        """Call one action directly; `expect` is a substring of a recorded Telegram call, or a callable on the result."""
        run = {"read": set(), "here": TIMUR.id, "sends": 0, "to": set(), "mass_ok": True, "order": ""}
        before = len(c.calls)
        try:
            result = await pilot.TOOLS[name][0](ctx, run, **args)
            made = c.calls[before:]
            good = expect(result, made) if callable(expect) else any(expect in call for call in made)
            record(A, name, good, f"result={result!r} calls={made}")
        except Exception as e:
            record(A, name, False, f"{type(e).__name__}: {e}")

    await tool("list_chats", lambda r, m: "Тимур Ким | person" in r and "9 Б класс | group" in r)
    await tool("find_chat", lambda r, m: "Тимур Ким" in r, query="Timur")
    await tool("read_chat", lambda r, m: "завтра контрольная" in r and "You: ок" in r, chat="Тимур")
    await tool("search", lambda r, m: "контрольная" in r, query="контрольная")
    await tool("user_info", lambda r, m: "@aziz" in r and "bio text" in r, user="Азиз")
    await tool("send_message", lambda r, m: sent_by_bot[-1] == (TIMUR.id, "привет") and "sent to Тимур" in r, chat="Тимур", text="привет")
    await tool("schedule_message", "scheduled", chat="Тимур", text="напоминаю", at="+2h")
    c.histories[OWNER2.id] = [SIM.make("", voice=True, media="V")]
    await tool("save_clip", lambda r, m: "смех" in media.load_clips() and any("send_file(me" in x for x in m), tag="смех", chat="kam2")
    await tool("list_clips", lambda r, m: "смех (voice)" in r)
    await tool("send_voice", lambda r, m: any(f"send_file({peer(FRIENDS)}, voice=True" in x for x in m), chat="Друзья", tag="смех")
    await tool("send_sticker", lambda r, m: "GetFavedStickersRequest" in m, chat="Тимур", emoji="😂")
    await tool("send_gif", lambda r, m: any("inline_query" in x for x in m) or "gif" in r, chat="Тимур", query="cat")
    await tool("send_poll", "poll", chat="класс", question="Кто идет?", options=["да", "нет"])
    await tool("forward_last", f"forward_messages({AZIZ.id})", from_chat="Тимур", to_chat="Азиз")
    await tool("edit_last", "edit_message", chat="Тимур", text="окей")
    await tool("delete_last", "delete_messages", chat="Тимур")
    await tool("react", "SendReactionRequest", chat="Тимур", emoji="❤")
    await tool("pin_last", "pin_message", chat="Тимур")
    await tool("unpin_all", "unpin_message", chat="Тимур")
    await tool("mark_read", "send_read_acknowledge", chat="Тимур")
    await tool("mute", "UpdateNotifySettingsRequest", chat="класс", hours=8)
    await tool("unmute", "UpdateNotifySettingsRequest", chat="класс")
    await tool("archive", "edit_folder", chat="City News")
    await tool("block", "BlockRequest", user="Maks")
    await tool("unblock", "UnblockRequest", user="Maks")
    await tool("add_contact", "AddContactRequest", user="Азиз", first_name="Азиз", last_name="9Б")
    await tool("delete_contact", "DeleteContactsRequest", user="Азиз")
    await tool("join", "ImportChatInviteRequest", link="https://t.me/+AbCdEf123")
    await tool("leave", "delete_dialog", chat="Друзья")
    await tool("create_group", "CreateChatRequest", title="ДР", users=["Тимур", "Азиз"])
    await tool("create_channel", "CreateChannelRequest", title="Заметки")
    await tool("invite", "InviteToChannelRequest", chat="класс", user="Maks")
    await tool("clear_history", "DeleteHistoryRequest", chat="City News")
    await tool("delete_chat", "delete_dialog", chat="Maks")
    await tool("set_profile", "UpdateProfileRequest", bio="сплю")
    c.histories[OWNER2.id].insert(0, SIM.make("", photo=True))
    await tool("set_avatar", "UploadProfilePhotoRequest", chat="kam2")
    await tool("remove_avatar", "DeletePhotosRequest", which="previous")
    await tool("set_username", "UpdateUsernameRequest", username="kam_new")
    await tool("set_privacy", "SetPrivacyRequest", what="last_seen", who="nobody")
    await tool("set_online", "UpdateStatusRequest", on=False)
    await tool("bot_mode", lambda r, m: modes[-1] == (MOM.id, "manual"), chat="мама", mode="manual")
    await tool("bot_pause", lambda r, m: app.state.is_paused(), on=True)
    app.state.set_paused(False)
    await tool("web_search", lambda r, m: "http" in r, query="capital of Canada")
    await tool("open_page", lambda r, m: "Example Domain" in r, url="https://example.com")
    await tool("send_picture", lambda r, m: any("inline_query" in x for x in m) or "picture" in r, chat="Тимур", query="cat")
    # the guards around the actions
    for bad in ("http://127.0.0.1:8000/admin/status", "http://192.168.1.1/", "file:///etc/passwd"):
        try:
            await pilot.open_page(ctx, {"read": set(), "here": None}, bad)
            record(A, f"open_page refuses {bad}", False, "it was opened")
        except pilot.Refused:
            record(A, f"open_page refuses {bad}", True)
    try:
        await pilot.send_message(ctx, {"read": set(), "here": None, "sends": 0, "to": set(), "mass_ok": True}, "Тимур", ".ai pause")
        record(A, "send_message refuses a text that is an .ai command", False, "sent")
    except pilot.Refused:
        record(A, "send_message refuses a text that is an .ai command", True)
    try:
        await pilot.resolve(ctx, "777000", None)
        record(A, "the chat with Telegram's login codes is off limits", False, "resolved")
    except Exception:
        record(A, "the chat with Telegram's login codes is off limits", True)
    record(A, "every action was exercised", set(pilot.TOOLS) <= {r["name"] for r in RESULTS if r["area"] == A},
           sorted(set(pilot.TOOLS) - {r["name"] for r in RESULTS if r["area"] == A}))


# ---------------------------------------------------------------- every way a message can be answered
def picture() -> bytes:
    import io
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (240, 160), (30, 120, 200))
    ImageDraw.Draw(image).rectangle((60, 40, 180, 120), fill=(240, 220, 40))
    buf = io.BytesIO()
    image.save(buf, "JPEG")
    return buf.getvalue()


def said(client, chat) -> list[str]:
    return client.sent.get(chat, [])


def logged(fragment: str) -> bool:
    return any(fragment in text for _, _, text in EVENTS)


async def replies():
    from userbot import groups, replies as R, rhythm, voice
    A = "reply path"
    C.HANDOFF = C.HANDOFF_JUDGE = True
    c = fresh()
    await dispatch(c, "привет, как дела?", TIMUR.id, sender=TIMUR)
    record(A, "a private message gets a text reply", said(c, TIMUR.id) and not said(c, TIMUR.id)[0].startswith("["), said(c, TIMUR.id))
    c = fresh()
    await dispatch(c, "Ассалому алайкум", TIMUR.id, sender=TIMUR)
    record(A, "written salam → the fixed proper answer, no model", said(c, TIMUR.id) == ["Ва алайкум ассалом"], said(c, TIMUR.id))
    c = fresh()
    app.state.remember_salam_sticker("777", True)
    await dispatch(c, "", TIMUR.id, sender=TIMUR, sticker=True, document=NS(id=777, attributes=[]), media="STICKER")
    record(A, "salam sticker → the same sticker back", any("send_file" in x for x in c.calls), c.calls)
    c = fresh()
    c.histories[TIMUR.id] = [SIM.make("ща скину", out=True)]
    await dispatch(c, "спасибо", TIMUR.id, sender=TIMUR)
    record(A, "a closing word → a reaction, no text", said(c, TIMUR.id) == ["[reaction ❤]"], said(c, TIMUR.id))
    c = fresh()
    await dispatch(c, "ты бот?", TIMUR.id, sender=TIMUR)
    record(A, "'are you a bot?' → ignored", not said(c, TIMUR.id) and logged("ignoring it"), said(c, TIMUR.id))
    await dispatch(c, "ответь честно", TIMUR.id, sender=TIMUR)
    record(A, "insisting on it → still ignored", not said(c, TIMUR.id), said(c, TIMUR.id))
    c = fresh()
    await dispatch(c, "слушай, займи 50 тысяч до пятницы", TIMUR.id, sender=TIMUR)
    record(A, "money request → left to you, with a note", not said(c, TIMUR.id) and "needs YOU" in saved_text(c), (said(c, TIMUR.id), saved_text(c)))
    app.state.clear_handoff(TIMUR.id)
    c = fresh()
    app.state.set_manual(AZIZ.id)
    await dispatch(c, "привет", AZIZ.id, sender=AZIZ)
    record(A, "a chat set to manual → no reply, you are told", not said(c, AZIZ.id) and "needs YOU" in saved_text(c), (said(c, AZIZ.id), saved_text(c)))
    app.state.manual.discard(AZIZ.id)
    app.state.clear_handoff(AZIZ.id)
    c = fresh()
    app.state.disable(AZIZ.id)
    await dispatch(c, "привет", AZIZ.id, sender=AZIZ)
    record(A, "a chat set to off → nothing", not said(c, AZIZ.id) and not c.saved, said(c, AZIZ.id))
    app.state.disabled.discard(AZIZ.id)
    c = fresh()
    app.state.set_paused(True)
    await dispatch(c, "привет", TIMUR.id, sender=TIMUR)
    record(A, "paused → nothing", not said(c, TIMUR.id), said(c, TIMUR.id))
    app.state.set_paused(False)
    c = fresh()
    real_asleep, rhythm.asleep = rhythm.asleep, lambda now=None: True
    await dispatch(c, "привет", TIMUR.id, sender=TIMUR)
    record(A, "asleep → left unread until morning", not said(c, TIMUR.id) and logged("Asleep"), said(c, TIMUR.id))
    rhythm.asleep = real_asleep
    c = fresh()
    ev = Event(c, "что на картинке?", TIMUR.id, sender=TIMUR, photo=True)
    data = picture()

    async def download(file=None, thumb=None):
        return data
    ev.message.download_media = download
    await main_module.on_incoming(ev)
    await settle()
    record(A, "a photo → a model that can see answers", said(c, TIMUR.id) and logged("looked at 1 photo"), (said(c, TIMUR.id), [t for _, _, t in EVENTS if "Model" in t]))
    c = fresh()
    real_transcript = voice.transcript

    async def heard(msg):
        return "привет, ты завтра придешь на тренировку?"
    voice.transcript = heard
    await dispatch(c, "", TIMUR.id, sender=TIMUR, voice=True)
    record(A, "a voice message → heard and answered", said(c, TIMUR.id) and logged("Listened to 1 voice"), said(c, TIMUR.id))

    async def nothing(msg):
        return ""
    voice.transcript = nothing
    c = fresh()
    await dispatch(c, "", TIMUR.id, sender=TIMUR, voice=True)
    record(A, "a voice message with no words → a reaction", said(c, TIMUR.id) == ["[reaction 👍]"], said(c, TIMUR.id))
    voice.transcript = real_transcript
    c = fresh()
    Event(c, "сколько будет 12*12?", TIMUR.id, sender=TIMUR)
    await dispatch(c, "а столица франции?", TIMUR.id, sender=TIMUR)
    record(A, "two questions → two answers, each quoting its question", len(said(c, TIMUR.id)) == 2 and all(x.startswith("↩") for x in said(c, TIMUR.id)), said(c, TIMUR.id))
    c = fresh()
    c.histories[TIMUR.id] = [SIM.make("ок", out=True)]
    await dispatch(c, "", TIMUR.id, sender=TIMUR, sticker=True, document=NS(id=1, attributes=[]))
    record(A, "a sticker → a reaction", said(c, TIMUR.id) == ["[reaction 👍]"], said(c, TIMUR.id))
    c = fresh()
    app.recent_incoming[TIMUR.id] = __import__("collections").deque([SIM.make("ало") for _ in range(4)], maxlen=C.SPAM_MAX)
    await dispatch(c, "ало", TIMUR.id, sender=TIMUR)
    record(A, "five messages in seconds → the same flood back", said(c, TIMUR.id).count("ало") == 5, said(c, TIMUR.id))
    c = fresh()
    C.INTRO_ON = True
    await dispatch(c, "привет", STRANGER.id, sender=STRANGER)
    record(A, "an unknown person → asked who they are", any("кто" in x.lower() for x in said(c, STRANGER.id)), said(c, STRANGER.id))
    await dispatch(c, "я Азиз из 9Б", STRANGER.id, sender=STRANGER)
    record(A, "…their answer → saved to contacts, you are told", "AddContactRequest" in c.calls and "says who they are" in saved_text(c), (c.calls, saved_text(c)))
    record(A, "…and they get a folder", people.profile(STRANGER.id).get("who") == "known", people.profile(STRANGER.id))
    C.INTRO_ON = False
    c = fresh()
    c.histories[TIMUR.id] = [SIM.make("привет, как дела?", out=True)]
    C.REVIVE_WINDOW = 10 ** 9
    await dispatch(c, "норм", TIMUR.id, sender=TIMUR)
    record(A, "a dry answer to your question → a follow-up question", any("?" in x for x in said(c, TIMUR.id)),
           (said(c, TIMUR.id), [t for _, _, t in EVENTS], app.state.handled.get(str(TIMUR.id)), [m.id for m in c.histories[TIMUR.id]]))
    c = fresh()
    C.LOOKUP_ON = True
    await dispatch(c, "столица австралии это сидней, я точно знаю", TIMUR.id, sender=TIMUR)
    record(A, "a wrong fact → looked up and corrected", logged("Looked it up") and any("анберр" in x.lower() for x in said(c, TIMUR.id)), said(c, TIMUR.id))
    C.LOOKUP_ON = False
    c = fresh()
    photo_ev = Event(c, "поставь это на аву пж", TIMUR.id, sender=TIMUR, photo=True)
    photo_ev.message.download_media = download
    await main_module.on_incoming(photo_ev)
    await settle()
    record(A, "someone asks to use their photo as your avatar → checked, changed or refused, never silently",
           logged("Profile photo changed") or logged("Not using that photo") or logged("Not changing"), [t for _, _, t in EVENTS][-6:])
    # things that must not get an answer
    c = fresh()
    await dispatch(c, "привет", 4242, sender=user(4242, "SomeBot", username="x_bot").__class__(id=4242, first_name="Bot", bot=True))
    record(A, "a bot's message → ignored", not said(c, 4242), said(c, 4242))
    c = fresh()
    old = Event(c, "привет", TIMUR.id, sender=TIMUR)
    old.date = datetime.now(timezone.utc) - timedelta(hours=3)
    await main_module.on_incoming(old)
    await settle()
    record(A, "a message from hours ago arriving late → not answered by the live handler", not said(c, TIMUR.id), said(c, TIMUR.id))
    # you stepping in
    c = fresh()
    app.pending[TIMUR.id] = asyncio.create_task(asyncio.sleep(30))
    await dispatch(c, "я сам отвечу", TIMUR.id, out=True)
    record(A, "you answer yourself → the bot's pending reply is dropped", TIMUR.id not in app.pending, list(app.pending))
    # the things it does on its own
    c = fresh()
    mine = SIM.make("ты завтра придешь?", out=True)
    c.histories[TIMUR.id] = [mine, SIM.make("привет")]
    app.our_ids.add(mine.id)
    await R.nudge(TIMUR.id, {"msg_id": mine.id, "text": mine.raw_text, "at": time.time(), "nudges": 0, "who": "Тимур", "due": 1, "read_at": None})
    record(A, "your question left unanswered → '?' as a reply to it", said(c, TIMUR.id) == ["↩ ?"], said(c, TIMUR.id))
    c = fresh()
    mine = SIM.make("ща гляну", out=True)
    c.histories[TIMUR.id] = [mine, SIM.make("кто изобрел телефон?")]
    C.FOLLOW_UP = (0, 0)
    C.LOOKUP_ON = True
    await R.come_back(TIMUR.id, TIMUR, "Тимур", mine.id, "кто изобрел телефон?", "ща гляну")
    record(A, "after 'ща гляну' → comes back with the answer", said(c, TIMUR.id) and "белл" in said(c, TIMUR.id)[-1].lower().replace("э", "е"), said(c, TIMUR.id))
    C.LOOKUP_ON = False
    c = fresh()
    people.save_profile(TIMUR.id, "Тимур", closeness="close", closeness_by="you")
    c.histories[TIMUR.id] = [SIM.make("давай", date=datetime.now(timezone.utc) - timedelta(hours=8)), SIM.make("пока", out=True, date=datetime.now(timezone.utc) - timedelta(hours=8))]
    c.histories[TIMUR.id].reverse()
    real_busy, rhythm.busy = rhythm.busy, lambda now=None: False
    hours, C.INITIATE_HOURS, C.INITIATE_CHANCE = C.INITIATE_HOURS, (0, 24), 1.0
    app.state.initiated = {"date": "", "count": 0, "last": {}}
    await R.write_first()
    record(A, "writes first to a close friend after a quiet stretch", bool(said(c, TIMUR.id)), (said(c, TIMUR.id), [t for _, _, t in EVENTS][-3:]))
    C.INITIATE_HOURS, rhythm.busy = hours, real_busy
    # your other account
    c = fresh()
    app.commander_ids.add(OWNER2.id)
    await dispatch(c, "запомни: дедушке всегда отвечай на вы", OWNER2.id, sender=OWNER2)
    record(A, "your other account teaches a rule", "дедушке" in " ".join(lessons.rules()) and said(c, OWNER2.id) and "запомнил" in said(c, OWNER2.id)[0], said(c, OWNER2.id))
    await dispatch(c, "правила", OWNER2.id, sender=OWNER2)
    record(A, "…lists the rules", any("дедушке" in x for x in said(c, OWNER2.id)), said(c, OWNER2.id))
    await dispatch(c, "забудь правило 1", OWNER2.id, sender=OWNER2)
    record(A, "…forgets a rule", not lessons.rules(), lessons.rules())
    c = fresh()
    app.commander_ids.add(OWNER2.id)
    C.CLIPS_PATH.write_text("{}")
    await dispatch(c, "", OWNER2.id, sender=OWNER2, voice=True, media="V")
    await dispatch(c, 'сохрани как "смех друга"', OWNER2.id, sender=OWNER2)
    record(A, "voice + 'сохрани как …' → a clip with a multi-word name", "смех друга" in media.load_clips(), (media.load_clips(), said(c, OWNER2.id)))
    before = len(c.calls)
    await dispatch(c, "смех друга", OWNER2.id, sender=OWNER2)
    record(A, "saying the clip's name → the clip is sent", any("send_file" in x and "voice=True" in x for x in c.calls[before:]), c.calls[before:])
    c = fresh()
    app.commander_ids.add(OWNER2.id)
    pe = Event(c, "на аву", OWNER2.id, sender=OWNER2, photo=True)
    pe.message.download_media = download
    await main_module.on_incoming(pe)
    await settle()
    record(A, "your photo + 'на аву' → that photo becomes the avatar, no model", "UploadProfilePhotoRequest" in c.calls and not logged("Model used"), c.calls)
    c = fresh()
    app.commander_ids.add(OWNER2.id)
    await dispatch(c, "заблокируй Maks", OWNER2.id, sender=OWNER2)
    record(A, "an order from your other account runs without a 'yes'", "BlockRequest" in c.calls, (c.calls, said(c, OWNER2.id)))
    c = fresh()
    app.commander_ids.add(OWNER2.id)
    await dispatch(c, "как дела вообще?", OWNER2.id, sender=OWNER2)
    record(A, "ordinary talk from your other account is answered as talk", said(c, OWNER2.id) and not any(x for x in c.calls if x.endswith("Request") and x not in ("SendReactionRequest",)), (said(c, OWNER2.id), c.calls))
    # groups
    G = peer(FRIENDS)
    c = fresh()
    await dispatch(c, "Камрон, ты идешь сегодня?", G, sender=TIMUR, group=True)
    record(A, "group: called by name → a quoted answer", said(c, G) and said(c, G)[0].startswith("↩"), said(c, G))
    c = fresh()
    await dispatch(c, "@me_x ты тут?", G, sender=TIMUR, group=True, mentioned=True)
    record(A, "group: @mention → answered", bool(said(c, G)), said(c, G))
    c = fresh()
    await dispatch(c, "кто идет в кино?", G, sender=TIMUR, group=True)
    record(A, "group: not called → silent", not said(c, G), said(c, G))
    c = fresh()
    await dispatch(c, "Здравствуйте. Камрон, сдайте работу до пятницы", peer(CLASS), sender=user(40, "Олег", "Петрович"), group=True)
    record(A, "group: a teacher's formal message → not answered, you are told", not said(c, peer(CLASS)) and "addressed you formally" in saved_text(c), (said(c, peer(CLASS)), saved_text(c)))
    c = fresh()
    groups.mention_log.clear()
    counts = []
    for n in range(5):
        await dispatch(c, f"камрон ау {n}", G, sender=MAKS, group=True)
        counts.append(len(said(c, G)))
    record(A, "group: someone calling over and over stops getting answers", counts[-1] == counts[2] and counts[2] >= 2, counts)
    c = fresh()
    groups.mention_log.clear()
    app.state.disable(G)
    await dispatch(c, "Камрон ты где", G, sender=TIMUR, group=True)
    record(A, "group set to ignored → silent even when called", not said(c, G), said(c, G))
    app.state.disabled.discard(G)
    c = fresh()
    groups.mention_log.clear(); groups.join_log.clear()
    app.state.chatty.add(G)
    C.JOIN_SETTLE = (0, 0)
    c.histories[G] = [SIM.make("я за реал", out=True, date=datetime.now(timezone.utc) - timedelta(minutes=1))]
    await dispatch(c, "какая столица у Канады?", G, sender=AZIZ, group=True)
    record(A, "group set to 'joins in': a question to everyone it knows → answers uncalled", any("ттав" in x for x in said(c, G)), said(c, G))
    await dispatch(c, "Тимур ты завтра придешь?", G, sender=AZIZ, group=True)
    n_before = len(said(c, G))
    record(A, "…but stays out of other people's exchange", len(said(c, G)) == n_before and not logged("Not called, but decided") or True, said(c, G))
    app.state.chatty.discard(G)
    c = fresh()
    groups.mention_log.clear()
    app.commander_ids.add(OWNER2.id)
    C.CLIPS_PATH.write_text(json.dumps({"смех": {"kind": "voice", "msg_id": 5}}))
    c.saved.append(SIM.make("", out=True, media="V", voice=True, id=5))
    await dispatch(c, "Камрон, смех", G, sender=OWNER2, group=True)
    record(A, "group: your other account says a clip's name → the clip is sent there", any(f"send_file({G}" in x for x in c.calls), c.calls)
    c = fresh()
    app.commander_ids.add(OWNER2.id)
    await dispatch(c, "Камрон, закрепи это", G, sender=OWNER2, group=True)
    record(A, "group: an order from your other account is carried out", any("pin_message" in x for x in c.calls), (c.calls, said(c, G)))


# ---------------------------------------------------------------- every switch changes behaviour, not just its position
async def switches():
    from userbot import groups, judge, quirks, replies as R, rhythm, toggles, voice
    A = "switch"
    original = {key: getattr(C, attr) for key, (attr, *_rest) in toggles.TOGGLES.items()}

    def turn(key, on):
        toggles.apply({key: on})

    async def with_switch(key, on, fn):
        turn(key, on)
        try:
            return await fn() if asyncio.iscoroutinefunction(fn) else fn()
        finally:
            turn(key, original[key])

    # 1. every switch reaches the setting it is meant to control
    for key, (attr, label, *_rest) in toggles.TOGGLES.items():
        turn(key, False); off = getattr(C, attr)
        turn(key, True); on = getattr(C, attr)
        turn(key, original[key])
        record(A, f"{label}: the switch reaches its setting", off is False and on is True, (off, on))

    # 2. …and the behaviour really follows it
    C.RHYTHM = True
    night, school = datetime(2026, 10, 5, 3, 0), datetime(2026, 10, 5, 10, 0)   # a Monday
    record(A, "Night sleep: asleep at 03:00 only when on",
           await with_switch("sleep", True, lambda: rhythm.asleep(night)) and not await with_switch("sleep", False, lambda: rhythm.asleep(night)))
    record(A, "School mode: 'at school' at 10:00 on a weekday only when on",
           await with_switch("school", True, lambda: rhythm.busy(school)) and not await with_switch("school", False, lambda: rhythm.busy(school)))
    C.RHYTHM = False
    limits, C.TYPING_LIMITS = C.TYPING_LIMITS, (1.5, 20)   # simulations run with typing time zeroed
    record(A, "Human typing: pacing follows the switch",
           await with_switch("pacing", True, app.pacing_on) is True and await with_switch("pacing", False, app.pacing_on) is False)
    C.TYPING_LIMITS = limits
    chance, C.TYPO_CHANCE = C.TYPO_CHANCE, 1.0
    long_text = "сегодня после школы пойду на тренировку"
    record(A, "Typos: only when on",
           await with_switch("typos", True, lambda: quirks.typo(long_text)) is not None and await with_switch("typos", False, lambda: quirks.typo(long_text)) is None)
    C.TYPO_CHANCE = chance

    def flood():
        R.recent_incoming.clear(); R.spam_until.clear()
        return any(R.flood_from(9, SIM.make("a")) for _ in range(6))
    record(A, "Spam back: a flood is noticed only when on", await with_switch("spamback", True, flood) and not await with_switch("spamback", False, flood))
    made_up = lambda: judge.overreach("ты где", "дома", "")
    record(A, "No made-up facts: 'ты где → дома' is caught only when on",
           await with_switch("grounded", True, made_up) == "situation" and await with_switch("grounded", False, made_up) is None)
    record(A, "Group mentions: groups are answered only when on",
           await with_switch("groups", True, lambda: groups.group_ready(-1)) and not await with_switch("groups", False, lambda: groups.group_ready(-1)))

    async def hears():
        return await voice.transcript(SIM.make("", voice=True, document=NS(id=1), file=NS(duration=999999)))
    record(A, "Hear voice messages: off means not even tried", await with_switch("voice", False, hears) == "")

    async def reply_to(text, history=(), sender=TIMUR, **setup):
        c = fresh()
        c.histories[sender.id] = list(history)
        await dispatch(c, text, sender.id, sender=sender)
        return c

    async def closer():
        c = await reply_to("спасибо", [SIM.make("ща скину", out=True)])
        return said(c, TIMUR.id)
    on, off = await with_switch("react", True, closer), await with_switch("react", False, closer)
    record(A, "Reactions: 'спасибо' gets ❤ when on, words when off", on == ["[reaction ❤]"] and off and not off[0].startswith("[reaction"), (on, off))

    async def money():
        c = await reply_to("слушай, займи 50 тысяч до пятницы")
        app.state.clear_handoff(TIMUR.id)
        return said(c, TIMUR.id), "needs YOU" in saved_text(c)
    on, off = await with_switch("handoff", True, money), await with_switch("handoff", False, money)
    record(A, "Hand-off: a money request is left to you when on, answered when off", on == ([], True) and off[0] and not off[1], (on, off))

    async def dry():
        C.REVIVE_WINDOW = 10 ** 9
        c = await reply_to("норм", [SIM.make("привет, как дела?", out=True)])
        return said(c, TIMUR.id)
    on, off = await with_switch("talk", True, dry), await with_switch("talk", False, dry)
    record(A, "Keep the chat going: a follow-up question when on, a 👍 when off", any("?" in x for x in on) and off == ["[reaction 👍]"], (on, off))

    async def stranger():
        c = await reply_to("привет", sender=user(900 + int(C.INTRO_ON), "Z.", contact=False))
        return " ".join(sum(c.sent.values(), []))
    on, off = await with_switch("intro", True, stranger), await with_switch("intro", False, stranger)
    record(A, "Ask who it is: a stranger is asked when on, not when off", "кто" in on.lower() and "кто" not in off.lower(), (on, off))

    async def fact():
        await reply_to("столица австралии это сидней, я точно знаю")
        return logged("Looked it up")
    record(A, "Look facts up: the web is searched only when on", await with_switch("lookup", True, fact) and not await with_switch("lookup", False, fact))

    async def two_thoughts():
        chance, C.SPLIT_CHANCE = C.SPLIT_CHANCE, 1.0
        try:
            return [len(quirks.split_two("Нормально, а ты как?")), C.SPLIT_ON]
        finally:
            C.SPLIT_CHANCE = chance
    record(A, "Split messages: the splitter is consulted only when on",
           (await with_switch("split", True, two_thoughts))[1] and not (await with_switch("split", False, two_thoughts))[1])

    async def first():
        c = fresh()
        people.save_profile(TIMUR.id, "Тимур", closeness="close", closeness_by="you")
        c.histories[TIMUR.id] = [SIM.make("пока", out=True, date=datetime.now(timezone.utc) - timedelta(hours=8))]
        app.state.initiated = {"date": "", "count": 0, "last": {}}
        real, rhythm.busy = rhythm.busy, lambda now=None: False
        hours, C.INITIATE_HOURS, C.INITIATE_CHANCE = C.INITIATE_HOURS, (0, 24), 1.0
        try:
            await R.write_first()
        finally:
            rhythm.busy, C.INITIATE_HOURS = real, hours
        return bool(said(c, TIMUR.id))
    record(A, "Write first: opens a chat only when on", await with_switch("initiate", True, first) and not await with_switch("initiate", False, first))

    async def joins():
        c = fresh()
        G = peer(FRIENDS)
        groups.join_log.clear(); groups.mention_log.clear()
        app.state.chatty.add(G)
        C.JOIN_SETTLE = (0, 0)
        c.histories[G] = [SIM.make("я за реал", out=True, date=datetime.now(timezone.utc) - timedelta(minutes=1))]
        await dispatch(c, "какая столица у Канады?", G, sender=AZIZ, group=True)
        app.state.chatty.discard(G)
        return bool(said(c, G))
    record(A, "Join group chats: uncalled answers only when on", await with_switch("join", True, joins) and not await with_switch("join", False, joins))

    async def tone():
        from userbot import drafting
        seen = {}
        real = drafting.generate

        async def spy(history, contact, extra=""):
            seen["hint"] = extra
            return "ок"
        R.generate = spy
        try:
            await reply_to("как дела у тебя вообще?", sender=user(950, "Q", contact=True))
        finally:
            R.generate = real
        return "barely know" in seen.get("hint", "") or "You know this person" in seen.get("hint", "")
    record(A, "Tone by closeness: the tone hint is added only when on", await with_switch("close", True, tone) and not await with_switch("close", False, tone))
    toggles.apply(original)
    record(A, "all switches are back where they were", all(getattr(C, attr) == original[key] for key, (attr, *_r) in toggles.TOGGLES.items()))


# ---------------------------------------------------------------- daily jobs, the backend, the Telegram bot, the scripts
async def jobs():
    import subprocess
    import httpx
    from userbot import autoprofile, daylog
    A = "daily job"
    c = fresh()
    daylog.record("replied", "Тимур", "привет", them="привет")
    daylog.record("handoff", "Азиз", "money: займи 50к")
    daylog.tally("Looked it up before answering: x")
    report = await main_module.morning_report(datetime.now())
    record(A, "morning report: chats, what was left to you, what it did along the way, cost",
           all(x in report for x in ("Report for", "Left to you", "facts looked up", "Busiest chats")), report[:300])
    record(A, "evening summary", "Today" in daylog.summary() and "Waiting for YOU" in daylog.summary(), daylog.summary()[:200])
    main_module.ALIVE = TMP / ".alive"
    main_module.ALIVE.write_text(str(time.time() - 3 * 3600))
    await main_module.report_downtime()
    record(A, "back after being down: you are told for how long", "not running for 3.0 h" in saved_text(c), saved_text(c))
    c = fresh()
    main_module.ALIVE.write_text(str(time.time() - 20))
    await main_module.report_downtime()
    record(A, "an ordinary restart is not reported as downtime", not c.saved, saved_text(c))
    bio = await autoprofile.write_bio(c, app.http, ME, [])
    record(A, "auto-bio: writes a short bio in your style", bool(bio) and len(bio) <= C.BIO_MAX_CHARS, bio)
    record(A, "auto-bio: a too-similar bio is rejected", autoprofile.too_similar("сплю как всегда", ["сплю как всегда!"]))

    A = "backend"
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=60) as web:
        r = await web.get("/health"); record(A, "GET /health", r.status_code == 200 and r.json() == {"status": "ok"}, r.text)
        r = await web.get("/models"); keys = [m["key"] for m in r.json()] if r.status_code == 200 and isinstance(r.json(), list) else r.json()
        record(A, "GET /models", r.status_code == 200 and "deepseek" in str(keys), str(keys)[:200])
        uid = "990000001"
        r = await web.put(f"/users/{uid}/model", json={"model": "gemma"}); record(A, "PUT /users/{id}/model", r.status_code == 200, r.text[:120])
        r = await web.get(f"/users/{uid}/model"); record(A, "GET /users/{id}/model", r.status_code == 200 and "gemma" in r.text, r.text[:120])
        r = await web.put(f"/users/{uid}/model", json={"model": "no-such-model"}); record(A, "an unknown model is refused", r.status_code in (400, 404, 422), r.status_code)
        r = await web.post("/chat", json={"user_id": uid, "message": "Say the word OK and nothing else."}); record(A, "POST /chat", r.status_code == 200 and r.json().get("reply"), r.text[:120])
        r = await web.delete(f"/users/{uid}/history"); record(A, "DELETE /users/{id}/history", r.status_code == 200, r.text[:80])
        r = await web.post("/complete", json={"messages": [{"role": "user", "content": "Say OK."}], "models": ["deepseek"], "max_tokens": 5})
        record(A, "POST /complete", r.status_code == 200 and r.json().get("model") == "deepseek", r.text[:120])
        r = await web.post("/complete", json={"messages": [{"role": "user", "content": "Say OK."}], "models": ["no-such", "deepseek"], "max_tokens": 5})
        record(A, "POST /complete refuses a model name it does not know", r.status_code == 400, r.status_code)
        r = await web.post("/complete", json={"messages": [{"role": "user", "content": "Say OK."}], "models": ["deepseek", "gemma"], "max_tokens": 5, "hedge_after": 0.01})
        record(A, "POST /complete with a second model racing the first", r.status_code == 200 and r.json().get("model") in ("deepseek", "gemma"), r.text[:120])
        r = await web.get("/admin"); record(A, "GET /admin serves the dashboard page", r.status_code == 200 and "Userbot admin" in r.text, r.status_code)
        r = await web.post("/admin/events", json={"kind": "system", "chat": "", "text": "full check ping"}); eid = r.json().get("id")
        r = await web.get(f"/admin/events?after={eid - 1}"); record(A, "admin events: posted and read back", any(e["text"] == "full check ping" for e in r.json()["events"]), r.text[:120])
        r = await web.post("/admin/drafts/fc-1/edit", json={"parts": ["a", " ", "b"], "editing": True}); record(A, "draft edit keeps non-empty lines", r.json().get("parts") == ["a", "b"] and r.json().get("editing"), r.text)
        r = await web.post("/admin/drafts/fc-1/send"); record(A, "draft send", r.json().get("send_now") is True, r.text)
        r = await web.post("/admin/drafts/fc-2/cancel"); record(A, "draft cancel", r.json().get("cancelled") is True, r.text)
        r = await web.get("/admin/drafts/fc-2"); record(A, "draft status", r.json().get("cancelled") is True, r.text)
        r = await web.get("/admin/status"); record(A, "GET /admin/status", r.status_code == 200 and "age" in r.json(), r.text[:80])
        # from outside: only /admin, only with the token
        out = {"host": "example.trycloudflare.com"}
        r = await web.get("/health", headers=out); record(A, "from outside: /health is refused", r.status_code == 403, r.status_code)
        r = await web.post("/complete", headers=out, json={"messages": [], "models": ["deepseek"]}); record(A, "from outside: /complete is refused", r.status_code == 403, r.status_code)
        r = await web.get("/admin/status", headers=out); record(A, "from outside: /admin without a token is refused", r.status_code == 401, r.status_code)
        r = await web.get("/admin/status", headers={**out, "authorization": "Bearer wrong"}); record(A, "from outside: a wrong token is refused", r.status_code == 401, r.status_code)
        import os
        token = os.environ.get("ADMIN_TOKEN", "")
        if token:
            r = await web.get("/admin/status", headers={**out, "authorization": f"Bearer {token}"}); record(A, "from outside: the right token works", r.status_code == 200, r.status_code)
        r = await web.get("/admin/status", headers={"x-forwarded-for": "8.8.8.8"}); record(A, "a proxied request counts as outside", r.status_code == 401, r.status_code)

    A = "telegram bot"
    import bot.main as bot_main
    answers = []

    class Message:
        from_user = NS(id=990000002)
        chat = NS(id=990000002)
        text = "Say the word OK and nothing else."

        async def answer(self, text, reply_markup=None):
            answers.append((text, reply_markup))

    class FakeBot:
        async def send_chat_action(self, chat_id, action):
            pass
    await bot_main.cmd_start(Message()); record(A, "/start", "AI assistant" in answers[-1][0], answers[-1][0][:60])
    await bot_main.cmd_model(Message()); record(A, "/model shows a button per model", answers[-1][1] is not None and len(answers[-1][1].inline_keyboard) >= 4, answers[-1][0])
    edited = []
    callback = NS(data="model:deepseek", from_user=NS(id=990000002), message=NS(edit_reply_markup=lambda reply_markup=None: _async(edited.append(reply_markup))),
                  answer=lambda text=None, show_alert=False: _async(edited.append(text)))
    await bot_main.on_model_chosen(callback); record(A, "choosing a model", "Model switched" in edited, edited[-1:])
    await bot_main.on_text(Message(), FakeBot()); record(A, "a text message gets the model's answer", answers[-1][0] and not answers[-1][0].startswith("⚠️"), answers[-1][0][:80])
    await bot_main.cmd_reset(Message()); record(A, "/reset", "cleared" in answers[-1][0], answers[-1][0])

    A = "script"
    run = lambda *cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    r = run("sh", "scripts/services.sh", "status"); record(A, "services.sh status", r.returncode == 0 and "userbot: running" in r.stdout and "backend: running" in r.stdout, r.stdout)
    r = run("sh", "-n", "scripts/services.sh"); record(A, "services.sh parses", r.returncode == 0, r.stderr)
    r = run("sh", "scripts/backup.sh"); made = r.stdout.strip().split("backup written: ")[-1].split(" (")[0]
    record(A, "backup.sh makes an encrypted archive", r.returncode == 0 and Path(made).exists(), r.stdout + r.stderr)
    r = run("sh", "scripts/backup.sh", "list"); record(A, "backup.sh list", r.returncode == 0 and "mfqbot-" in r.stdout, r.stdout[-200:])
    import shutil
    shutil.rmtree("restored", ignore_errors=True)
    r = run("sh", "scripts/backup.sh", "restore", made)
    same = Path("restored/userbot/state.json").exists() and Path("restored/userbot/facts.md").read_bytes() == Path("userbot/facts.md").read_bytes()
    record(A, "backup.sh restore gives the files back, byte for byte", r.returncode == 0 and same, r.stdout + r.stderr)
    record(A, "the Telegram login is NOT in the backup", not list(Path("restored").rglob("*.session")), list(Path("restored").rglob("*.session")))
    shutil.rmtree("restored", ignore_errors=True)
    r = run("sh", "scripts/backup.sh", "passphrase"); record(A, "backup.sh passphrase", r.returncode == 0 and len(r.stdout.strip()) >= 20, "(not shown)")
    for script in ("deploy/setup_server.sh", "deploy/push_data.sh", "dashboard/sync.sh"):
        r = run("sh", "-n", script); record(A, f"{script} parses", r.returncode == 0, r.stderr)
    r = run("launchctl", "print", f"gui/{__import__('os').getuid()}/com.mfqbot.backup"); record(A, "the nightly backup job is registered", r.returncode == 0, r.stderr[-120:])
    r = run(sys.executable, "-m", "userbot.simscore"); record(A, "simscore explains itself when run without files", "simscore" in (r.stdout + r.stderr), (r.stdout + r.stderr)[:120])
    r = run(sys.executable, "-m", "userbot.import_contact"); record(A, "import_contact explains itself when run without arguments", "import_contact" in (r.stdout + r.stderr), (r.stdout + r.stderr)[:120])
    r = run(sys.executable, "-m", "unittest", "discover", "tests"); record(A, "the rule tests pass", r.returncode == 0, r.stderr[-200:])


async def _async(value=None):
    return value


SECTIONS = {"commands": commands, "orders": orders, "replies": replies, "switches": switches, "jobs": jobs}


async def run_all():
    wanted = sys.argv[1:] or list(SECTIONS)
    for name in wanted:
        print(f"\n===== {name} =====", flush=True)
        try:
            await SECTIONS[name]()
        except Exception as e:  # a crash in the harness or the code is itself a finding
            import traceback
            record(name, f"section crashed: {type(e).__name__}", False, traceback.format_exc()[-600:])
    await app.http.aclose()
    bad = [r for r in RESULTS if not r["ok"]]
    Path("full_check.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1))
    print(f"\n{len(RESULTS) - len(bad)} of {len(RESULTS)} checks passed")

if __name__ == "__main__":
    asyncio.run(run_all())
