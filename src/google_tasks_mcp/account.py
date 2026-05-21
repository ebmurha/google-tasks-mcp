"""Request-local Google account selection."""

from __future__ import annotations

from contextvars import ContextVar, Token


DEFAULT_ACCOUNT_ID = "default"

_current_account_id: ContextVar[str] = ContextVar(
    "google_tasks_mcp_account_id",
    default=DEFAULT_ACCOUNT_ID,
)


def get_current_account_id() -> str:
    return _current_account_id.get()


def set_current_account_id(account_id: str) -> Token[str]:
    clean = account_id.strip() or DEFAULT_ACCOUNT_ID
    return _current_account_id.set(clean)


def reset_current_account_id(token: Token[str]) -> None:
    _current_account_id.reset(token)
