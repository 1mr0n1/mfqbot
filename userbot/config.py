import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

HERE = Path(__file__).parent

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_PATH = str(HERE / "account")  # Telethon appends .session — treat this file like a password
STATE_PATH = HERE / "state.json"
PERSONA_PATH = HERE / "persona.md"
STYLE_DIR = HERE / "style"  # written by learn_style.py (your personal messages — git-ignored)
STYLE_EXAMPLES = 40         # of your real messages shown to the model per reply
STYLE_PAIRS = 5             # random real "they wrote → you answered" exchanges shown per reply (general manner)
CONTACT_PAIRS = 6           # same, for a person with their own style file (style/contacts/<username>.json)
RECALL_PAIRS = int(os.environ.get("USERBOT_RECALL_PAIRS", "8"))            # plus the exchanges most similar to the incoming message (see recall.py)
CLIPS_PATH = HERE / "clips.json"  # tag -> your voice/round-video clip in Saved Messages
MEDIA_ENABLED = os.environ.get("USERBOT_MEDIA", "true").lower() in ("1", "true", "yes")

# A second look at every draft before sending (see judge.review)
REVIEW = os.environ.get("USERBOT_REVIEW", "true").lower() in ("1", "true", "yes")

# Daily rhythm and presence (see rhythm.py) — local time of this machine
RHYTHM = os.environ.get("USERBOT_RHYTHM", "true").lower() in ("1", "true", "yes")
# Individual switches (flipped from the dashboard, see toggles.py)
SLEEP_ON = True     # night sleep
SCHOOL_ON = True    # slower replies during BUSY_WINDOW on weekdays
SLOW_ON = True      # the occasional slow reply
PACING = True       # reading/thinking pause + typing indicator
TYPOS_ON = True     # rare typo that gets fixed
SLEEP_WINDOW = os.environ.get("USERBOT_SLEEP", "00:00-07:00")   # asleep: nothing is read or answered
BUSY_WINDOW = os.environ.get("USERBOT_BUSY", "08:30-15:30")     # weekdays (school): answers come late
WAKE_JITTER_MIN = (5, 30)        # minutes after waking before the phone is picked up
BUSY_DELAY = (180, 1200)         # seconds until a message is looked at while busy
SLOW_CHANCE = float(os.environ.get("USERBOT_SLOW_CHANCE", "0.06"))  # chance that a message waits a while anyway
SLOW_DELAY = (60, 240)
ACTIVE_CHAT_SECONDS = 240        # after a reply the chat counts as an ongoing conversation: no delays
ONLINE_LINGER = (15, 60)         # seconds to stay "online" after doing something

# Small human touches (see quirks.py)
TEMPERATURE = float(os.environ.get("USERBOT_TEMPERATURE", "0.5"))  # lower = steadier wording, fewer made-up words
EXTRA_REACTION_CHANCE = float(os.environ.get("USERBOT_REACTION_CHANCE", "0.3"))  # also react to a message you answer
EMOJI_KEEP_CHANCE = float(os.environ.get("USERBOT_EMOJI_CHANCE", "0.04"))  # share of replies allowed to keep ONE emoji
TYPO_CHANCE = float(os.environ.get("USERBOT_TYPO_CHANCE", "0.06"))  # share of messages sent with a typo, then fixed
QUOTE_IF_OLDER_THAN = 3600       # answering something this old (seconds): quote it

# Evening summary in Saved Messages (see daylog.py)
DAYLOG_PATH = HERE / "daylog.json"
SUMMARY_TIME = os.environ.get("USERBOT_SUMMARY_TIME", "21:30")  # empty = no automatic summary

# Group chats: answer only when mentioned or replied to
GROUPS = os.environ.get("USERBOT_GROUPS", "true").lower() in ("1", "true", "yes")
GROUP_CONTEXT = 15               # how many recent group messages the model sees

# Voice messages are transcribed locally with Whisper (see voice.py)
VOICE_TRANSCRIBE = os.environ.get("USERBOT_VOICE", "true").lower() in ("1", "true", "yes")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")
VOICE_MAX_SECONDS = 180

# What the account knows (see memory.py) and when it stays out (see judge.py)
FACTS_PATH = HERE / "facts.md"   # you write this; git-ignored
MEMORY_DIR = HERE / "memory"     # automatic notes per person; git-ignored
TODAY_PATH = HERE / "today.json" # what you told it about today (.ai today …); git-ignored
REMEMBER = os.environ.get("USERBOT_REMEMBER", "true").lower() in ("1", "true", "yes")
SMART_SKIP = os.environ.get("USERBOT_SMART_SKIP", "true").lower() in ("1", "true", "yes")  # react / stay silent
HANDOFF = os.environ.get("USERBOT_HANDOFF", "true").lower() in ("1", "true", "yes")        # sensitive -> you
HANDOFF_JUDGE = True             # also hand off messages a model judges serious (distress, bad news); off = keywords only
HANDOFF_HOLD = 30 * 60           # after handing a chat to you, stay out of it this long (or until you write there)

