from __future__ import annotations

from starlette.testclient import TestClient

from google_tasks_mcp.http_app import create_protected_app


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
