from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlparse

from starlette.testclient import TestClient

from google_tasks_mcp import db
from google_tasks_mcp.config import reset_settings_cache
from google_tasks_mcp.http_app import create_app
from mcp_oauth_gateway.store import TokenStore


ISSUER = "https://tasks.example.com/base"
RESOURCE = f"{ISSUER}/mcp"
REDIRECT_URI = "https://chatgpt.com/connector_platform_oauth_redirect"


def _configure(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OAUTH_ISSUER", ISSUER)
    monkeypatch.setenv("MCP_OAUTH_RESOURCE", RESOURCE)
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "pre-registered-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "pre-registered-secret")
    monkeypatch.setenv("MCP_OAUTH_SIGNING_SECRET", "s" * 64)
    monkeypatch.setenv("MCP_OAUTH_REDIRECT_URIS", REDIRECT_URI)
    monkeypatch.setenv("MCP_OAUTH_ENABLE_DCR", "true")
    reset_settings_cache()


def _pkce_pair() -> tuple[str, str]:
    verifier = "test-verifier-with-enough-entropy-for-pkce"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _register(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/register",
        json={
            "client_name": "ChatGPT",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert response.status_code == 201
    return response.json()["client_id"], response.json()["client_secret"]


def _authorize(client: TestClient, client_id: str) -> tuple[str, str]:
    verifier, challenge = _pkce_pair()
    consent = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "state": "state-1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        },
    )
    assert consent.status_code == 200
    approval = client.post(
        "/authorize",
        data={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "state": "state-1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        },
        follow_redirects=False,
    )
    assert approval.status_code == 302
    params = parse_qs(urlparse(approval.headers["location"]).query)
    assert params["iss"] == [ISSUER]
    assert params["state"] == ["state-1"]
    return params["code"][0], verifier


def test_metadata_and_challenge_are_resource_consistent(configured_env, monkeypatch):
    _configure(monkeypatch)

    with TestClient(create_app()) as client:
        protected = client.get("/.well-known/oauth-protected-resource/base/mcp")
        authorization = client.get("/.well-known/oauth-authorization-server/base")
        challenge = client.post("/mcp")

    assert protected.json() == {
        "resource": RESOURCE,
        "authorization_servers": [ISSUER],
        "scopes_supported": ["mcp"],
    }
    metadata = authorization.json()
    assert metadata["issuer"] == ISSUER
    assert metadata["registration_endpoint"] == f"{ISSUER}/register"
    assert metadata["authorization_response_iss_parameter_supported"] is True
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert challenge.status_code == 401
    assert (
        'resource_metadata="https://tasks.example.com/.well-known/'
        'oauth-protected-resource/base/mcp"'
        in challenge.headers["www-authenticate"]
    )


def test_dcr_client_and_refresh_survive_restart(configured_env, monkeypatch):
    _configure(monkeypatch)

    with TestClient(create_app()) as client:
        client_id, client_secret = _register(client)

    with db._connect() as conn:
        row = conn.execute(
            "SELECT client_secret_hash, metadata_json FROM mcp_oauth_clients WHERE client_id = ?",
            (client_id,),
        ).fetchone()
    assert row is not None
    assert row["client_secret_hash"] != client_secret
    assert client_secret not in row["metadata_json"]

    with TestClient(create_app()) as restarted_client:
        code, verifier = _authorize(restarted_client, client_id)
        token = restarted_client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "resource": RESOURCE,
            },
        )
    assert token.status_code == 200
    refresh_token = token.json()["refresh_token"]

    with TestClient(create_app()) as restarted_again:
        refreshed = restarted_again.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "resource": RESOURCE,
            },
        )
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != refresh_token


def test_resource_mismatches_are_rejected(configured_env, monkeypatch):
    _configure(monkeypatch)
    with TestClient(create_app()) as client:
        code, verifier = _authorize(client, "pre-registered-client")
        wrong_exchange = client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "pre-registered-client",
                "client_secret": "pre-registered-secret",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "resource": "https://other.example/mcp",
            },
        )
        wrong_token = TokenStore("s" * 64, issuer=ISSUER).issue_access_token(
            "pre-registered-client", "https://other.example/mcp", 3600
        )
        wrong_request = client.post(
            "/mcp", headers={"Authorization": f"Bearer {wrong_token}"}
        )

    assert wrong_exchange.status_code == 400
    assert wrong_exchange.json()["error"] == "invalid_target"
    assert wrong_request.status_code == 401


def test_authorization_error_redirect_includes_exact_issuer(configured_env, monkeypatch):
    _configure(monkeypatch)
    _, challenge = _pkce_pair()
    with TestClient(create_app()) as client:
        response = client.get(
            "/authorize",
            params={
                "response_type": "token",
                "client_id": "pre-registered-client",
                "redirect_uri": REDIRECT_URI,
                "state": "state-2",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": RESOURCE,
            },
            follow_redirects=False,
        )
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["error"] == ["unsupported_response_type"]
    assert params["iss"] == [ISSUER]
    assert params["state"] == ["state-2"]
