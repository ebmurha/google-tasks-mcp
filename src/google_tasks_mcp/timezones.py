"""Timezone resolution helpers."""

from __future__ import annotations

import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from .errors import InvalidInputError


_DEFAULT_TZ = (os.getenv("GOOGLE_TASKS_MCP_DEFAULT_TZ") or "").strip() or None
_IANA_TIMEZONES = available_timezones()


def _validate(name: str) -> ZoneInfo:
    if name not in _IANA_TIMEZONES:
        raise InvalidInputError(f"Invalid timezone: {name}", timezone=name)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise InvalidInputError(f"Invalid timezone: {name}", timezone=name) from exc


def resolve_timezone(timezone: str | None = None) -> ZoneInfo | None:
    """Resolve explicit timezone, env default, or UTC pass-through."""

    requested = (timezone or "").strip()
    if requested:
        return _validate(requested)
    if _DEFAULT_TZ:
        return _validate(_DEFAULT_TZ)
    return None
