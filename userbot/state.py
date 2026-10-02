"""Persistent userbot switches: which chats are enabled, and a global pause."""
import json
import time

from .config import STATE_PATH


class State:
    def __init__(self):
        data = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
        self.enabled: set[int] = set(data.get("enabled", []))
        self.disabled: set[int] = set(data.get("disabled", []))
        self.manual: set[int] = set(data.get("manual", []))  # chats that are always left to you (with a note)
        self.paused: bool = data.get("paused", False)
        self.awake_until: float = data.get("awake_until", 0)  # ".ai awake": don't sleep before this time
        self.settings: dict[str, bool] = data.get("settings", {})  # dashboard switches (see toggles.py)
        self.approve: bool = data.get("approve", False)  # hold every draft until it's approved on the dashboard
        self.paused_until: float = data.get("paused_until", 0)  # temporary pause (unix time)
        # message ids the userbot sent, per chat — so style learning never mistakes them for yours
        self.bot_sent: dict[str, list[int]] = data.get("bot_sent", {})
        # sticker document id -> is it an "Assalomu alaykum" sticker (learned by vision or taught with .ai salam)
        self.salam_stickers: dict[str, bool] = data.get("salam_stickers", {})
        self.pfp_changes: list[float] = data.get("pfp_changes", [])  # when chat-requested photo changes happened
        # chat id -> newest incoming message id already dealt with / time until which the chat is left to the owner
        self.handled: dict[str, int] = data.get("handled", {})
        self.handoff: dict[str, float] = data.get("handoff", {})
        # your own other accounts, as given in USERBOT_COMMANDERS -> the numeric id each one was pinned to
        self.commanders: dict[str, int] = data.get("commanders", {})
        # chats the account opened by itself: {"date": "YYYY-MM-DD", "count": n, "last": {chat id: unix time}}
        self.initiated: dict = data.get("initiated", {"date": "", "count": 0, "last": {}})
        self.spent: float = data.get("spent", -1)  # OpenRouter usage in $ at the last morning report
        self.bio_history: list[str] = data.get("bio_history", [])
        self.last_bio_at: float = data.get("last_bio_at", 0)

    def save(self):
        STATE_PATH.write_text(json.dumps({
            "enabled": sorted(self.enabled), "disabled": sorted(self.disabled), "paused": self.paused,
            "manual": sorted(self.manual), "approve": self.approve, "awake_until": self.awake_until,
            "settings": self.settings,
            "paused_until": self.paused_until, "bot_sent": self.bot_sent,
            "bio_history": self.bio_history, "last_bio_at": self.last_bio_at,
            "salam_stickers": self.salam_stickers, "pfp_changes": self.pfp_changes,
            "handled": self.handled, "handoff": self.handoff, "commanders": self.commanders, "initiated": self.initiated, "spent": self.spent,
        }, indent=2, ensure_ascii=False))

    def mark_handled(self, chat_id: int, message_id: int):
        if self.handled.get(str(chat_id)) != message_id:
            self.handled[str(chat_id)] = message_id
            self.save()

    def is_handled(self, chat_id: int, message_id: int) -> bool:
        return self.handled.get(str(chat_id)) == message_id

    def hand_off(self, chat_id: int, seconds: float):
        self.handoff = {k: v for k, v in self.handoff.items() if v > time.time()}
        self.handoff[str(chat_id)] = time.time() + seconds
        self.save()

    def clear_handoff(self, chat_id: int):
        if self.handoff.pop(str(chat_id), None) is not None:
            self.save()

    def handed_off(self, chat_id: int) -> bool:
        return time.time() < self.handoff.get(str(chat_id), 0)

    def pfp_allowed(self) -> bool:
        from .config import PFP_MAX_PER_DAY, PFP_MIN_GAP
        recent = [t for t in self.pfp_changes if time.time() - t < 86400]
        return len(recent) < PFP_MAX_PER_DAY and (not recent or time.time() - max(recent) >= PFP_MIN_GAP)

    def record_pfp(self):
        self.pfp_changes = [t for t in self.pfp_changes if time.time() - t < 86400] + [time.time()]
        self.save()

    def remember_salam_sticker(self, doc_id: str, is_salam: bool):
        self.salam_stickers[doc_id] = is_salam
        self.save()

    def record_bio(self, bio: str):
        self.bio_history = (self.bio_history + [bio])[-20:]
        self.last_bio_at = time.time()
        self.save()

    def enable(self, chat_id: int):
        self.enabled.add(chat_id)
        self.disabled.discard(chat_id)
        self.manual.discard(chat_id)
        self.save()

    def set_manual(self, chat_id: int):
        self.manual.add(chat_id)
        self.disabled.discard(chat_id)
        self.save()

    def set_approve(self, on: bool):
        self.approve = on
        self.save()

    def mode_of(self, chat_id: int) -> str:
        return "off" if chat_id in self.disabled else "manual" if chat_id in self.manual else "auto"

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
