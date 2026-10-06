"""Starlette HTTP app for MCP, health checks, and OAuth callback."""

from __future__ import annotations

import hmac
import html
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mcp_oauth_gateway import add_mcp_oauth_gateway

from . import db
from .account import DEFAULT_ACCOUNT_ID, reset_current_account_id, set_current_account_id
from .auth import authorization_url, build_authorization_flow, exchange_code
from .config import Settings, get_settings
from .errors import AuthRequired, ConfigError
from .server import create_mcp_server


LOGGER = logging.getLogger(__name__)
GOOGLE_OAUTH_STATE_TTL_SECONDS = 600
GOOGLE_OAUTH_ONBOARDING_PATH = "/google/oauth"


def _hosted_google_oauth_enabled(settings: Settings) -> bool:
    return bool(
        settings.google_oauth_onboarding_url
        and settings.google_oauth_setup_secret
    )


def _hosted_html(body: str, *, status: int = 200, form_action: str | None = None) -> HTMLResponse:
    form_policy = f"; form-action {form_action}" if form_action else ""
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head>"
        "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\">"
        "<title>Google Tasks authorization</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:34rem;margin:4rem auto;padding:0 1rem}"
        ".card{border:1px solid #dbe3ea;border-radius:12px;padding:1.5rem}"
        "input,button{box-sizing:border-box;width:100%;padding:.75rem;margin-top:.75rem}"
        "a{display:inline-block;margin-top:1rem}</style></head><body><div class=\"card\">"
        f"{body}</div></body></html>",
        status_code=status,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                f"frame-ancestors 'none'{form_policy}"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


def resolve_bearer_token_account(token: str) -> str | None:
    settings = get_settings()
    if settings.mcp_bearer_token and hmac.compare_digest(token, settings.mcp_bearer_token):
        return DEFAULT_ACCOUNT_ID
    record = db.get_bearer_token(token)
    if record and record.enabled:
        return record.account_id
    return None


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        if not authorization.lower().startswith("bearer "):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        token = authorization[7:].strip()
        try:
            account_id = resolve_bearer_token_account(token)
        except ConfigError:
            LOGGER.error("MCP bearer token validation is not configured")
            return JSONResponse({"error": "Server authentication is not configured"}, status_code=500)

        if account_id is None:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        context_token = set_current_account_id(account_id)
        try:
            return await call_next(request)
        finally:
            reset_current_account_id(context_token)


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def google_oauth_onboarding(request: Request) -> HTMLResponse:
    try:
        settings = get_settings()
    except ConfigError:
        return _hosted_html("<h1>Not found</h1>", status=404)
    if not _hosted_google_oauth_enabled(settings):
        return _hosted_html("<h1>Not found</h1>", status=404)

    onboarding_url = settings.google_oauth_onboarding_url or ""
    connected = db.get_token(DEFAULT_ACCOUNT_ID) is not None
    if request.method == "GET":
        status = "Google is connected." if connected else "Google is not connected."
        action = "Reconnect Google" if connected else "Connect Google"
        return _hosted_html(
            f"<h1>{status}</h1>"
            "<p>Enter the operator setup password to authorize this server.</p>"
            f'<form method="post" action="{html.escape(onboarding_url, quote=True)}">'
            '<label for="secret">Operator setup password</label>'
            '<input id="secret" name="secret" type="password" autocomplete="current-password" required>'
            f"<button type=\"submit\">{action}</button></form>",
            form_action=onboarding_url,
        )

    form = await request.form()
    supplied_secret = str(form.get("secret", ""))
    expected_secret = settings.google_oauth_setup_secret or ""
    if not hmac.compare_digest(supplied_secret, expected_secret):
        return _hosted_html(
            "<h1>Authorization denied</h1><p>The operator setup password is incorrect.</p>",
            status=401,
        )

    state = secrets.token_urlsafe(32)
    db.save_google_oauth_state(
        state,
        account_id=DEFAULT_ACCOUNT_ID,
        callback_uri=settings.google_redirect_uri,
        expires_at=int(time.time()) + GOOGLE_OAUTH_STATE_TTL_SECONDS,
    )
    flow = build_authorization_flow(settings, state=state)
    google_url = authorization_url(flow, state=state)
    return _hosted_html(
        "<h1>Continue to Google</h1>"
        "<p>The setup password was accepted. Continue to Google's consent screen.</p>"
        f'<a href="{html.escape(google_url, quote=True)}">Continue to Google</a>'
    )


