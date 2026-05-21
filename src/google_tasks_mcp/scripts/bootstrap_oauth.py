"""One-time OAuth bootstrap for Google Tasks."""

from __future__ import annotations

import argparse
import sys

from google_tasks_mcp.auth import authorization_url, build_authorization_flow, exchange_code
from google_tasks_mcp.account import DEFAULT_ACCOUNT_ID
from google_tasks_mcp.errors import AuthRequired, ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Google OAuth for Google Tasks")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="account id to store the Google token under")
    args = parser.parse_args(argv)

    try:
        flow = build_authorization_flow()
        print("Open this URL in a browser and approve access:")
        print(authorization_url(flow))
        code = input("Paste the code or full callback URL: ").strip()
        exchange_code(code, flow=flow, account_id=args.account_id)
    except (AuthRequired, ConfigError) as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 2

    print(f"OAuth token stored for account '{args.account_id}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
