from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from google_tasks_mcp import db, http_app
from google_tasks_mcp.auth import _oauth_error_details, _oauth_error_message
from google_tasks_mcp.config import reset_settings_cache
from google_tasks_mcp.errors import AuthRequired


CLIENT_REDIRECT = "https://unrelated-client.example/oauth/callback"
VERIFIER = "unrelated-client-pkce-verifier-with-enough-entropy"
CHALLENGE = base64.urlsafe_b64encode(
    hashlib.sha256(VERIFIER.encode()).digest()
).rstrip(b"=").decode()


def _configure(monkeypatch, issuer_path: str) -> tuple[str, str, str]:
    issuer = f"https://tasks.example{issuer_path}"
    resource = f"{issuer}/mcp"
    callback = f"{issuer}/callback"
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", callback)
    monkeypatch.setenv("MCP_OAUTH_ISSUER", issuer)
    monkeypatch.setenv("MCP_OAUTH_RESOURCE", resource)
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "unrelated-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "unrelated-secret")
    monkeypatch.setenv("MCP_OAUTH_SIGNING_SECRET", "z" * 64)
    monkeypatch.setenv("MCP_OAUTH_REDIRECT_URIS", CLIENT_REDIRECT)
    reset_settings_cache()
    return issuer, resource, callback


