"""SQLite persistence boundary."""

from __future__ import annotations

import sqlite3
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from .account import DEFAULT_ACCOUNT_ID, get_current_account_id
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


@dataclass(frozen=True)
class BearerToken:
    token_hash: str
    account_id: str
    label: str | None
    enabled: bool
    created_at: int
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

CREATE TABLE IF NOT EXISTS google_oauth_tokens (
    account_id TEXT PRIMARY KEY,
    refresh_token TEXT NOT NULL,
    access_token TEXT,
    access_expires_at INTEGER,
    scope TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS account_tasklist_cache (
    account_id TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (account_id, id)
);

CREATE TABLE IF NOT EXISTS bearer_tokens (
    token_hash TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_oauth_refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
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


def _account_id(account_id: str | None = None) -> str:
    return (account_id or get_current_account_id() or DEFAULT_ACCOUNT_ID).strip() or DEFAULT_ACCOUNT_ID


def bearer_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def get_token(account_id: str | None = None) -> Token | None:
    init_db()
    selected_account = _account_id(account_id)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT refresh_token, access_token, access_expires_at, scope, updated_at
            FROM google_oauth_tokens
            WHERE account_id = ?
            """,
            (selected_account,),
        ).fetchone()
        if row is None and selected_account == DEFAULT_ACCOUNT_ID:
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


def save_token(
    refresh: str,
    access: str | None,
    expires_at: int | None,
    scope: str,
    *,
    account_id: str | None = None,
) -> None:
    init_db()
    selected_account = _account_id(account_id)
    updated_at = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO google_oauth_tokens (
                account_id, refresh_token, access_token, access_expires_at, scope, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                refresh_token = excluded.refresh_token,
                access_token = excluded.access_token,
                access_expires_at = excluded.access_expires_at,
                scope = excluded.scope,
                updated_at = excluded.updated_at
            """,
            (selected_account, refresh, access, expires_at, scope, updated_at),
        )
        if selected_account == DEFAULT_ACCOUNT_ID:
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
                (refresh, access, expires_at, scope, updated_at),
            )


def update_access_token(access: str, expires_at: int, *, account_id: str | None = None) -> None:
    init_db()
    selected_account = _account_id(account_id)
    updated_at = _now()
    with _connect() as conn:
        result = conn.execute(
            """
            UPDATE google_oauth_tokens
            SET access_token = ?, access_expires_at = ?, updated_at = ?
            WHERE account_id = ?
            """,
            (access, expires_at, updated_at, selected_account),
        )
        if selected_account == DEFAULT_ACCOUNT_ID:
            conn.execute(
                """
                UPDATE oauth_token
                SET access_token = ?, access_expires_at = ?, updated_at = ?
                WHERE id = 1
                """,
                (access, expires_at, updated_at),
            )
        if result.rowcount == 0 and selected_account != DEFAULT_ACCOUNT_ID:
            raise ValueError(f"No OAuth token row exists for account_id={selected_account!r}")


def list_tasklists_cached(account_id: str | None = None) -> list[Tasklist]:
    init_db()
    selected_account = _account_id(account_id)
    with _connect() as conn:
        rows: Iterator[sqlite3.Row] = conn.execute(
            """
            SELECT id, title, updated_at
            FROM account_tasklist_cache
            WHERE account_id = ?
            ORDER BY rowid ASC
            """,
            (selected_account,),
        )
        cached = [Tasklist(id=row["id"], title=row["title"], updated_at=row["updated_at"]) for row in rows]
        if cached or selected_account != DEFAULT_ACCOUNT_ID:
            return cached
        legacy_rows: Iterator[sqlite3.Row] = conn.execute(
            """
            SELECT id, title, updated_at
            FROM tasklist_cache
            ORDER BY rowid ASC
            """
        )
        return [Tasklist(id=row["id"], title=row["title"], updated_at=row["updated_at"]) for row in legacy_rows]


