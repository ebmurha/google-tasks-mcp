"""
add_mcp_oauth_gateway()
-----------------------
Wraps an existing Starlette / FastAPI app with:
  - OAuth 2.0 authorization-server endpoints
  - Bearer-token protection on /mcp

The resulting app is drop-in compatible: same ASGI interface.
"""
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from .config import GatewayConfig
from .endpoints import build_oauth_router
from .middleware import MCPAuthMiddleware
from .store import TokenStore


def add_mcp_oauth_gateway(
    mcp_app: ASGIApp,
    *,
    issuer: str,
    client_id: str,
    client_secret: str,
    signing_secret: str,
    allowed_redirect_uris: list = None,
    access_token_ttl: int = 3600,
    refresh_token_ttl: int = 86400 * 30,
    auth_code_ttl: int = 300,
    admin_password: str = None,
    static_bearer_token: str = None,
    mcp_path_prefix: str = "/mcp",
    enable_dcr: bool = False,
) -> ASGIApp:
    """
    Wrap an MCP ASGI app with a full OAuth 2.0 front door.

    Parameters
    ----------
    mcp_app             : Your existing MCP Starlette/FastAPI app.
    issuer              : Public HTTPS base URL of this server.
    client_id           : OAuth client ID Claude will present.
    client_secret       : OAuth client secret Claude will present.
    signing_secret      : >=32-char secret for signing access tokens.
    allowed_redirect_uris: Explicit list; empty = Bearer-only mode (OAuth disabled).
    access_token_ttl    : Seconds access token is valid (default 3600).
    refresh_token_ttl   : Seconds refresh token is valid (default 30d).
    auth_code_ttl       : Seconds auth code is valid (default 300).
    admin_password      : If set, consent screen requires this password.
                          If None, consent screen has a single Approve button.
    static_bearer_token : If set, also accepted at /mcp alongside OAuth tokens.
    mcp_path_prefix     : Path to protect (default "/mcp").
    enable_dcr          : Also allow Dynamic Client Registration (RFC 7591).

    Returns
    -------
    A new ASGI app that:
      - Serves OAuth endpoints at /.well-known/…, /authorize, /token, /revoke
      - Proxies authenticated requests to mcp_app at /mcp
    """
    cfg = GatewayConfig(
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        allowed_redirect_uris=allowed_redirect_uris if allowed_redirect_uris is not None else [],
        signing_secret=signing_secret,
        access_token_ttl=access_token_ttl,
        refresh_token_ttl=refresh_token_ttl,
        auth_code_ttl=auth_code_ttl,
        admin_password=admin_password,
        static_bearer_token=static_bearer_token,
        mcp_path_prefix=mcp_path_prefix,
        enable_dcr=enable_dcr,
    )
    cfg.validate()

    store = TokenStore(cfg.signing_secret)
    oauth_router = build_oauth_router(cfg, store)

    # Compose: OAuth routes first, then MCP app (protected by middleware)
    protected_mcp = MCPAuthMiddleware(mcp_app, cfg, store)

    # Mount OAuth router on the same root; MCP app handles /mcp paths
    # We combine them in a Starlette app so routing works correctly.
    combined = _CombinedApp(oauth_router, protected_mcp, mcp_path_prefix)
    return combined


class _CombinedApp:
    """
    Routes:
      /mcp*            -> MCPAuthMiddleware -> mcp_app
      everything else  -> oauth_router (discovery, /authorize, /token, /revoke)
    """

    def __init__(self, oauth_router, protected_mcp, mcp_path_prefix: str):
        self._oauth = oauth_router
        self._mcp = protected_mcp
        self._prefix = mcp_path_prefix

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._mcp(scope, receive, send)
            return

        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path.startswith(self._prefix):
                await self._mcp(scope, receive, send)
                return
        await self._oauth(scope, receive, send)
