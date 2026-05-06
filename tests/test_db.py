from __future__ import annotations

from google_tasks_mcp import db


def test_save_token_then_get_token_round_trips(configured_env):
    db.save_token("refresh", "access", 1234, "scope-a scope-b")

    token = db.get_token()

    assert token is not None
    assert token.refresh_token == "refresh"
    assert token.access_token == "access"
    assert token.access_expires_at == 1234
    assert token.scope == "scope-a scope-b"


def test_update_access_token_does_not_clobber_refresh(configured_env):
    db.save_token("refresh", "old-access", 1234, "scope")

    db.update_access_token("new-access", 5678)
    token = db.get_token()

    assert token is not None
    assert token.refresh_token == "refresh"
    assert token.access_token == "new-access"
    assert token.access_expires_at == 5678
    assert token.scope == "scope"


def test_tasklist_cache_round_trips(configured_env):
    db.upsert_tasklist("list-1", "Inbox")
    db.upsert_tasklist("list-2", "Work")
    db.upsert_tasklist("list-1", "Inbox Updated")

    cached = db.list_tasklists_cached()

    assert [(item.id, item.title) for item in cached] == [
        ("list-1", "Inbox Updated"),
        ("list-2", "Work"),
    ]
