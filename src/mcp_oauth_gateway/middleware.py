"""
Middleware that:
1. Intercepts requests to /mcp (or cfg.mcp_path_prefix)
2. Validates the Bearer token from Authorization header
3. If valid, forwards to the underlying MCP ASGI app
4. If invalid, returns 401

All other paths (/, /authorize, /token, etc.) pass through to the OAuth router.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import GatewayConfig
from .store import TokenStore


def _unauthorized(msg: str) -> JSONResponse:
    return JSONResponse(
        {"error": "unauthorized", "error_description": msg},
        status_code=401,
        headers={
            "WWW-Authenticate": 'Bearer error="invalid_token"',
            "Cache-Control": "no-store",
        },
    )


class MCPAuthMiddleware:
    """
    Pure ASGI middleware (no starlette dependency on BaseHTTPMiddleware overhead).
    Protects cfg.mcp_path_prefix with Bearer token validation.
    """

    def __init__(self, app: ASGIApp, cfg: GatewayConfig, store: TokenStore):
        self.app = app
        self.cfg = cfg
        self.store = store

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith(self.cfg.mcp_path_prefix):
            await self.app(scope, receive, send)
            return

        # Extract Bearer token
        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("utf-8", errors="replace")
        if not auth.lower().startswith("bearer "):
            resp = _unauthorized("Missing Bearer token")
            await resp(scope, receive, send)
            return

        token = auth[7:].strip()

        # Accept legacy static Bearer token (backwards compat with MCP_BEARER_TOKEN)
        import hmac as _hmac
        if self.cfg.static_bearer_token:
            if _hmac.compare_digest(token, self.cfg.static_bearer_token):
                await self.app(scope, receive, send)
                return

        # Accept OAuth-issued token
        payload = self.store.verify_access_token(token)
        if not payload:
            resp = _unauthorized("Token invalid or expired")
            await resp(scope, receive, send)
            return

        # Token valid — forward to inner MCP app
        await self.app(scope, receive, send)