async def callback(request: Request) -> HTMLResponse:
    try:
        settings = get_settings()
    except ConfigError:
        settings = None
    if settings is not None and _hosted_google_oauth_enabled(settings):
        state = request.query_params.get("state", "")
        if not state:
            return _hosted_html(
                "<h1>Authorization failed</h1><p>OAuth state is missing.</p>",
                status=400,
            )
        state_record = db.consume_google_oauth_state(
            state,
            callback_uri=settings.google_redirect_uri,
        )
        if state_record is None:
            return _hosted_html(
                "<h1>Authorization failed</h1><p>OAuth state is invalid, expired, or already used.</p>",
                status=400,
            )
        if request.query_params.get("error"):
            return _hosted_html(
                "<h1>Google authorization was denied</h1>"
                "<p>No Google credentials were changed. Start again when ready.</p>",
                status=400,
            )
        code = request.query_params.get("code", "")
        if not code:
            return _hosted_html(
                "<h1>Authorization failed</h1><p>Google did not return an authorization code.</p>",
                status=400,
            )
        try:
            flow = build_authorization_flow(settings, state=state)
            exchange_code(code, flow=flow, account_id=state_record.account_id)
        except AuthRequired:
            return _hosted_html(
                "<h1>Authorization failed</h1>"
                "<p>The code could not be exchanged. Start a new authorization.</p>",
                status=400,
            )
        return _hosted_html(
            "<h1>Google account connected</h1>"
            "<p>Return to your MCP client and retry the Google Tasks request.</p>"
        )

    code = request.query_params.get("code")
    if code:
        escaped_code = html.escape(code, quote=True)
        body = (
            "<!doctype html><html><body>"
            "<p>Copy this code into your terminal:</p>"
            f"<code>{escaped_code}</code>"
            "</body></html>"
        )
    else:
        body = (
            "<!doctype html><html><body>"
            "<p>No OAuth code was provided.</p>"
            "</body></html>"
        )
    return HTMLResponse(body)


def _build_starlette_app() -> Starlette:
    try:
        settings = get_settings()
    except ConfigError:
        settings = None
    mcp_server = create_mcp_server()
    mcp_app = mcp_server.streamable_http_app()
    mcp_route = next(route for route in mcp_app.routes if getattr(route, "path", None) == "/mcp")
    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route(GOOGLE_OAUTH_ONBOARDING_PATH, google_oauth_onboarding, methods=["GET", "POST"]),
        Route("/callback", callback, methods=["GET"]),
        Route("/mcp", endpoint=mcp_route.endpoint),
    ]
    if settings is not None and settings.google_oauth_onboarding_url:
        public_onboarding_path = urlsplit(settings.google_oauth_onboarding_url).path
        if public_onboarding_path and public_onboarding_path != GOOGLE_OAUTH_ONBOARDING_PATH:
            routes.insert(
                2,
                Route(public_onboarding_path, google_oauth_onboarding, methods=["GET", "POST"]),
            )
    if settings is not None:
        public_callback_path = urlsplit(settings.google_redirect_uri).path
        if public_callback_path and public_callback_path != "/callback":
            routes.insert(3, Route(public_callback_path, callback, methods=["GET"]))
    return Starlette(
        routes=routes,
        middleware=[],
        lifespan=lambda app: mcp_server.session_manager.run(),
    )


def create_protected_app() -> Starlette:
    """Build the app with simple bearer-token auth (no OAuth gateway)."""
    starlette_app = _build_starlette_app()
    starlette_app.add_middleware(BearerAuthMiddleware)
    return starlette_app


def create_app() -> ASGIApp:
    """Build the app with the OAuth 2.0 authorization-server gateway."""
    raw_uris = os.environ.get("MCP_OAUTH_REDIRECT_URIS", "")
    redirect_uris = [u.strip() for u in raw_uris.split(",") if u.strip()]
    issuer = os.environ["MCP_OAUTH_ISSUER"].rstrip("/")
    resource = os.environ.get("MCP_OAUTH_RESOURCE", f"{issuer}/mcp").rstrip("/")
    return add_mcp_oauth_gateway(
        _build_starlette_app(),
        issuer=issuer,
        resource=resource,
        client_id=os.environ["MCP_OAUTH_CLIENT_ID"],
        client_secret=os.environ["MCP_OAUTH_CLIENT_SECRET"],
        signing_secret=os.environ["MCP_OAUTH_SIGNING_SECRET"],
        admin_password=os.environ.get("MCP_OAUTH_ADMIN_PASSWORD"),
        static_bearer_token=os.environ.get("MCP_BEARER_TOKEN"),
        bearer_token_resolver=resolve_bearer_token_account,
        set_account_context=set_current_account_id,
        reset_account_context=reset_current_account_id,
        refresh_token_backend=db.McpOAuthRefreshTokenBackend(),
        client_backend=db.McpOAuthClientBackend(),
        allowed_redirect_uris=redirect_uris,
        enable_dcr=os.environ.get("MCP_OAUTH_ENABLE_DCR", "").strip().lower()
        in {"1", "true", "yes", "on"},
    )


class EnvironmentApp:
    """Create the configured ASGI app lazily when the server starts."""

    def __init__(self) -> None:
        self._app: ASGIApp | None = None

    def _get_app(self) -> ASGIApp:
        if self._app is None:
            self._app = create_app() if os.environ.get("MCP_OAUTH_ISSUER") else create_protected_app()
        return self._app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._get_app()(scope, receive, send)


app: ASGIApp = EnvironmentApp()
