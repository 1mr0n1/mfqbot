"""Run scripted conversations through the real reply pipeline without touching Telegram.

  .venv/bin/python -m userbot.simulate scenarios.json [out.json] [--only 3,17,42]

The Telegram client is replaced by a fake that records what would have been sent (messages, reactions,
stickers, notes to yourself). Everything else is the production code path: hand-off check, identity and salam
rules, closers, the model, length limit, punctuation, second look. State, day log and notes go to a temp
folder, timing is switched off, and nothing is ever sent to a real person. The backend must be running.

scenarios.json:
  {"contacts": {"friend": {"first_name": "Said", "username": "some_username"}, ...},
   "scenarios": [{"id": 1, "who": "friend", "tag": "greeting", "turns": ["привет", ["two", "messages"]],
                  "history": [["earlier message from them", false], ["earlier message from you", true]]}]}
"""
import asyncio
import itertools
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

os.environ.update(USERBOT_HUMAN_PACING="false", USERBOT_RHYTHM="false", USERBOT_TYPO_CHANCE="0", USERBOT_REMEMBER="false")

from telethon.tl.types import User  # noqa: E402

from . import config as C  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="userbot-sim-")
C.DAYLOG_PATH = Path(_tmp) / "daylog.json"
C.MEMORY_DIR = Path(_tmp) / "memory"
C.RETRY_DELAY = (0, 0)
C.BETWEEN_MESSAGES = (0, 0)
from . import state as state_module  # noqa: E402

state_module.STATE_PATH = Path(_tmp) / "state.json"

from . import main as U  # noqa: E402
from . import trace  # noqa: E402

_ids = itertools.count(1000)


def message(text="", out=False, **kw):
    msg = NS(id=next(_ids), message=text, out=out, date=datetime.now(timezone.utc), photo=None, voice=None, video=None,
             video_note=None, document=None, sticker=None, gif=None, media=None, file=None, is_reply=False,
             sender=None, fwd_from=None)
    msg.__dict__.update(kw)
    return msg


class _Msg(NS):
    @property
    def raw_text(self):
        return self.message

    async def download_media(self, file=None, thumb=None):
        return None

    async def get_reply_message(self):
        return None


def make(text="", out=False, **kw):
    return _Msg(**message(text, out, **kw).__dict__)


class _Action:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeClient:
    """Stands in for Telegram: serves the scripted history and records what the bot does."""

    def __init__(self):
        self.histories: dict[int, list] = {}   # chat_id -> messages, newest first
        self.sent: dict[int, list[str]] = {}
        self.notes: list[str] = []

    async def get_me(self):
        return U.me

    async def get_messages(self, chat_id, limit=30, **kw):
        return self.histories.get(chat_id, [])[:limit]

    async def send_read_acknowledge(self, chat_id):
        pass

    def action(self, chat_id, kind):
        return _Action()

    def _record(self, chat_id, text, out_msg=True):
        self.sent.setdefault(chat_id, []).append(text)
        msg = make(text if not text.startswith("[") else "", out=True)
        self.histories.setdefault(chat_id, []).insert(0, msg)
        return msg

    async def send_message(self, chat_id, text, reply_to=None, **kw):
        if chat_id == "me":
            sink = _emit_sink.get()
            if sink is not None:
                sink.append(("note", text))
            return make(text, out=True)
        return self._record(chat_id, ("↩ " if reply_to else "") + text)

    async def send_file(self, chat_id, file, **kw):
        return self._record(chat_id, "[sticker/media sent]")

    async def edit_message(self, chat_id, msg_id, text):
        pass

    async def __call__(self, request):
        reaction = getattr(request, "reaction", None)
        if reaction:
            self.sent.setdefault(request.peer, []).append(f"[reaction {reaction[0].emoticon}]")
        return NS(stickers=[], set=NS(title="pack", short_name="pack"))

    async def inline_query(self, bot, query):
        return []


