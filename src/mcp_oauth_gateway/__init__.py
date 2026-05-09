"""
mcp-oauth-gateway
-----------------
A reusable OAuth 2.0 authorization-server front door for remote MCP servers.

Usage
-----
from mcp_oauth_gateway import add_mcp_oauth_gateway

app = your_starlette_or_fastapi_app
app = add_mcp_oauth_gateway(
    app,
    issuer="https://tasks.example.com",
    client_id="claude-connector",
    client_secret="changeme",
    allowed_redirect_uris=[
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
    ],
    signing_secret="random-32-char-string",
)
"""

from .gateway import add_mcp_oauth_gateway
from .config import GatewayConfig

__all__ = ["add_mcp_oauth_gateway", "GatewayConfig"]
__version__ = "0.1.0"
