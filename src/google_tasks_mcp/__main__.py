"""Command entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import get_settings
from .db import init_db
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
        settings = get_settings(require_bearer_token=args.transport == "http")
        init_db()
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
