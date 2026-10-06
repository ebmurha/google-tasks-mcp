from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

import pytest
import uvicorn
from playwright.sync_api import sync_playwright
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from mcp_oauth_gateway.endpoints import AUTOAPPROVE_HTML, _consent_response


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _serve(app: Starlette, port: int):
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


@pytest.mark.parametrize("issuer_path", ["", "/team/tasks"])
def test_browser_allows_consent_post_and_callback_redirect(issuer_path: str):
    auth_port = _free_port()
    callback_port = _free_port()
    issuer = f"http://127.0.0.1:{auth_port}{issuer_path}"
    callback_url = f"http://127.0.0.1:{callback_port}/callback"
    authorize_path = f"{urlsplit(issuer).path.rstrip('/')}/authorize"

    async def consent(_request) -> HTMLResponse:
        return _consent_response(
            AUTOAPPROVE_HTML,
            state="browser-state",
            client_id="browser-client",
            redirect_uri=callback_url,
            code_challenge="browser-challenge",
            resource=f"{issuer}/mcp",
            issuer=issuer,
            client_name="Browser client",
        )

    async def approve(_request) -> RedirectResponse:
        return RedirectResponse(f"{callback_url}?state=browser-state", status_code=302)

    async def callback(_request) -> HTMLResponse:
        return HTMLResponse("OAuth callback reached")

    auth_app = Starlette(
        routes=[
            Route(authorize_path, consent, methods=["GET"]),
            Route(authorize_path, approve, methods=["POST"]),
        ]
    )
    callback_app = Starlette(routes=[Route("/callback", callback)])

    with _serve(callback_app, callback_port), _serve(auth_app, auth_port):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                page = browser.new_page()
                page.goto(f"{issuer}/authorize")
                page.get_by_role("button", name="Approve access").click()
                page.wait_for_url(f"{callback_url}?state=browser-state")
                assert page.get_by_text("OAuth callback reached").is_visible()
            finally:
                browser.close()
