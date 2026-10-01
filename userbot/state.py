"""Persistent userbot switches: which chats are enabled, and a global pause."""
import json
import time

from .config import STATE_PATH


class State:
    def __init__(self):
        data = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
        self.enabled: set[int] = set(data.get("enabled", []))
        self.disabled: set[int] = set(data.get("disabled", []))
        self.paused: bool = data.get("paused", False)
        self.paused_until: float = data.get("paused_until", 0)  # temporary pause (unix time)
        # message ids the userbot sent, per chat — so style learning never mistakes them for yours
        self.bot_sent: dict[str, list[int]] = data.get("bot_sent", {})
        self.bio_history: list[str] = data.get("bio_history", [])
        self.last_bio_at: float = data.get("last_bio_at", 0)

    def save(self):
        STATE_PATH.write_text(json.dumps({
            "enabled": sorted(self.enabled), "disabled": sorted(self.disabled), "paused": self.paused,
            "paused_until": self.paused_until, "bot_sent": self.bot_sent,
            "bio_history": self.bio_history, "last_bio_at": self.last_bio_at,
        }, indent=2, ensure_ascii=False))

    def record_bio(self, bio: str):
        self.bio_history = (self.bio_history + [bio])[-20:]
        self.last_bio_at = time.time()
        self.save()

    def enable(self, chat_id: int):
        self.enabled.add(chat_id)
        self.disabled.discard(chat_id)
        self.save()

    def disable(self, chat_id: int):
        self.disabled.add(chat_id)
        self.enabled.discard(chat_id)
        self.save()

    def record_sent(self, chat_id: int, message_id: int):
        self.bot_sent.setdefault(str(chat_id), []).append(message_id)
        self.save()

    def sent_by_bot(self, chat_id: int, message_id: int) -> bool:
        return message_id in self.bot_sent.get(str(chat_id), [])

    def set_paused(self, paused: bool, seconds: float = 0):
        """pause indefinitely, pause for `seconds`, or resume (paused=False)."""
        self.paused = paused and not seconds
        self.paused_until = time.time() + seconds if paused and seconds else 0
        self.save()

    def is_paused(self) -> bool:
        return self.paused or time.time() < self.paused_until

    def is_active(self, chat_id: int, mode: str) -> bool:
        if self.is_paused() or chat_id in self.disabled:
            return False
        return mode == "all" or chat_id in self.enabled
