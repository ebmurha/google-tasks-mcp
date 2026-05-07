from __future__ import annotations

from datetime import date

import pytest

from google_tasks_mcp import server
from google_tasks_mcp.errors import AmbiguousTitleError, InvalidInputError, NotFoundError


@pytest.fixture
def fake_task_store(monkeypatch, configured_env):
    store = {
        "default": [
            {
                "id": "today-1",
                "title": "Due today",
                "due": "2026-05-05T00:00:00.000Z",
                "status": "needsAction",
                "position": "0001",
                "updated": "2026-05-04T10:00:00.000Z",
                "links": [],
                "webViewLink": "https://tasks.google.com/task/today-1",
                "kind": "tasks#task",
            },
            {
                "id": "old-1",
                "title": "Old task",
                "notes": "Contains Alpha",
                "due": "2026-05-04T00:00:00.000Z",
                "status": "needsAction",
                "position": "0002",
                "updated": "2026-05-04T11:00:00.000Z",
                "links": [],
                "webViewLink": "https://tasks.google.com/task/old-1",
            },
            {
                "id": "done-1",
                "title": "Done task",
                "notes": "alpha done",
                "status": "completed",
                "completed": "2026-05-05T08:00:00.000Z",
                "position": "0003",
                "updated": "2026-05-05T08:00:00.000Z",
                "links": [],
                "webViewLink": "https://tasks.google.com/task/done-1",
            },
        ],
        "target": [],
    }
    deleted_prefetches = []

    monkeypatch.setattr(server, "_today", lambda: date(2026, 5, 5))
    monkeypatch.setattr(
        server.tasks_api,
        "list_tasklists",
        lambda: [{"id": "default", "title": "Default"}, {"id": "target", "title": "Target"}],
    )
    monkeypatch.setattr(
        server.tasks_api,
        "resolve_tasklist",
        lambda name=None: "target" if name and name.casefold() == "target" else "default",
    )
    monkeypatch.setattr(
        server.tasks_api,
        "get_tasklist_title",
        lambda tasklist_id: "Target" if tasklist_id == "target" else "Default",
    )

    def list_tasks(tasklist_id, *, show_completed=False, due_min=None, due_max=None, max_results=100):
        items = list(store[tasklist_id])
        if not show_completed:
            items = [item for item in items if item.get("status") != "completed"]
        if due_min:
            items = [item for item in items if item.get("due", "9999") >= due_min]
        if due_max:
            items = [item for item in items if item.get("due", "9999") < due_max]
        return items[:max_results]

    def get_task(tasklist_id, task_id):
        return next(item for item in store[tasklist_id] if item["id"] == task_id)

    def insert_task(tasklist_id, *, title, notes=None, due=None):
        task_id = f"new-{len(store[tasklist_id]) + 1}"
        task = {
            "id": task_id,
            "title": title,
            "status": "needsAction",
            "completed": None,
            "parent": None,
            "position": f"{len(store[tasklist_id]) + 1:04d}",
            "updated": "2026-05-05T12:00:00.000Z",
            "links": [],
            "webViewLink": f"https://tasks.google.com/task/{task_id}",
        }
        if notes is not None:
            task["notes"] = notes
        if due is not None:
            task["due"] = f"{due}T00:00:00.000Z" if "T" not in due else due
        store[tasklist_id].append(task)
        return task

    def complete_task(tasklist_id, task_id):
        task = get_task(tasklist_id, task_id)
        task["status"] = "completed"
        task["completed"] = "2026-05-05T13:00:00.000Z"
        return task

    def update_task(tasklist_id, task_id, **kwargs):
        task = get_task(tasklist_id, task_id)
        for key, value in kwargs.items():
            if value is not None:
                task[key] = value
        return task

    def delete_task(tasklist_id, task_id):
        deleted_prefetches.append(get_task(tasklist_id, task_id).copy())
        store[tasklist_id] = [item for item in store[tasklist_id] if item["id"] != task_id]

    monkeypatch.setattr(server.tasks_api, "list_tasks", list_tasks)
    monkeypatch.setattr(server.tasks_api, "get_task", get_task)
    monkeypatch.setattr(server.tasks_api, "insert_task", insert_task)
    monkeypatch.setattr(server.tasks_api, "complete_task", complete_task)
    monkeypatch.setattr(server.tasks_api, "update_task", update_task)
    monkeypatch.setattr(server.tasks_api, "delete_task", delete_task)
    monkeypatch.setattr(server.tasks_api, "move_task", lambda tasklist_id, task_id: get_task(tasklist_id, task_id))
    return store, deleted_prefetches


