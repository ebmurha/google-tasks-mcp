"""Thin Google Tasks API wrapper."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import get_credentials
from . import resolver
from .errors import AmbiguousTitleError, GoogleTasksApiError, InvalidInputError, NotFoundError


def _service() -> Any:
    return build("tasks", "v1", credentials=get_credentials(), cache_discovery=False)


def _execute(request: Any) -> Any:
    try:
        return request.execute()
    except HttpError as exc:
        raise GoogleTasksApiError("Google Tasks API request failed") from exc


def clear_tasklist_cache() -> None:
    resolver.clear_tasklist_cache()


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


def get_tasklist_title(tasklist_id: str) -> str:
    return resolver.get_tasklist_title(tasklist_id)


def create_tasklist(*, title: str) -> dict[str, Any]:
    clean_title = title.strip()
    if not clean_title:
        raise InvalidInputError("Tasklist title is required")
    service = _service()
    created = _execute(service.tasklists().insert(body={"title": clean_title}))
    resolver.clear_tasklist_cache()
    return created


def get_tasklist(tasklist_id: str) -> dict[str, Any]:
    service = _service()
    return _execute(service.tasklists().get(tasklist=tasklist_id))


def update_tasklist(tasklist_id: str, *, title: str) -> dict[str, Any]:
    clean_title = title.strip()
    if not tasklist_id.strip():
        raise InvalidInputError("Tasklist id is required")
    if not clean_title:
        raise InvalidInputError("New tasklist title is required")
    service = _service()
    updated = _execute(service.tasklists().patch(tasklist=tasklist_id, body={"title": clean_title}))
    resolver.clear_tasklist_cache()
    return updated


def delete_tasklist(tasklist_id: str) -> None:
    if not tasklist_id.strip():
        raise InvalidInputError("Tasklist id is required")
    service = _service()
    _execute(service.tasklists().delete(tasklist=tasklist_id))
    resolver.delete_tasklist_cached(tasklist_id)


def resolve_task_by_title(
    tasklist_id: str,
    title: str,
    *,
    include_completed: bool = False,
    tasklist_title: str | None = None,
) -> str:
    query = title.strip()
    tasklist_name = tasklist_title or get_tasklist_title(tasklist_id)
    candidates = []
    for task in list_tasks(tasklist_id, show_completed=include_completed, max_results=100):
        if task.get("deleted") is True:
            continue
        if not include_completed and task.get("status") == "completed":
            continue
        if str(task.get("title") or "").strip().casefold() == query.casefold():
            candidates.append(task)

    if len(candidates) == 1:
        return str(candidates[0]["id"])
    if len(candidates) > 1:
        raise AmbiguousTitleError(
            f"Multiple active tasks match title '{query}'",
            candidates=[
                {
                    "id": task.get("id"),
                    "title": task.get("title", ""),
                    "due": str(task.get("due")).split("T", 1)[0] if task.get("due") else None,
                    "tasklist_title": tasklist_name,
                }
                for task in candidates
            ],
            query=query,
            searched_tasklist=tasklist_name,
        )
    raise NotFoundError(
        f"No active task matching '{query}' in tasklist '{tasklist_name}'",
        searched_tasklist=tasklist_name,
        query=query,
    )


def list_tasks(
    tasklist_id: str,
    *,
    show_completed: bool = False,
    show_deleted: bool = False,
    show_hidden: bool | None = None,
    show_assigned: bool = False,
    due_min: str | None = None,
    due_max: str | None = None,
    completed_min: str | None = None,
    completed_max: str | None = None,
    updated_min: str | None = None,
    max_results: int = 100,
    page_token: str | None = None,
) -> list[dict[str, Any]]:
    bounded_max = max(1, min(max_results, 1000))
    items: list[dict[str, Any]] = []
    next_page_token = page_token
    while len(items) < bounded_max:
        result = list_tasks_page(
            tasklist_id,
            show_completed=show_completed,
            show_deleted=show_deleted,
            show_hidden=show_hidden,
            show_assigned=show_assigned,
            due_min=due_min,
            due_max=due_max,
            completed_min=completed_min,
            completed_max=completed_max,
            updated_min=updated_min,
            max_results=min(bounded_max - len(items), 100),
            page_token=next_page_token,
        )
        if not isinstance(result, dict):
            break
        page_items = result.get("items", []) or []
        items.extend(page_items)
        next_page_token = result.get("nextPageToken")
        if not next_page_token or not page_items:
            break
    return items


def list_tasks_page(
    tasklist_id: str,
    *,
    show_completed: bool = False,
    show_deleted: bool = False,
    show_hidden: bool | None = None,
    show_assigned: bool = False,
    due_min: str | None = None,
    due_max: str | None = None,
    completed_min: str | None = None,
    completed_max: str | None = None,
    updated_min: str | None = None,
    max_results: int = 100,
    page_token: str | None = None,
) -> dict[str, Any]:
    service = _service()
    params: dict[str, Any] = {
        "tasklist": tasklist_id,
        "showCompleted": show_completed,
        "showDeleted": show_deleted,
        "showHidden": show_completed if show_hidden is None else show_hidden,
        "showAssigned": show_assigned,
        "maxResults": max(1, min(max_results, 100)),
    }
    if page_token:
        params["pageToken"] = page_token
    if due_min:
        params["dueMin"] = due_min
    if due_max:
        params["dueMax"] = due_max
    if completed_min:
        params["completedMin"] = completed_min
    if completed_max:
        params["completedMax"] = completed_max
    if updated_min:
        params["updatedMin"] = updated_min
    result = _execute(service.tasks().list(**params))
    return result if isinstance(result, dict) else {}


def get_task(tasklist_id: str, task_id: str) -> dict[str, Any]:
    service = _service()
    return _execute(service.tasks().get(tasklist=tasklist_id, task=task_id))


def insert_task(
    tasklist_id: str,
    *,
    title: str,
    notes: str | None = None,
    due: str | None = None,
    parent: str | None = None,
    previous: str | None = None,
) -> dict[str, Any]:
    service = _service()
    body: dict[str, Any] = {"title": title}
    if notes is not None:
        body["notes"] = notes
    if due is not None:
        body["due"] = date_to_rfc3339(due)
    params: dict[str, Any] = {"tasklist": tasklist_id, "body": body}
    if parent is not None:
        params["parent"] = parent
    if previous is not None:
        params["previous"] = previous
    return _execute(service.tasks().insert(**params))


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


def clear_completed(tasklist_id: str) -> None:
    service = _service()
    _execute(service.tasks().clear(tasklist=tasklist_id))


def move_task(
    tasklist_id: str,
    task_id: str,
    *,
    parent: str | None = None,
    previous: str | None = None,
    destination_tasklist: str | None = None,
) -> dict[str, Any]:
    service = _service()
    params: dict[str, Any] = {"tasklist": tasklist_id, "task": task_id}
    if parent is not None:
        params["parent"] = parent
    if previous is not None:
        params["previous"] = previous
    if destination_tasklist is not None:
        params["destinationTasklist"] = destination_tasklist
    return _execute(service.tasks().move(**params))
