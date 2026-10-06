"""Configuration and OAuth client credential loading."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import load_dotenv

from .errors import ConfigError


DEFAULT_DB_PATH = "/var/lib/google-tasks-mcp/google-tasks.db"
DEFAULT_OAUTH_KEYS_PATH = "gcp-oauth.keys.json"
WINDOWS_ENV_VAR_PATTERN = re.compile(r"%([^%]+)%")


@dataclass(frozen=True)
class OAuthClientInfo:
    client_id: str
    client_secret: str
    redirect_uris: tuple[str, ...] = ()
    source: str = "env"


@dataclass(frozen=True)
class Settings:
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    mcp_bearer_token: str | None
    db_path: Path
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787
    log_level: str = "INFO"
    default_tasklist: str | None = None
    oauth_keys_path: Path = Path(DEFAULT_OAUTH_KEYS_PATH)
    oauth_client_source: str = "env"
    google_oauth_onboarding_url: str | None = None
    google_oauth_setup_secret: str | None = None

    def client_config(self) -> dict[str, Any]:
        return {
            "web": {
                "client_id": self.google_client_id,
                "client_secret": self.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.google_redirect_uri],
            }
        }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _expand_path(value: str) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(value))
    expanded = WINDOWS_ENV_VAR_PATTERN.sub(
        lambda match: os.environ.get(match.group(1), match.group(0)),
        expanded,
    )
    return Path(expanded)


def _read_oauth_keys(path: Path) -> OAuthClientInfo | None:
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read OAuth key file at {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"OAuth key file at {path} is not valid JSON") from exc

    section_name = "web" if "web" in data else "installed" if "installed" in data else None
    if section_name is None:
        raise ConfigError("OAuth key file must contain a 'web' or 'installed' section")

    section = data.get(section_name) or {}
    client_id = _clean(section.get("client_id"))
    client_secret = _clean(section.get("client_secret"))
    redirect_uris = tuple(uri for uri in section.get("redirect_uris", []) if isinstance(uri, str))

    if not client_id or not client_secret:
        raise ConfigError("OAuth key file is missing client_id or client_secret")

    return OAuthClientInfo(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uris=redirect_uris,
        source=str(path),
    )


def _required(name: str, value: str | None) -> str:
    value = _clean(value)
    if not value:
        raise ConfigError(f"Missing required setting: {name}")
    return value


def _parse_port(value: str | None) -> int:
    raw = _clean(value) or "8787"
    try:
        port = int(raw)
    except ValueError as exc:
        raise ConfigError("BIND_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ConfigError("BIND_PORT must be between 1 and 65535")
    return port


@lru_cache(maxsize=2)
def get_settings(*, require_bearer_token: bool = False) -> Settings:
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

    oauth_keys_path = _expand_path(_clean(os.getenv("GOOGLE_OAUTH_KEYS_PATH")) or DEFAULT_OAUTH_KEYS_PATH)
    file_client = _read_oauth_keys(oauth_keys_path)

    env_client_id = _clean(os.getenv("GOOGLE_CLIENT_ID"))
    env_client_secret = _clean(os.getenv("GOOGLE_CLIENT_SECRET"))

    if env_client_id or env_client_secret:
        client_id = _required("GOOGLE_CLIENT_ID", env_client_id)
        client_secret = _required("GOOGLE_CLIENT_SECRET", env_client_secret)
        oauth_source = "env"
        redirect_candidates: tuple[str, ...] = ()
    elif file_client:
        client_id = file_client.client_id
        client_secret = file_client.client_secret
        oauth_source = file_client.source
        redirect_candidates = file_client.redirect_uris
    else:
        raise ConfigError(
            "Missing Google OAuth credentials: set GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET, or provide gcp-oauth.keys.json"
        )

    redirect_uri = _clean(os.getenv("GOOGLE_REDIRECT_URI"))
    if not redirect_uri and redirect_candidates:
        redirect_uri = redirect_candidates[0]

    bearer_token = _clean(os.getenv("MCP_BEARER_TOKEN"))
    if require_bearer_token:
        bearer_token = _required("MCP_BEARER_TOKEN", bearer_token)

    onboarding_url = _clean(os.getenv("GOOGLE_OAUTH_ONBOARDING_URL"))
    setup_secret = _clean(os.getenv("GOOGLE_OAUTH_SETUP_SECRET"))
    if bool(onboarding_url) != bool(setup_secret):
        raise ConfigError(
            "GOOGLE_OAUTH_ONBOARDING_URL and GOOGLE_OAUTH_SETUP_SECRET must be set together"
        )
    if onboarding_url and setup_secret:
        try:
            parsed_onboarding_url = urlsplit(onboarding_url)
        except ValueError as exc:
            raise ConfigError("GOOGLE_OAUTH_ONBOARDING_URL must be a valid HTTP(S) URL") from exc
        if (
            parsed_onboarding_url.scheme not in {"http", "https"}
            or not parsed_onboarding_url.netloc
            or parsed_onboarding_url.username
            or parsed_onboarding_url.password
            or parsed_onboarding_url.query
            or parsed_onboarding_url.fragment
            or any(character.isspace() for character in onboarding_url)
        ):
            raise ConfigError(
                "GOOGLE_OAUTH_ONBOARDING_URL must be an absolute HTTP(S) URL "
                "without credentials, query, fragment, or whitespace"
            )
        if (
            parsed_onboarding_url.scheme != "https"
            and parsed_onboarding_url.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ConfigError(
                "GOOGLE_OAUTH_ONBOARDING_URL must use HTTPS except on loopback hosts"
            )
        if setup_secret in onboarding_url:
            raise ConfigError("GOOGLE_OAUTH_ONBOARDING_URL must not contain the setup secret")

    return Settings(
        google_client_id=client_id,
        google_client_secret=client_secret,
        google_redirect_uri=_required("GOOGLE_REDIRECT_URI", redirect_uri),
        mcp_bearer_token=bearer_token,
        db_path=_expand_path(_clean(os.getenv("DB_PATH")) or DEFAULT_DB_PATH),
        bind_host=_clean(os.getenv("BIND_HOST")) or "127.0.0.1",
        bind_port=_parse_port(os.getenv("BIND_PORT") or os.getenv("PORT")),
        log_level=(_clean(os.getenv("LOG_LEVEL")) or "INFO").upper(),
        default_tasklist=_clean(os.getenv("DEFAULT_TASKLIST")),
        oauth_keys_path=oauth_keys_path,
        oauth_client_source=oauth_source,
        google_oauth_onboarding_url=onboarding_url,
        google_oauth_setup_secret=setup_secret,
    )


def reset_settings_cache() -> None:
    get_settings.cache_clear()
