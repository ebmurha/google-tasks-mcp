"""Starlette HTTP app for MCP, health checks, and OAuth callback."""

from __future__ import annotations

import hmac
import html
import logging
import os
from collections.abc import Awaitable, Callable

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from mcp_oauth_gateway import add_mcp_oauth_gateway

from .config import get_settings
from .errors import ConfigError
from .server import create_mcp_server


LOGGER = logging.getLogger(__name__)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        try:
            expected = get_settings(require_bearer_token=True).mcp_bearer_token
        except ConfigError:
            LOGGER.error("MCP bearer token is not configured")
            return JSONResponse({"error": "Server authentication is not configured"}, status_code=500)

        authorization = request.headers.get("authorization", "")
        if not hmac.compare_digest(authorization, f"Bearer {expected}"):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        return await call_next(request)


async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def callback(request: Request) -> HTMLResponse:
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
    mcp_server = create_mcp_server()
    mcp_app = mcp_server.streamable_http_app()
    mcp_route = next(route for route in mcp_app.routes if getattr(route, "path", None) == "/mcp")
    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/callback", callback, methods=["GET"]),
            Route("/mcp", endpoint=mcp_route.endpoint),
        ],
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
    return add_mcp_oauth_gateway(
        _build_starlette_app(),
        issuer=os.environ["MCP_OAUTH_ISSUER"],
        client_id=os.environ["MCP_OAUTH_CLIENT_ID"],
        client_secret=os.environ["MCP_OAUTH_CLIENT_SECRET"],
        signing_secret=os.environ["MCP_OAUTH_SIGNING_SECRET"],
        admin_password=os.environ.get("MCP_OAUTH_ADMIN_PASSWORD"),
        static_bearer_token=os.environ.get("MCP_BEARER_TOKEN"),
        allowed_redirect_uris=redirect_uris,
    )


app: ASGIApp = create_app() if os.environ.get("MCP_OAUTH_ISSUER") else create_protected_app()
