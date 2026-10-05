from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from google_tasks_mcp import __main__ as server_entrypoint
from scripts import bootstrap_oauth, create_bearer_token, set_refresh_token


def test_bootstrap_help_exits_cleanly(capsys):
    try:
        bootstrap_oauth.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    output = capsys.readouterr().out
    assert "Bootstrap Google OAuth" in output


def test_set_refresh_token_help_exits_cleanly(capsys):
    try:
        set_refresh_token.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    output = capsys.readouterr().out
    assert "Store a Google OAuth refresh token" in output


def test_create_bearer_token_help_exits_cleanly(capsys):
    try:
        create_bearer_token.main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    output = capsys.readouterr().out
    assert "Create an MCP bearer token" in output


def test_http_startup_bootstraps_refresh_token_from_environment(configured_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "synthetic-refresh-token")
    uvicorn = SimpleNamespace(run=Mock())
    with patch.dict("sys.modules", {"uvicorn": uvicorn}), patch(
        "google_tasks_mcp.__main__.set_refresh_token"
    ) as set_token:
        assert server_entrypoint.main(["--transport", "http"]) == 0

    set_token.assert_called_once_with("synthetic-refresh-token")
    uvicorn.run.assert_called_once()
