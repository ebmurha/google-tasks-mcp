from __future__ import annotations

from datetime import date

import pytest

from google_tasks_mcp import server
from google_tasks_mcp.errors import AmbiguousTitleError, InvalidInputError, NotFoundError


@pytest.fixture
def fake_task_store(monkeypatch, configured_env):
    tasklists = {
        "default": {"id": "default", "title": "Default", "updated": "2026-05-04T10:00:00.000Z"},
        "target": {"id": "target", "title": "Target", "updated": "2026-05-04T11:00:00.000Z"},
    }
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
            {
                "id": "done-2",
                "title": "Another done task",
                "status": "completed",
                "completed": "2026-05-05T09:00:00.000Z",
                "position": "0004",
                "updated": "2026-05-05T09:00:00.000Z",
                "links": [],
            },
        ],
        "target": [],
    }
    deleted_prefetches = []
    invalidations = []

    monkeypatch.setattr(server, "_today", lambda: date(2026, 5, 5))
    monkeypatch.setattr(
        server.tasks_api,
        "list_tasklists",
        lambda: list(tasklists.values()),
    )
    monkeypatch.setattr(
        server.tasks_api,
        "resolve_tasklist",
        lambda name=None: next(
            (
                tasklist_id
                for tasklist_id, item in tasklists.items()
                if name and (name == tasklist_id or name.casefold() == item["title"].casefold())
            ),
            "default",
        ),
    )
    monkeypatch.setattr(
        server.tasks_api,
        "get_tasklist_title",
        lambda tasklist_id: tasklists[tasklist_id]["title"],
    )

    def _filtered_items(
        tasklist_id,
        *,
        show_completed=False,
        show_deleted=False,
        show_hidden=False,
        show_assigned=False,
        due_min=None,
        due_max=None,
        completed_min=None,
        completed_max=None,
        updated_min=None,
        max_results=100,
    ):
        items = list(store[tasklist_id])
        if not show_completed:
            items = [item for item in items if item.get("status") != "completed"]
        if not show_deleted:
            items = [item for item in items if item.get("deleted") is not True]
        if not show_hidden:
            items = [item for item in items if item.get("hidden") is not True]
        if due_min:
            items = [item for item in items if item.get("due", "9999") >= due_min]
        if due_max:
            items = [item for item in items if item.get("due", "9999") < due_max]
        if completed_min:
            items = [item for item in items if item.get("completed", "0000") >= completed_min]
        if completed_max:
            items = [item for item in items if item.get("completed", "9999") < completed_max]
        if updated_min:
            items = [item for item in items if item.get("updated", "0000") >= updated_min]
        return items[:max_results]

    def list_tasks(tasklist_id, **kwargs):
        return _filtered_items(tasklist_id, **kwargs)

    def list_tasks_page(tasklist_id, *, page_token=None, max_results=100, **kwargs):
        offset = int(page_token or "0")
        items = _filtered_items(tasklist_id, max_results=1000, **kwargs)
        page = items[offset : offset + max_results]
        result = {"items": page}
        if offset + max_results < len(items):
            result["nextPageToken"] = str(offset + max_results)
        return result

    def get_task(tasklist_id, task_id):
        return next(item for item in store[tasklist_id] if item["id"] == task_id)

    def insert_task(tasklist_id, *, title, notes=None, due=None, parent=None, previous=None):
        task_id = f"new-{len(store[tasklist_id]) + 1}"
        task = {
            "id": task_id,
            "title": title,
            "status": "needsAction",
            "completed": None,
            "parent": parent,
            "position": f"{len(store[tasklist_id]) + 1:04d}",
            "updated": "2026-05-05T12:00:00.000Z",
            "links": [],
            "webViewLink": f"https://tasks.google.com/task/{task_id}",
        }
        if notes is not None:
            task["notes"] = notes
        if due is not None:
            task["due"] = f"{due}T00:00:00.000Z" if "T" not in due else due
        if previous:
            for index, item in enumerate(store[tasklist_id]):
                if item["id"] == previous:
                    store[tasklist_id].insert(index + 1, task)
                    break
            else:
                store[tasklist_id].append(task)
        else:
            store[tasklist_id].append(task)
        for index, item in enumerate(store[tasklist_id], start=1):
            item["position"] = f"{index:04d}"
        return task

    def move_task(tasklist_id, task_id, *, parent=None, previous=None, destination_tasklist=None):
        destination_id = destination_tasklist or tasklist_id
        task = get_task(tasklist_id, task_id)
        store[tasklist_id] = [item for item in store[tasklist_id] if item["id"] != task_id]
        task["parent"] = parent
        if previous:
            for index, item in enumerate(store[destination_id]):
                if item["id"] == previous:
                    store[destination_id].insert(index + 1, task)
                    break
            else:
                store[destination_id].append(task)
        else:
            store[destination_id].append(task)
        for list_id in {tasklist_id, destination_id}:
            for index, item in enumerate(store[list_id], start=1):
                item["position"] = f"{index:04d}"
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

    def clear_completed(tasklist_id):
        for task in store[tasklist_id]:
            if task.get("status") == "completed":
                task["hidden"] = True

    def create_tasklist(*, title):
        tasklist_id = f"list-{len(tasklists) + 1}"
        tasklist = {
            "id": tasklist_id,
            "title": title.strip(),
            "updated": "2026-05-05T14:00:00.000Z",
            "kind": "tasks#taskList",
            "etag": '"etag"',
            "selfLink": "https://example.invalid/tasklist",
        }
        tasklists[tasklist_id] = tasklist
        store[tasklist_id] = []
        return tasklist

    def get_tasklist(tasklist_id):
        return tasklists[tasklist_id]

    def update_tasklist(tasklist_id, *, title):
        tasklists[tasklist_id]["title"] = title.strip()
        tasklists[tasklist_id]["updated"] = "2026-05-05T15:00:00.000Z"
        return tasklists[tasklist_id]

    def delete_tasklist(tasklist_id):
        del tasklists[tasklist_id]
        del store[tasklist_id]

    monkeypatch.setattr(server.tasks_api, "list_tasks", list_tasks)
    monkeypatch.setattr(server.tasks_api, "list_tasks_page", list_tasks_page)
    monkeypatch.setattr(server.tasks_api, "get_task", get_task)
    monkeypatch.setattr(server.tasks_api, "insert_task", insert_task)
    monkeypatch.setattr(server.tasks_api, "complete_task", complete_task)
    monkeypatch.setattr(server.tasks_api, "update_task", update_task)
    monkeypatch.setattr(server.tasks_api, "delete_task", delete_task)
    monkeypatch.setattr(server.tasks_api, "clear_completed", clear_completed)
    monkeypatch.setattr(server.tasks_api, "move_task", move_task)
    monkeypatch.setattr(server.tasks_api, "create_tasklist", create_tasklist)
    monkeypatch.setattr(server.tasks_api, "get_tasklist", get_tasklist)
    monkeypatch.setattr(server.tasks_api, "update_tasklist", update_tasklist)
    monkeypatch.setattr(server.tasks_api, "delete_tasklist", delete_tasklist)
    monkeypatch.setattr(server.tasks_api, "clear_tasklist_cache", lambda: invalidations.append(True))
    return store, deleted_prefetches, tasklists, invalidations


