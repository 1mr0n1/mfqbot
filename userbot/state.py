"""Persistent userbot switches: which chats are enabled, and a global pause."""
import json

from .config import STATE_PATH


class State:
    def __init__(self):
        data = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
        self.enabled: set[int] = set(data.get("enabled", []))
        self.disabled: set[int] = set(data.get("disabled", []))
        self.paused: bool = data.get("paused", False)

    def save(self):
        STATE_PATH.write_text(json.dumps({
            "enabled": sorted(self.enabled), "disabled": sorted(self.disabled), "paused": self.paused,
        }, indent=2))

    def enable(self, chat_id: int):
        self.enabled.add(chat_id)
        self.disabled.discard(chat_id)
        self.save()

    def disable(self, chat_id: int):
        self.disabled.add(chat_id)
        self.enabled.discard(chat_id)
        self.save()

    def set_paused(self, paused: bool):
        self.paused = paused
        self.save()

    def is_active(self, chat_id: int, mode: str) -> bool:
        if self.paused or chat_id in self.disabled:
            return False
        return mode == "all" or chat_id in self.enabled
