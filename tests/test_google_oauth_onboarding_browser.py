from __future__ import annotations

import socket
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse
from contextlib import contextmanager

import pytest
import uvicorn
from playwright.sync_api import sync_playwright
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from google_tasks_mcp import db
from google_tasks_mcp import http_app
from google_tasks_mcp.config import reset_settings_cache
from google_tasks_mcp.errors import AuthRequired


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _serve(app, port: int):
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        raise RuntimeError("Local browser-test server did not start")
    try:
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.parametrize(
    "deployment_path",
    ["", "/team"],
)
def test_hosted_google_onboarding_completes_and_survives_restart(
    configured_env,
    monkeypatch,
    deployment_path: str,
):
    app_port = _free_port()
    provider_port = _free_port()
    app_origin = f"http://127.0.0.1:{app_port}"
    onboarding_path = f"{deployment_path}/google/oauth"
    callback_path = f"{deployment_path}/callback"
    onboarding_url = f"{app_origin}{onboarding_path}"
    callback_url = f"{app_origin}{callback_path}"
    provider_url = f"http://127.0.0.1:{provider_port}/authorize"

    monkeypatch.setenv("GOOGLE_OAUTH_ONBOARDING_URL", onboarding_url)
    monkeypatch.setenv("GOOGLE_OAUTH_SETUP_SECRET", "operator-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", callback_url)
    reset_settings_cache()

    def authorization_url(_flow, *, state: str) -> str:
        return f"{provider_url}?state={state}"

    def exchange_code(code: str, *, flow, account_id: str):
        assert code == "synthetic-google-code"
        assert account_id == "default"
        db.save_token(
            "synthetic-hosted-refresh",
            "synthetic-hosted-access",
            9999999999,
            "https://www.googleapis.com/auth/tasks",
            account_id=account_id,
        )
        return db.get_token(account_id)

    monkeypatch.setattr(http_app, "build_authorization_flow", lambda *args, **kwargs: object())
    monkeypatch.setattr(http_app, "authorization_url", authorization_url)
    monkeypatch.setattr(http_app, "exchange_code", exchange_code)

    async def provider_authorize(request: Request) -> RedirectResponse:
        state = request.query_params["state"]
        return RedirectResponse(
            f"{callback_url}?state={state}&code=synthetic-google-code",
            status_code=302,
        )

    provider_app = Starlette(
        routes=[Route("/authorize", provider_authorize, methods=["GET"])]
    )
    app = http_app.create_protected_app()

    with _serve(provider_app, provider_port), _serve(app, app_port):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                page.goto(onboarding_url)
                page.get_by_label("Operator setup password").fill("operator-secret")
                page.get_by_role("button", name="Connect Google").click()
                assert "operator-secret" not in page.url
                page.get_by_role("link", name="Continue to Google").click()
                page.wait_for_url(f"{callback_url}?state=*&code=synthetic-google-code")
                assert page.get_by_text("Google account connected").is_visible()
            finally:
                browser.close()

    token = db.get_token("default")
    assert token is not None
    assert token.refresh_token == "synthetic-hosted-refresh"

    with TestClient(http_app.create_protected_app()) as restarted_client:
        restarted = restarted_client.get(onboarding_path)
    assert restarted.status_code == 200
    assert "Google is connected" in restarted.text


@pytest.mark.parametrize("deployment_path", ["", "/team"])
def test_mcp_connect_chains_google_and_returns_to_unrelated_client(
    configured_env, monkeypatch, deployment_path: str
):
    app_port = _free_port()
    external_port = _free_port()
    app_origin = f"http://127.0.0.1:{app_port}"
    external_origin = f"http://127.0.0.1:{external_port}"
    issuer = f"{app_origin}{deployment_path}"
    resource = f"{issuer}/mcp"
    callback_url = f"{issuer}/callback"
    client_callback = f"{external_origin}/client/callback"
    provider_url = f"{external_origin}/google/authorize"

    monkeypatch.setenv("GOOGLE_REDIRECT_URI", callback_url)
    monkeypatch.setenv("MCP_OAUTH_ISSUER", issuer)
    monkeypatch.setenv("MCP_OAUTH_RESOURCE", resource)
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "browser-neutral-client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "browser-neutral-secret")
    monkeypatch.setenv("MCP_OAUTH_SIGNING_SECRET", "b" * 64)
    monkeypatch.setenv("MCP_OAUTH_REDIRECT_URIS", client_callback)
    monkeypatch.setenv("MCP_OAUTH_ADMIN_PASSWORD", "operator-password")
    reset_settings_cache()
    monkeypatch.setattr(
        http_app,
        "get_credentials",
        lambda _account_id=None: (_ for _ in ()).throw(AuthRequired("missing")),
    )
    monkeypatch.setattr(http_app, "build_authorization_flow", lambda *a, **k: object())
    monkeypatch.setattr(
        http_app,
        "authorization_url",
        lambda _flow, *, state: f"{provider_url}?state={state}",
    )

    def exchange_code(code: str, *, flow, account_id: str):
        assert code == "browser-google-code"
        db.save_token("browser-refresh", "browser-access", 9999999999, "scope")
        return db.get_token(account_id)

    monkeypatch.setattr(http_app, "exchange_code", exchange_code)

    async def google_authorize(request: Request) -> RedirectResponse:
        state = request.query_params["state"]
        return RedirectResponse(
            f"{callback_url}?{urlencode({'state': state, 'code': 'browser-google-code'})}",
            status_code=302,
        )

    async def client_done(_request: Request):
        from starlette.responses import HTMLResponse
        return HTMLResponse("<h1>Client connected</h1>")

    external_app = Starlette(routes=[
        Route("/google/authorize", google_authorize),
        Route("/client/callback", client_done),
    ])
    authorize_query = urlencode({
        "response_type": "code",
        "client_id": "browser-neutral-client",
        "redirect_uri": client_callback,
        "state": "browser-client-state",
        "resource": resource,
        "code_challenge": "browser-pkce-challenge",
        "code_challenge_method": "S256",
    })

    with _serve(external_app, external_port), _serve(http_app.create_app(), app_port):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                page.goto(f"{issuer}/authorize?{authorize_query}")
                page.get_by_label("Admin password").fill("operator-password")
                page.get_by_role("button", name="Approve access").click()
                page.wait_for_url(f"{client_callback}?*")
                params = parse_qs(urlparse(page.url).query)
                assert page.get_by_text("Client connected").is_visible()
            finally:
                browser.close()

    assert params["state"] == ["browser-client-state"]
    assert params["iss"] == [issuer]
    assert "code" in params
    assert db.get_token("default").refresh_token == "browser-refresh"
