from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from google_tasks_mcp import tasks
from google_tasks_mcp.errors import AmbiguousTitleError, GoogleTasksApiError, InvalidInputError, NotFoundError


class _Request:
    def __init__(self, response=None):
        self.response = response

    def execute(self):
        return self.response


class _TasklistsResource:
    def __init__(self):
        self.calls = []

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))
        return _Request({"id": "list-1", "title": kwargs["body"]["title"]})

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return _Request({"id": kwargs["tasklist"], "title": "Inbox"})

    def patch(self, **kwargs):
        self.calls.append(("patch", kwargs))
        return _Request({"id": kwargs["tasklist"], "title": kwargs["body"]["title"]})

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return _Request(None)


class _TasksResource:
    def __init__(self):
        self.calls = []
        self.list_items = None

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        if self.list_items is not None:
            offset = int(kwargs.get("pageToken") or "0")
            max_results = kwargs.get("maxResults", 100)
            page = self.list_items[offset : offset + max_results]
            response = {"items": page}
            if offset + max_results < len(self.list_items):
                response["nextPageToken"] = str(offset + max_results)
            return _Request(response)
        return _Request({"items": [{"id": "task-1"}], "nextPageToken": "next"})

    def clear(self, **kwargs):
        self.calls.append(("clear", kwargs))
        return _Request(None)

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))
        body = kwargs["body"]
        return _Request(
            {
                "id": "new-task",
                "title": body["title"],
                "parent": kwargs.get("parent"),
            }
        )

    def move(self, **kwargs):
        self.calls.append(("move", kwargs))
        return _Request(
            {
                "id": kwargs["task"],
                "parent": kwargs.get("parent"),
                "position": "0002",
            }
        )


class _TasklistService:
    def __init__(self):
        self.resource = _TasklistsResource()
        self.tasks_resource = _TasksResource()

    def tasklists(self):
        return self.resource

    def tasks(self):
        return self.tasks_resource


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


def test_tasklist_crud_wrappers_call_google_methods_and_invalidate(monkeypatch, configured_env):
    service = _TasklistService()
    full_invalidations = []
    deleted_invalidations = []
    monkeypatch.setattr(tasks, "_service", lambda: service)
    monkeypatch.setattr(tasks.resolver, "clear_tasklist_cache", lambda: full_invalidations.append(True))
    monkeypatch.setattr(tasks.resolver, "delete_tasklist_cached", lambda tasklist_id: deleted_invalidations.append(tasklist_id))

    assert tasks.create_tasklist(title=" Inbox ") == {"id": "list-1", "title": "Inbox"}
    assert tasks.get_tasklist("list-1") == {"id": "list-1", "title": "Inbox"}
    assert tasks.update_tasklist("list-1", title=" Work ") == {"id": "list-1", "title": "Work"}
    assert tasks.delete_tasklist("list-1") is None

    assert service.resource.calls == [
        ("insert", {"body": {"title": "Inbox"}}),
        ("get", {"tasklist": "list-1"}),
        ("patch", {"tasklist": "list-1", "body": {"title": "Work"}}),
        ("delete", {"tasklist": "list-1"}),
    ]
    assert len(full_invalidations) == 2
    assert deleted_invalidations == ["list-1"]


def test_tasklist_crud_wrappers_reject_blank_input():
    with pytest.raises(InvalidInputError):
        tasks.create_tasklist(title=" ")
    with pytest.raises(InvalidInputError):
        tasks.update_tasklist("list-1", title=" ")
    with pytest.raises(InvalidInputError):
        tasks.delete_tasklist(" ")


def test_list_tasks_page_passes_supported_filters(monkeypatch, configured_env):
    service = _TasklistService()
    monkeypatch.setattr(tasks, "_service", lambda: service)

    result = tasks.list_tasks_page(
        "list-1",
        show_completed=True,
        show_deleted=True,
        show_hidden=True,
        show_assigned=True,
        due_min="2026-05-01T00:00:00.000Z",
        due_max="2026-05-08T00:00:00.000Z",
        completed_min="2026-05-02T00:00:00.000Z",
        completed_max="2026-05-03T00:00:00.000Z",
        updated_min="2026-05-04T00:00:00.000Z",
        max_results=500,
        page_token="abc",
    )

    assert result["items"] == [{"id": "task-1"}]
    assert service.tasks_resource.calls == [
        (
            "list",
            {
                "tasklist": "list-1",
                "showCompleted": True,
                "showDeleted": True,
                "showHidden": True,
                "showAssigned": True,
                "maxResults": 100,
                "pageToken": "abc",
                "dueMin": "2026-05-01T00:00:00.000Z",
                "dueMax": "2026-05-08T00:00:00.000Z",
                "completedMin": "2026-05-02T00:00:00.000Z",
                "completedMax": "2026-05-03T00:00:00.000Z",
                "updatedMin": "2026-05-04T00:00:00.000Z",
            },
        )
    ]


def test_list_tasks_auto_paginates_to_requested_cap(monkeypatch, configured_env):
    service = _TasklistService()
    service.tasks_resource.list_items = [{"id": f"task-{index:03d}"} for index in range(150)]
    monkeypatch.setattr(tasks, "_service", lambda: service)

    result = tasks.list_tasks("list-1", max_results=150)

    assert len(result) == 150
    assert result[0]["id"] == "task-000"
    assert result[-1]["id"] == "task-149"
    assert service.tasks_resource.calls == [
        ("list", {"tasklist": "list-1", "showCompleted": False, "showDeleted": False, "showHidden": False, "showAssigned": False, "maxResults": 100}),
        ("list", {"tasklist": "list-1", "showCompleted": False, "showDeleted": False, "showHidden": False, "showAssigned": False, "maxResults": 50, "pageToken": "100"}),
    ]


def test_clear_completed_calls_google_clear(monkeypatch, configured_env):
    service = _TasklistService()
    monkeypatch.setattr(tasks, "_service", lambda: service)

    assert tasks.clear_completed("list-1") is None
    assert service.tasks_resource.calls == [("clear", {"tasklist": "list-1"})]


def test_insert_task_passes_parent_and_previous(monkeypatch, configured_env):
    service = _TasklistService()
    monkeypatch.setattr(tasks, "_service", lambda: service)

    result = tasks.insert_task(
        "list-1",
        title="Child",
        notes="note",
        due="2026-05-05",
        parent="parent-1",
        previous="sibling-1",
    )

    assert result == {"id": "new-task", "title": "Child", "parent": "parent-1"}
    assert service.tasks_resource.calls == [
        (
            "insert",
            {
                "tasklist": "list-1",
                "body": {
                    "title": "Child",
                    "notes": "note",
                    "due": "2026-05-05T00:00:00.000Z",
                },
                "parent": "parent-1",
                "previous": "sibling-1",
            },
        )
    ]


def test_move_task_passes_positioning_controls(monkeypatch, configured_env):
    service = _TasklistService()
    monkeypatch.setattr(tasks, "_service", lambda: service)

    result = tasks.move_task(
        "list-1",
        "task-1",
        parent="parent-1",
        previous="sibling-1",
        destination_tasklist="list-2",
    )

    assert result == {"id": "task-1", "parent": "parent-1", "position": "0002"}
    assert service.tasks_resource.calls == [
        (
            "move",
            {
                "tasklist": "list-1",
                "task": "task-1",
                "parent": "parent-1",
                "previous": "sibling-1",
                "destinationTasklist": "list-2",
            },
        )
    ]
