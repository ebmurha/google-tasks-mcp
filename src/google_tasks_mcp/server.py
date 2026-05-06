"""MCP tool definitions and orchestration."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import date, timedelta
from functools import wraps
from typing import Any, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from . import digest
from .errors import AuthRequired, ConfigError, GoogleTasksApiError, GoogleTasksMcpError
from . import tasks as tasks_api


LOGGER = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


def _error_payload(exc: Exception) -> dict[str, str]:
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


def _today() -> date:
    return date.today()


def _incomplete(task_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [task for task in task_items if task.get("status") != "completed"]


def _due_date(task: dict[str, Any]) -> str | None:
    due = task.get("due")
    if not due:
        return None
    return str(due).split("T", 1)[0]


def list_tasklists_tool() -> dict[str, list[dict[str, str]]]:
    tasklists = tasks_api.list_tasklists()
    return {
        "tasklists": [
            {"id": item.get("id", ""), "title": item.get("title", "")}
            for item in tasklists
            if item.get("id")
        ]
    }


def today_tool(tasklist: str | None = None) -> dict[str, Any]:
    tasklist_id = _resolve(tasklist)
    start, end = digest.utc_day_bounds(_today())
    task_items = _incomplete(tasks_api.list_tasks(tasklist_id, due_min=start, due_max=end))
    return digest.shrink_list(task_items)


def overdue_tool(tasklist: str | None = None) -> dict[str, Any]:
    tasklist_id = _resolve(tasklist)
    start, _end = digest.utc_day_bounds(_today())
    task_items = _incomplete(tasks_api.list_tasks(tasklist_id, due_max=start))
    return digest.shrink_list(task_items)


def upcoming_tool(days: int = 7, tasklist: str | None = None) -> dict[str, Any]:
    bounded_days = max(1, min(days, 365))
    tasklist_id = _resolve(tasklist)
    start, _ = digest.utc_day_bounds(_today())
    end_day = _today() + timedelta(days=bounded_days + 1)
    end, _unused = digest.utc_day_bounds(end_day)
    task_items = _incomplete(tasks_api.list_tasks(tasklist_id, due_min=start, due_max=end))
    return digest.shrink_list(task_items)


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
    tasklist_id = _resolve(tasklist)
    task_items = tasks_api.list_tasks(
        tasklist_id,
        show_completed=include_completed,
        max_results=max(100, bounded_limit),
    )
    matches = []
    for task in task_items:
        haystack = f"{task.get('title', '')}\n{task.get('notes', '')}".casefold()
        if needle in haystack and (include_completed or task.get("status") != "completed"):
            matches.append(task)
        if len(matches) >= bounded_limit:
            break
    return digest.shrink_list(matches)


def get_task_tool(id: str, tasklist: str | None = None) -> dict[str, Any]:
    task = tasks_api.get_task(_resolve(tasklist), id)
    return digest.shrink_task(task, include_notes=True)


def digest_tool(tasklist: str | None = None) -> dict[str, str]:
    task_items = _incomplete(tasks_api.list_tasks(_resolve(tasklist), max_results=100))
    return {"text": digest.text_digest(task_items)}


def add_tool(
    title: str,
    notes: str | None = None,
    due: str | None = None,
    tasklist: str | None = None,
) -> dict[str, Any]:
    created = tasks_api.insert_task(_resolve(tasklist), title=title, notes=notes, due=due)
    return digest.shrink_task(created)


def complete_tool(id: str, tasklist: str | None = None) -> dict[str, str]:
    completed = tasks_api.complete_task(_resolve(tasklist), id)
    return {"id": completed.get("id", id), "status": "completed"}


def update_tool(
    id: str,
    title: str | None = None,
    notes: str | None = None,
    due: str | None = None,
    tasklist: str | None = None,
) -> dict[str, Any]:
    updated = tasks_api.update_task(_resolve(tasklist), id, title=title, notes=notes, due=due)
    return digest.shrink_task(updated)


def delete_tool(id: str, tasklist: str | None = None) -> dict[str, Any]:
    tasks_api.delete_task(_resolve(tasklist), id)
    return {"id": id, "deleted": True}


def move_tool(id: str, tasklist: str, from_tasklist: str | None = None) -> dict[str, Any]:
    target_tasklist_id = _resolve(tasklist)
    source_tasklist_id = _resolve(from_tasklist)

    if source_tasklist_id == target_tasklist_id:
        moved = tasks_api.move_task(source_tasklist_id, id)
        return digest.shrink_task(moved)

    original = tasks_api.get_task(source_tasklist_id, id)
    moved = tasks_api.insert_task(
        target_tasklist_id,
        title=original.get("title", ""),
        notes=original.get("notes"),
        due=_due_date(original),
    )
    tasks_api.delete_task(source_tasklist_id, id)
    return digest.shrink_task(moved)


def create_mcp_server() -> FastMCP:
    mcp = FastMCP(
        "google-tasks-mcp",
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    tool_map: dict[str, Callable[..., Any]] = {
        "list_tasklists": list_tasklists_tool,
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