def test_list_tasklists_is_compact(fake_task_store):
    result = server.list_tasklists_tool()

    assert result == {
        "tasklists": [{"id": "default", "title": "Default"}, {"id": "target", "title": "Target"}]
    }


def test_tasklist_crud_round_trip_and_strips_google_fields(fake_task_store):
    created = server.create_tasklist_tool("Projects")
    assert created == {
        "id": "list-3",
        "title": "Projects",
        "updated": "2026-05-05T14:00:00.000Z",
        "human_summary": "Created tasklist 'Projects'",
    }
    assert "kind" not in created
    assert "etag" not in created
    assert "selfLink" not in created

    fetched = server.get_tasklist_tool(title="projects")
    assert fetched == {
        "id": "list-3",
        "title": "Projects",
        "updated": "2026-05-05T14:00:00.000Z",
    }

    updated = server.update_tasklist_tool(id="list-3", new_title="Projects Renamed")
    assert updated["title"] == "Projects Renamed"
    assert updated["human_summary"] == "Renamed tasklist to 'Projects Renamed'"

    deleted = server.delete_tasklist_tool(id="list-3", confirm=True)
    assert deleted["id"] == "list-3"
    assert deleted["tasks_deleted_count"] == 0
    assert deleted["human_summary"] == "Deleted tasklist 'Projects Renamed'"
    assert "list-3" not in fake_task_store[2]


