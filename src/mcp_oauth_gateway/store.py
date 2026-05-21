"""
Token / code store.

Keeps auth codes, access tokens, and refresh tokens.
Uses an in-process dict with TTL eviction by default.
Replace with Redis or SQLite for multi-process deployments.
"""
import time
import secrets
import hashlib
import hmac
import json
import base64
from typing import Optional, Dict, Any, Protocol


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).rstrip(b"=").decode()


def _sign(payload: dict, secret: str) -> str:
    """Produce a compact signed token: base64(payload).signature"""
    body = _b64(json.dumps(payload, separators=(",", ":")))
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify(token: str, secret: str) -> Optional[dict]:
    """Return payload dict if signature valid and not expired, else None."""
    try:
        body, sig = token.rsplit(".", 1)
        expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        padding = 4 - len(body) % 4
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * padding))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


class RefreshTokenBackend(Protocol):
    def save(self, token: str, record: Dict[str, Any]) -> None: ...
    def consume(self, token: str) -> Optional[Dict[str, Any]]: ...
    def revoke(self, token: str) -> None: ...
    def purge_expired(self) -> None: ...


class TokenStore:
    def __init__(self, signing_secret: str, refresh_backend: RefreshTokenBackend | None = None):
        self._secret = signing_secret
        self._refresh_backend = refresh_backend
        # code -> {client_id, redirect_uri, code_challenge, expires_at}
        self._codes: Dict[str, Dict[str, Any]] = {}
        # refresh_token -> {client_id, issued_at, expires_at}
        self._refresh: Dict[str, Dict[str, Any]] = {}

    # ---- Auth codes --------------------------------------------------------

    def issue_code(self, client_id: str, redirect_uri: str,
                   code_challenge: Optional[str], ttl: int) -> str:
        code = secrets.token_urlsafe(32)
        self._codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "expires_at": time.time() + ttl,
        }
        return code

    def consume_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Return and delete code record, or None if invalid/expired."""
        rec = self._codes.pop(code, None)
        if rec and rec["expires_at"] >= time.time():
            return rec
        return None

    # ---- Access tokens (signed JWTs) ---------------------------------------

    def issue_access_token(self, client_id: str, ttl: int) -> str:
        payload = {
            "sub": client_id,
            "iat": int(time.time()),
            "exp": int(time.time()) + ttl,
            "jti": secrets.token_hex(8),
        }
        return _sign(payload, self._secret)

    def verify_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        return _verify(token, self._secret)

    # ---- Refresh tokens (opaque) -------------------------------------------

    def issue_refresh_token(self, client_id: str, ttl: int) -> str:
        token = secrets.token_urlsafe(48)
        record = {
            "client_id": client_id,
            "expires_at": time.time() + ttl,
        }
        if self._refresh_backend is not None:
            self._refresh_backend.save(token, record)
        else:
            self._refresh[token] = record
        return token

    def consume_refresh_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Return and delete refresh record (rotation), or None if invalid."""
        if self._refresh_backend is not None:
            return self._refresh_backend.consume(token)
        rec = self._refresh.pop(token, None)
        if rec and rec["expires_at"] >= time.time():
            return rec
        return None

    def revoke_refresh_token(self, token: str):
        if self._refresh_backend is not None:
            self._refresh_backend.revoke(token)
        else:
            self._refresh.pop(token, None)

    # ---- DCR registered clients (optional) ---------------------------------

    def __init_dcr(self):
        if not hasattr(self, "_dcr_clients"):
            self._dcr_clients: Dict[str, Dict[str, Any]] = {}

    def register_dcr_client(self, metadata: dict) -> dict:
        self.__init_dcr()
        client_id = "dcr_" + secrets.token_hex(12)
        client_secret = secrets.token_urlsafe(32)
        record = {**metadata, "client_id": client_id, "client_secret": client_secret}
        self._dcr_clients[client_id] = record
        return record

    def get_dcr_client(self, client_id: str) -> Optional[dict]:
        self.__init_dcr()
        return self._dcr_clients.get(client_id)

    # ---- Cleanup -----------------------------------------------------------

    def purge_expired(self):
        now = time.time()
        self._codes = {k: v for k, v in self._codes.items() if v["expires_at"] > now}
        if self._refresh_backend is not None:
            self._refresh_backend.purge_expired()
        else:
            self._refresh = {k: v for k, v in self._refresh.items() if v["expires_at"] > now}
