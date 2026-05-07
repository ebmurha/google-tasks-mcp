"""MCP tool definitions and orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, datetime, time as datetime_time, timedelta, timezone as datetime_timezone
from functools import wraps
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import digest, timezones
from .errors import AuthRequired, ConfigError, GoogleTasksApiError, GoogleTasksMcpError, InvalidInputError
from . import tasks as tasks_api


LOGGER = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, GoogleTasksMcpError) and hasattr(exc, "error"):
        if getattr(exc, "code", 500) in {400, 404, 409}:
            return {
                "error": exc.error,
                "code": exc.code,
                "message": exc.message or str(exc),
                **exc.details,
            }
    if isinstance(exc, AuthRequired):
        return {"error": str(exc), "hint": "Run scripts/bootstrap_oauth.py"}
    if isinstance(exc, ConfigError):
        return {"error": str(exc), "hint": "Check server configuration"}
    if isinstance(exc, GoogleTasksApiError):
        return {"error": str(exc)}
    if isinstance(exc, GoogleTasksMcpError):
        return {"error": str(exc)}
    LOGGER.exception("Unhandled tool error")
    return {"error": "Internal server error"}


def _logged_tool(name: str, func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            return _error_payload(exc)
        finally:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.info(
                "mcp_tool_invoked",
                extra={"tool_name": name, "arg_keys": sorted(kwargs), "elapsed_ms": elapsed_ms},
            )

    return wrapper  # type: ignore[return-value]


def _resolve(tasklist: str | None = None) -> str:
    return tasks_api.resolve_tasklist(tasklist)


def _tasklist_title(tasklist_id: str) -> str:
    return tasks_api.get_tasklist_title(tasklist_id)


def _resolve_task_id(
    tasklist_id: str,
    id: str | None,
    title: str | None,
    *,
    include_completed: bool = False,
) -> str:
    if id:
        return id
    if title:
        return tasks_api.resolve_task_by_title(
            tasklist_id,
            title,
            include_completed=include_completed,
            tasklist_title=_tasklist_title(tasklist_id),
        )
    raise InvalidInputError("Task id or title is required")


def _resolve_task_reference(tasklist_id: str, reference: str | None) -> str | None:
    if reference is None:
        return None
    query = reference.strip()
    if not query:
        raise InvalidInputError("Task reference must not be empty")
    for task in tasks_api.list_tasks(tasklist_id, show_completed=False, max_results=1000):
        if task.get("deleted") is True or task.get("status") == "completed":
            continue
        if str(task.get("id") or "") == query:
            return query
    return tasks_api.resolve_task_by_title(
        tasklist_id,
        query,
        include_completed=False,
        tasklist_title=_tasklist_title(tasklist_id),
    )


def _today() -> date:
    return date.today()


def _incomplete(task_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [task for task in task_items if task.get("status") != "completed"]


def _due_date(task: dict[str, Any]) -> str | None:
    due = task.get("due")
    if not due:
        return None
    return str(due).split("T", 1)[0]


def _rfc3339(value: str | None, tz: ZoneInfo | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if "T" in raw:
        return raw
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise InvalidInputError("Date filters must be YYYY-MM-DD or RFC 3339", value=raw) from exc
    if tz is None:
        return f"{parsed.isoformat()}T00:00:00.000Z"
    dt = datetime.combine(parsed, datetime_time.min, tzinfo=tz)
    return dt.isoformat(timespec="milliseconds")


def _today_in_timezone(tz: ZoneInfo | None) -> date:
    if tz is None:
        return _today()
    return datetime.now(datetime_timezone.utc).astimezone(tz).date()


def list_tasklists_tool() -> dict[str, list[dict[str, str]]]:
    tasklists = tasks_api.list_tasklists()
    return {
        "tasklists": [
            {"id": item.get("id", ""), "title": item.get("title", "")}
            for item in tasklists
            if item.get("id")
        ]
    }


def list_tasks_tool(
    tasklist: str | None = None,
    due_min: str | None = None,
    due_max: str | None = None,
    completed_min: str | None = None,
    completed_max: str | None = None,
    updated_min: str | None = None,
    show_completed: bool = False,
    show_deleted: bool = False,
    show_hidden: bool = False,
    show_assigned: bool = False,
    max_results: int = 1000,
    page_token: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    """List tasks with Google Tasks filters and compact rich task objects."""

    tz = timezones.resolve_timezone(timezone)
    tasklist_id = _resolve(tasklist)
    tasklist_title = _tasklist_title(tasklist_id)
    bounded_max = max(1, min(max_results, 1000))
    effective_show_completed = show_completed or show_hidden
    response = tasks_api.list_tasks_page(
        tasklist_id,
        due_min=_rfc3339(due_min, tz),
        due_max=_rfc3339(due_max, tz),
        completed_min=_rfc3339(completed_min, tz),
        completed_max=_rfc3339(completed_max, tz),
        updated_min=_rfc3339(updated_min, tz),
        show_completed=effective_show_completed,
        show_deleted=show_deleted,
        show_hidden=show_hidden,
        show_assigned=show_assigned,
        max_results=bounded_max,
        page_token=page_token,
    )
    ordered_items = sorted(
        response.get("items", []) or [],
        key=lambda task: str(task.get("position") or ""),
    )
    tasks = [
        digest.full_task_object(task, tasklist_id, tasklist_title)
        for task in ordered_items
    ]
    result: dict[str, Any] = {
        "tasks": tasks,
        "count": len(tasks),
        "tasklist_title": tasklist_title,
    }
    next_page_token = response.get("nextPageToken")
    if next_page_token:
        result["next_page_token"] = next_page_token
    return result


def clear_completed_tool(tasklist: str | None = None, confirm: bool = False) -> dict[str, Any]:
    """Hide completed tasks in a list after explicit confirmation.

    Google Tasks clear hides completed tasks rather than deleting them; they can
    reappear when listing hidden tasks.
    """

    if confirm is not True:
        raise InvalidInputError("clear_completed requires confirm=true")
    tasklist_id = _resolve(tasklist)
    tasklist_title = _tasklist_title(tasklist_id)
    completed_tasks = [
        task
        for task in tasks_api.list_tasks(
            tasklist_id,
            show_completed=True,
            show_hidden=False,
            max_results=1000,
        )
        if task.get("status") == "completed" and task.get("deleted") is not True
    ]
    cleared_count = len(completed_tasks)
    tasks_api.clear_completed(tasklist_id)
    return {
        "cleared_count": cleared_count,
        "tasklist_title": tasklist_title,
        "human_summary": f"Cleared {cleared_count} completed tasks from {tasklist_title}",
    }


def create_tasklist_tool(title: str) -> dict[str, Any]:
    """Create a Google tasklist and return compact metadata with human_summary."""

    created = tasks_api.create_tasklist(title=title)
    tasks_api.clear_tasklist_cache()
    return digest.build_tasklist_response(created, operation="create")


def get_tasklist_tool(id: str | None = None, title: str | None = None) -> dict[str, Any]:
    """Get a Google tasklist by ID, or by exact title when ID is omitted."""

    if id:
        tasklist_id = id
    elif title:
        tasklist_id = _resolve(title)
    else:
        raise InvalidInputError("Tasklist id or title is required")
    tasklist = tasks_api.get_tasklist(tasklist_id)
    return digest.shrink_tasklist(tasklist)


def update_tasklist_tool(id: str | None = None, new_title: str | None = None) -> dict[str, Any]:
    """Rename a Google tasklist by ID only; title lookup is intentionally not supported."""

    if not id:
        raise InvalidInputError("Tasklist id is required")
    if new_title is None:
        raise InvalidInputError("New tasklist title is required")
    updated = tasks_api.update_tasklist(id, title=new_title)
    tasks_api.clear_tasklist_cache()
    return digest.build_tasklist_response(updated, operation="update")


def delete_tasklist_tool(
    id: str | None = None,
    confirm: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Delete a Google tasklist by ID only after explicit confirmation.

    Non-empty tasklists are rejected unless force is true. The response reports
    how many visible or completed tasks were implicitly deleted with the list.
    """

    if not id:
        raise InvalidInputError("Tasklist id is required")
    if confirm is not True:
        raise InvalidInputError("delete_tasklist requires confirm=true")

    existing = tasks_api.get_tasklist(id)
    task_items = tasks_api.list_tasks(id, show_completed=True, max_results=1000)
    tasks_deleted_count = len([task for task in task_items if task.get("deleted") is not True])
    if tasks_deleted_count and not force:
        raise InvalidInputError(
            "Tasklist is not empty; set force=true to delete it",
            tasks_deleted_count=tasks_deleted_count,
        )

    tasks_api.delete_tasklist(id)
    tasks_api.clear_tasklist_cache()
    return digest.build_tasklist_response(
        existing,
        operation="delete",
        tasks_deleted_count=tasks_deleted_count,
    )


