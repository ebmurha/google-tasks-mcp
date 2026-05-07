from __future__ import annotations

import importlib

import pytest

from google_tasks_mcp import server, timezones
from google_tasks_mcp.errors import InvalidInputError


def test_resolve_timezone_explicit():
    tz = timezones.resolve_timezone("Africa/Nairobi")

    assert tz is not None
    assert tz.key == "Africa/Nairobi"


def test_resolve_timezone_env_default(monkeypatch):
    monkeypatch.setenv("GOOGLE_TASKS_MCP_DEFAULT_TZ", "America/Los_Angeles")
    reloaded = importlib.reload(timezones)

    tz = reloaded.resolve_timezone()

    assert tz is not None
    assert tz.key == "America/Los_Angeles"


def test_resolve_timezone_without_default_is_pass_through(monkeypatch):
    monkeypatch.delenv("GOOGLE_TASKS_MCP_DEFAULT_TZ", raising=False)
    reloaded = importlib.reload(timezones)

    assert reloaded.resolve_timezone() is None


def test_bad_timezone_raises_invalid_input():
    with pytest.raises(InvalidInputError) as exc_info:
        timezones.resolve_timezone("Not/AZone")

    assert exc_info.value.code == 400
    assert "Not/AZone" in exc_info.value.message


def test_bad_timezone_error_payload_names_value():
    payload = server._error_payload(InvalidInputError("Invalid timezone: Not/AZone", timezone="Not/AZone"))

    assert payload == {
        "error": "INVALID_INPUT",
        "code": 400,
        "message": "Invalid timezone: Not/AZone",
        "timezone": "Not/AZone",
    }
