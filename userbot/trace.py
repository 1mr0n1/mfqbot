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
    if kind in ("decision", "warning", "system"):
        from . import daylog
        try:
            daylog.tally(text)
        except Exception:
            pass  # the report is a convenience; it must never get in the way of a reply
    task = asyncio.create_task(_post({"kind": kind, "chat": chat, "text": text, "data": data}))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def new_draft_id() -> str:
    return uuid.uuid4().hex[:12]


async def draft_state(draft_id: str) -> dict:
    """What you did with this draft on the dashboard: {"cancelled", "send_now", "parts"}."""
    try:
        return (await _http.get(f"/admin/drafts/{draft_id}")).json()
    except (httpx.HTTPError, ValueError):
        return {}


async def draft_cancelled(draft_id: str) -> bool:
    """True if you pressed Cancel on the dashboard for this draft."""
    return bool((await draft_state(draft_id)).get("cancelled"))


async def commands(after: int) -> tuple[int, list[dict]]:
    """Commands typed/clicked on the dashboard since `after` -> (latest id, new commands)."""
    try:
        data = (await _http.get("/admin/commands", params={"after": after})).json()
        return data.get("latest", 0), data.get("commands", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        return after, []


async def report_status(status: dict):
    try:
        await _http.post("/admin/status", json=status)
    except httpx.HTTPError:
        pass


async def report_history(chat: str, messages: list[dict]):
    try:
        await _http.post("/admin/history", json={"chat": chat, "messages": messages})
    except httpx.HTTPError:
        pass
