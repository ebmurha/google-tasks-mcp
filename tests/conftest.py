from __future__ import annotations

import pytest

from google_tasks_mcp.account import DEFAULT_ACCOUNT_ID, set_current_account_id
from google_tasks_mcp.config import reset_settings_cache
from google_tasks_mcp.tasks import clear_tasklist_cache


@pytest.fixture(autouse=True)
def reset_global_state(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in [
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "GOOGLE_OAUTH_KEYS_PATH",
        "MCP_BEARER_TOKEN",
        "DB_PATH",
        "BIND_HOST",
        "BIND_PORT",
        "LOG_LEVEL",
        "DEFAULT_TASKLIST",
        "GOOGLE_TASKS_MCP_DEFAULT_TZ",
    ]:
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()
    set_current_account_id(DEFAULT_ACCOUNT_ID)
    clear_tasklist_cache()
    yield
    reset_settings_cache()
    set_current_account_id(DEFAULT_ACCOUNT_ID)
    clear_tasklist_cache()


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8787/callback")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "bearer-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    reset_settings_cache()
    return tmp_path
