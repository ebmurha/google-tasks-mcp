"""Container health probe using the configured MCP issuer path."""

from __future__ import annotations

import json
import os
import urllib.request
from urllib.parse import urlsplit


def health_path_for_issuer(issuer: str) -> str:
    """Return the health route registered for an MCP OAuth issuer."""
    issuer_path = urlsplit(issuer.rstrip("/")).path
    return f"{issuer_path}/healthz"


def main() -> None:
    port = os.getenv("BIND_PORT") or os.getenv("PORT", "8787")
    path = health_path_for_issuer(os.getenv("MCP_OAUTH_ISSUER", ""))
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}{path}", timeout=5
    ) as response:
        if json.load(response) != {"ok": True}:
            raise SystemExit("Health endpoint returned an unexpected response")


if __name__ == "__main__":
    main()
