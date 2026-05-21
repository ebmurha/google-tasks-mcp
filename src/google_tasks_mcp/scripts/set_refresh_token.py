"""Store an existing Google OAuth refresh token."""

from __future__ import annotations

import argparse
import sys

from google_tasks_mcp.auth import set_refresh_token
from google_tasks_mcp.account import DEFAULT_ACCOUNT_ID
from google_tasks_mcp.errors import AuthRequired, ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Store a Google OAuth refresh token")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="account id to store the refresh token under")
    parser.add_argument("--refresh-token", required=True, help="existing Google OAuth refresh token")
    args = parser.parse_args(argv)

    try:
        set_refresh_token(args.refresh_token, account_id=args.account_id)
    except (AuthRequired, ConfigError) as exc:
        print(f"could not store refresh token: {exc}", file=sys.stderr)
        return 2

    print(f"Refresh token stored for account '{args.account_id}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
