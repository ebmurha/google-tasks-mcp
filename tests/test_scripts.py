from __future__ import annotations

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
