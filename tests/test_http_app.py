from __future__ import annotations

import base64
import hashlib
import re
import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from google_tasks_mcp import db
from google_tasks_mcp.account import get_current_account_id
from google_tasks_mcp.config import reset_settings_cache
from google_tasks_mcp.errors import AuthRequired
from google_tasks_mcp.http_app import BearerAuthMiddleware, create_app, create_protected_app


async def _account_endpoint(_request):
    return JSONResponse({"account_id": get_current_account_id()})


def _enable_hosted_google_oauth(monkeypatch, *, path: str = "/google/oauth") -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_ONBOARDING_URL", f"https://testserver{path}")
    monkeypatch.setenv("GOOGLE_OAUTH_SETUP_SECRET", "operator-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://testserver/callback")
    reset_settings_cache()


def test_healthz_is_unauthenticated():
    client = TestClient(create_protected_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_callback_is_unauthenticated_and_escapes_code():
    client = TestClient(create_protected_app())

    response = client.get("/callback?code=<abc>")

    assert response.status_code == 200
    assert "&lt;abc&gt;" in response.text


def test_hosted_google_oauth_page_has_no_secret_and_supports_configured_path(
    configured_env, monkeypatch
):
    _enable_hosted_google_oauth(monkeypatch, path="/team/setup/google")

    with TestClient(create_protected_app()) as client:
        response = client.get("/team/setup/google")

    assert response.status_code == 200
    assert "Google is not connected" in response.text
    assert 'action="https://testserver/team/setup/google"' in response.text
    assert "operator-secret" not in response.text
    assert (
        "form-action https://testserver/team/setup/google"
        in response.headers["content-security-policy"]
    )


def test_hosted_google_oauth_requires_operator_secret(configured_env, monkeypatch):
    _enable_hosted_google_oauth(monkeypatch)

    with TestClient(create_protected_app()) as client:
        response = client.post("/google/oauth", data={"secret": "wrong"})

    assert response.status_code == 401
    assert "operator-secret" not in response.text
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM google_oauth_states").fetchone()[0] == 0


def test_hosted_google_oauth_stores_only_state_hash(configured_env, monkeypatch):
    _enable_hosted_google_oauth(monkeypatch)

    def fake_authorization_url(_flow, *, state):
        return f"https://accounts.example/authorize?state={state}"

    with patch(
        "google_tasks_mcp.http_app.build_authorization_flow", return_value=object()
    ), patch(
        "google_tasks_mcp.http_app.authorization_url",
        side_effect=fake_authorization_url,
    ), TestClient(create_protected_app()) as client:
        response = client.post(
            "/google/oauth", data={"secret": "operator-secret"}
        )

    assert response.status_code == 200
    match = re.search(r"state=([A-Za-z0-9_-]+)", response.text)
    assert match is not None
    raw_state = match.group(1)
    assert "operator-secret" not in response.text
    with db._connect() as conn:
        row = conn.execute(
            "SELECT state_hash, account_id, callback_uri, expires_at, consumed_at "
            "FROM google_oauth_states"
        ).fetchone()
    assert row is not None
    assert row["state_hash"] != raw_state
    assert row["account_id"] == "default"
    assert row["callback_uri"] == "http://testserver/callback"
    assert row["expires_at"] > int(time.time())
    assert row["consumed_at"] is None


def test_hosted_google_callback_exchanges_stores_and_rejects_replay(
    configured_env, monkeypatch
):
    _enable_hosted_google_oauth(monkeypatch)
    db.save_google_oauth_state(
        "valid-state",
        account_id="default",
        callback_uri="http://testserver/callback",
        expires_at=int(time.time()) + 60,
    )

    def fake_exchange(_code, *, flow, account_id):
        assert flow is fake_flow
        assert account_id == "default"
        db.save_token("hosted-refresh", "hosted-access", 9999999999, "scope")

    fake_flow = object()
    with patch(
        "google_tasks_mcp.http_app.build_authorization_flow", return_value=fake_flow
    ), patch(
        "google_tasks_mcp.http_app.exchange_code", side_effect=fake_exchange
    ) as exchange, TestClient(create_protected_app()) as client:
        response = client.get("/callback?state=valid-state&code=google-code")
        replay = client.get("/callback?state=valid-state&code=google-code")

    assert response.status_code == 200
    assert "Google account connected" in response.text
    assert "google-code" not in response.text
    assert "hosted-refresh" not in response.text
    assert replay.status_code == 400
    exchange.assert_called_once()
    assert db.get_token() is not None
    assert db.get_token().refresh_token == "hosted-refresh"


def test_hosted_google_denial_consumes_state_without_overwriting_token(
    configured_env, monkeypatch
):
    _enable_hosted_google_oauth(monkeypatch)
    db.save_token("existing-refresh", None, 0, "scope")
    db.save_google_oauth_state(
        "denied-state",
        account_id="default",
        callback_uri="http://testserver/callback",
        expires_at=int(time.time()) + 60,
    )

    with TestClient(create_protected_app()) as client:
        denied = client.get("/callback?state=denied-state&error=access_denied")
        replay = client.get("/callback?state=denied-state&code=unused")

    assert denied.status_code == 400
    assert "was denied" in denied.text
    assert replay.status_code == 400
    assert db.get_token() is not None
    assert db.get_token().refresh_token == "existing-refresh"


def test_hosted_google_exchange_failure_consumes_state_without_overwriting_token(
    configured_env, monkeypatch
):
    _enable_hosted_google_oauth(monkeypatch)
    db.save_token("existing-refresh", None, 0, "scope")
    db.save_google_oauth_state(
        "failed-state",
        account_id="default",
        callback_uri="http://testserver/callback",
        expires_at=int(time.time()) + 60,
    )

    with patch(
        "google_tasks_mcp.http_app.build_authorization_flow", return_value=object()
    ), patch(
        "google_tasks_mcp.http_app.exchange_code",
        side_effect=AuthRequired("synthetic exchange failure"),
    ) as exchange, TestClient(create_protected_app()) as client:
        failed = client.get("/callback?state=failed-state&code=synthetic-code")
        replay = client.get("/callback?state=failed-state&code=synthetic-code")

    assert failed.status_code == 400
    assert "could not be exchanged" in failed.text
    assert "synthetic-code" not in failed.text
    assert "synthetic exchange failure" not in failed.text
    assert replay.status_code == 400
    exchange.assert_called_once()
    assert db.get_token() is not None
    assert db.get_token().refresh_token == "existing-refresh"


def test_mcp_requires_bearer_token(configured_env):
    client = TestClient(create_protected_app())

    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401
    assert response.json() == {"error": "Unauthorized"}


def test_mcp_tools_list_accepts_valid_bearer_token(configured_env):
    with TestClient(create_protected_app()) as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer bearer-token",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

    assert response.status_code == 200
    assert "list_tasklists" in response.text
    assert "today" in response.text
    assert "move" in response.text


def test_bearer_middleware_routes_stored_token_to_account(configured_env):
    db.save_bearer_token(
        account_id="work",
        token_hash=db.bearer_token_hash("work-token"),
        label="Work",
    )
    app = Starlette(routes=[Route("/mcp", _account_endpoint, methods=["POST"])])
    app.add_middleware(BearerAuthMiddleware)

    with TestClient(app) as client:
        response = client.post("/mcp", headers={"Authorization": "Bearer work-token"})

    assert response.status_code == 200
    assert response.json() == {"account_id": "work"}


def test_bearer_middleware_routes_legacy_env_token_to_default(configured_env):
    app = Starlette(routes=[Route("/mcp", _account_endpoint, methods=["POST"])])
    app.add_middleware(BearerAuthMiddleware)

    with TestClient(app) as client:
        response = client.post("/mcp", headers={"Authorization": "Bearer bearer-token"})

    assert response.status_code == 200
    assert response.json() == {"account_id": "default"}


def test_oauth_gateway_accepts_legacy_bearer_token(configured_env, monkeypatch):
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "https://tasks.example.com")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "mcp-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "mcp-client-secret")
    monkeypatch.setenv("MCP_OAUTH_SIGNING_SECRET", "x" * 64)
    reset_settings_cache()

    with TestClient(create_app()) as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer bearer-token",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "0"},
                },
            },
        )

    assert response.status_code == 200
    assert '"protocolVersion":"2025-11-25"' in response.text


