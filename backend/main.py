import logging
import os
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import admin, storage
from .config import MAX_TOKENS, MODELS, SYSTEM_PROMPT
from .llm import LLMError, complete

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()


app = FastAPI(title="Chatbot backend", lifespan=lifespan)
app.include_router(admin.router)

# ----- access from outside this machine (e.g. the dashboard hosted on Vercel, reaching the backend through a tunnel) -----
# Requests that arrive from anywhere but this machine may only touch /admin, and only with ADMIN_TOKEN.
# Everything else (/chat, /complete, … — they spend your API keys) is never reachable from outside.
# With ADMIN_TOKEN unset, remote access is simply off.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
ADMIN_ORIGINS = [o.strip() for o in os.getenv("ADMIN_ORIGINS", "").split(",") if o.strip()]  # e.g. https://my-panel.vercel.app
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "x-real-ip", "forwarded", "x-forwarded-host")


def is_remote(request: Request) -> bool:
    host = (request.headers.get("host") or "").lower()
    host = host.rsplit(":", 1)[0] if not host.endswith("]") else host
    return host not in LOCAL_HOSTS or any(h in request.headers for h in PROXY_HEADERS)


@app.middleware("http")
async def remote_guard(request: Request, call_next):
    if is_remote(request):
        if not request.url.path.startswith("/admin"):
            return JSONResponse({"detail": "Not available from outside this machine."}, status_code=403)
        if not ADMIN_TOKEN:
            return JSONResponse({"detail": "Remote access is off (no ADMIN_TOKEN set)."}, status_code=403)
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not secrets.compare_digest(given.encode(), ADMIN_TOKEN.encode()):
            return JSONResponse({"detail": "Wrong or missing token."}, status_code=401)
    return await call_next(request)


if ADMIN_ORIGINS:  # added last so it runs first: browsers' preflight requests are answered before the guard
    app.add_middleware(CORSMiddleware, allow_origins=ADMIN_ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])


class ChatRequest(BaseModel):
    user_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    model: str


class ModelChoice(BaseModel):
    model: str


class CompleteRequest(BaseModel):
    messages: list[dict]
    system: str | None = None
    models: list[str] = list(MODELS)  # tried in order until one succeeds
    max_tokens: int = Field(MAX_TOKENS, ge=1, le=16384)  # reasoning models spend part of this thinking
    reasoning: bool = False  # let the model think first (slower; for analysis jobs, not chat replies)
    temperature: float | None = Field(None, ge=0, le=2)  # lower = more predictable, fewer made-up words


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/models")
async def list_models():
    return [{"key": k, "name": v["name"]} for k, v in MODELS.items()]


@app.get("/users/{user_id}/model")
async def get_model(user_id: str):
    return {"model": storage.get_user(user_id).model}


@app.put("/users/{user_id}/model")
async def set_model(user_id: str, body: ModelChoice):
    if body.model not in MODELS:
        raise HTTPException(400, f"Unknown model. Choose one of: {', '.join(MODELS)}")
    storage.get_user(user_id).model = body.model
    return {"model": body.model}


@app.delete("/users/{user_id}/history")
async def reset(user_id: str):
    storage.reset_history(user_id)
    return {"status": "cleared"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    user = storage.get_user(req.user_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *user.history,
                {"role": "user", "content": req.message}]
    try:
        reply = await complete(app.state.http, MODELS[user.model], messages)
    except LLMError as e:
        raise HTTPException(503, str(e))

    storage.append_history(req.user_id, "user", req.message)
    storage.append_history(req.user_id, "assistant", reply)
    return ChatResponse(reply=reply, model=user.model)


@app.post("/complete", response_model=ChatResponse)
async def complete_stateless(req: CompleteRequest):
    """Stateless completion: caller supplies the full context (used by the userbot)."""
    unknown = [m for m in req.models if m not in MODELS]
    if unknown or not req.models:
        raise HTTPException(400, f"Unknown models: {unknown}. Choose from: {', '.join(MODELS)}")
    messages = ([{"role": "system", "content": req.system}] if req.system else []) + req.messages

    # With images in the request, try models that can actually see them first.
    has_images = any(isinstance(m.get("content"), list) for m in req.messages)
    order = sorted(req.models, key=lambda k: not MODELS[k].get("vision")) if has_images else req.models

    error = None
    for key in order:
        try:
            reply = await complete(app.state.http, MODELS[key], messages, req.max_tokens, req.reasoning,
                                   req.temperature)
            return ChatResponse(reply=reply, model=key)
        except LLMError as e:
            error = e
    raise HTTPException(503, str(error))


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run("backend.main:app", host=os.getenv("BACKEND_HOST", "127.0.0.1"),
                port=int(os.getenv("BACKEND_PORT", "8000")))
