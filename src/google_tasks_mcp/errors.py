"""Project-specific errors with safe, user-facing messages."""

from __future__ import annotations

from typing import Any


class GoogleTasksMcpError(Exception):
    """Base project error."""

    error = "GOOGLE_TASKS_MCP_ERROR"
    code = 500

    def __init__(self, message: str = "", **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ConfigError(GoogleTasksMcpError):
    """Configuration is missing or invalid."""


class AuthRequired(GoogleTasksMcpError):
    """OAuth bootstrap or re-authentication is required."""


class GoogleTasksApiError(GoogleTasksMcpError):
    """Google Tasks API call failed."""


class NotFoundError(GoogleTasksMcpError):
    """Requested task or tasklist was not found."""

    error = "NOT_FOUND"
    code = 404


class AmbiguousTitleError(GoogleTasksMcpError):
    """A title lookup matched multiple candidates."""

    error = "AMBIGUOUS_TITLE"
    code = 409


class InvalidInputError(GoogleTasksMcpError):
    """Caller supplied invalid input."""

    error = "INVALID_INPUT"
    code = 400
