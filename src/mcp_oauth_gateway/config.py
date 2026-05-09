"""Configuration for the MCP OAuth Gateway."""
from dataclasses import dataclass, field
from typing import List, Optional
import secrets


@dataclass
class GatewayConfig:
    # OAuth server identity
    issuer: str                          # e.g. "https://tasks.example.com"

    # Pre-registered client for Claude.ai web
    client_id: str                       # e.g. "claude-connector"
    client_secret: str                   # secret Claude presents at /token

    # Where clients are allowed to redirect after consent.
    # Empty list = OAuth disabled (Bearer-only mode); no startup error.
    allowed_redirect_uris: List[str] = field(default_factory=list)

    # JWT / opaque token signing
    signing_secret: str = field(default_factory=lambda: secrets.token_hex(32))

    # How long access tokens live (seconds)
    access_token_ttl: int = 3600         # 1 hour

    # How long refresh tokens live (seconds)
    refresh_token_ttl: int = 86400 * 30  # 30 days

    # How long auth codes live (seconds)
    auth_code_ttl: int = 300             # 5 minutes

    # Single-operator gate: if set, only this password unlocks the consent screen.
    # Leave None for auto-approve (useful for local/trusted deployments).
    admin_password: Optional[str] = None

    # Path prefix where the OAuth endpoints are mounted (default: root)
    # The MCP app is expected to live at /mcp; we protect that path.
    mcp_path_prefix: str = "/mcp"

    # If True, Dynamic Client Registration (RFC 7591) is also accepted.
    # The pre-registered client above always works regardless of this flag.
    enable_dcr: bool = False

    # Legacy static Bearer token accepted alongside OAuth-issued tokens.
    static_bearer_token: Optional[str] = None

    def validate(self):
        assert self.issuer.startswith("https://"), "issuer must be https"
        assert self.client_id, "client_id required"
        assert self.client_secret, "client_secret required"
        assert len(self.signing_secret) >= 32, "signing_secret must be >= 32 chars"
