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
    db.replace_tasklist_cache([("list-2", "Work"), ("list-1", "Inbox")])

    cached = db.list_tasklists_cached()

    assert [(item.id, item.title) for item in cached] == [
        ("list-2", "Work"),
        ("list-1", "Inbox"),
    ]


def test_replace_tasklist_cache_removes_stale_rows(configured_env):
    db.replace_tasklist_cache([("list-1", "Inbox"), ("list-2", "Work")])
    db.replace_tasklist_cache([("list-2", "Work Renamed")])

    cached = db.list_tasklists_cached()

    assert [(item.id, item.title) for item in cached] == [("list-2", "Work Renamed")]


def test_delete_and_clear_tasklist_cache(configured_env):
    db.replace_tasklist_cache([("list-1", "Inbox"), ("list-2", "Work")])

    db.delete_tasklist_cached("list-1")

    assert [(item.id, item.title) for item in db.list_tasklists_cached()] == [("list-2", "Work")]

    db.clear_tasklist_cache()

    assert db.list_tasklists_cached() == []
