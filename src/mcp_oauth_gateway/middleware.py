"""
Middleware that:
1. Intercepts requests to /mcp (or cfg.mcp_path_prefix)
2. Validates the Bearer token from Authorization header
3. If valid, forwards to the underlying MCP ASGI app
4. If invalid, returns 401

All other paths (/, /authorize, /token, etc.) pass through to the OAuth router.
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import GatewayConfig
from .store import TokenStore


DEFAULT_ACCOUNT_ID = "default"


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
    Pure ASGI middleware.
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

        headers = dict(scope.get("headers", []))
        auth = headers.get(b"authorization", b"").decode("utf-8", errors="replace")
        if not auth.lower().startswith("bearer "):
            resp = _unauthorized("Missing Bearer token")
            await resp(scope, receive, send)
            return

        token = auth[7:].strip()
        account_id = None

        if self.cfg.bearer_token_resolver:
            account_id = self.cfg.bearer_token_resolver(token)
        else:
            import hmac as _hmac

            if self.cfg.static_bearer_token and _hmac.compare_digest(token, self.cfg.static_bearer_token):
                account_id = DEFAULT_ACCOUNT_ID

        if account_id is None:
            payload = self.store.verify_access_token(token)
            if not payload:
                resp = _unauthorized("Token invalid or expired")
                await resp(scope, receive, send)
                return
            account_id = payload.get("account_id") or DEFAULT_ACCOUNT_ID

        context_token = None
        if self.cfg.set_account_context:
            context_token = self.cfg.set_account_context(account_id)
        try:
            await self.app(scope, receive, send)
        finally:
            if context_token is not None and self.cfg.reset_account_context:
                self.cfg.reset_account_context(context_token)
