"""Starlette HTTP app for MCP, health checks, and OAuth callback."""

from __future__ import annotations

import html
import logging
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from mcp_oauth_gateway import add_mcp_oauth_gateway

from .server import create_mcp_server


LOGGER = logging.getLogger(__name__)


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


def create_app() -> ASGIApp:
    raw_mcp_app = _build_starlette_app()
    raw_uris = os.environ.get("MCP_OAUTH_REDIRECT_URIS", "")
    redirect_uris = [u.strip() for u in raw_uris.split(",") if u.strip()]
    return add_mcp_oauth_gateway(
        raw_mcp_app,
        issuer=os.environ["MCP_OAUTH_ISSUER"],
        client_id=os.environ["MCP_OAUTH_CLIENT_ID"],
        client_secret=os.environ["MCP_OAUTH_CLIENT_SECRET"],
        signing_secret=os.environ["MCP_OAUTH_SIGNING_SECRET"],
        admin_password=os.environ.get("MCP_OAUTH_ADMIN_PASSWORD"),
        static_bearer_token=os.environ.get("MCP_BEARER_TOKEN"),
        allowed_redirect_uris=redirect_uris,
    )


app = create_app()
