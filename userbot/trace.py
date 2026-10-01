"""Sends the userbot's decision log to the backend's admin dashboard (http://127.0.0.1:8000/admin).

Fire-and-forget: if the backend is down or slow, the userbot carries on unaffected.
"""
import asyncio
import uuid

import httpx

from . import config as C

_http = httpx.AsyncClient(base_url=C.BACKEND_URL, timeout=3)
_tasks: set[asyncio.Task] = set()


async def _post(payload: dict):
    try:
        await _http.post("/admin/events", json=payload)
    except httpx.HTTPError:
        pass


def emit(kind: str, chat: str = "", text: str = "", **data):
    """kind: incoming | decision | draft | sent | cancelled | warning | system"""
    task = asyncio.create_task(_post({"kind": kind, "chat": chat, "text": text, "data": data}))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def new_draft_id() -> str:
    return uuid.uuid4().hex[:12]


async def draft_cancelled(draft_id: str) -> bool:
    """True if you pressed Cancel on the dashboard for this draft."""
    try:
        resp = await _http.get(f"/admin/drafts/{draft_id}")
        return bool(resp.json().get("cancelled"))
    except (httpx.HTTPError, ValueError):
        return False
