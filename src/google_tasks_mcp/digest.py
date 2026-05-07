"""Compact Google Tasks response formatters."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


MAX_NOTES_CHARS = 200


def _date_only(value: str | None) -> str | None:
    if not value:
        return None
    if "T" in value:
        return value.split("T", 1)[0]
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return value[:10]


def _truncate_notes(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= MAX_NOTES_CHARS:
        return value
    return value[:MAX_NOTES_CHARS] + "..."


def shrink_task(t: dict[str, Any], *, include_notes: bool = False) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "id": t.get("id"),
        "title": t.get("title", ""),
        "status": t.get("status", "needsAction"),
    }
    due = _date_only(t.get("due"))
    if due:
        compact["due"] = due
    if include_notes and t.get("notes") is not None:
        compact["notes"] = _truncate_notes(str(t.get("notes")))
    if include_notes:
        for source, target in (
            ("completed", "completed"),
            ("parent", "parent"),
            ("position", "position"),
            ("updated", "updated"),
            ("links", "links"),
            ("webViewLink", "web_view_link"),
        ):
            if t.get(source) is not None:
                compact[target] = t.get(source)
    return compact


def shrink_tasklist(tasklist: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "id": tasklist.get("id"),
        "title": tasklist.get("title", ""),
    }
    if tasklist.get("updated") is not None:
        compact["updated"] = tasklist.get("updated")
    return compact


def build_tasklist_response(
    tasklist: dict[str, Any],
    *,
    operation: str,
    tasks_deleted_count: int | None = None,
) -> dict[str, Any]:
    compact = shrink_tasklist(tasklist)
    title = str(compact.get("title") or "Untitled")
    if operation == "create":
        summary = f"Created tasklist '{title}'"
    elif operation == "update":
        summary = f"Renamed tasklist to '{title}'"
    elif operation == "delete":
        summary = f"Deleted tasklist '{title}'"
    else:
        summary = f"{operation.title()} tasklist '{title}'"
    compact["human_summary"] = summary
    if tasks_deleted_count is not None:
        compact["tasks_deleted_count"] = tasks_deleted_count
    return compact


def _human_summary(
    task: dict[str, Any],
    *,
    operation: str,
    tasklist_title: str,
    deleted: bool,
    changes: list[str] | None,
    move_target: str | None,
) -> str:
    title = str(task.get("title") or "Untitled")
    due = _date_only(task.get("due"))
    if operation == "add":
        due_phrase = f" due {due}" if due else ""
        return f"Created '{title}'{due_phrase} in {tasklist_title}"
    if operation == "complete":
        due_phrase = f" (was due {due})" if due else ""
        return f"Completed '{title}'{due_phrase}"
    if operation == "update":
        changed = ", ".join(changes or []) or "fields"
        return f"Updated '{title}': {changed}"
    if operation == "delete" or deleted:
        return f"Deleted '{title}' from {tasklist_title}"
    if operation == "move":
        return f"Moved '{title}' to {move_target or tasklist_title}"
    return f"{operation.title()} '{title}'"


def build_mutation_response(
    task: dict[str, Any],
    tasklist_id: str,
    tasklist_title: str,
    *,
    operation: str,
    deleted: bool = False,
    changes: list[str] | None = None,
    move_target: str | None = None,
) -> dict[str, Any]:
    """Build the rich mutation response shape shared by write tools."""

    return {
        "id": task.get("id"),
        "title": task.get("title", ""),
        "notes": task.get("notes"),
        "status": task.get("status", "needsAction"),
        "due": _date_only(task.get("due")),
        "completed": task.get("completed"),
        "parent": task.get("parent"),
        "position": task.get("position"),
        "updated": task.get("updated"),
        "links": task.get("links", []),
        "web_view_link": task.get("webViewLink"),
        "tasklist_id": tasklist_id,
        "tasklist_title": tasklist_title,
        "human_summary": _human_summary(
            task,
            operation=operation,
            tasklist_title=tasklist_title,
            deleted=deleted,
            changes=changes,
            move_target=move_target,
        ),
        **({"deleted": True} if deleted else {}),
    }


def full_task_object(
    task: dict[str, Any],
    tasklist_id: str,
    tasklist_title: str,
) -> dict[str, Any]:
    """Build the richer task shape used by general list responses."""

    return {
        "id": task.get("id"),
        "title": task.get("title", ""),
        "notes": task.get("notes"),
        "status": task.get("status", "needsAction"),
        "due": _date_only(task.get("due")),
        "completed": task.get("completed"),
        "parent": task.get("parent"),
        "position": task.get("position"),
        "updated": task.get("updated"),
        "links": task.get("links", []),
        "web_view_link": task.get("webViewLink"),
        "tasklist_id": tasklist_id,
        "tasklist_title": tasklist_title,
    }


def shrink_list(tasks: list[dict[str, Any]], *, include_notes: bool = False) -> dict[str, Any]:
    return {
        "count": len(tasks),
        "tasks": [shrink_task(task, include_notes=include_notes) for task in tasks],
    }


def _parse_due(value: str | None) -> date | None:
    due = _date_only(value)
    if not due:
        return None
    try:
        return date.fromisoformat(due)
    except ValueError:
        return None


def _days_phrase(due: date, today: date) -> str:
    delta = (today - due).days
    if delta == 1:
        return "yesterday"
    if delta > 1:
        return f"{delta}d ago"
    if delta == -1:
        return "tomorrow"
    if delta < -1:
        return f"in {-delta}d"
    return "today"


def text_digest(tasks: list[dict[str, Any]], *, group_by: str | None = "due") -> str:
    if not tasks:
        return "No tasks."

    today = date.today()
    due_today: list[str] = []
    overdue: list[str] = []
    upcoming: list[str] = []
    no_due: list[str] = []

    for task in tasks:
        title = str(task.get("title") or "Untitled")
        due = _parse_due(task.get("due"))
        if group_by != "due" or due is None:
            no_due.append(title)
        elif due < today:
            overdue.append(f"{title} ({_days_phrase(due, today)})")
        elif due == today:
            due_today.append(title)
        else:
            upcoming.append(f"{title} ({_days_phrase(due, today)})")

    lines: list[str] = []
    if due_today:
        lines.append(f"{len(due_today)} due today: " + ", ".join(f'"{t}"' for t in due_today))
    if overdue:
        lines.append(f"{len(overdue)} overdue: " + ", ".join(f'"{t}"' for t in overdue))
    if upcoming:
        lines.append(f"{len(upcoming)} upcoming: " + ", ".join(f'"{t}"' for t in upcoming))
    if no_due:
        lines.append(f"{len(no_due)} unscheduled: " + ", ".join(f'"{t}"' for t in no_due))
    return "\n".join(lines)


def utc_day_bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, datetime.min.time()).strftime("%Y-%m-%dT00:00:00.000Z")
    next_day = date.fromordinal(day.toordinal() + 1)
    end = datetime.combine(next_day, datetime.min.time()).strftime("%Y-%m-%dT00:00:00.000Z")
    return start, end