def test_oauth_gateway_mcp_probe_requires_auth_and_advertises_metadata(configured_env, monkeypatch):
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "https://tasks.example.com")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "mcp-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "mcp-client-secret")
    monkeypatch.setenv("MCP_OAUTH_SIGNING_SECRET", "x" * 64)
    monkeypatch.setenv("MCP_OAUTH_REDIRECT_URIS", "https://client.example/callback")
    reset_settings_cache()

    with TestClient(create_app()) as client:
        response = client.post(
            "/mcp",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert "list_tasklists" not in response.text
    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="https://tasks.example.com/.well-known/oauth-protected-resource/mcp", '
        'scope="mcp", error="invalid_token"'
    )


def test_oauth_refresh_token_survives_app_restart(configured_env, monkeypatch):
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "https://tasks.example.com")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "mcp-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "mcp-client-secret")
    monkeypatch.setenv("MCP_OAUTH_SIGNING_SECRET", "x" * 64)
    monkeypatch.setenv("MCP_OAUTH_REDIRECT_URIS", "https://client.example/callback")
    reset_settings_cache()

    verifier = "test-verifier-with-enough-entropy-for-pkce"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    with TestClient(create_app()) as client:
        authorize = client.post(
            "/authorize",
            data={
                "response_type": "code",
                "client_id": "mcp-client",
                "redirect_uri": "https://client.example/callback",
                "state": "state-1",
                "resource": "https://tasks.example.com/mcp",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert authorize.status_code == 302
        code = parse_qs(urlparse(authorize.headers["location"]).query)["code"][0]
        token_response = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "mcp-client",
                "client_secret": "mcp-client-secret",
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "resource": "https://tasks.example.com/mcp",
                "code_verifier": verifier,
            },
        )
        assert token_response.status_code == 200
        first_refresh = token_response.json()["refresh_token"]

    with TestClient(create_app()) as restarted_client:
        refresh_response = restarted_client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "mcp-client",
                "client_secret": "mcp-client-secret",
                "refresh_token": first_refresh,
                "resource": "https://tasks.example.com/mcp",
            },
        )
        replay_response = restarted_client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": "mcp-client",
                "client_secret": "mcp-client-secret",
                "refresh_token": first_refresh,
                "resource": "https://tasks.example.com/mcp",
            },
        )

    assert refresh_response.status_code == 200
    assert refresh_response.json()["refresh_token"] != first_refresh
    assert replay_response.status_code == 400
    assert replay_response.json()["error"] == "invalid_grant"


def test_oauth_gateway_serves_discovery_and_support_routes(configured_env, monkeypatch):
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "https://tasks.example.com")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "mcp-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "mcp-client-secret")
    monkeypatch.setenv("MCP_OAUTH_SIGNING_SECRET", "x" * 64)
    reset_settings_cache()

    with TestClient(create_app()) as client:
        discovery = client.get("/.well-known/oauth-authorization-server")
        healthz = client.get("/healthz")
        callback = client.get("/callback?code=<abc>")

    assert discovery.status_code == 200
    assert discovery.json()["issuer"] == "https://tasks.example.com"
    assert discovery.json()["authorization_endpoint"] == "https://tasks.example.com/authorize"
    assert healthz.status_code == 200
    assert healthz.json() == {"ok": True}
    assert callback.status_code == 200
    assert "&lt;abc&gt;" in callback.text
