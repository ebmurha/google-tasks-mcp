"""In-process tasklist resolver with title lookup and duplicate detection."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import db
from .account import get_current_account_id
from .auth import get_credentials
from .config import get_settings
from .errors import AmbiguousTitleError, ConfigError, GoogleTasksApiError, NotFoundError


# SQLite tier is write-through; never authoritative; invalidate on every tasklist mutation.
TASKLIST_CACHE_SECONDS = 300


@dataclass(frozen=True)
class TasklistEntry:
    id: str
    title: str
    updated: str | None = None


@dataclass
class _Cache:
    fetched_at: float
    by_id: dict[str, TasklistEntry]
    by_title: dict[str, list[str]]


_caches: dict[str, _Cache] = {}
_refresh_lock = threading.Lock()


def _service() -> Any:
    return build("tasks", "v1", credentials=get_credentials(), cache_discovery=False)


def _execute(request: Any) -> Any:
    try:
        return request.execute()
    except HttpError as exc:
        raise GoogleTasksApiError("Google Tasks API request failed") from exc


def _normalize_title(value: str) -> str:
    return value.strip().casefold()


def _is_fresh(now: float | None = None) -> bool:
    cache = _caches.get(get_current_account_id())
    if cache is None:
        return False
    checked_at = time.time() if now is None else now
    return checked_at - cache.fetched_at < TASKLIST_CACHE_SECONDS


def invalidate() -> None:
    """Drop the in-memory tasklist cache."""

    with _refresh_lock:
        _caches.pop(get_current_account_id(), None)


def clear_tasklist_cache() -> None:
    """Drop both in-memory and SQLite tasklist cache tiers."""

    account_id = get_current_account_id()
    with _refresh_lock:
        _caches.pop(account_id, None)
        try:
            db.clear_tasklist_cache(account_id=account_id)
        except ConfigError:
            pass


def delete_tasklist_cached(tasklist_id: str) -> None:
    """Drop a deleted tasklist from both cache tiers."""

    account_id = get_current_account_id()
    with _refresh_lock:
        _caches.pop(account_id, None)
        try:
            db.delete_tasklist_cached(tasklist_id, account_id=account_id)
        except ConfigError:
            pass


def _build_cache(entries: list[TasklistEntry], fetched_at: float) -> _Cache:
    by_id: dict[str, TasklistEntry] = {}
    by_title: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        by_id[entry.id] = entry
        by_title[_normalize_title(entry.title)].append(entry.id)
    return _Cache(fetched_at=fetched_at, by_id=by_id, by_title=dict(by_title))


def _seed_from_sqlite(now: float, account_id: str) -> _Cache | None:
    rows = db.list_tasklists_cached(account_id=account_id)
    if not rows:
        return None

    oldest_updated_at = min(row.updated_at for row in rows)
    if now - oldest_updated_at >= TASKLIST_CACHE_SECONDS:
        return None

    entries = [TasklistEntry(id=row.id, title=row.title) for row in rows]
    return _build_cache(entries, fetched_at=float(oldest_updated_at))


def _refresh(*, force: bool = False) -> _Cache:
    account_id = get_current_account_id()

    now = time.time()
    if not force and _is_fresh(now):
        return _caches[account_id]

    with _refresh_lock:
        now = time.time()
        if not force and _is_fresh(now):
            return _caches[account_id]

        if not force:
            seeded = _seed_from_sqlite(now, account_id)
            if seeded is not None:
                _caches[account_id] = seeded
                return seeded

        service = _service()
        entries: list[TasklistEntry] = []
        page_token: str | None = None

        while True:
            params: dict[str, Any] = {"maxResults": 100}
            if page_token:
                params["pageToken"] = page_token
            result = _execute(service.tasklists().list(**params))
            if isinstance(result, dict):
                for item in result.get("items", []) or []:
                    tasklist_id = item.get("id")
                    if not tasklist_id:
                        continue
                    entry = TasklistEntry(
                        id=str(tasklist_id),
                        title=str(item.get("title") or ""),
                        updated=item.get("updated"),
                    )
                    entries.append(entry)
                page_token = result.get("nextPageToken")
            else:
                page_token = None
            if not page_token:
                break

        cache = _build_cache(entries, fetched_at=now)
        _caches[account_id] = cache
        db.replace_tasklist_cache(
            ((entry.id, entry.title) for entry in cache.by_id.values()),
            account_id=account_id,
        )
        return cache


def list_tasklists() -> list[dict[str, str]]:
    """Return compact tasklist entries from the memory cache."""

    cache = _refresh()
    return [{"id": item.id, "title": item.title} for item in cache.by_id.values()]


def _candidate_payload(ids: list[str], cache: _Cache) -> list[dict[str, str | None]]:
    return [
        {"id": tasklist_id, "title": cache.by_id[tasklist_id].title, "updated": cache.by_id[tasklist_id].updated}
        for tasklist_id in ids
        if tasklist_id in cache.by_id
    ]


def resolve_tasklist_by_title(title: str) -> str:
    """Resolve a tasklist title to its ID, refreshing once on a miss."""

    query = title.strip()
    normalized = _normalize_title(query)
    cache = _refresh()
    ids = cache.by_title.get(normalized, [])
    if not ids:
        cache = _refresh(force=True)
        ids = cache.by_title.get(normalized, [])
    if len(ids) > 1:
        raise AmbiguousTitleError(
            f"Multiple tasklists match title '{query}'",
            candidates=_candidate_payload(ids, cache),
            query=query,
        )
    if not ids:
        raise NotFoundError(f"Tasklist not found: {query}", query=query)
    return ids[0]


def resolve_tasklist(title_or_id: str | None = None) -> str:
    """Resolve a tasklist ID or title, defaulting to configured or first list."""

    settings = get_settings()
    requested = (title_or_id or settings.default_tasklist or "").strip()
    cache = _refresh()

    if requested:
        if requested in cache.by_id:
            return requested
        return resolve_tasklist_by_title(requested)

    if not cache.by_id:
        raise NotFoundError("No Google tasklists were found")
    return next(iter(cache.by_id))


def get_tasklist_title(tasklist_id: str) -> str:
    """Return the title for a known tasklist ID."""

    cache = _refresh()
    entry = cache.by_id.get(tasklist_id)
    if entry is None:
        cache = _refresh(force=True)
        entry = cache.by_id.get(tasklist_id)
    if entry is None:
        raise NotFoundError(f"Tasklist not found: {tasklist_id}", query=tasklist_id)
    return entry.title
