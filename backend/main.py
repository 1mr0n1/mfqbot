import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import storage
from .config import MODELS, SYSTEM_PROMPT
from .llm import LLMError, complete

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()


app = FastAPI(title="Chatbot backend", lifespan=lifespan)


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

    error = None
    for key in req.models:
        try:
            return ChatResponse(reply=await complete(app.state.http, MODELS[key], messages), model=key)
        except LLMError as e:
            error = e
    raise HTTPException(503, str(error))


if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run("backend.main:app", host=os.getenv("BACKEND_HOST", "127.0.0.1"),
                port=int(os.getenv("BACKEND_PORT", "8000")))