def test_list_tasklists_is_compact(fake_task_store):
    result = server.list_tasklists_tool()

    assert result == {
        "tasklists": [{"id": "default", "title": "Default"}, {"id": "target", "title": "Target"}]
    }


def test_today_filters_and_strips_google_fields(fake_task_store):
    result = server.today_tool()

    assert result == {
        "count": 1,
        "tasks": [
            {
                "id": "today-1",
                "title": "Due today",
                "due": "2026-05-05",
                "status": "needsAction",
            }
        ],
    }
    assert "kind" not in result["tasks"][0]


def test_overdue_only_incomplete(fake_task_store):
    result = server.overdue_tool()

    assert result["count"] == 1
    assert result["tasks"][0]["id"] == "old-1"


def test_search_is_case_insensitive_and_excludes_completed_by_default(fake_task_store):
    result = server.search_tool("alpha")

    assert result["count"] == 1
    assert result["tasks"][0]["id"] == "old-1"


def test_add_complete_update_delete_flow(fake_task_store):
    created = server.add_tool("New task", notes="note", due="2026-05-06")
    assert created == {
        "id": "new-4",
        "title": "New task",
        "notes": "note",
        "status": "needsAction",
        "due": "2026-05-06",
        "completed": None,
        "parent": None,
        "position": "0004",
        "updated": "2026-05-05T12:00:00.000Z",
        "links": [],
        "web_view_link": "https://tasks.google.com/task/new-4",
        "tasklist_id": "default",
        "tasklist_title": "Default",
        "human_summary": "Created 'New task' due 2026-05-06 in Default",
    }

    completed = server.complete_tool(created["id"])
    assert completed["id"] == created["id"]
    assert completed["title"] == "New task"
    assert completed["due"] == "2026-05-06"
    assert completed["status"] == "completed"
    assert completed["completed"] == "2026-05-05T13:00:00.000Z"
    assert completed["human_summary"] == "Completed 'New task' (was due 2026-05-06)"

    updated = server.update_tool(created["id"], due="2026-05-07")
    assert updated["title"] == "New task"
    assert updated["due"] == "2026-05-07"
    assert updated["human_summary"] == "Updated 'New task': due"

    deleted = server.delete_tool(created["id"])
    assert deleted["id"] == created["id"]
    assert deleted["title"] == "New task"
    assert deleted["deleted"] is True
    assert deleted["human_summary"] == "Deleted 'New task' from Default"
    assert fake_task_store[1][-1]["id"] == created["id"]


def test_get_task_includes_truncated_notes(fake_task_store):
    fake_task_store[0]["default"][0]["notes"] = "x" * 250

    result = server.get_task_tool("today-1")

    assert result["notes"] == ("x" * 200) + "..."


def test_cross_list_move_emulates_insert_delete(fake_task_store):
    result = server.move_tool("old-1", tasklist="Target")

    assert result["title"] == "Old task"
    assert result["id"].startswith("new-")
    assert result["tasklist_id"] == "target"
    assert result["tasklist_title"] == "Target"
    assert result["human_summary"] == "Moved 'Old task' to Target"
    assert all(item["id"] != "old-1" for item in fake_task_store[0]["default"])
    assert any(item["title"] == "Old task" for item in fake_task_store[0]["target"])


def test_registered_mcp_tools_have_exact_names():
    import asyncio

    async def run():
        mcp = server.create_mcp_server()
        return [tool.name for tool in await mcp.list_tools()]

    assert asyncio.run(run()) == [
        "list_tasklists",
        "today",
        "overdue",
        "upcoming",
        "search",
        "get_task",
        "digest",
        "add",
        "complete",
        "update",
        "delete",
        "move",
    ]


def test_error_payload_for_structured_errors():
    assert server._error_payload(NotFoundError("Missing task", query="Friday ship")) == {
        "error": "NOT_FOUND",
        "code": 404,
        "message": "Missing task",
        "query": "Friday ship",
    }
    assert server._error_payload(
        AmbiguousTitleError("Multiple tasklists match title 'Work'", candidates=[{"id": "a"}])
    ) == {
        "error": "AMBIGUOUS_TITLE",
        "code": 409,
        "message": "Multiple tasklists match title 'Work'",
        "candidates": [{"id": "a"}],
    }
    assert server._error_payload(InvalidInputError("Invalid timezone: Bad/TZ", timezone="Bad/TZ")) == {
        "error": "INVALID_INPUT",
        "code": 400,
        "message": "Invalid timezone: Bad/TZ",
        "timezone": "Bad/TZ",
    }
