# Telegram AI chatbot

```
Telegram user ──> bot/ (aiogram) ──HTTP──> backend/ (FastAPI) ──> OpenRouter  (Qwen)
                                                                  └──> NVIDIA API (Nemotron)
```

The bot is only an interface: all LLM calls, chat history and per-user model choice live in the backend.

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in OPENROUTER_API_KEY, NVIDIA_API_KEY, TELEGRAM_BOT_TOKEN

.venv/bin/python -m backend.main   # terminal 1
.venv/bin/python -m bot.main       # terminal 2
```

## Bot commands
- `/start` — intro
- `/model` — pick Qwen or Nemotron (inline buttons, ✅ marks the current one)
- `/reset` — clear conversation history
- any text — chat

## Backend API
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/models` | available models |
| GET/PUT | `/users/{id}/model` | get / set user's model |
| DELETE | `/users/{id}/history` | clear history |
| POST | `/chat` | `{user_id, message}` → `{reply, model}` |

Interactive docs: http://127.0.0.1:8000/docs

## Notes
- Models and providers are configured in `backend/config.py` (`MODELS`, `PROVIDERS`). Any OpenAI-compatible provider can be added.
- Free models are often rate-limited (429/503); `backend/llm.py` retries twice with backoff.
- State is in memory (`backend/storage.py`) — lost on restart. Swap for Redis/Postgres when needed.
