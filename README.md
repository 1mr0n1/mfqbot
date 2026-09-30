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
| POST | `/complete` | stateless: `{messages, system?, models[]}` → `{reply, model}`, tries models in order |

Interactive docs: http://127.0.0.1:8000/docs

## Userbot (replies from your own Telegram account)

`userbot/` logs in as **your account** (Telethon) and replies in private chats like a human would:
waits for the other person to finish typing, marks the chat read after a random delay, shows "typing…"
for a time proportional to the reply length, and sometimes splits replies into several messages.
Context is read from the real chat history, so your own manual messages are taken into account.

```bash
# fill TELEGRAM_API_ID / TELEGRAM_API_HASH in .env (from https://my.telegram.org)
.venv/bin/python -m userbot.login   # once, interactive: phone, code, 2FA password
.venv/bin/python -m userbot.main    # needs the backend running
```

Control it by typing these from your account (the command is deleted, confirmation goes to Saved Messages):

| Command | Where | Effect |
|---|---|---|
| `.ai on` / `.ai off` | a private chat | enable / disable auto-replies there |
| `.ai pause` / `.ai resume` | anywhere | stop / restart all auto-replies |
| `.ai status` | anywhere | show state |

Safety behaviour: private chats only (no groups/channels/bots/Telegram service messages), stays quiet
if you wrote in the chat within the last 2 minutes, cancels its reply if you start replying yourself,
won't commit you to meetings/money/favors. Style is in `userbot/persona.md`, timing in `userbot/config.py`.
`USERBOT_REPLY_MODE=all` replies in every private chat instead of only enabled ones.

### Teaching it your texting style

Either from a Telegram Desktop export (Chat → ⋮ → Export chat history → HTML) or from a live account:

```bash
.venv/bin/python -m userbot.import_export chat-histories "ImrOnO"   # folder of exports + your name in them
.venv/bin/python -m userbot.learn_style [session]                    # live account (userbot stopped)
```

Only your own messages are learned from (forwards, links and messages containing slurs are skipped).
This writes `userbot/style/` (profile + 400 real example messages, git-ignored); each reply includes the
profile and 40 random examples. Re-run any time — the userbot picks it up without a restart.

Guards: model reasoning is switched off for replies and any reply that looks like leaked reasoning is
never sent; assistant-speak lines are dropped; "are you a bot?" always gets a fixed honest auto-reply
and a heads-up in your Saved Messages.

⚠️ `userbot/account.session` gives full access to your account — never share or commit it.
Telegram may restrict accounts that look automated; keep volumes low.

## Notes
- Models and providers are configured in `backend/config.py` (`MODELS`, `PROVIDERS`). Any OpenAI-compatible provider can be added.
- Free models are often rate-limited (429/503); `backend/llm.py` retries twice with backoff.
- State is in memory (`backend/storage.py`) — lost on restart. Swap for Redis/Postgres when needed.
