from __future__ import annotations

from google_tasks_mcp.account import reset_current_account_id, set_current_account_id
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


def test_google_tokens_are_account_scoped(configured_env):
    db.save_token("default-refresh", "default-access", 1234, "scope", account_id="default")
    db.save_token("work-refresh", "work-access", 5678, "scope", account_id="work")

    default_token = db.get_token("default")
    work_token = db.get_token("work")

    assert default_token is not None
    assert work_token is not None
    assert default_token.refresh_token == "default-refresh"
    assert work_token.refresh_token == "work-refresh"


def test_tasklist_cache_is_account_scoped(configured_env):
    db.replace_tasklist_cache([("default-list", "Default")], account_id="default")
    db.replace_tasklist_cache([("work-list", "Work")], account_id="work")

    assert [(item.id, item.title) for item in db.list_tasklists_cached(account_id="default")] == [
        ("default-list", "Default")
    ]
    assert [(item.id, item.title) for item in db.list_tasklists_cached(account_id="work")] == [
        ("work-list", "Work")
    ]


def test_tasklist_cache_uses_current_account_context(configured_env):
    db.replace_tasklist_cache([("work-list", "Work")], account_id="work")
    token = set_current_account_id("work")
    try:
        assert [(item.id, item.title) for item in db.list_tasklists_cached()] == [("work-list", "Work")]
    finally:
        reset_current_account_id(token)


def test_bearer_token_lookup_uses_hash_and_enabled_flag(configured_env):
    token_hash = db.bearer_token_hash("secret-token")
    db.save_bearer_token(account_id="work", token_hash=token_hash, label="Work")

    record = db.get_bearer_token("secret-token")

    assert record is not None
    assert record.account_id == "work"
    assert record.label == "Work"
    assert record.enabled is True
    assert record.token_hash == token_hash

    db.revoke_bearer_token_hash(token_hash)

    revoked = db.get_bearer_token("secret-token")
    assert revoked is not None
    assert revoked.enabled is False


def test_mcp_oauth_refresh_tokens_rotate_and_do_not_store_raw_values(configured_env):
    db.save_mcp_oauth_refresh_token("refresh-token", "mcp-client", 9999999999)

    record = db.consume_mcp_oauth_refresh_token("refresh-token")
    replay = db.consume_mcp_oauth_refresh_token("refresh-token")

    assert record == {"client_id": "mcp-client", "expires_at": 9999999999}
    assert replay is None

    with db._connect() as conn:
        rows = conn.execute("SELECT token_hash FROM mcp_oauth_refresh_tokens").fetchall()
    assert all(row["token_hash"] != "refresh-token" for row in rows)


def test_mcp_oauth_refresh_token_backend(configured_env):
    backend = db.McpOAuthRefreshTokenBackend()

    backend.save("refresh-token", {"client_id": "mcp-client", "expires_at": 9999999999})
    record = backend.consume("refresh-token")

    assert record == {"client_id": "mcp-client", "expires_at": 9999999999}
    assert backend.consume("refresh-token") is None