def test_tasklist_mutations_invalidate_resolver_cache(fake_task_store):
    created = server.create_tasklist_tool("Fresh")

    assert fake_task_store[3]
    assert server.get_tasklist_tool(title="Fresh")["id"] == created["id"]


def test_list_tasks_filters_and_returns_rich_objects(fake_task_store):
    result = server.list_tasks_tool(
        tasklist="Default",
        due_min="2026-05-04",
        due_max="2026-05-06",
        show_completed=False,
    )

    assert result["count"] == 2
    assert result["tasklist_title"] == "Default"
    assert [task["id"] for task in result["tasks"]] == ["today-1", "old-1"]
    assert result["tasks"][0]["tasklist_id"] == "default"
    assert result["tasks"][0]["tasklist_title"] == "Default"
    assert result["tasks"][0]["due"] == "2026-05-05"
    assert "human_summary" not in result["tasks"][0]
    assert "kind" not in result["tasks"][0]
    assert "webViewLink" not in result["tasks"][0]
    assert "next_page_token" not in result


def test_list_tasks_show_completed_and_pagination(fake_task_store):
    result = server.list_tasks_tool(show_completed=True, max_results=2)

    assert result["count"] == 2
    assert [task["id"] for task in result["tasks"]] == ["today-1", "old-1"]
    assert result["next_page_token"] == "2"

    next_page = server.list_tasks_tool(show_completed=True, page_token=result["next_page_token"])
    assert next_page["count"] == 2
    assert next_page["tasks"][0]["id"] == "done-1"


def test_list_tasks_timezone_changes_bare_date_filters(monkeypatch, fake_task_store):
    captured = []

    def list_tasks_page(tasklist_id, **kwargs):
        captured.append(kwargs)
        return {"items": []}

    monkeypatch.setattr(server.tasks_api, "list_tasks_page", list_tasks_page)

    server.list_tasks_tool(due_min="2026-05-10", due_max="2026-05-11", timezone="Africa/Nairobi")
    server.list_tasks_tool(due_min="2026-05-10", due_max="2026-05-11", timezone="America/Los_Angeles")

    assert captured[0]["due_min"] == "2026-05-10T00:00:00.000+03:00"
    assert captured[1]["due_min"] == "2026-05-10T00:00:00.000-07:00"
    assert captured[0]["due_min"] != captured[1]["due_min"]


def test_update_and_delete_tasklist_require_id(fake_task_store):
    update_result = server._logged_tool("update_tasklist", server.update_tasklist_tool)(
        new_title="Nope"
    )
    delete_result = server._logged_tool("delete_tasklist", server.delete_tasklist_tool)(confirm=True)

    assert update_result["error"] == "INVALID_INPUT"
    assert update_result["code"] == 400
    assert delete_result["error"] == "INVALID_INPUT"
    assert delete_result["code"] == 400


def test_delete_tasklist_requires_confirm(fake_task_store):
    result = server._logged_tool("delete_tasklist", server.delete_tasklist_tool)(id="target")

    assert result["error"] == "INVALID_INPUT"
    assert result["code"] == 400
    assert result["message"] == "delete_tasklist requires confirm=true"


def test_delete_tasklist_non_empty_requires_force(fake_task_store):
    rejected = server._logged_tool("delete_tasklist", server.delete_tasklist_tool)(
        id="default", confirm=True
    )
    assert rejected["error"] == "INVALID_INPUT"
    assert rejected["code"] == 400
    assert rejected["tasks_deleted_count"] == 4

    deleted = server.delete_tasklist_tool(id="default", confirm=True, force=True)
    assert deleted["tasks_deleted_count"] == 4
    assert "default" not in fake_task_store[2]


def test_clear_completed_requires_confirm(fake_task_store):
    result = server._logged_tool("clear_completed", server.clear_completed_tool)()

    assert result["error"] == "INVALID_INPUT"
    assert result["code"] == 400
    assert result["message"] == "clear_completed requires confirm=true"


def test_clear_completed_hides_completed_tasks(fake_task_store):
    result = server.clear_completed_tool(confirm=True)

    assert result == {
        "cleared_count": 2,
        "tasklist_title": "Default",
        "human_summary": "Cleared 2 completed tasks from Default",
    }
    assert server.list_tasks_tool(show_completed=True)["count"] == 2
    hidden = server.list_tasks_tool(show_hidden=True)
    assert hidden["count"] == 4
    assert {task["id"] for task in hidden["tasks"] if task["status"] == "completed"} == {
        "done-1",
        "done-2",
    }


