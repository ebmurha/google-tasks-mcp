"""
Basic tests for mcp_oauth_gateway.
Run with: pytest tests/test_gateway.py -v
"""
import pytest
import base64
import hashlib
import secrets
import json
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_oauth_gateway import add_mcp_oauth_gateway


# ---- Fake MCP app ----------------------------------------------------------

async def fake_mcp(scope, receive, send):
    """Minimal ASGI app pretending to be an MCP server."""
    response = JSONResponse({"ok": True})
    await response(scope, receive, send)


# ---- Helpers ----------------------------------------------------------------

CLIENT_ID     = "claude-connector"
CLIENT_SECRET = "test-secret-abc123"
SIGNING_SECRET = secrets.token_hex(32)
ISSUER        = "https://tasks.example.com"
REDIRECT_URI  = "https://claude.ai/api/mcp/auth_callback"


def _pkce_pair():
    verifier  = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _basic(cid, secret):
    creds = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def app():
    wrapped = add_mcp_oauth_gateway(
        fake_mcp,
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        signing_secret=SIGNING_SECRET,
        admin_password=None,          # auto-approve for tests
        allowed_redirect_uris=[REDIRECT_URI],
    )
    return TestClient(wrapped, raise_server_exceptions=True)


# ---- Tests ------------------------------------------------------------------

def test_discovery(app):
    r = app.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert data["issuer"] == ISSUER
    assert "/authorize" in data["authorization_endpoint"]
    assert "/token" in data["token_endpoint"]
    assert "S256" in data["code_challenge_methods_supported"]


def test_authorize_get_shows_consent(app):
    verifier, challenge = _pkce_pair()
    r = app.get("/authorize", params={
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": "abc",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    assert r.status_code == 200
    assert "Authorize Claude Connector" in r.text


def test_full_authorization_code_flow(app):
    verifier, challenge = _pkce_pair()

    # Step 1: GET /authorize
    r = app.get("/authorize", params={
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": "mystate",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    assert r.status_code == 200

    # Step 2: POST /authorize (consent)
    r = app.post("/authorize", data={
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": "mystate",
        "code_challenge": challenge,
    }, follow_redirects=False)
    assert r.status_code == 302
    location = r.headers["location"]
    assert "code=" in location
    code = dict(p.split("=") for p in location.split("?", 1)[1].split("&"))["code"]

    # Step 3: POST /token
    r = app.post("/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
        },
        headers=_basic(CLIENT_ID, CLIENT_SECRET),
    )
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "Bearer"
    return tokens


def test_mcp_blocked_without_token(app):
    r = app.get("/mcp")
    assert r.status_code == 401


def test_mcp_accessible_with_valid_token(app):
    tokens = test_full_authorization_code_flow(app)
    r = app.get("/mcp", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    # fake_mcp returns 200
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_mcp_blocked_with_bad_token(app):
    r = app.get("/mcp", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401


def test_refresh_token_flow(app):
    tokens = test_full_authorization_code_flow(app)
    r = app.post("/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        headers=_basic(CLIENT_ID, CLIENT_SECRET),
    )
    assert r.status_code == 200
    new_tokens = r.json()
    assert "access_token" in new_tokens
    assert new_tokens["access_token"] != tokens["access_token"]  # rotation


def test_wrong_client_secret_rejected(app):
    r = app.post("/token",
        data={"grant_type": "authorization_code", "code": "x", "redirect_uri": REDIRECT_URI},
        headers=_basic(CLIENT_ID, "wrong-secret"),
    )
    assert r.status_code == 401


def test_bad_redirect_uri_rejected(app):
    r = app.get("/authorize", params={
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": "https://evil.com/callback",
        "state": "x",
    })
    assert r.status_code == 401


def test_revoke(app):
    tokens = test_full_authorization_code_flow(app)
    r = app.post("/revoke", data={"token": tokens["refresh_token"]})
    assert r.status_code == 200
    # After revoke, refresh should fail
    r2 = app.post("/token",
        data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]},
        headers=_basic(CLIENT_ID, CLIENT_SECRET),
    )
    assert r2.status_code == 400
