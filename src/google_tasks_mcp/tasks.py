"""Thin Google Tasks API wrapper."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import get_credentials
from . import resolver
from .errors import GoogleTasksApiError


def _service() -> Any:
    return build("tasks", "v1", credentials=get_credentials(), cache_discovery=False)


def _execute(request: Any) -> Any:
    try:
        return request.execute()
    except HttpError as exc:
        raise GoogleTasksApiError("Google Tasks API request failed") from exc


def clear_tasklist_cache() -> None:
    resolver.invalidate()


def date_to_rfc3339(value: str | date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00.000Z"
    raw = value.strip()
    if not raw:
        return None
    if "T" in raw:
        return raw
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise GoogleTasksApiError("Due date must be YYYY-MM-DD or RFC 3339") from exc
    return f"{parsed.isoformat()}T00:00:00.000Z"


def list_tasklists() -> list[dict[str, Any]]:
    return resolver.list_tasklists()


def resolve_tasklist(title_or_id: str | None = None) -> str:
    return resolver.resolve_tasklist(title_or_id)


def list_tasks(
    tasklist_id: str,
    *,
    show_completed: bool = False,
    due_min: str | None = None,
    due_max: str | None = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    service = _service()
    params: dict[str, Any] = {
        "tasklist": tasklist_id,
        "showCompleted": show_completed,
        "showHidden": show_completed,
        "maxResults": max_results,
    }
    if due_min:
        params["dueMin"] = due_min
    if due_max:
        params["dueMax"] = due_max
    result = _execute(service.tasks().list(**params))
    return result.get("items", []) if isinstance(result, dict) else []


def get_task(tasklist_id: str, task_id: str) -> dict[str, Any]:
    service = _service()
    return _execute(service.tasks().get(tasklist=tasklist_id, task=task_id))


def insert_task(
    tasklist_id: str,
    *,
    title: str,
    notes: str | None = None,
    due: str | None = None,
) -> dict[str, Any]:
    service = _service()
    body: dict[str, Any] = {"title": title}
    if notes is not None:
        body["notes"] = notes
    if due is not None:
        body["due"] = date_to_rfc3339(due)
    return _execute(service.tasks().insert(tasklist=tasklist_id, body=body))


def update_task(
    tasklist_id: str,
    task_id: str,
    *,
    title: str | None = None,
    notes: str | None = None,
    due: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    service = _service()
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if notes is not None:
        body["notes"] = notes
    if due is not None:
        body["due"] = date_to_rfc3339(due)
    if status is not None:
        body["status"] = status
    return _execute(service.tasks().patch(tasklist=tasklist_id, task=task_id, body=body))


def complete_task(tasklist_id: str, task_id: str) -> dict[str, Any]:
    return update_task(tasklist_id, task_id, status="completed")


def delete_task(tasklist_id: str, task_id: str) -> None:
    service = _service()
    _execute(service.tasks().delete(tasklist=tasklist_id, task=task_id))


def move_task(
    tasklist_id: str,
    task_id: str,
    *,
    parent: str | None = None,
    previous: str | None = None,
) -> dict[str, Any]:
    service = _service()
    params: dict[str, Any] = {"tasklist": tasklist_id, "task": task_id}
    if parent is not None:
        params["parent"] = parent
    if previous is not None:
        params["previous"] = previous
    return _execute(service.tasks().move(**params))