def test_clear_completed_empty_list_returns_zero(fake_task_store):
    result = server.clear_completed_tool(tasklist="Target", confirm=True)

    assert result["cleared_count"] == 0
    assert result["tasklist_title"] == "Target"
    assert result["human_summary"] == "Cleared 0 completed tasks from Target"


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


def test_get_task_by_title_is_case_insensitive_and_exact(fake_task_store):
    result = server.get_task_tool(title=" due today ")

    assert result["id"] == "today-1"
    assert result["title"] == "Due today"


def test_add_complete_update_delete_flow(fake_task_store):
    created = server.add_tool("New task", notes="note", due="2026-05-06")
    assert created == {
        "id": "new-5",
        "title": "New task",
        "notes": "note",
        "status": "needsAction",
        "due": "2026-05-06",
        "completed": None,
        "parent": None,
        "position": "0005",
        "updated": "2026-05-05T12:00:00.000Z",
        "links": [],
        "web_view_link": "https://tasks.google.com/task/new-5",
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


def test_add_subtask_with_parent_title(fake_task_store):
    result = server.add_tool("Child task", parent="Due today")

    assert result["title"] == "Child task"
    assert result["parent"] == "today-1"
    assert result["human_summary"] == "Created 'Child task' in Default"


def test_add_subtask_with_previous_title_orders_after_sibling(fake_task_store):
    first = server.add_tool("First child", parent="Due today")
    second = server.add_tool("Second child", parent="Due today", previous="First child")

    children = [
        task
        for task in server.list_tasks_tool(show_completed=True)["tasks"]
        if task.get("parent") == "today-1"
    ]
    assert [task["id"] for task in children] == [first["id"], second["id"]]
    assert second["parent"] == "today-1"


def test_add_previous_prefers_exact_id(fake_task_store):
    first = server.add_tool("Sibling one")
    second = server.add_tool("Sibling two", previous=first["id"])

    tasks = server.list_tasks_tool(show_completed=True)["tasks"]
    ids = [task["id"] for task in tasks]
    assert ids.index(second["id"]) == ids.index(first["id"]) + 1


def test_complete_by_title_succeeds_with_no_id(fake_task_store):
    result = server.complete_tool(title="Due today")

    assert result["id"] == "today-1"
    assert result["status"] == "completed"
    assert result["human_summary"] == "Completed 'Due today' (was due 2026-05-05)"


def test_delete_by_title_with_tasklist_title(fake_task_store):
    created = server.add_tool("Target task", tasklist="Target")

    result = server.delete_tool(title="target task", tasklist="Target")

    assert result["id"] == created["id"]
    assert result["title"] == "Target task"
    assert result["tasklist_title"] == "Target"
    assert result["deleted"] is True


def test_update_by_title_changes_non_title_fields(fake_task_store):
    result = server.update_tool(title="Due today", due="2026-05-08")

    assert result["id"] == "today-1"
    assert result["title"] == "Due today"
    assert result["due"] == "2026-05-08"
    assert result["human_summary"] == "Updated 'Due today': due"


def test_update_by_id_preserves_existing_title_update_behavior(fake_task_store):
    result = server.update_tool(id="today-1", title="Renamed")

    assert result["id"] == "today-1"
    assert result["title"] == "Renamed"
    assert result["human_summary"] == "Updated 'Renamed': title"


def test_title_lookup_excludes_completed_by_default(fake_task_store):
    result = server._logged_tool("get_task", server.get_task_tool)(title="Done task")

    assert result["error"] == "NOT_FOUND"
    assert result["code"] == 404
    assert result["searched_tasklist"] == "Default"
    assert result["query"] == "Done task"


def test_title_lookup_can_include_completed(fake_task_store):
    result = server.get_task_tool(title="Done task", include_completed=True)

    assert result["id"] == "done-1"
    assert result["title"] == "Done task"


def test_ambiguous_title_returns_candidates(fake_task_store):
    fake_task_store[0]["default"].append(
        {
            "id": "today-2",
            "title": "Due today",
            "due": "2026-05-06T00:00:00.000Z",
            "status": "needsAction",
        }
    )

    result = server._logged_tool("complete", server.complete_tool)(title="Due today")

    assert result["error"] == "AMBIGUOUS_TITLE"
    assert result["code"] == 409
    assert result["message"] == "Multiple active tasks match title 'Due today'"
    assert result["searched_tasklist"] == "Default"
    assert [candidate["id"] for candidate in result["candidates"]] == ["today-1", "today-2"]


def test_after_completing_one_duplicate_title_lookup_succeeds(fake_task_store):
    fake_task_store[0]["default"].append(
        {
            "id": "today-2",
            "title": "Due today",
            "due": "2026-05-06T00:00:00.000Z",
            "status": "completed",
        }
    )

    result = server.complete_tool(title="Due today")

    assert result["id"] == "today-1"
    assert result["status"] == "completed"


def test_id_preferred_when_id_and_title_are_both_provided(fake_task_store):
    result = server.complete_tool(id="old-1", title="Due today")

    assert result["id"] == "old-1"
    assert result["title"] == "Old task"


def test_move_by_title_uses_source_tasklist(fake_task_store):
    result = server.move_tool(title="Old task", tasklist="Target")

    assert result["title"] == "Old task"
    assert result["tasklist_id"] == "target"
    assert all(item["id"] != "old-1" for item in fake_task_store[0]["default"])


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


def test_move_accepts_task_reference_and_destination_tasklist(fake_task_store):
    result = server.move_tool(task="old-1", destination_tasklist="Target")

    assert result["title"] == "Old task"
    assert result["id"].startswith("new-")
    assert result["id"] != "old-1"
    assert result["tasklist_id"] == "target"
    assert all(item["id"] != "old-1" for item in fake_task_store[0]["default"])
    assert any(item["id"] == result["id"] for item in fake_task_store[0]["target"])


def test_move_task_reference_accepts_exact_title(fake_task_store):
    result = server.move_tool(task="Old task", destination_tasklist="Target")

    assert result["title"] == "Old task"
    assert result["tasklist_id"] == "target"
    assert all(item["id"] != "old-1" for item in fake_task_store[0]["default"])


def test_same_list_move_reparents_task(fake_task_store):
    child = server.add_tool("Existing child", parent="Due today")

    result = server.move_tool(task=child["id"], destination_parent="Old task")

    assert result["id"] == child["id"]
    assert result["parent"] == "old-1"
    assert result["tasklist_id"] == "default"


def test_same_list_move_reorders_after_previous(fake_task_store):
    first = server.add_tool("First reorder")
    second = server.add_tool("Second reorder")

    result = server.move_tool(task=first["id"], destination_previous=second["id"])
    ordered_ids = [task["id"] for task in server.list_tasks_tool(show_completed=True)["tasks"]]

    assert result["id"] == first["id"]
    assert ordered_ids.index(first["id"]) == ordered_ids.index(second["id"]) + 1


def test_same_list_move_to_top_level_clears_parent(fake_task_store):
    child = server.add_tool("Top level child", parent="Due today")

    result = server.move_tool(task=child["id"], destination_parent=None)

    assert result["id"] == child["id"]
    assert result["parent"] is None


def test_cross_list_move_combines_destination_parent_and_previous(fake_task_store):
    parent = server.add_tool("Destination parent", tasklist="Target")
    first = server.add_tool("Destination first", tasklist="Target", parent=parent["id"])

    result = server.move_tool(
        task="old-1",
        destination_tasklist="Target",
        destination_parent=parent["id"],
        destination_previous=first["id"],
    )
    target_ids = [task["id"] for task in server.list_tasks_tool(tasklist="Target", show_completed=True)["tasks"]]

    assert result["id"].startswith("new-")
    assert result["id"] != "old-1"
    assert result["parent"] == parent["id"]
    assert target_ids.index(result["id"]) == target_ids.index(first["id"]) + 1
    assert all(item["id"] != "old-1" for item in fake_task_store[0]["default"])


def test_registered_mcp_tools_have_exact_names():
    import asyncio

    async def run():
        mcp = server.create_mcp_server()
        return [tool.name for tool in await mcp.list_tools()]

    assert asyncio.run(run()) == [
        "list_tasklists",
        "create_tasklist",
        "get_tasklist",
        "update_tasklist",
        "delete_tasklist",
        "list_tasks",
        "clear_completed",
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
