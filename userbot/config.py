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
CLIPS_PATH = HERE / "clips.json"  # tag -> your voice/round-video clip in Saved Messages
MEDIA_ENABLED = os.environ.get("USERBOT_MEDIA", "true").lower() in ("1", "true", "yes")

# Auto-bio: the account updates its own bio now and then (see autoprofile.py)
AUTO_BIO = os.environ.get("USERBOT_AUTO_BIO", "true").lower() in ("1", "true", "yes")
BIO_INTERVAL_HOURS = (6, 14)
BIO_QUIET_HOURS = (1, 8)       # no bio changes between 01:00 and 08:00
BIO_MAX_CHARS = 70             # Telegram limit without Premium

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
MODELS = [m.strip() for m in os.environ.get("USERBOT_MODELS", "nemotron,qwen").split(",") if m.strip()]
REPLY_MODE = os.environ.get("USERBOT_REPLY_MODE", "allowlist")  # "allowlist" or "all"

# --- Human-like timing (seconds) ---
DEBOUNCE = (6, 12)             # wait for the other person to finish a burst of messages
READ_DELAY = (3, 25)           # "picking up the phone" before the chat is marked read
THINK_DELAY = (1, 4)           # pause between reading and starting to type
TYPING_CHARS_PER_SEC = (5, 9)  # typing speed
TYPING_LIMITS = (1.5, 20)      # min/max typing time per message
BETWEEN_MESSAGES = (0.8, 3)    # pause between split messages
MAX_PARTS = 3                  # max messages a reply is split into
GENERATE_RETRIES = 3           # if every model fails, try again later this many times
RETRY_DELAY = (45, 90)         # wait between those attempts

CONTEXT_MESSAGES = 30          # how much chat history the model sees
if os.environ.get("USERBOT_HUMAN_PACING", "true").lower() not in ("1", "true", "yes"):
    # Instant mode: reply as soon as the model answers (typing indicator only while generating).
    DEBOUNCE = READ_DELAY = THINK_DELAY = TYPING_LIMITS = (0, 0)
    BETWEEN_MESSAGES = (0.3, 0.6)

OWNER_ACTIVE_WINDOW = 120      # don't auto-reply if you personally wrote in the chat this recently
VISION = os.environ.get("USERBOT_VISION", "true").lower() in ("1", "true", "yes")
MAX_IMAGES = 2                 # newest photos from the other person passed to the model per reply
UNREAD_MAX_AGE = 24 * 3600     # unread DMs older than this are left alone
UNREAD_SCAN_DIALOGS = 150      # how many recent chats to scan for unread DMs
IGNORE_OLDER_THAN = 300        # ignore messages older than this (e.g. backlog after restart)
