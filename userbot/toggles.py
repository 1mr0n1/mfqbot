"""Switches you can flip from the dashboard while the bot runs. Each one maps to a flag in config.py;
what you set is kept in state.json and re-applied at every start (it overrides the value from .env)."""
from . import config as C

# key -> (config attribute, label, what it does, group)
TOGGLES = {
    "sleep":    ("SLEEP_ON",        "Night sleep",          "Quiet during the sleep window; answers after waking up", "Timing"),
    "school":   ("SCHOOL_ON",       "School mode",          "On weekdays in school hours, replies come 3–20 min late", "Timing"),
    "slow":     ("SLOW_ON",         "Occasional slow reply", "Now and then a message waits a few minutes", "Timing"),
    "pacing":   ("PACING",          "Human typing",         "Reading/thinking pause and a typing indicator; off = instant", "Timing"),
    "typos":    ("TYPOS_ON",        "Typos",                "Rarely sends a typo, then fixes it", "Style"),
    "media":    ("MEDIA_ENABLED",   "Stickers & GIFs",      "May send stickers, GIFs and your recorded clips", "Style"),
    "talk":     ("KEEP_TALKING",    "Keep the chat going",  "Dry answers get a question about their day or a new topic (2 tries)", "Style"),
    "nudge":    ("NUDGE_ON",        "Ask again when ignored", "A question left without an answer gets a \"?\", then is asked again in other words", "Style"),
    "split":    ("SPLIT_ON",        "Split messages",       "A reply with two thoughts is sent as two short messages", "Style"),
    "spamback": ("SPAM_BACK",       "Spam back",            "5+ messages in a few seconds get the same flood sent back", "Style"),
    "react":    ("SMART_SKIP",      "Reactions",            "👍 / ❤ instead of text on closing messages; fillers get no reply", "Style"),
    "handoff":  ("HANDOFF",         "Hand-off",             "Requests for money, codes, emergencies, teachers → left to you", "Safety"),
    "emotional": ("HANDOFF_JUDGE",  "Hand-off: serious messages", "Also leaves to you someone in real distress or with bad news", "Safety"),
    "grounded": ("GROUNDED",        "No made-up facts",     "A reply that invents where you are, what you ordered, when you arrive… is rewritten", "Safety"),
    "review":   ("REVIEW",          "Second look",          "Checks each draft (language, nonsense, repeats) before sending", "Safety"),
    "vision":   ("VISION",          "See photos",           "Passes incoming photos to a model that can see them", "Abilities"),
    "voice":    ("VOICE_TRANSCRIBE", "Hear voice messages", "Transcribes voice and round-video messages on this Mac", "Abilities"),
    "remember": ("REMEMBER",        "Notes about people",   "Keeps facts people state about themselves", "Abilities"),
    "groups":   ("GROUPS",          "Group mentions",       "In groups, answers when you are mentioned or replied to", "Abilities"),
    "pfp":      ("PFP_FROM_CHATS",  "Profile photo on request", "Sets a photo someone sends and asks you to use", "Abilities"),
    "autobio":  ("AUTO_BIO",        "Auto-bio",             "Rewrites your bio every 6–14 hours", "Abilities"),
}


def apply(settings: dict[str, bool]):
    """Push saved switch positions into the running config."""
    for key, on in settings.items():
        if key in TOGGLES:
            setattr(C, TOGGLES[key][0], bool(on))


def snapshot() -> list[dict]:
    return [{"key": key, "label": label, "hint": hint, "group": group, "on": bool(getattr(C, attr))}
            for key, (attr, label, hint, group) in TOGGLES.items()]