async def run_scenario(fake: FakeClient, contacts: dict, sc: dict) -> dict:
    spec = contacts[sc["who"]]
    chat_id = 100000 + sc["id"]
    contact = User(id=chat_id, first_name=spec["first_name"], last_name=spec.get("last_name"),
                   username=spec.get("username"))
    earlier = datetime.now(timezone.utc) - timedelta(hours=1)  # older than the "you're active here" window
    fake.histories[chat_id] = [make(t, out=o, date=earlier) for t, o in reversed(sc.get("history", []))]
    turns, events = [], []
    for turn in sc["turns"]:
        incoming = turn if isinstance(turn, list) else [turn]
        for text in incoming:
            kw = {}
            if text.startswith("[sticker"):
                kw, text = {"sticker": True, "document": NS(id=next(_ids), attributes=[])}, ""
            fake.histories[chat_id].insert(0, make(text, **kw))
        before = len(fake.sent.get(chat_id, []))
        captured = []
        token = _emit_sink.set(captured)
        started = time.monotonic()
        try:
            await U.reply_flow(chat_id, contact)
        finally:
            _emit_sink.reset(token)
        sent = fake.sent.get(chat_id, [])[before:]
        turns.append({"them": incoming, "bot": sent, "notes": [t for k, t in captured if k == "note"],
                      "why": [t for k, t in captured if k in ("warning", "decision") and not t.startswith(("Typing", "Done", "Read the chat", "Model used"))],
                      "seconds": round(time.monotonic() - started, 1)})
    return {"id": sc["id"], "who": sc["who"], "tag": sc.get("tag", ""), "turns": turns}


import contextvars  # noqa: E402

_emit_sink: contextvars.ContextVar = contextvars.ContextVar("emit_sink", default=None)


def _emit(kind, chat="", text="", **data):
    sink = _emit_sink.get()
    if sink is not None:
        sink.append((kind, text))


async def _never_cancelled(draft_id):
    return False


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = next((set(int(x) for x in a.split("=", 1)[1].split(",")) for a in sys.argv[1:] if a.startswith("--only=")), None)
    data = json.loads(Path(args[0]).read_text())
    out_path = Path(args[1]) if len(args) > 1 else None
    scenarios = [s for s in data["scenarios"] if not only or s["id"] in only]

    fake = FakeClient()
    U.client = fake
    U.me = User(id=1, first_name=data.get("me", {}).get("first_name", "Me"), last_name=data.get("me", {}).get("last_name"))
    trace.emit = _emit
    trace.draft_cancelled = _never_cancelled
    U.trace.emit, U.trace.draft_cancelled = _emit, _never_cancelled

    sem = asyncio.Semaphore(int(os.environ.get("SIM_PARALLEL", "3")))

    async def guarded(sc):
        async with sem:
            try:
                return await run_scenario(fake, data["contacts"], sc)
            except Exception as e:  # a crash in the pipeline is a finding too
                return {"id": sc["id"], "who": sc["who"], "tag": sc.get("tag", ""), "turns": [], "crash": repr(e)}

    results = sorted(await asyncio.gather(*(guarded(s) for s in scenarios)), key=lambda r: r["id"])
    for r in results:
        print(f"#{r['id']:<3} [{r['who']}/{r['tag']}]" + (f"  CRASH {r['crash']}" if r.get("crash") else ""))
        for t in r["turns"]:
            print(f"     THEM: {' ⏎ '.join(t['them'])}")
            print(f"     BOT : {' ⏎ '.join(t['bot']) if t['bot'] else '(nothing sent)'}" + (f"   ⟨{'; '.join(t['why'])[:150]}⟩" if t["why"] else ""))
            for n in t["notes"]:
                print(f"     NOTE TO YOU: {n[:160]}")
    if out_path:
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    await U.http.aclose()


if __name__ == "__main__":
    asyncio.run(main())
