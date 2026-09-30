"""Persistent userbot switches: which chats are enabled, and a global pause."""
import json

from .config import STATE_PATH


class State:
    def __init__(self):
        data = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
        self.enabled: set[int] = set(data.get("enabled", []))
        self.disabled: set[int] = set(data.get("disabled", []))
        self.paused: bool = data.get("paused", False)
        # message ids the userbot sent, per chat — so style learning never mistakes them for yours
        self.bot_sent: dict[str, list[int]] = data.get("bot_sent", {})

    def save(self):
        STATE_PATH.write_text(json.dumps({
            "enabled": sorted(self.enabled), "disabled": sorted(self.disabled), "paused": self.paused,
            "bot_sent": self.bot_sent,
        }, indent=2))

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

    def set_paused(self, paused: bool):
        self.paused = paused
        self.save()

    def is_active(self, chat_id: int, mode: str) -> bool:
        if self.paused or chat_id in self.disabled:
            return False
        return mode == "all" or chat_id in self.enabled
