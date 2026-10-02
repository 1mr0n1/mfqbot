# Telegram account that answers like you

Three programs:

```
people on Telegram ──> userbot/  (your own account, Telethon) ──HTTP──┐
Telegram bot users ──> bot/      (a normal bot, aiogram)      ──HTTP──┼──> backend/ (FastAPI) ──> model providers
you, in a browser  ──> dashboard (backend/admin.html)         ──HTTP──┘
```

- **backend/** — the only part that talks to language models (OpenRouter, NVIDIA, a local server). It also
  relays between the dashboard and the userbot.
- **userbot/** — logs in as *your* account and replies in private chats and groups the way you write.
- **bot/** — a small ordinary chatbot (`/start`, `/model`, `/reset`, any text).

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                    # API keys, bot token, Telegram api_id / api_hash (my.telegram.org)
.venv/bin/python -m userbot.login       # once: phone, code, 2FA password
sh scripts/services.sh install          # macOS: runs backend, userbot and bot as services, restarts them if they stop
```

`sh scripts/services.sh status | restart | stop | start | logs`. Logs: `~/Library/Logs/mfqbot/`.
By hand instead: `.venv/bin/python -m backend.main`, `-m userbot.main`, `-m bot.main`.
On a server: see `deploy/README.md`.

A laptop that sleeps stops answering; after more than a few minutes down, the account says so in Saved Messages
when it is back.

## Models

`backend/config.py` lists the models (`MODELS`) and providers (`PROVIDERS`); any OpenAI-compatible provider can be
added. The userbot picks by purpose in `.env`:

| Setting | Used for |
|---|---|
| `USERBOT_MODELS` | replies and orders — the first answers, the second joins if the first is slow |
| `USERBOT_PHOTO_MODELS` | messages with photos (models that can see) |
| `USERBOT_JUDGE_MODELS` | small checks: who-is-this answers, follow-ups, note-taking |

## How it replies

Style comes from your own chats (see "Teaching it" below), never from a generic persona.

- **Short, like you.** Your punctuation habits, almost no emoji, one thought per message: a reply with two
  thoughts goes out as two messages; two versions of the same thought are sent once.
- **Several questions** each get their own answer, sent as a reply to that question.
- **Closing words get a reaction.** "ок", "спасибо", "пока" after your message get 👍 / ❤, not more text.
- **A dry answer to your question** ("как дела?" — "норм") gets a follow-up question, twice at most.
- **"Щас" means something follows.** After "ок щас" / "lemme check" it comes back within about a minute with
  the answer, or a plain "couldn't find out".
- **Facts are looked up.** A checkable claim or a dispute about the world is searched on the web before
  answering; asked for proof, it sends the source. Sums ("сколько будет 17*23") are worked out, not guessed.
- **A mood for the day** (`.ai mood`), and an online pattern that looks like a person's rather than "always on".
- **Voice messages** are transcribed locally (Whisper). One with no words in it gets a reaction.
- **Photos** go to a model that can see them.
- **Timing.** Reading and thinking time depend on the message; typing sometimes pauses or restarts. Night sleep,
  school hours and an occasional slow reply are switches.
- **Asking again.** A question of yours left unanswered gets a "?", then is asked once more in other words.
- **Writing first.** Up to twice a day it opens a chat itself: to ask how something they mentioned went, or just
  what's up — close friends only.

### What it will not do

- **Promise or claim things for you.** It does not agree to meet, lend, buy or come, does not say what you did,
  ate or ordered, where you are, what mark you got, when the test is, or that something "is done" — unless you
  told it (`.ai today <text>`) or it is in `facts.md`. Such drafts are rewritten into "не знаю ещё" ("Ты где?"
  gets "а что?"), and for things only you know, you get a note. The same goes for things about *them* it was
  never told (their birthday, what they lent you).
- **Say who or what is answering.** "Are you a bot?" is ignored — not confirmed, not denied — and so is insisting.
- **Repeat itself**, parrot the other person, or send text that could act as one of your commands.
- **Answer the serious things** (switchable): money and debts, codes, emergencies, a formal message from a
  teacher. Those are left unread and reported to you.
- **Answer someone in real trouble** (not switchable): "не хочу жить", "меня бьют", "бабушке плохо, скорую
  вызвали" always go to you, at once.
- **Do an assistant's chores.** "Напиши стих", "write me an essay" get brushed off the way you would; `.ai …`
  typed by someone else means nothing to it. Adverts and bait from strangers are ignored without bothering you.

### People

Everyone it talks to gets a folder in `userbot/memory/people/`: who they are, what they told it about
themselves, and things to ask about later. Tone follows closeness — family, close friend, acquaintance, stranger —
counted from your history with them and adjustable on the dashboard.
Someone unknown who writes for the first time is asked who they are, once; a valid answer saves them to your
Telegram contacts and tells you.

`userbot/facts.md` (copy `facts.example.md`) holds what is true about you: school, timetable, family, interests.
The account answers from it and stays vague about everything else. Your age and today's / tomorrow's lessons are
worked out from it rather than left to a model.

### Groups

Per group, on the dashboard: **Answers when called** (your name, your @username, or a reply to you),
**Also joins in** (may write uncalled when it judges a member would — a few times an hour, never after a formal
message), or **Ignored**. Each person who calls gets their own answer; someone calling over and over stops
getting replies for a while.

## Controlling it

### Commands you type from the account (`.ai …`)

The message is deleted; the answer goes to Saved Messages.

| Command | Effect |
|---|---|
| `.ai on` / `off` / `manual` | in a chat: answer / ignore / never answer, only tell you |
| `.ai pause [30m]` / `resume` / `status` / `awake 2h` | all auto-replies; stay up past the sleep window |
| `.ai unread` | answer waiting private messages now |
| `.ai today <text>` | tell it what is going on today (so it may say so) |
| `.ai note <text>` / `notes` / `forgetnotes` | in a chat: notes about that person |
| `.ai save <tag>` / `clips` / `forget <tag>` | reply to your voice or round video in Saved Messages: a clip it can send |
| `.ai name …` / `surname …` / `bio …` / `photo` / `profile` / `pfp undo` | your profile |
| `.ai fwd <who>` | reply to a message: forward it |
| `.ai summary` / `.ai report [today]` | the evening digest / the morning report, now |
| `.ai do <anything>` | an order in plain words — see below |

### Orders in plain words

`.ai do напиши Тимуру что буду в 6`, `.ai do mute the class group for 8 hours`, `.ai do что писала мама?` — or the
box on the dashboard. About forty actions: messages (send, schedule, forward, edit, delete, react, pin, voice
clips, pictures, polls), chats (read, search, mute, archive, join, leave, create), people (block, contacts),
your profile and privacy, the web (search, open a page).

- Common orders are understood by fixed rules (`userbot/quick.py`); the rest is planned by a model, one step at
  a time. The report lists what actually ran.
- Steps that can't be undone wait for `.ai do yes`.
- After reading what other people wrote, it may only act in the chats the order is about — text in a chat can
  never redirect it.
- Refused by a fixed rule, before any model sees the order: deleting the account, sessions, password, phone
  number, login codes.
- An order that repeats the same step three times stops itself.
- Web addresses on this machine or the local network are never opened.

### Your other account (`USERBOT_COMMANDERS`)

An account listed there — pinned by numeric id on first start — is you. What it writes to this account is an
order when it opens with a command ("напиши…", "удали…", "поставь это на аву"), carried out without asking back;
everything else is ordinary conversation. It can also teach:

| It writes | Effect |
|---|---|
| `запомни: …`, `если … отвечай …`, `никогда не …` | a rule that goes into every reply |
| `правила` / `забудь правило 3` | list / remove rules |
| a voice message + `сохрани как смех` | a clip; later just `смех` sends it |
| a photo + `на аву` | that photo becomes the profile photo |

### Dashboard

http://127.0.0.1:8000/admin while backend and userbot run.

- **About to send** — every draft before it goes out: edit, Send now, Cancel. *Approve before sending* holds all
  of them. A draft you correct is remembered as an example.
- **Tell the account what to do** — the order box, with Yes / No.
- **Settings** — every behaviour above as a switch; they apply at once and survive restarts.
- **Chats, Groups, People** — mode per chat, Answer now, a box to send your own text; closeness per person.
- **Decision log** — Messages (who wrote / what was sent), Everything (why), Problems.
- If it cannot connect, it says which part is broken.

From a phone: deploy `dashboard/` as a static site and reach the backend through a tunnel
(`dashboard/README.md`). From outside, the backend serves only `/admin/*` and only with `ADMIN_TOKEN`; the
dashboard can send messages from your account, so treat the token like a password.

### Reports

A morning report (`USERBOT_REPORT_TIME`) about yesterday — chats, replies, what was left to you, what it rewrote
or caught, what the models cost — and an evening digest (`USERBOT_SUMMARY_TIME`), both in Saved Messages.

## Teaching it your style

From Telegram Desktop exports (Chat → ⋮ → Export chat history → HTML):

```bash
.venv/bin/python -m userbot.import_export chat-histories "YourName"                       # general style
.venv/bin/python -m userbot.import_contact "chat-histories/ChatExport_X" "YourName" their_username   # one person
.venv/bin/python -m userbot.get_uz_dictionary                                              # Uzbek word list (optional)
```

A person with a style file is answered only the way your real chat with them shows. Someone without a
@username: use `_` + their name as it appears in your Telegram (`_папа`). Only your own messages are learned
from; links, numbers and slurs are skipped. Everything lands in `userbot/style/` and is picked up without a restart.

## Private data

None of this is in git: `.env`, `userbot/account.session`, `userbot/state.json`, `userbot/facts.md`,
`userbot/lessons.json`, `userbot/memory/`, `userbot/style/`, `userbot/clips.json`, the day log, `chat-histories/`.
`sh scripts/backup.sh` makes an encrypted copy of all of it except the session (nightly once the services are
installed; `backup.sh passphrase` shows the key — keep it somewhere else too).

⚠️ `account.session` is full access to your account: never share or commit it. Telegram may restrict accounts
that look automated; keep volumes low.

## Tests

```bash
.venv/bin/python -m unittest discover tests      # the rules: seconds, no model, no Telegram
```

Conversations, orders, groups and the dashboard are tested against the real code with a fake Telegram — nothing
is sent to anyone. See `tests/README.md`.

## Layout

| | |
|---|---|
| `userbot/main.py` | start-up, Telegram event handlers, the daily loops |
| `userbot/replies.py` · `groups.py` | private chats · group chats |
| `userbot/drafting.py` · `wording.py` · `judge.py` | the prompt and model call · rules about the text · what must not be said |
| `userbot/commands.py` · `pilot.py` · `quick.py` | `.ai` commands and dashboard actions · orders · orders by rule |
| `userbot/people.py` · `memory.py` · `lessons.py` | who is who · facts and notes · what you taught it |
| `userbot/lookup.py` · `voice.py` · `media.py` · `rhythm.py` | web lookups · transcription · stickers, GIFs, clips · timing |
| `userbot/simulate.py` · `simscore.py` | running and scoring conversations without Telegram |
| `backend/` | models (`llm.py`, `config.py`), dashboard relay (`admin.py`, `admin.html`) |
| `scripts/` · `deploy/` · `tests/` | services and backups · server setup · tests |
