from __future__ import annotations

from starlette.testclient import TestClient

from google_tasks_mcp.config import reset_settings_cache
from google_tasks_mcp.http_app import create_app, create_protected_app


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