def today_tool(tasklist: str | None = None) -> dict[str, Any]:
    tz = timezones.resolve_timezone()
    today = _today_in_timezone(tz)
    tomorrow = today + timedelta(days=1)
    result = list_tasks_tool(
        tasklist=tasklist,
        due_min=today.isoformat(),
        due_max=tomorrow.isoformat(),
        show_completed=False,
    )
    return digest.shrink_list(result["tasks"])


def overdue_tool(tasklist: str | None = None) -> dict[str, Any]:
    tz = timezones.resolve_timezone()
    today = _today_in_timezone(tz)
    result = list_tasks_tool(
        tasklist=tasklist,
        due_max=today.isoformat(),
        show_completed=False,
    )
    return digest.shrink_list(result["tasks"])


def upcoming_tool(days: int = 7, tasklist: str | None = None) -> dict[str, Any]:
    bounded_days = max(1, min(days, 365))
    tz = timezones.resolve_timezone()
    today = _today_in_timezone(tz)
    end_day = today + timedelta(days=bounded_days + 1)
    result = list_tasks_tool(
        tasklist=tasklist,
        due_min=today.isoformat(),
        due_max=end_day.isoformat(),
        show_completed=False,
    )
    return digest.shrink_list(result["tasks"])


def search_tool(
    query: str,
    limit: int = 20,
    tasklist: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    needle = query.casefold().strip()
    if not needle:
        return digest.shrink_list([])
    bounded_limit = max(1, min(limit, 100))
    listed = list_tasks_tool(
        tasklist=tasklist,
        show_completed=include_completed,
        max_results=max(100, bounded_limit),
    )
    matches = []
    for task in listed["tasks"]:
        haystack = f"{task.get('title', '')}\n{task.get('notes', '')}".casefold()
        if needle in haystack and (include_completed or task.get("status") != "completed"):
            matches.append(task)
        if len(matches) >= bounded_limit:
            break
    return digest.shrink_list(matches)


def get_task_tool(
    id: str | None = None,
    tasklist: str | None = None,
    title: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Get a single task by ID or exact title, including full notes."""

    tasklist_id = _resolve(tasklist)
    task_id = _resolve_task_id(tasklist_id, id, title, include_completed=include_completed)
    task = tasks_api.get_task(tasklist_id, task_id)
    return digest.shrink_task(task, include_notes=True)


def digest_tool(tasklist: str | None = None) -> dict[str, str]:
    task_items = list_tasks_tool(tasklist=tasklist, max_results=100)["tasks"]
    return {"text": digest.text_digest(_incomplete(task_items))}


def add_tool(
    title: str,
    notes: str | None = None,
    due: str | None = None,
    tasklist: str | None = None,
    parent: str | None = None,
    previous: str | None = None,
) -> dict[str, Any]:
    """Create a task, optionally under a parent or after a sibling by ID or exact title."""

    tasklist_id = _resolve(tasklist)
    parent_id = _resolve_task_reference(tasklist_id, parent)
    previous_id = _resolve_task_reference(tasklist_id, previous)
    created = tasks_api.insert_task(
        tasklist_id,
        title=title,
        notes=notes,
        due=due,
        parent=parent_id,
        previous=previous_id,
    )
    return digest.build_mutation_response(
        created,
        tasklist_id,
        _tasklist_title(tasklist_id),
        operation="add",
    )


def complete_tool(
    id: str | None = None,
    tasklist: str | None = None,
    title: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Mark a task completed by ID or exact title and return its rich mutation response."""

    tasklist_id = _resolve(tasklist)
    task_id = _resolve_task_id(tasklist_id, id, title, include_completed=include_completed)
    completed = tasks_api.complete_task(tasklist_id, task_id)
    return digest.build_mutation_response(
        completed,
        tasklist_id,
        _tasklist_title(tasklist_id),
        operation="complete",
    )


def update_tool(
    id: str | None = None,
    title: str | None = None,
    notes: str | None = None,
    due: str | None = None,
    tasklist: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Edit a task by ID, or by exact title when ID is omitted."""

    tasklist_id = _resolve(tasklist)
    task_id = _resolve_task_id(tasklist_id, id, title, include_completed=include_completed)
    new_title = title if id else None
    changes = [
        field
        for field, value in (("title", new_title), ("notes", notes), ("due", due))
        if value is not None
    ]
    updated = tasks_api.update_task(tasklist_id, task_id, title=new_title, notes=notes, due=due)
    return digest.build_mutation_response(
        updated,
        tasklist_id,
        _tasklist_title(tasklist_id),
        operation="update",
        changes=changes,
    )


def delete_tool(
    id: str | None = None,
    tasklist: str | None = None,
    title: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Delete a task by ID or exact title after pre-fetching it."""

    tasklist_id = _resolve(tasklist)
    task_id = _resolve_task_id(tasklist_id, id, title, include_completed=include_completed)
    existing = tasks_api.get_task(tasklist_id, task_id)
    tasks_api.delete_task(tasklist_id, task_id)
    return digest.build_mutation_response(
        existing,
        tasklist_id,
        _tasklist_title(tasklist_id),
        operation="delete",
        deleted=True,
    )


def move_tool(
    id: str | None = None,
    tasklist: str | None = None,
    from_tasklist: str | None = None,
    title: str | None = None,
    include_completed: bool = False,
) -> dict[str, Any]:
    """Move a task by ID or exact title to another list and return its rich mutation response."""

    target_tasklist_id = _resolve(tasklist)
    source_tasklist_id = _resolve(from_tasklist)
    task_id = _resolve_task_id(source_tasklist_id, id, title, include_completed=include_completed)
    target_title = _tasklist_title(target_tasklist_id)

    if source_tasklist_id == target_tasklist_id:
        moved = tasks_api.move_task(source_tasklist_id, task_id)
        return digest.build_mutation_response(
            moved,
            target_tasklist_id,
            target_title,
            operation="move",
            move_target=target_title,
        )

    original = tasks_api.get_task(source_tasklist_id, task_id)
    moved = tasks_api.insert_task(
        target_tasklist_id,
        title=original.get("title", ""),
        notes=original.get("notes"),
        due=_due_date(original),
    )
    tasks_api.delete_task(source_tasklist_id, task_id)
    return digest.build_mutation_response(
        moved,
        target_tasklist_id,
        target_title,
        operation="move",
        move_target=target_title,
    )


def create_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "google-tasks-mcp",
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    tool_map: dict[str, Callable[..., Any]] = {
        "list_tasklists": list_tasklists_tool,
        "create_tasklist": create_tasklist_tool,
        "get_tasklist": get_tasklist_tool,
        "update_tasklist": update_tasklist_tool,
        "delete_tasklist": delete_tasklist_tool,
        "list_tasks": list_tasks_tool,
        "clear_completed": clear_completed_tool,
        "today": today_tool,
        "overdue": overdue_tool,
        "upcoming": upcoming_tool,
        "search": search_tool,
        "get_task": get_task_tool,
        "digest": digest_tool,
        "add": add_tool,
        "complete": complete_tool,
        "update": update_tool,
        "delete": delete_tool,
        "move": move_tool,
    }
    for name, func in tool_map.items():
        mcp.add_tool(_logged_tool(name, func), name=name, structured_output=True)
    return mcp
