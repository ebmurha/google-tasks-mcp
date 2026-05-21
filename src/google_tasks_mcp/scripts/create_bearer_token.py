"""Create an MCP bearer token for an account."""

from __future__ import annotations

import argparse
import secrets
import sys

from google_tasks_mcp import db
from google_tasks_mcp.account import DEFAULT_ACCOUNT_ID
from google_tasks_mcp.config import get_settings
from google_tasks_mcp.errors import ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an MCP bearer token")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="account id this token routes to")
    parser.add_argument("--label", default=None, help="optional operator label for this token")
    args = parser.parse_args(argv)

    token = secrets.token_urlsafe(48)
    try:
        get_settings()
        db.save_bearer_token(
            account_id=args.account_id,
            token_hash=db.bearer_token_hash(token),
            label=args.label,
        )
    except ConfigError as exc:
        print(f"could not create bearer token: {exc}", file=sys.stderr)
        return 2

    print(f"Account: {args.account_id}")
    print(f"Bearer token: {token}")
    print("Store this token now; only its hash was saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
