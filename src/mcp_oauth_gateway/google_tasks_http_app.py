"""
google_tasks_mcp/http_app.py  — updated version
------------------------------------------------
Drop-in replacement that wraps the existing MCP app with the OAuth gateway.

ENVIRONMENT VARIABLES (add to your systemd unit / .env):

  MCP_OAUTH_ISSUER          = https://tasks.example.com
  MCP_OAUTH_RESOURCE        = https://resource.example.com/custom/mcp
  MCP_OAUTH_CLIENT_ID       = claude-connector
  MCP_OAUTH_CLIENT_SECRET   = <generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">
  MCP_OAUTH_SIGNING_SECRET  = <generate with: python -c "import secrets; print(secrets.token_hex(32))">
  MCP_OAUTH_ADMIN_PASSWORD  = <your-consent-screen-password>   # optional

  # Keep your existing Google auth env vars unchanged:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, etc.

DO NOT CHANGE the MCP tool definitions in server.py. This only touches http_app.py.
"""

import os
from starlette.applications import Starlette

# Import the current Google Tasks HTTP app (no tool changes).
from google_tasks_mcp.http_app import _build_starlette_app

# Import the gateway
from mcp_oauth_gateway import add_mcp_oauth_gateway


def create_http_app() -> Starlette:
    """Build the raw MCP Starlette app (unchanged from original)."""
    return _build_starlette_app()


def create_app():
    """
    Build the full app: MCP app wrapped with OAuth gateway.
    Called by your uvicorn/gunicorn entrypoint.
    """
    raw_mcp_app = create_http_app()

    issuer         = os.environ["MCP_OAUTH_ISSUER"]          # required
    resource       = os.environ.get("MCP_OAUTH_RESOURCE", f"{issuer.rstrip('/')}/mcp")
    client_id      = os.environ["MCP_OAUTH_CLIENT_ID"]       # required
    client_secret  = os.environ["MCP_OAUTH_CLIENT_SECRET"]   # required
    signing_secret = os.environ["MCP_OAUTH_SIGNING_SECRET"]  # required
    admin_password = os.environ.get("MCP_OAUTH_ADMIN_PASSWORD")  # optional

    return add_mcp_oauth_gateway(
        raw_mcp_app,
        issuer=issuer,
        resource=resource,
        client_id=client_id,
        client_secret=client_secret,
        signing_secret=signing_secret,
        admin_password=admin_password,
        allowed_redirect_uris=[
            "https://claude.ai/api/mcp/auth_callback",
            "https://claude.com/api/mcp/auth_callback",
        ],
        mcp_path_prefix="/mcp",
    )


# Entrypoint used by uvicorn / systemd
app = create_app()
