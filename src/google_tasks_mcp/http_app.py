"""Starlette HTTP app for MCP, health checks, and OAuth callback."""

from __future__ import annotations

import hmac
import html
import logging
from collections.abc import Awaitable, Callable

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

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


def create_app() -> Starlette:
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
    app = create_app()
    app.add_middleware(BearerAuthMiddleware)
    return app


app = create_protected_app()
