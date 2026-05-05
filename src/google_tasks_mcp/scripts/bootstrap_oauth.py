"""One-time OAuth bootstrap for Google Tasks."""

from __future__ import annotations

import argparse
import sys

from google_tasks_mcp.auth import authorization_url, exchange_code
from google_tasks_mcp.errors import AuthRequired, ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap Google OAuth for Google Tasks")
    parser.parse_args(argv)

    try:
        print("Open this URL in a browser and approve access:")
        print(authorization_url())
        code = input("Paste the code from the callback page: ").strip()
        exchange_code(code)
    except (AuthRequired, ConfigError) as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 2

    print("OAuth token stored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
