from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from google_tasks_mcp import tasks
from google_tasks_mcp.errors import GoogleTasksApiError


def test_date_to_rfc3339_from_date_string():
    assert tasks.date_to_rfc3339("2026-05-05") == "2026-05-05T00:00:00.000Z"


def test_date_to_rfc3339_from_date_object():
    assert tasks.date_to_rfc3339(date(2026, 5, 5)) == "2026-05-05T00:00:00.000Z"


def test_date_to_rfc3339_from_datetime():
    value = datetime(2026, 5, 5, 10, 30, tzinfo=timezone.utc)
    assert tasks.date_to_rfc3339(value) == "2026-05-05T10:30:00.000Z"


def test_date_to_rfc3339_rejects_bad_date():
    with pytest.raises(GoogleTasksApiError):
        tasks.date_to_rfc3339("05/05/2026")


def test_resolve_tasklist_delegates_to_resolver(monkeypatch, configured_env):
    calls = []
    monkeypatch.setattr(tasks.resolver, "resolve_tasklist", lambda value=None: calls.append(value) or "abc")

    assert tasks.resolve_tasklist("inbox") == "abc"
    assert calls == ["inbox"]


def test_resolve_tasklist_uses_first_when_no_default(monkeypatch, configured_env):
    monkeypatch.setattr(tasks.resolver, "resolve_tasklist", lambda value=None: "first")

    assert tasks.resolve_tasklist() == "first"
