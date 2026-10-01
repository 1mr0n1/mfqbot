"""Local admin dashboard: watch the userbot's decisions live — and change them.

The page can edit or cancel a draft before it is sent, hold every draft until you approve it, make the bot
answer a chat it left alone, send your own text, switch a chat between auto / manual / off, and pause everything.
The backend only relays: the dashboard posts commands here, the userbot polls and executes them.

Everything is kept in memory only (lost on restart) and the backend listens on 127.0.0.1, so the page — which
can send messages from your account — is only reachable from this machine. Don't expose this port.
"""
import itertools
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter(prefix="/admin")

MAX_EVENTS = 500
_events: deque[dict] = deque(maxlen=MAX_EVENTS)
_ids = itertools.count(1)
_drafts: dict[str, dict] = {}            # draft id -> {"cancelled": bool, "send_now": bool, "parts": [...] | None}
_commands: deque[dict] = deque(maxlen=200)
_command_ids = itertools.count(1)
_status: dict = {}
PAGE = Path(__file__).with_name("admin.html")


class Event(BaseModel):
    kind: str            # incoming | decision | draft | sent | cancelled | warning | system
    chat: str = ""       # person's name
    text: str = ""
    data: dict = {}      # e.g. {"draft_id": ..., "parts": [...], "hold": 2.5}


class DraftEdit(BaseModel):
    parts: list[str] | None = None   # replacement messages, one per item
    editing: bool = False            # you started typing: the draft waits for Send now / Cancel


class Command(BaseModel):
    type: str            # pause | resume | approve | mode | answer | say
    chat: str = ""       # person's name as shown on the dashboard
    text: str = ""       # for "say"
    value: str = ""      # for "mode": auto | manual | off; for "approve": on | off


@router.get("", response_class=HTMLResponse)
async def page():
    return PAGE.read_text()


@router.post("/events")
async def add_event(event: Event):
    item = {"id": next(_ids), "ts": time.time(), **event.model_dump()}
    _events.append(item)
    return {"id": item["id"]}


@router.get("/events")
async def list_events(after: int = 0):
    return {"now": time.time(), "events": [e for e in _events if e["id"] > after]}


# ----- drafts: cancel, edit, send now -----
def _draft(draft_id: str) -> dict:
    return _drafts.setdefault(draft_id, {"cancelled": False, "send_now": False, "parts": None, "editing": False})


@router.post("/drafts/{draft_id}/cancel")
async def cancel_draft(draft_id: str):
    _draft(draft_id)["cancelled"] = True
    return _draft(draft_id)


@router.post("/drafts/{draft_id}/edit")
async def edit_draft(draft_id: str, body: DraftEdit):
    _draft(draft_id)["parts"] = [p.strip() for p in (body.parts or []) if p.strip()] or None
    _draft(draft_id)["editing"] = _draft(draft_id)["editing"] or body.editing
    return _draft(draft_id)


@router.post("/drafts/{draft_id}/send")
async def send_draft(draft_id: str, body: DraftEdit | None = None):
    draft = _draft(draft_id)
    if body and body.parts is not None:
        draft["parts"] = [p.strip() for p in body.parts if p.strip()] or None
    draft["send_now"] = True
    return draft


@router.get("/drafts/{draft_id}")
async def draft_status(draft_id: str):
    return _draft(draft_id)


# ----- commands from the dashboard to the userbot -----
@router.post("/commands")
async def add_command(command: Command):
    item = {"id": next(_command_ids), "ts": time.time(), **command.model_dump()}
    _commands.append(item)
    return {"id": item["id"]}


@router.get("/commands")
async def list_commands(after: int = 0):
    latest = _commands[-1]["id"] if _commands else 0  # lets the userbot notice a backend restart (ids start over)
    return {"latest": latest, "commands": [c for c in _commands if c["id"] > after]}


# ----- what the userbot is doing right now (it reports every few seconds) -----
@router.post("/status")
async def set_status(status: dict):
    _status.clear()
    _status.update(status, ts=time.time())
    return {"ok": True}


@router.get("/status")
async def get_status():
    return {**_status, "age": time.time() - _status["ts"]} if _status else {"age": None}
