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
| `.ai pause 30m` (m/h/d) | anywhere | pause for a while, then resume automatically |
| `.ai status` | anywhere | show state |
| `.ai unread` | anywhere | answer unread private messages now (also done at startup) |
| `.ai save <tag>` | Saved Messages, as a reply | add your voice / round video message to the clip library |
| `.ai clips` / `.ai forget <tag>` | anywhere | list / remove clips |
| `.ai savepack` | anywhere, as a reply to a sticker | add that sticker's whole pack to your account |
| `.ai salam` / `.ai notsalam` | anywhere, as a reply to a sticker | teach that it is / isn't an "Assalomu alaykum" sticker |
| `.ai name …` / `.ai surname …` / `.ai bio …` | Saved Messages | change your profile (`-` clears surname/bio) |
| `.ai photo` | Saved Messages, as a reply to a photo | set it as your profile photo |
| `.ai profile` | Saved Messages | show current name / surname / bio |
| `.ai pfp undo` | anywhere | remove the newest profile photo (the previous one comes back) |

Media: replies can include stickers (your favorites/recents first), GIFs (via @gif) and your own recorded
voice / round video clips. The model never fakes voice or video — it can only send clips you recorded.
Profile photo on request (`USERBOT_PFP_FROM_CHATS`): if someone sends a photo and explicitly asks you to use it
as your profile picture, the account sets it — after a vision model clears the picture (fails closed), at
most 3 times a day and 10 minutes apart; each change is reported in Saved Messages. Name, surname and bio
are never changed from chats.
Vision: photos the other person sends are passed to a model that can see them (`omni`, then `qwen`/`local`);
text-only models get a `[photo]` placeholder. Unread DMs up to 24h old are answered at startup — private
chats only, never groups, channels or bots.
Auto-bio (`USERBOT_AUTO_BIO`): every 6–14h, never at night, the account rewrites its own bio in the learned
style (no chat content is used, so nothing private leaks); each change is noted in Saved Messages.
Name, surname and photo are only changed by you (`.ai …` commands or `python -m userbot.profile`).
`USERBOT_REPLY_MODE=all` replies in every private chat (`.ai off` excludes one); `allowlist` only in chats
enabled with `.ai on`. `USERBOT_HUMAN_PACING=false` replies instantly; `USERBOT_MEDIA=false` disables media.

Safety behaviour: private chats only (no groups/channels/bots/Telegram service messages), stays quiet
if you wrote in the chat within the last 2 minutes, cancels its reply if you start replying yourself,
won't commit you to meetings/money/favors. Style is in `userbot/persona.md`, timing in `userbot/config.py`.
Vision: photos the other person sends are passed to a model that can see them (`omni`, then `qwen`/`local`);
text-only models get a `[photo]` placeholder. Unread DMs up to 24h old are answered at startup — private
chats only, never groups, channels or bots.
Auto-bio (`USERBOT_AUTO_BIO`): every 6–14h, never at night, the account rewrites its own bio in the learned
style (no chat content is used, so nothing private leaks); each change is noted in Saved Messages.
Name, surname and photo are only changed by you (`.ai …` commands or `python -m userbot.profile`).
`USERBOT_REPLY_MODE=all` replies in every private chat instead of only enabled ones.

### What it knows, and when it stays out

- **Facts about you** — copy `userbot/facts.example.md` to `userbot/facts.md` and fill it in (school, routine,
  family, interests). The account answers from it and stays vague about anything not listed.
- **Notes per person** — after a reply, lasting things the *other person* said (a move, a birthday, a request)
  are saved under `userbot/memory/` and used in later chats. `.ai note <text>`, `.ai notes`, `.ai forgetnotes`
  inside that person's chat. Notes are never taken from the bot's own messages.
- **Not everything gets a reply** — an "ok" / "👍" / "спасибо" after your message is left alone or gets an emoji
  reaction instead of text (`USERBOT_SMART_SKIP`).
- **Identity questions are ignored** — "are you a bot?", "who are you?", "is this really you?" get no answer
  (neither confirmed nor denied; any line claiming to be human is dropped). If the message also says
  something else, only that part is answered.
- **Hand-off** — money, verification codes/passwords, emergencies, or someone upset / wanting a serious talk are
  not answered: the message stays unread, you get a 🚨 note in Saved Messages, and the account stays out of
  that chat for 30 minutes or until you write there (`USERBOT_HANDOFF`).

### Admin dashboard

Open http://127.0.0.1:8000/admin while the backend and userbot run. It shows a live **decision log**
(who wrote, why the bot waits or stays quiet, which model answered, what was blocked) and an
**About to send** panel: every draft is held for 2–3 s (`DRAFT_HOLD`) with a Cancel button, then typed
out with a human-length "typing…" indicator. Events live in memory only and the page is reachable
only from this machine.

### Teaching it your texting style

Either from a Telegram Desktop export (Chat → ⋮ → Export chat history → HTML) or from a live account:

```bash
.venv/bin/python -m userbot.import_export chat-histories "YourName"   # folder of exports + your name as shown in them
.venv/bin/python -m userbot.learn_style [session]                    # live account (userbot stopped)
```

Per-person style (built locally, no model call) — the userbot then talks to that username only the way
your real chat with them shows, in one language at a time, without stickers/GIFs:

```bash
.venv/bin/python -m userbot.import_contact "chat-histories/ChatExport_X" "YourName" their_username
```

Salam: a written "Assalomu alaykum (va rahmatullohi va barokatuh)" in Latin, Cyrillic or Arabic script gets the
fixed proper answer in the same script and length; a salam sticker is answered with the very same sticker
and its pack is saved. Stickers are recognized by one look from a vision model (remembered per sticker) or by
what you taught with `.ai salam`.

Replies are language-aware (Uzbek incl. everyday Tashkent forms, Russian, English, plus ~25 other languages
by script or common words; anything unrecognized is answered in the language it was written in), mirror formality
(вы/siz for formal messages) and stay non-committal about plans, times, money and favors.
Model routing: `USERBOT_MODELS=nemotron,omni,…` — text goes to the first model, photos to vision models first.

Only your own messages are learned from (forwards, links and messages containing slurs are skipped).
This writes `userbot/style/` (profile + 400 real example messages, git-ignored); each reply includes the
profile and 40 random examples. Re-run any time — the userbot picks it up without a restart.

Guards: model reasoning is switched off for replies and any reply that looks like leaked reasoning is
never sent; assistant-speak lines are dropped; identity questions ("are you a bot?") are ignored.

⚠️ `userbot/account.session` gives full access to your account — never share or commit it.
Telegram may restrict accounts that look automated; keep volumes low.

## Notes
- Models and providers are configured in `backend/config.py` (`MODELS`, `PROVIDERS`). Any OpenAI-compatible provider can be added.
- Free models are often rate-limited (429/503); `backend/llm.py` retries twice with backoff.
- State is in memory (`backend/storage.py`) — lost on restart. Swap for Redis/Postgres when needed.
