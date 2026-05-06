"""SQLite persistence boundary."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .config import get_settings


@dataclass(frozen=True)
class Token:
    refresh_token: str
    access_token: str | None
    access_expires_at: int | None
    scope: str
    updated_at: int


@dataclass(frozen=True)
class Tasklist:
    id: str
    title: str
    updated_at: int


SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_token (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    refresh_token TEXT NOT NULL,
    access_token TEXT,
    access_expires_at INTEGER,
    scope TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tasklist_cache (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


def _db_path() -> Path:
    return get_settings().db_path


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> int:
    return int(time.time())


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def get_token() -> Token | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT refresh_token, access_token, access_expires_at, scope, updated_at
            FROM oauth_token
            WHERE id = 1
            """
        ).fetchone()
    if row is None:
        return None
    return Token(
        refresh_token=row["refresh_token"],
        access_token=row["access_token"],
        access_expires_at=row["access_expires_at"],
        scope=row["scope"],
        updated_at=row["updated_at"],
    )


def save_token(refresh: str, access: str | None, expires_at: int | None, scope: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO oauth_token (
                id, refresh_token, access_token, access_expires_at, scope, updated_at
            )
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                refresh_token = excluded.refresh_token,
                access_token = excluded.access_token,
                access_expires_at = excluded.access_expires_at,
                scope = excluded.scope,
                updated_at = excluded.updated_at
            """,
            (refresh, access, expires_at, scope, _now()),
        )


def update_access_token(access: str, expires_at: int) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE oauth_token
            SET access_token = ?, access_expires_at = ?, updated_at = ?
            WHERE id = 1
            """,
            (access, expires_at, _now()),
        )


def list_tasklists_cached() -> list[Tasklist]:
    init_db()
    with _connect() as conn:
        rows: Iterator[sqlite3.Row] = conn.execute(
            """
            SELECT id, title, updated_at
            FROM tasklist_cache
            ORDER BY title COLLATE NOCASE ASC
            """
        )
        return [
            Tasklist(id=row["id"], title=row["title"], updated_at=row["updated_at"])
            for row in rows
        ]


def upsert_tasklist(id: str, title: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO tasklist_cache (id, title, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                updated_at = excluded.updated_at
            """,
            (id, title, _now()),
        )
