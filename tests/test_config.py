from __future__ import annotations

import json

import pytest

from google_tasks_mcp.config import get_settings, reset_settings_cache
from google_tasks_mcp.errors import ConfigError


def test_settings_loads_from_env(configured_env):
    settings = get_settings()

    assert settings.google_client_id == "client-id"
    assert settings.google_client_secret == "client-secret"
    assert settings.google_redirect_uri == "http://localhost:8787/callback"
    assert settings.mcp_bearer_token == "bearer-token"
    assert settings.db_path == configured_env / "test.db"


@pytest.mark.parametrize(
    ("external_base_url", "expected"),
    [
        ("https://tasks.example.net", "https://tasks.example.net"),
        (
            "https://tasks.example.net/team/mcp-server/",
            "https://tasks.example.net/team/mcp-server",
        ),
    ],
)
def test_external_base_url_derives_google_callback(
    configured_env, monkeypatch, external_base_url, expected
):
    monkeypatch.setenv("EXTERNAL_BASE_URL", external_base_url)
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://stale.example/callback")
    reset_settings_cache()

    settings = get_settings()

    assert settings.external_base_url == expected
    assert settings.google_redirect_uri == f"{expected}/callback"


@pytest.mark.parametrize(
    "value",
    [
        "http://tasks.example.net",
        "https://tasks.example.net:8443",
        "https://tasks.example.net/base?mode=test",
    ],
)
def test_external_base_url_rejects_noncanonical_values(configured_env, monkeypatch, value):
    monkeypatch.setenv("EXTERNAL_BASE_URL", value)
    reset_settings_cache()

    with pytest.raises(ConfigError, match="EXTERNAL_BASE_URL"):
        get_settings()


def test_oauth_json_used_when_env_credentials_missing(monkeypatch, tmp_path):
    key_file = tmp_path / "gcp-oauth.keys.json"
    key_file.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "json-client",
                    "client_secret": "json-secret",
                    "redirect_uris": ["http://localhost:8787/callback"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_OAUTH_KEYS_PATH", str(key_file))
    monkeypatch.setenv("MCP_BEARER_TOKEN", "bearer-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    reset_settings_cache()

    settings = get_settings()

    assert settings.google_client_id == "json-client"
    assert settings.google_client_secret == "json-secret"
    assert settings.google_redirect_uri == "http://localhost:8787/callback"
    assert settings.oauth_client_source == str(key_file)


def test_oauth_json_path_expands_environment_variables(monkeypatch, tmp_path):
    key_file = tmp_path / "gcp-oauth.keys.json"
    key_file.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "json-client",
                    "client_secret": "json-secret",
                    "redirect_uris": ["http://localhost:8787/callback"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_TASKS_TEST_DIR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_OAUTH_KEYS_PATH", "%GOOGLE_TASKS_TEST_DIR%/gcp-oauth.keys.json")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "bearer-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    reset_settings_cache()

    settings = get_settings()

    assert settings.google_client_id == "json-client"
    assert settings.oauth_client_source == str(key_file)


def test_env_credentials_take_precedence_over_oauth_json(monkeypatch, tmp_path):
    key_file = tmp_path / "gcp-oauth.keys.json"
    key_file.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "json-client",
                    "client_secret": "json-secret",
                    "redirect_uris": ["http://localhost:8787/callback"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_OAUTH_KEYS_PATH", str(key_file))
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://env.example/callback")
    monkeypatch.setenv("MCP_BEARER_TOKEN", "bearer-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    reset_settings_cache()

    settings = get_settings()

    assert settings.google_client_id == "env-client"
    assert settings.google_client_secret == "env-secret"
    assert settings.google_redirect_uri == "http://env.example/callback"
    assert settings.oauth_client_source == "env"


def test_malformed_oauth_json_fails(monkeypatch, tmp_path):
    key_file = tmp_path / "gcp-oauth.keys.json"
    key_file.write_text("{", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_OAUTH_KEYS_PATH", str(key_file))
    monkeypatch.setenv("MCP_BEARER_TOKEN", "bearer-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    reset_settings_cache()

    with pytest.raises(ConfigError):
        get_settings()


def test_bearer_token_only_required_when_requested(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost:8787/callback")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    reset_settings_cache()

    settings = get_settings()
    assert settings.mcp_bearer_token is None

    with pytest.raises(ConfigError):
        get_settings(require_bearer_token=True)
