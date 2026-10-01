"""Local admin dashboard: live decision log of the userbot + drafts you can cancel before they're sent.

Everything is kept in memory only (lost on restart, never written to disk) and the backend listens on
127.0.0.1, so the page is only reachable from this machine.
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
_cancelled_drafts: set[str] = set()
PAGE = Path(__file__).with_name("admin.html")


class Event(BaseModel):
    kind: str            # incoming | decision | draft | sent | cancelled | warning | system
    chat: str = ""       # person's name
    text: str = ""
    data: dict = {}      # e.g. {"draft_id": ..., "parts": [...], "hold": 2.5}


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


@router.post("/drafts/{draft_id}/cancel")
async def cancel_draft(draft_id: str):
    _cancelled_drafts.add(draft_id)
    return {"cancelled": True}


@router.get("/drafts/{draft_id}")
async def draft_status(draft_id: str):
    return {"cancelled": draft_id in _cancelled_drafts}
