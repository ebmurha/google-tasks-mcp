"""Compatibility wrapper for the packaged bearer-token command."""

from google_tasks_mcp.scripts.create_bearer_token import main


if __name__ == "__main__":
    raise SystemExit(main())
