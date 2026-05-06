"""Thin Google Tasks API wrapper."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import db
from .auth import get_credentials
from .config import get_settings
from .errors import GoogleTasksApiError


TASKLIST_CACHE_SECONDS = 300
_tasklist_cache: tuple[float, list[dict[str, Any]]] | None = None


def _service() -> Any:
    return build("tasks", "v1", credentials=get_credentials(), cache_discovery=False)


def _execute(request: Any) -> Any:
    try:
        return request.execute()
    except HttpError as exc:
        raise GoogleTasksApiError("Google Tasks API request failed") from exc


def clear_tasklist_cache() -> None:
    global _tasklist_cache
    _tasklist_cache = None


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
    global _tasklist_cache

    now = time.time()
    if _tasklist_cache and now - _tasklist_cache[0] < TASKLIST_CACHE_SECONDS:
        return list(_tasklist_cache[1])

    service = _service()
    result = _execute(service.tasklists().list(maxResults=100))
    tasklists = result.get("items", []) if isinstance(result, dict) else []
    compact = [
        {"id": item["id"], "title": item.get("title", "")}
        for item in tasklists
        if item.get("id")
    ]
    for item in compact:
        db.upsert_tasklist(item["id"], item["title"])
    _tasklist_cache = (now, compact)
    return list(compact)


def resolve_tasklist(title_or_id: str | None = None) -> str:
    settings = get_settings()
    requested = (title_or_id or settings.default_tasklist or "").strip()

    cached = db.list_tasklists_cached()
    if requested:
        for item in cached:
            if requested == item.id or requested.casefold() == item.title.casefold():
                return item.id

    tasklists = list_tasklists()
    if not tasklists:
        raise GoogleTasksApiError("No Google tasklists were found")

    if requested:
        for item in tasklists:
            title = item.get("title", "")
            if requested == item.get("id") or requested.casefold() == title.casefold():
                return item["id"]
        raise GoogleTasksApiError(f"Tasklist not found: {requested}")

    return tasklists[0]["id"]


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
