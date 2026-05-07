from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from google_tasks_mcp import tasks
from google_tasks_mcp.errors import AmbiguousTitleError, GoogleTasksApiError, NotFoundError


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


def test_resolve_task_by_title_matches_active_task(monkeypatch, configured_env):
    monkeypatch.setattr(tasks, "get_tasklist_title", lambda tasklist_id: "Default")
    monkeypatch.setattr(
        tasks,
        "list_tasks",
        lambda tasklist_id, **kwargs: [
            {"id": "task-1", "title": "Write notes", "status": "needsAction"},
            {"id": "task-2", "title": "Write notes", "status": "completed"},
        ],
    )

    assert tasks.resolve_task_by_title("default", " write notes ") == "task-1"


def test_resolve_task_by_title_can_include_completed(monkeypatch, configured_env):
    monkeypatch.setattr(tasks, "get_tasklist_title", lambda tasklist_id: "Default")
    monkeypatch.setattr(
        tasks,
        "list_tasks",
        lambda tasklist_id, **kwargs: [{"id": "task-1", "title": "Done", "status": "completed"}],
    )

    assert tasks.resolve_task_by_title("default", "Done", include_completed=True) == "task-1"


def test_resolve_task_by_title_not_found(monkeypatch, configured_env):
    monkeypatch.setattr(tasks, "get_tasklist_title", lambda tasklist_id: "Default")
    monkeypatch.setattr(tasks, "list_tasks", lambda tasklist_id, **kwargs: [])

    with pytest.raises(NotFoundError) as exc_info:
        tasks.resolve_task_by_title("default", "Missing")

    assert exc_info.value.details["searched_tasklist"] == "Default"
    assert exc_info.value.details["query"] == "Missing"


def test_resolve_task_by_title_ambiguous(monkeypatch, configured_env):
    monkeypatch.setattr(tasks, "get_tasklist_title", lambda tasklist_id: "Default")
    monkeypatch.setattr(
        tasks,
        "list_tasks",
        lambda tasklist_id, **kwargs: [
            {"id": "one", "title": "Same", "status": "needsAction"},
            {"id": "two", "title": "Same", "status": "needsAction", "due": "2026-05-08T00:00:00.000Z"},
        ],
    )

    with pytest.raises(AmbiguousTitleError) as exc_info:
        tasks.resolve_task_by_title("default", "Same")

    assert [candidate["id"] for candidate in exc_info.value.details["candidates"]] == ["one", "two"]
    assert exc_info.value.details["candidates"][1]["due"] == "2026-05-08"
