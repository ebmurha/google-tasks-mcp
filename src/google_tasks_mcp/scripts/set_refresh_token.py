"""Store an existing Google OAuth refresh token."""

from __future__ import annotations

import argparse
import sys

from google_tasks_mcp.auth import set_refresh_token
from google_tasks_mcp.errors import AuthRequired, ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Store a Google OAuth refresh token")
    parser.add_argument("--refresh-token", required=True, help="existing Google OAuth refresh token")
    args = parser.parse_args(argv)

    try:
        set_refresh_token(args.refresh_token)
    except (AuthRequired, ConfigError) as exc:
        print(f"could not store refresh token: {exc}", file=sys.stderr)
        return 2

    print("Refresh token stored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
