"""In-memory per-user state. Swap for Redis/Postgres later — keep the same interface."""
from dataclasses import dataclass, field

from .config import DEFAULT_MODEL, MAX_HISTORY_MESSAGES


@dataclass
class UserState:
    model: str = DEFAULT_MODEL
    history: list[dict] = field(default_factory=list)


_users: dict[str, UserState] = {}


def get_user(user_id: str) -> UserState:
    return _users.setdefault(user_id, UserState())


def append_history(user_id: str, role: str, content: str) -> None:
    user = get_user(user_id)
    user.history.append({"role": role, "content": content})
    del user.history[:-MAX_HISTORY_MESSAGES]


def reset_history(user_id: str) -> None:
    get_user(user_id).history.clear()
