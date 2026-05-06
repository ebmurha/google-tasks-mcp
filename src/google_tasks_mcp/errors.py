"""Project-specific errors with safe, user-facing messages."""


class GoogleTasksMcpError(Exception):
    """Base project error."""


class ConfigError(GoogleTasksMcpError):
    """Configuration is missing or invalid."""


class AuthRequired(GoogleTasksMcpError):
    """OAuth bootstrap or re-authentication is required."""


class GoogleTasksApiError(GoogleTasksMcpError):
    """Google Tasks API call failed."""
