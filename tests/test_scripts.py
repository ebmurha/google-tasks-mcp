from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

from google_tasks_mcp import __main__ as server_entrypoint
from google_tasks_mcp import db
from google_tasks_mcp.auth import _oauth_error_details, _oauth_error_message
from google_tasks_mcp.errors import AuthRequired
from google_tasks_mcp.scripts import bootstrap_oauth as installed_bootstrap_oauth
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


def test_bootstrap_failure_never_prints_provider_controlled_text(capsys):
    raw_provider_text = "token=secret-refresh-token\nFORGED log entry"
    provider_exception = ValueError("raw provider response")
    provider_exception.error = raw_provider_text  # type: ignore[attr-defined]
    sanitized = AuthRequired(
        _oauth_error_message(provider_exception),
        **_oauth_error_details(provider_exception),
    )
    with patch.object(
        installed_bootstrap_oauth,
        "build_authorization_flow",
        return_value=object(),
    ), patch.object(
        installed_bootstrap_oauth,
        "authorization_url",
        return_value="https://accounts.example/auth",
    ), patch("builtins.input", return_value="synthetic-code"), patch.object(
        installed_bootstrap_oauth,
        "exchange_code",
        side_effect=sanitized,
    ):
        assert installed_bootstrap_oauth.main([]) == 2

    captured = capsys.readouterr()
    assert captured.err == "bootstrap failed: OAuth code exchange failed\n"
    assert raw_provider_text not in captured.out + captured.err


def test_http_startup_bootstraps_refresh_token_from_environment(configured_env, monkeypatch):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "synthetic-refresh-token")
    uvicorn = SimpleNamespace(run=Mock())
    with patch.dict("sys.modules", {"uvicorn": uvicorn}), patch(
        "google_tasks_mcp.__main__.set_refresh_token"
    ) as set_token:
        assert server_entrypoint.main(["--transport", "http"]) == 0

    set_token.assert_called_once_with("synthetic-refresh-token")
    uvicorn.run.assert_called_once()


def test_http_startup_does_not_overwrite_existing_google_token(
    configured_env, monkeypatch
):
    db.save_token("stored-refresh-token", None, 0, "scope")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "stale-environment-token")
    uvicorn = SimpleNamespace(run=Mock())
    with patch.dict("sys.modules", {"uvicorn": uvicorn}), patch(
        "google_tasks_mcp.__main__.set_refresh_token"
    ) as set_token:
        assert server_entrypoint.main(["--transport", "http"]) == 0

    set_token.assert_not_called()
    assert db.get_token() is not None
    assert db.get_token().refresh_token == "stored-refresh-token"