# Profile photo on request: someone sends a photo and asks you to use it as your profile picture (see pfp.py)
PFP_FROM_CHATS = os.environ.get("USERBOT_PFP_FROM_CHATS", "true").lower() in ("1", "true", "yes")
PFP_MAX_PER_DAY = 3
PFP_MIN_GAP = 600              # seconds between two changes

# Auto-bio: the account updates its own bio now and then (see autoprofile.py)
AUTO_BIO = os.environ.get("USERBOT_AUTO_BIO", "true").lower() in ("1", "true", "yes")
BIO_INTERVAL_HOURS = (6, 14)
BIO_QUIET_HOURS = (1, 8)       # no bio changes between 01:00 and 08:00
BIO_MAX_CHARS = 70             # Telegram limit without Premium

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
MODELS = [m.strip() for m in os.environ.get("USERBOT_MODELS", "nemotron,qwen").split(",") if m.strip()]
REPLY_MODE = os.environ.get("USERBOT_REPLY_MODE", "allowlist")  # "allowlist" or "all"
_models = lambda name, default: [m.strip() for m in os.environ.get(name, default).split(",") if m.strip()]
# Small yes/no jobs (hand-off check, note-taking) don't need the big model: the local one is as accurate, much
# faster, and keeps the rate-limited model free for writing replies.
JUDGE_MODELS = _models("USERBOT_JUDGE_MODELS", "local,nemotron")
PHOTO_MODELS = _models("USERBOT_PHOTO_MODELS", "omni,local,qwen,nemotron")  # who looks at pictures, in order
HEDGE_AFTER = float(os.environ.get("USERBOT_HEDGE_AFTER", "2.5"))  # s before the 2nd model starts alongside the 1st

# --- Timing (seconds) ---
DEBOUNCE = (0, 0)              # extra wait before reading (the draft hold below already absorbs message bursts)
READ_DELAY = (0, 0)            # "picking up the phone" before the chat is marked read
THINK_DELAY = (0, 0)           # pause between reading and writing
DASHBOARD_HISTORY = 40         # messages per chat shown in the dashboard's dialog view
APPROVE_TIMEOUT = 15 * 60      # in "approve before sending" mode an unapproved draft is dropped after this long
MIN_HOLD = 1.0                 # a draft is always visible (and cancellable on /admin) at least this long
DRAFT_HOLD = (2, 3)            # legacy fixed hold; real timing now comes from rhythm.reading/thinking_seconds
TYPING_CHARS_PER_SEC = (5, 9)  # typing speed while the "typing…" indicator is shown
TYPING_LIMITS = (1.5, 20)      # min/max typing time per message
BETWEEN_MESSAGES = (0.8, 3)    # pause between split messages
MAX_PARTS = 2                  # max messages a reply is split into (anything beyond is dropped)
GENERATE_RETRIES = 3           # if every model fails, try again later this many times
RETRY_DELAY = (45, 90)         # wait between those attempts

CONTEXT_MESSAGES = 30          # how much chat history the model sees
if os.environ.get("USERBOT_HUMAN_PACING", "true").lower() not in ("1", "true", "yes"):
    # Instant mode: no draft hold and no typing simulation.
    DRAFT_HOLD = TYPING_LIMITS = (0, 0)
    BETWEEN_MESSAGES = (0.3, 0.6)

# After you type in a chat yourself, wait this long before the bot answers there again. 0 = never wait:
# the bot answers whenever the other person writes, even if you were just in that chat.
OWNER_ACTIVE_WINDOW = int(os.environ.get("USERBOT_OWNER_WINDOW", "0"))
VISION = os.environ.get("USERBOT_VISION", "true").lower() in ("1", "true", "yes")
VISION_MODELS = ["omni", "qwen", "local"]  # models that can look at a picture (used to recognize salam stickers)
MAX_IMAGES = 2                 # newest photos from the other person passed to the model per reply
UNREAD_MAX_AGE = 24 * 3600     # unread DMs older than this are left alone
UNREAD_SCAN_DIALOGS = 150      # how many recent chats to scan for unread DMs
RECENT_UNANSWERED = 10 * 3600  # read-but-unanswered messages this recent still get an answer — opening a chat
                               # yourself must not cancel the reply (covers a whole night of sleep)
UNREAD_RESCAN_SECONDS = 45     # re-check the 30 most recent chats for unread DMs this often

# Someone floods the chat -> the same flood goes back at them
SPAM_BACK = True
SPAM_TRIGGER = 5               # this many messages from one person...
SPAM_WINDOW = 12               # ...within this many seconds counts as spam
SPAM_MAX = 15                  # never more than this many messages in one go
SPAM_GAP = (0.35, 0.9)         # seconds between them (faster gets the account rate-limited by Telegram)
SPAM_COOLDOWN = 90             # after spamming back, answer normally for this long
SPAM_ECHO_CHARS = 40           # their short messages are sent back as they are; longer ones become "?"
IGNORE_OLDER_THAN = 300        # ignore messages older than this (e.g. backlog after restart)
