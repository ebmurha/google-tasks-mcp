"""Google OAuth bootstrap and runtime credential refresh."""

from __future__ import annotations

import time
from datetime import timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from . import db
from .account import get_current_account_id
from .config import Settings, get_settings
from .errors import AuthRequired


SCOPES = ("https://www.googleapis.com/auth/tasks",)
REFRESH_BUFFER_SECONDS = 60
RECOGNIZED_OAUTH_ERRORS = frozenset(
    {
        "access_denied",
        "invalid_client",
        "invalid_grant",
        "invalid_request",
        "invalid_scope",
        "redirect_uri_mismatch",
        "server_error",
        "temporarily_unavailable",
        "unauthorized_client",
        "unsupported_grant_type",
    }
)
UNRECOGNIZED_OAUTH_ERROR = "unrecognized"


def _oauth_error_message(_exc: Exception) -> str:
    return "OAuth code exchange failed"


def _oauth_error_details(exc: Exception) -> dict[str, str | int]:
    provider_error = getattr(exc, "error", None)
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if response is not None:
        status_code = status_code or getattr(response, "status_code", None)
        try:
            body: Any = response.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            provider_error = provider_error or body.get("error")

    category = (
        provider_error
        if isinstance(provider_error, str)
        and provider_error in RECOGNIZED_OAUTH_ERRORS
        else UNRECOGNIZED_OAUTH_ERROR
    )
    details: dict[str, str | int] = {"provider_error": category}
    if type(status_code) is int and 100 <= status_code <= 599:
        details["provider_status"] = status_code
    return details


def _extract_code(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.query:
        code = parse_qs(parsed.query).get("code", [""])[0]
        if code:
            return code.strip()
    return value


def _build_flow(
    settings: Settings | None = None,
    *,
    state: str | None = None,
    code_verifier: str | None = None,
) -> Flow:
    settings = settings or get_settings()
    flow = Flow.from_client_config(
        settings.client_config(),
        scopes=list(SCOPES),
        state=state,
        code_verifier=code_verifier,
    )
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def build_authorization_flow(
    settings: Settings | None = None,
    *,
    state: str | None = None,
    code_verifier: str | None = None,
) -> Flow:
    return _build_flow(settings, state=state, code_verifier=code_verifier)


def authorization_url(flow: Flow | None = None, *, state: str | None = None) -> str:
    flow = flow or _build_flow()
    kwargs: dict[str, str] = {}
    if state is not None:
        kwargs["state"] = state
    url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        **kwargs,
    )
    return url


def _expiry_epoch(credentials: Credentials) -> int:
    if credentials.expiry is None:
        return 0
    return int(credentials.expiry.replace(tzinfo=timezone.utc).timestamp())


def exchange_code(code: str, *, flow: Flow | None = None, account_id: str | None = None) -> db.Token:
    code = _extract_code(code)
    if not code:
        raise AuthRequired("No OAuth code was provided")

    flow = flow or _build_flow()
    try:
        flow.fetch_token(code=code)
    except Exception as exc:  # google-auth-oauthlib raises requests/oauthlib errors.
        raise AuthRequired(
            _oauth_error_message(exc),
            **_oauth_error_details(exc),
        ) from exc

    credentials = flow.credentials
    if not credentials.refresh_token:
        raise AuthRequired("Google did not return a refresh token; run bootstrap again")

    scope = " ".join(credentials.scopes or SCOPES)
    db.save_token(
        refresh=credentials.refresh_token,
        access=credentials.token,
        expires_at=_expiry_epoch(credentials),
        scope=scope,
        account_id=account_id,
    )
    token = db.get_token(account_id)
    if token is None:
        raise AuthRequired("OAuth token could not be stored")
    return token


def set_refresh_token(
    refresh_token: str,
    *,
    scope: str | None = None,
    account_id: str | None = None,
) -> db.Token:
    refresh_token = refresh_token.strip()
    if not refresh_token:
        raise AuthRequired("Refresh token must not be empty")
    db.save_token(refresh=refresh_token, access=None, expires_at=0, scope=scope or SCOPES[0], account_id=account_id)
    token = db.get_token(account_id)
    if token is None:
        raise AuthRequired("Refresh token could not be stored")
    return token


def _needs_refresh(token: db.Token) -> bool:
    if not token.access_token or not token.access_expires_at:
        return True
    return token.access_expires_at <= int(time.time()) + REFRESH_BUFFER_SECONDS


def get_credentials(account_id: str | None = None) -> Credentials:
    settings = get_settings()
    account_id = account_id or get_current_account_id()
    token = db.get_token(account_id)
    if token is None:
        raise AuthRequired(f"Google account '{account_id}' is not connected")

    credentials = Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=token.scope.split(),
    )

    if _needs_refresh(token):
        try:
            credentials.refresh(Request())
        except (RefreshError, GoogleAuthError) as exc:
            raise AuthRequired("Google authorization expired or was revoked") from exc
        if not credentials.token:
            raise AuthRequired("Google access token refresh returned no token")
        db.update_access_token(credentials.token, _expiry_epoch(credentials), account_id=account_id)

    return credentials
