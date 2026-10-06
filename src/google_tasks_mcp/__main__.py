"""Command entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from .config import get_settings
from .auth import set_refresh_token
from .account import DEFAULT_ACCOUNT_ID
from .db import get_token, init_db
from .errors import ConfigError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Google Tasks MCP server")
    parser.add_argument(
        "--transport",
        choices=["http", "stdio"],
        default="http",
        help="server transport to run",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and initialize the database, then exit",
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings(require_bearer_token=False)
        init_db()
        if args.transport == "http" and not args.check:
            refresh_token = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
            if refresh_token and get_token(DEFAULT_ACCOUNT_ID) is None:
                set_refresh_token(refresh_token)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.check:
        print(f"ok: configuration loaded; database ready at {settings.db_path}")
        return 0

    if args.transport == "stdio":
        from .server import create_mcp_server

        asyncio.run(create_mcp_server().run_stdio_async())
        return 0

    import uvicorn

    uvicorn.run(
        "google_tasks_mcp.http_app:app",
        host=settings.bind_host,
        port=settings.bind_port,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
