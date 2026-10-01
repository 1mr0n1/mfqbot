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
STYLE_PAIRS = 8             # real "they wrote → you answered" exchanges shown per reply
CONTACT_PAIRS = 14          # same, for a person with their own style file (style/contacts/<username>.json)
CLIPS_PATH = HERE / "clips.json"  # tag -> your voice/round-video clip in Saved Messages
MEDIA_ENABLED = os.environ.get("USERBOT_MEDIA", "true").lower() in ("1", "true", "yes")

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

# --- Timing (seconds) ---
DEBOUNCE = (0, 0)              # extra wait before reading (the draft hold below already absorbs message bursts)
READ_DELAY = (0, 0)            # "picking up the phone" before the chat is marked read
THINK_DELAY = (0, 0)           # pause between reading and writing
DRAFT_HOLD = (2, 3)            # the finished draft waits this long (visible + cancellable on /admin) before typing
TYPING_CHARS_PER_SEC = (5, 9)  # typing speed while the "typing…" indicator is shown
TYPING_LIMITS = (1.5, 20)      # min/max typing time per message
BETWEEN_MESSAGES = (0.8, 3)    # pause between split messages
MAX_PARTS = 3                  # max messages a reply is split into
GENERATE_RETRIES = 3           # if every model fails, try again later this many times
RETRY_DELAY = (45, 90)         # wait between those attempts

CONTEXT_MESSAGES = 30          # how much chat history the model sees
if os.environ.get("USERBOT_HUMAN_PACING", "true").lower() not in ("1", "true", "yes"):
    # Instant mode: no draft hold and no typing simulation.
    DRAFT_HOLD = TYPING_LIMITS = (0, 0)
    BETWEEN_MESSAGES = (0.3, 0.6)

OWNER_ACTIVE_WINDOW = 120      # don't auto-reply if you personally wrote in the chat this recently
VISION = os.environ.get("USERBOT_VISION", "true").lower() in ("1", "true", "yes")
VISION_MODELS = ["omni", "qwen", "local"]  # models that can look at a picture (used to recognize salam stickers)
MAX_IMAGES = 2                 # newest photos from the other person passed to the model per reply
UNREAD_MAX_AGE = 24 * 3600     # unread DMs older than this are left alone
UNREAD_SCAN_DIALOGS = 150      # how many recent chats to scan for unread DMs
UNREAD_RESCAN_SECONDS = 45     # re-check the 30 most recent chats for unread DMs this often
IGNORE_OLDER_THAN = 300        # ignore messages older than this (e.g. backlog after restart)
