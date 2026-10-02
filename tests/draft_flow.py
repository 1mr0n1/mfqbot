"""The life of a draft on the dashboard, through the real reply flow (real model, fake Telegram):
held in approve mode → edited and sent / cancelled / sent untouched when its time runs out.

  PYTHONPATH=. .venv/bin/python tests/draft_flow.py        (the backend must be running)
"""
import asyncio
import tempfile
from pathlib import Path

from telethon.tl.types import User

from userbot import simulate as SIM
from userbot import app, config as C, lessons, replies, trace

lessons.PATH = Path(tempfile.mkdtemp()) / "lessons.json"
results = []


def ok(name, cond, detail=""):
    results.append(bool(cond))
    print(("ok    " if cond else "FAIL  ") + name + ("" if cond else f"   [{detail}]"), flush=True)


async def one(case: int, decide, approve: bool, hold: float = 0.0):
    """Someone writes; `decide(draft_text)` says what the dashboard answers when the bot asks about the draft."""
    fake = app.client
    chat_id = 900 + case
    contact = User(id=chat_id, first_name="Timur", contact=True)
    fake.histories[chat_id] = [SIM.make("привет, как дела?"), SIM.make("привет", out=True)]
    app.state.approve = approve
    C.MIN_HOLD = hold
    seen = {}
    events = []
    trace.emit = lambda kind, chat="", text="", **data: (events.append((kind, text)), seen.update(draft=text) if kind == "draft" else None)

    async def draft_state(draft_id):
        return decide(seen.get("draft")) if "draft" in seen else {}
    trace.draft_state = draft_state

    async def cancelled(draft_id):
        return bool((await draft_state(draft_id)).get("cancelled"))
    trace.draft_cancelled = cancelled
    await asyncio.wait_for(replies.reply_flow(chat_id, contact), 90)
    return fake.sent.get(chat_id, []), events, seen.get("draft")


async def main():
    app.client = SIM.FakeClient()
    app.me = User(id=1, first_name="Kamron")
    sent, events, draft = await one(1, lambda d: {"send_now": True, "parts": ["нормально, сам как"], "editing": True}, approve=True)
    ok("approve mode: a draft is shown", draft, events[-3:])
    ok("edited + Send now: exactly your text is sent", sent == ["нормально, сам как"], sent)
    ok("your correction is remembered as a lesson", any(f["yours"] == "нормально, сам как" for f in lessons._load()["fixes"]), lessons._load())
    sent, events, draft = await one(2, lambda d: {"cancelled": True}, approve=True)
    ok("Cancel: nothing is sent", sent == [], sent)
    ok("Cancel: the log says so", any(k == "cancelled" for k, _ in events), [k for k, _ in events][-4:])
    sent, events, draft = await one(3, lambda d: {"send_now": True, "parts": None}, approve=True)
    ok("Send now without editing: the model's draft is sent as it was", sent and "\n".join(s.lstrip("↩ ") for s in sent) == draft, (sent, draft))
    sent, events, draft = await one(4, lambda d: {}, approve=False, hold=0.5)
    ok("left alone (approve off): it sends itself when the bar runs out", bool(sent), sent)
    C.APPROVE_TIMEOUT = 2
    sent, events, draft = await one(5, lambda d: {}, approve=True)
    ok("approve mode, never approved: nothing is sent", sent == [], sent)
    await app.http.aclose()
    print(f"\n{sum(results)} of {len(results)} checks passed")

asyncio.run(main())