def replace_tasklist_cache(entries: Iterable[tuple[str, str]], *, account_id: str | None = None) -> None:
    init_db()
    selected_account = _account_id(account_id)
    rows = [(tasklist_id, title, _now()) for tasklist_id, title in entries]
    with _connect() as conn:
        conn.execute("DELETE FROM account_tasklist_cache WHERE account_id = ?", (selected_account,))
        conn.executemany(
            """
            INSERT INTO account_tasklist_cache (account_id, id, title, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            [(selected_account, tasklist_id, title, updated_at) for tasklist_id, title, updated_at in rows],
        )
        if selected_account == DEFAULT_ACCOUNT_ID:
            conn.execute("DELETE FROM tasklist_cache")
            conn.executemany(
                """
                INSERT INTO tasklist_cache (id, title, updated_at)
                VALUES (?, ?, ?)
                """,
                rows,
            )


def delete_tasklist_cached(id: str, *, account_id: str | None = None) -> None:
    init_db()
    selected_account = _account_id(account_id)
    with _connect() as conn:
        conn.execute(
            "DELETE FROM account_tasklist_cache WHERE account_id = ? AND id = ?",
            (selected_account, id),
        )
        if selected_account == DEFAULT_ACCOUNT_ID:
            conn.execute("DELETE FROM tasklist_cache WHERE id = ?", (id,))


def clear_tasklist_cache(*, account_id: str | None = None) -> None:
    init_db()
    selected_account = _account_id(account_id)
    with _connect() as conn:
        conn.execute("DELETE FROM account_tasklist_cache WHERE account_id = ?", (selected_account,))
        if selected_account == DEFAULT_ACCOUNT_ID:
            conn.execute("DELETE FROM tasklist_cache")


def save_bearer_token(
    *,
    account_id: str,
    token_hash: str,
    label: str | None = None,
    enabled: bool = True,
) -> None:
    init_db()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO bearer_tokens (token_hash, account_id, label, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(token_hash) DO UPDATE SET
                account_id = excluded.account_id,
                label = excluded.label,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (token_hash, account_id, label, 1 if enabled else 0, now, now),
        )


def get_bearer_token(token: str) -> BearerToken | None:
    init_db()
    token_hash = bearer_token_hash(token)
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT token_hash, account_id, label, enabled, created_at, updated_at
            FROM bearer_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    if row is None:
        return None
    return BearerToken(
        token_hash=row["token_hash"],
        account_id=row["account_id"],
        label=row["label"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def revoke_bearer_token_hash(token_hash: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE bearer_tokens
            SET enabled = 0, updated_at = ?
            WHERE token_hash = ?
            """,
            (_now(), token_hash),
        )


def _oauth_refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def save_mcp_oauth_refresh_token(token: str, client_id: str, expires_at: float) -> None:
    init_db()
    now = _now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mcp_oauth_refresh_tokens (token_hash, client_id, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(token_hash) DO UPDATE SET
                client_id = excluded.client_id,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (_oauth_refresh_token_hash(token), client_id, int(expires_at), now, now),
        )


def consume_mcp_oauth_refresh_token(token: str) -> dict[str, int | str] | None:
    init_db()
    token_hash = _oauth_refresh_token_hash(token)
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT client_id, expires_at
            FROM mcp_oauth_refresh_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        conn.execute("DELETE FROM mcp_oauth_refresh_tokens WHERE token_hash = ?", (token_hash,))
    if row is None or row["expires_at"] < now:
        return None
    return {"client_id": row["client_id"], "expires_at": row["expires_at"]}


def revoke_mcp_oauth_refresh_token(token: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM mcp_oauth_refresh_tokens WHERE token_hash = ?",
            (_oauth_refresh_token_hash(token),),
        )


def purge_expired_mcp_oauth_refresh_tokens() -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM mcp_oauth_refresh_tokens WHERE expires_at < ?",
            (_now(),),
        )


class McpOAuthRefreshTokenBackend:
    """SQLite-backed MCP OAuth refresh-token store; raw tokens are never persisted."""

    def save(self, token: str, record: dict[str, Any]) -> None:
        save_mcp_oauth_refresh_token(
            token,
            client_id=str(record["client_id"]),
            expires_at=float(record["expires_at"]),
        )

    def consume(self, token: str) -> dict[str, Any] | None:
        record = consume_mcp_oauth_refresh_token(token)
        return dict(record) if record is not None else None

    def revoke(self, token: str) -> None:
        revoke_mcp_oauth_refresh_token(token)

    def purge_expired(self) -> None:
        purge_expired_mcp_oauth_refresh_tokens()