def _approve(client: TestClient, issuer: str, resource: str):
    return client.post(
        f"{urlparse(issuer).path}/authorize",
        data={
            "response_type": "code",
            "client_id": "unrelated-client",
            "redirect_uri": CLIENT_REDIRECT,
            "state": "original-client-state",
            "resource": resource,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )


def _google_state(response) -> str:
    match = re.search(r"https://google\.example/authorize\?state=([A-Za-z0-9_-]+)", response.text)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize("issuer_path", ["", "/team"])
def test_connect_chains_google_and_resumes_after_restart(
    configured_env, monkeypatch, issuer_path
):
    issuer, resource, callback = _configure(monkeypatch, issuer_path)
    monkeypatch.setattr(
        http_app,
        "get_credentials",
        lambda _account_id=None: (_ for _ in ()).throw(AuthRequired("missing")),
    )
    monkeypatch.setattr(http_app, "build_authorization_flow", lambda *a, **k: object())
    monkeypatch.setattr(
        http_app,
        "authorization_url",
        lambda _flow, *, state: f"https://google.example/authorize?state={state}",
    )

    with TestClient(http_app.create_app()) as client:
        google_redirect = _approve(client, issuer, resource)
    assert google_redirect.status_code == 200
    assert "location" not in google_redirect.headers
    assert "http-equiv=\"refresh\"" in google_redirect.text
    assert google_redirect.headers["content-security-policy"] == (
        "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    google_state = _google_state(google_redirect)
    with db._connect() as conn:
        row = conn.execute(
            "SELECT state_hash, mcp_client_id, mcp_redirect_uri, mcp_resource, "
            "mcp_code_challenge, mcp_state, mcp_issuer FROM google_oauth_states"
        ).fetchone()
    assert row["state_hash"] != google_state
    assert row["mcp_client_id"] == "unrelated-client"
    assert row["mcp_redirect_uri"] == CLIENT_REDIRECT
    assert row["mcp_resource"] == resource
    assert row["mcp_code_challenge"] == CHALLENGE
    assert row["mcp_state"] == "original-client-state"
    assert row["mcp_issuer"] == issuer

    def exchange(code, *, flow, account_id):
        assert code == "synthetic-google-code"
        db.save_token("refresh", "access", 9999999999, "scope", account_id=account_id)
        return db.get_token(account_id)

    monkeypatch.setattr(http_app, "exchange_code", exchange)
    callback_path = urlparse(callback).path
    with TestClient(http_app.create_app()) as restarted:
        resumed = restarted.get(
            callback_path,
            params={"state": google_state, "code": "synthetic-google-code"},
            follow_redirects=False,
        )
        replay = restarted.get(
            callback_path,
            params={"state": google_state, "code": "synthetic-google-code"},
            follow_redirects=False,
        )
        resumed_params = parse_qs(urlparse(resumed.headers["location"]).query)
        token = restarted.post(
            f"{urlparse(issuer).path}/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "unrelated-client",
                "client_secret": "unrelated-secret",
                "code": resumed_params["code"][0],
                "redirect_uri": CLIENT_REDIRECT,
                "resource": resource,
                "code_verifier": VERIFIER,
            },
        )

    assert resumed.status_code == 302
    assert resumed_params["state"] == ["original-client-state"]
    assert resumed_params["iss"] == [issuer]
    assert token.status_code == 200
    assert replay.status_code == 400


def test_connect_skips_google_when_stored_authorization_is_usable(
    configured_env, monkeypatch
):
    issuer, resource, _callback = _configure(monkeypatch, "")
    monkeypatch.setattr(http_app, "get_credentials", lambda _account_id=None: object())
    with TestClient(http_app.create_app()) as client:
        response = _approve(client, issuer, resource)
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert urlparse(response.headers["location"]).netloc == "unrelated-client.example"
    assert "code" in params
    assert params["state"] == ["original-client-state"]


def test_google_denial_returns_client_error_without_mcp_code(
    configured_env, monkeypatch
):
    issuer, resource, callback = _configure(monkeypatch, "")
    monkeypatch.setattr(
        http_app,
        "get_credentials",
        lambda _account_id=None: (_ for _ in ()).throw(AuthRequired("revoked")),
    )
    monkeypatch.setattr(http_app, "build_authorization_flow", lambda *a, **k: object())
    monkeypatch.setattr(
        http_app,
        "authorization_url",
        lambda _flow, *, state: f"https://google.example/authorize?state={state}",
    )
    with TestClient(http_app.create_app()) as client:
        started = _approve(client, issuer, resource)
        state = _google_state(started)
        denied = client.get(
            urlparse(callback).path,
            params={"state": state, "error": "access_denied"},
            follow_redirects=False,
        )
    params = parse_qs(urlparse(denied.headers["location"]).query)
    assert params["error"] == ["access_denied"]
    assert params["state"] == ["original-client-state"]
    assert params["iss"] == [issuer]
    assert "code" not in params


def test_exchange_failure_returns_safe_provider_category_without_mcp_code(
    configured_env, monkeypatch, caplog
):
    issuer, resource, callback = _configure(monkeypatch, "")
    monkeypatch.setattr(
        http_app,
        "get_credentials",
        lambda _account_id=None: (_ for _ in ()).throw(AuthRequired("missing")),
    )
    monkeypatch.setattr(http_app, "build_authorization_flow", lambda *a, **k: object())
    monkeypatch.setattr(
        http_app,
        "authorization_url",
        lambda _flow, *, state: f"https://google.example/authorize?state={state}",
    )
    monkeypatch.setattr(
        http_app,
        "exchange_code",
        lambda *a, **k: (_ for _ in ()).throw(
            AuthRequired(
                "provider response intentionally hidden",
                provider_error="invalid_client",
                provider_status=401,
            )
        ),
    )

    with TestClient(http_app.create_app()) as client:
        started = _approve(client, issuer, resource)
        state = _google_state(started)
        failed = client.get(
            urlparse(callback).path,
            params={"state": state, "code": "secret-google-code"},
            follow_redirects=False,
        )

    params = parse_qs(urlparse(failed.headers["location"]).query)
    assert params["error"] == ["server_error"]
    assert params["error_description"] == [
        "Google rejected the configured OAuth client credentials"
    ]
    assert "code" not in params
    assert "secret-google-code" not in caplog.text
    assert "provider_error=invalid_client" in caplog.text
    assert "provider_status=401" in caplog.text


@pytest.mark.parametrize(
    "provider_value",
    [
        "mystery",
        "x" * 10000,
        "invalid_grant\nFORGED log entry",
        "code=secret-authorization-code",
        "token=secret-refresh-token",
    ],
)
def test_unrecognized_provider_values_never_cross_callback_outputs(
    configured_env, monkeypatch, caplog, provider_value
):
    issuer, resource, callback = _configure(monkeypatch, "")
    monkeypatch.setattr(
        http_app,
        "get_credentials",
        lambda _account_id=None: (_ for _ in ()).throw(AuthRequired("missing")),
    )
    monkeypatch.setattr(http_app, "build_authorization_flow", lambda *a, **k: object())
    monkeypatch.setattr(
        http_app,
        "authorization_url",
        lambda _flow, *, state: f"https://google.example/authorize?state={state}",
    )
    provider_exception = ValueError("raw provider response")
    provider_exception.error = provider_value  # type: ignore[attr-defined]
    sanitized = AuthRequired(
        _oauth_error_message(provider_exception),
        **_oauth_error_details(provider_exception),
    )
    monkeypatch.setattr(
        http_app,
        "exchange_code",
        lambda *a, **k: (_ for _ in ()).throw(sanitized),
    )

    with TestClient(http_app.create_app()) as client:
        started = _approve(client, issuer, resource)
        state = _google_state(started)
        failed = client.get(
            urlparse(callback).path,
            params={"state": state, "code": "synthetic-code"},
            follow_redirects=False,
        )

    db.save_google_oauth_state(
        "standalone-state",
        account_id="default",
        callback_uri=callback,
        expires_at=9999999999,
    )
    with TestClient(http_app.create_app()) as client:
        failure_page = client.get(
            urlparse(callback).path,
            params={"state": "standalone-state", "code": "synthetic-code"},
        )

    combined_output = (
        failed.headers["location"]
        + failure_page.text
        + caplog.text
        + str(sanitized)
    )
    assert provider_value not in combined_output
    assert "raw provider response" not in combined_output
    assert "provider_error=unrecognized" in caplog.text
    params = parse_qs(urlparse(failed.headers["location"]).query)
    assert params["error_description"] == [
        "Google authorization could not be completed"
    ]
