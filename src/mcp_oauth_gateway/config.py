"""Configuration for the MCP OAuth Gateway."""
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional
import secrets
from urllib.parse import urlsplit, urlunsplit


def _is_https_or_loopback_http(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme == "https" or (
        parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )


def well_known_url(identifier: str, suffix: str) -> str:
    """Build an RFC 8414/9728 metadata URL for an identifier with an optional path."""
    parsed = urlsplit(identifier)
    identifier_path = parsed.path.rstrip("/")
    path = f"/.well-known/{suffix}{identifier_path}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


@dataclass
class GatewayConfig:
    # OAuth server identity
    issuer: str                          # e.g. "https://tasks.example.com"
    resource: str                        # canonical MCP resource URL

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

    # Optional host-app hooks for routing bearer tokens to request-local accounts.
    bearer_token_resolver: Optional[Callable[[str], Optional[str]]] = None
    set_account_context: Optional[Callable[[str], Any]] = None
    reset_account_context: Optional[Callable[[Any], None]] = None

    def validate(self):
        assert _is_https_or_loopback_http(self.issuer), (
            "issuer must be https except on loopback hosts"
        )
        assert _is_https_or_loopback_http(self.resource), (
            "resource must be https except on loopback hosts"
        )
        assert self.client_id, "client_id required"
        assert self.client_secret, "client_secret required"
        assert len(self.signing_secret) >= 32, "signing_secret must be >= 32 chars"

    @property
    def issuer_path(self) -> str:
        return urlsplit(self.issuer).path.rstrip("/")
