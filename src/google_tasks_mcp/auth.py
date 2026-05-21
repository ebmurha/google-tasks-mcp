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


def _oauth_error_message(exc: Exception) -> str:
    details: list[str] = []
    for attr in ("error", "description", "status_code"):
        value = getattr(exc, attr, None)
        if value:
            details.append(f"{attr}={value}")

    response = getattr(exc, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if status_code:
            details.append(f"status_code={status_code}")
        try:
            body: Any = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            for key in ("error", "error_description"):
                value = body.get(key)
                if value:
                    details.append(f"{key}={value}")

    if not details:
        return "OAuth code exchange failed; run bootstrap again"
    return "OAuth code exchange failed; " + "; ".join(details)


def _extract_code(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.query:
        code = parse_qs(parsed.query).get("code", [""])[0]
        if code:
            return code.strip()
    return value


def _build_flow(settings: Settings | None = None) -> Flow:
    settings = settings or get_settings()
    flow = Flow.from_client_config(settings.client_config(), scopes=list(SCOPES))
    flow.redirect_uri = settings.google_redirect_uri
    return flow


def build_authorization_flow(settings: Settings | None = None) -> Flow:
    return _build_flow(settings)


def authorization_url(flow: Flow | None = None) -> str:
    flow = flow or _build_flow()
    url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
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
        raise AuthRequired(_oauth_error_message(exc)) from exc

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


def get_credentials() -> Credentials:
    settings = get_settings()
    account_id = get_current_account_id()
    token = db.get_token(account_id)
    if token is None:
        raise AuthRequired(f"Run bootstrap_oauth.py for account '{account_id}' before using Google Tasks")

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
            raise AuthRequired("Google access token refresh failed; run bootstrap_oauth.py") from exc
        if not credentials.token:
            raise AuthRequired("Google access token refresh returned no token")
        db.update_access_token(credentials.token, _expiry_epoch(credentials), account_id=account_id)

    return credentials
