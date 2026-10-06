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
import threading
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
    def consume(
        self, token: str, client_id: str, resource: str
    ) -> Optional[Dict[str, Any]]: ...
    def revoke(self, token: str) -> None: ...
    def purge_expired(self) -> None: ...


class ClientBackend(Protocol):
    def save(self, client_id: str, client_secret: str, metadata: Dict[str, Any]) -> None: ...
    def get(self, client_id: str) -> Optional[Dict[str, Any]]: ...
    def authenticate(self, client_id: str, client_secret: str) -> bool: ...


class TokenStore:
    def __init__(
        self,
        signing_secret: str,
        *,
        issuer: str = "",
        refresh_backend: RefreshTokenBackend | None = None,
        client_backend: ClientBackend | None = None,
    ):
        self._secret = signing_secret
        self._issuer = issuer
        self._refresh_backend = refresh_backend
        self._client_backend = client_backend
        self._lock = threading.RLock()
        # code -> {client_id, redirect_uri, code_challenge, expires_at}
        self._codes: Dict[str, Dict[str, Any]] = {}
        # refresh_token -> {client_id, issued_at, expires_at}
        self._refresh: Dict[str, Dict[str, Any]] = {}

    # ---- Auth codes --------------------------------------------------------

    def issue_code(self, client_id: str, redirect_uri: str,
                   code_challenge: Optional[str], resource: str, ttl: int) -> str:
        code = secrets.token_urlsafe(32)
        with self._lock:
            self._codes[code] = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "code_challenge": code_challenge,
                "resource": resource,
                "expires_at": time.time() + ttl,
            }
        return code

    def get_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Return a copy of an unexpired code record without consuming it."""
        with self._lock:
            rec = self._codes.get(code)
            if rec is None:
                return None
            if rec["expires_at"] < time.time():
                self._codes.pop(code, None)
                return None
            return dict(rec)

    def consume_code(
        self,
        code: str,
        *,
        client_id: str,
        redirect_uri: str,
        resource: str,
        code_challenge: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Atomically delete a code only when every binding matches."""
        with self._lock:
            rec = self._codes.get(code)
            if rec is None:
                return None
            if rec["expires_at"] < time.time():
                self._codes.pop(code, None)
                return None
            if (
                rec["client_id"] != client_id
                or rec["redirect_uri"] != redirect_uri
                or rec["resource"] != resource
                or rec["code_challenge"] != code_challenge
            ):
                return None
            self._codes.pop(code, None)
            return rec

    # ---- Access tokens (signed JWTs) ---------------------------------------

    def issue_access_token(self, client_id: str, resource: str, ttl: int) -> str:
        payload = {
            "sub": client_id,
            "iss": self._issuer,
            "aud": resource,
            "iat": int(time.time()),
            "exp": int(time.time()) + ttl,
            "jti": secrets.token_hex(8),
        }
        return _sign(payload, self._secret)

    def verify_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        return _verify(token, self._secret)

    # ---- Refresh tokens (opaque) -------------------------------------------

    def issue_refresh_token(self, client_id: str, resource: str, ttl: int) -> str:
        token = secrets.token_urlsafe(48)
        record = {
            "client_id": client_id,
            "resource": resource,
            "expires_at": time.time() + ttl,
        }
        if self._refresh_backend is not None:
            self._refresh_backend.save(token, record)
        else:
            with self._lock:
                self._refresh[token] = record
        return token

    def consume_refresh_token(
        self, token: str, client_id: str, resource: str
    ) -> Optional[Dict[str, Any]]:
        """Atomically rotate a token only when client and resource match."""
        if self._refresh_backend is not None:
            return self._refresh_backend.consume(token, client_id, resource)
        with self._lock:
            rec = self._refresh.get(token)
            if rec is None:
                return None
            if rec["expires_at"] < time.time():
                self._refresh.pop(token, None)
                return None
            if rec["client_id"] != client_id or rec["resource"] != resource:
                return None
            self._refresh.pop(token, None)
            return rec

    def revoke_refresh_token(self, token: str):
        if self._refresh_backend is not None:
            self._refresh_backend.revoke(token)
        else:
            with self._lock:
                self._refresh.pop(token, None)

    # ---- DCR registered clients (optional) ---------------------------------

    def __init_dcr(self):
        if not hasattr(self, "_dcr_clients"):
            self._dcr_clients: Dict[str, Dict[str, Any]] = {}

    def register_dcr_client(self, metadata: dict) -> dict:
        self.__init_dcr()
        client_id = "dcr_" + secrets.token_hex(12)
        client_secret = secrets.token_urlsafe(32)
        clean_metadata = {
            key: value
            for key, value in metadata.items()
            if key not in {"client_id", "client_secret", "client_id_issued_at", "client_secret_expires_at"}
        }
        record = {**clean_metadata, "client_id": client_id}
        if self._client_backend is not None:
            self._client_backend.save(client_id, client_secret, record)
        else:
            self._dcr_clients[client_id] = {**record, "client_secret": client_secret}
        return {**record, "client_secret": client_secret}

    def get_dcr_client(self, client_id: str) -> Optional[dict]:
        self.__init_dcr()
        if self._client_backend is not None:
            return self._client_backend.get(client_id)
        return self._dcr_clients.get(client_id)

    def authenticate_dcr_client(self, client_id: str, client_secret: str) -> bool:
        if self._client_backend is not None:
            return self._client_backend.authenticate(client_id, client_secret)
        rec = self.get_dcr_client(client_id)
        return bool(rec and hmac.compare_digest(client_secret, rec.get("client_secret", "")))

    # ---- Cleanup -----------------------------------------------------------

    def purge_expired(self):
        now = time.time()
        self._codes = {k: v for k, v in self._codes.items() if v["expires_at"] > now}
        if self._refresh_backend is not None:
            self._refresh_backend.purge_expired()
        else:
            self._refresh = {k: v for k, v in self._refresh.items() if v["expires_at"] > now}
