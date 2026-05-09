"""
OAuth 2.0 endpoints for MCP connector auth.

Implements:
  GET  /.well-known/oauth-authorization-server   (RFC 8414 metadata)
  GET  /authorize                                 (consent screen + code issue)
  POST /token                                     (code exchange + refresh)
  POST /register                                  (DCR - RFC 7591, optional)
  POST /revoke                                    (RFC 7009, optional)
"""
import base64
import hashlib
import json
import time
import urllib.parse
from typing import Optional

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route, Router

from .config import GatewayConfig
from .store import TokenStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONSENT_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Authorize Claude Connector</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:420px;margin:80px auto;padding:0 20px;color:#111}}
    h2{{margin-bottom:8px}}
    p{{color:#555;margin-bottom:24px}}
    .card{{border:1px solid #e2e8f0;border-radius:12px;padding:28px}}
    label{{display:block;margin-bottom:6px;font-weight:500}}
    input[type=password]{{width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:8px;
      font-size:15px;box-sizing:border-box;margin-bottom:16px}}
    button{{width:100%;padding:12px;background:#2563eb;color:#fff;border:none;
      border-radius:8px;font-size:15px;cursor:pointer;font-weight:600}}
    button:hover{{background:#1d4ed8}}
    .err{{color:#dc2626;font-size:14px;margin-bottom:12px}}
    .meta{{font-size:12px;color:#94a3b8;margin-top:16px;text-align:center}}
  </style>
</head>
<body>
<div class="card">
  <h2>Authorize Claude Connector</h2>
  <p>A Claude.ai connector is requesting access. Enter the admin password to approve.</p>
  {error_block}
  <form method="POST">
    <input type="hidden" name="state"          value="{state}">
    <input type="hidden" name="client_id"      value="{client_id}">
    <input type="hidden" name="redirect_uri"   value="{redirect_uri}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="response_type"  value="code">
    <label for="pw">Admin password</label>
    <input type="password" id="pw" name="password" autofocus placeholder="password">
    <button type="submit">Approve access</button>
  </form>
  <p class="meta">Issuer: {issuer}</p>
</div>
</body>
</html>
"""

AUTOAPPROVE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Authorize Claude Connector</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:420px;margin:80px auto;padding:0 20px;color:#111}}
    .card{{border:1px solid #e2e8f0;border-radius:12px;padding:28px}}
    h2{{margin-bottom:8px}}p{{color:#555;margin-bottom:24px}}
    button{{width:100%;padding:12px;background:#2563eb;color:#fff;border:none;
      border-radius:8px;font-size:15px;cursor:pointer;font-weight:600}}
    button:hover{{background:#1d4ed8}}
    .meta{{font-size:12px;color:#94a3b8;margin-top:16px;text-align:center}}
  </style>
</head>
<body>
<div class="card">
  <h2>Authorize Claude Connector</h2>
  <p>Click approve to grant this Claude connector access.</p>
  <form method="POST">
    <input type="hidden" name="state"          value="{state}">
    <input type="hidden" name="client_id"      value="{client_id}">
    <input type="hidden" name="redirect_uri"   value="{redirect_uri}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="response_type"  value="code">
    <button type="submit">Approve access</button>
  </form>
  <p class="meta">Issuer: {issuer}</p>
</div>
</body>
</html>
"""


def _json(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status,
                        headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _error(error: str, description: str, status: int = 400) -> JSONResponse:
    return _json({"error": error, "error_description": description}, status)


def _pkce_verify(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == challenge


def _basic_auth(request: Request) -> Optional[tuple]:
    """Parse HTTP Basic auth header, return (client_id, client_secret) or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        cid, secret = decoded.split(":", 1)
        return cid, secret
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def build_oauth_router(cfg: GatewayConfig, store: TokenStore) -> Router:

    # ---- Discovery ---------------------------------------------------------

    async def discovery(request: Request) -> JSONResponse:
        base = cfg.issuer.rstrip("/")
        meta = {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "revocation_endpoint": f"{base}/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "scopes_supported": ["mcp"],
        }
        if cfg.enable_dcr:
            meta["registration_endpoint"] = f"{base}/register"
        return _json(meta)

    # ---- /authorize GET (show consent) ------------------------------------

    async def authorize_get(request: Request) -> Response:
        params = dict(request.query_params)
        client_id    = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state        = params.get("state", "")
        code_challenge = params.get("code_challenge", "")
        response_type  = params.get("response_type", "code")

        if response_type != "code":
            return _error("unsupported_response_type", "Only 'code' is supported")

        if not _validate_client_and_redirect(cfg, store, client_id, redirect_uri):
            return _error("unauthorized_client",
                          f"client_id or redirect_uri not recognised: {client_id} / {redirect_uri}",
                          status=401)

        if cfg.admin_password:
            html = CONSENT_HTML.format(
                state=state, client_id=client_id, redirect_uri=redirect_uri,
                code_challenge=code_challenge, issuer=cfg.issuer, error_block="")
        else:
            html = AUTOAPPROVE_HTML.format(
                state=state, client_id=client_id, redirect_uri=redirect_uri,
                code_challenge=code_challenge, issuer=cfg.issuer)
        return HTMLResponse(html)

    # ---- /authorize POST (form submit) ------------------------------------

    async def authorize_post(request: Request) -> Response:
        form = await request.form()
        client_id      = str(form.get("client_id", ""))
        redirect_uri   = str(form.get("redirect_uri", ""))
        state          = str(form.get("state", ""))
        code_challenge = str(form.get("code_challenge", ""))
        password       = str(form.get("password", ""))

        if not _validate_client_and_redirect(cfg, store, client_id, redirect_uri):
            return _error("unauthorized_client", "client_id or redirect_uri not recognised", 401)

        # Password gate
        if cfg.admin_password:
            import hmac as _hmac
            if not _hmac.compare_digest(password, cfg.admin_password):
                html = CONSENT_HTML.format(
                    state=state, client_id=client_id, redirect_uri=redirect_uri,
                    code_challenge=code_challenge, issuer=cfg.issuer,
                    error_block='<p class="err">Incorrect password. Try again.</p>')
                return HTMLResponse(html, status_code=401)

        code = store.issue_code(client_id, redirect_uri, code_challenge or None,
                                cfg.auth_code_ttl)
        sep = "&" if "?" in redirect_uri else "?"
        location = f"{redirect_uri}{sep}code={code}&state={urllib.parse.quote(state)}"
        return RedirectResponse(location, status_code=302)

    # ---- /token ------------------------------------------------------------

    async def token(request: Request) -> JSONResponse:
        # Accept application/x-www-form-urlencoded
        try:
            form = await request.form()
        except Exception:
            return _error("invalid_request", "Expected form body")

        grant_type = str(form.get("grant_type", ""))

        # Resolve client credentials (Basic header or form params)
        creds = _basic_auth(request)
        if creds:
            req_client_id, req_secret = creds
        else:
            req_client_id = str(form.get("client_id", ""))
            req_secret    = str(form.get("client_secret", ""))

        if not _authenticate_client(cfg, store, req_client_id, req_secret):
            return _error("invalid_client", "client_id or client_secret invalid", status=401)

        # --- authorization_code grant ----------------------------------------
        if grant_type == "authorization_code":
            code         = str(form.get("code", ""))
            redirect_uri = str(form.get("redirect_uri", ""))
            verifier     = str(form.get("code_verifier", ""))

            rec = store.consume_code(code)
            if not rec:
                return _error("invalid_grant", "Code invalid or expired")
            if rec["client_id"] != req_client_id:
                return _error("invalid_grant", "client_id mismatch")
            if rec["redirect_uri"] != redirect_uri:
                return _error("invalid_grant", "redirect_uri mismatch")
            if rec["code_challenge"]:
                if not verifier:
                    return _error("invalid_grant", "code_verifier required")
                if not _pkce_verify(verifier, rec["code_challenge"]):
                    return _error("invalid_grant", "PKCE verification failed")

            access_token  = store.issue_access_token(req_client_id, cfg.access_token_ttl)
            refresh_token = store.issue_refresh_token(req_client_id, cfg.refresh_token_ttl)
            return _json({
                "access_token":  access_token,
                "token_type":    "Bearer",
                "expires_in":    cfg.access_token_ttl,
                "refresh_token": refresh_token,
                "scope":         "mcp",
            })

        # --- refresh_token grant ---------------------------------------------
        if grant_type == "refresh_token":
            rt = str(form.get("refresh_token", ""))
            rec = store.consume_refresh_token(rt)
            if not rec:
                return _error("invalid_grant", "Refresh token invalid or expired")
            if rec["client_id"] != req_client_id:
                return _error("invalid_grant", "client_id mismatch")

            access_token  = store.issue_access_token(req_client_id, cfg.access_token_ttl)
            new_refresh   = store.issue_refresh_token(req_client_id, cfg.refresh_token_ttl)
            return _json({
                "access_token":  access_token,
                "token_type":    "Bearer",
                "expires_in":    cfg.access_token_ttl,
                "refresh_token": new_refresh,
                "scope":         "mcp",
            })

        return _error("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")

    # ---- /revoke -----------------------------------------------------------

    async def revoke(request: Request) -> Response:
        try:
            form = await request.form()
        except Exception:
            return _error("invalid_request", "Expected form body")
        token_val = str(form.get("token", ""))
        store.revoke_refresh_token(token_val)
        return Response(status_code=200)

    # ---- /register (DCR - optional) ----------------------------------------

    async def register(request: Request) -> JSONResponse:
        if not cfg.enable_dcr:
            return _error("not_supported", "Dynamic Client Registration is disabled", 404)
        try:
            body = await request.json()
        except Exception:
            return _error("invalid_client_metadata", "Expected JSON body")
        redirect_uris = body.get("redirect_uris", [])
        for uri in redirect_uris:
            if uri not in cfg.allowed_redirect_uris:
                return _error("invalid_redirect_uri",
                              f"Redirect URI not in allowlist: {uri}")
        record = store.register_dcr_client(body)
        return _json(record, status=201)

    # ---- routing -----------------------------------------------------------

    routes = [
        Route("/.well-known/oauth-authorization-server", discovery),
        Route("/authorize", authorize_get,  methods=["GET"]),
        Route("/authorize", authorize_post, methods=["POST"]),
        Route("/token",     token,          methods=["POST"]),
        Route("/revoke",    revoke,         methods=["POST"]),
        Route("/register",  register,       methods=["POST"]),
    ]
    return Router(routes=routes)


# ---------------------------------------------------------------------------
# Client validation helpers
# ---------------------------------------------------------------------------

def _validate_client_and_redirect(cfg: GatewayConfig, store: TokenStore,
                                   client_id: str, redirect_uri: str) -> bool:
    """Return True if client_id is known AND redirect_uri is allowed."""
    if client_id == cfg.client_id:
        # Empty list = OAuth disabled — reject all
        if not cfg.allowed_redirect_uris:
            return False
        return redirect_uri in cfg.allowed_redirect_uris

    if cfg.enable_dcr:
        rec = store.get_dcr_client(client_id)
        if rec:
            allowed = rec.get("redirect_uris", [])
            if not allowed:
                return False
            return redirect_uri in allowed

    return False


def _authenticate_client(cfg: GatewayConfig, store: TokenStore,
                          client_id: str, client_secret: str) -> bool:
    """Return True if client credentials are valid."""
    import hmac as _hmac
    if client_id == cfg.client_id:
        return _hmac.compare_digest(client_secret, cfg.client_secret)
    if cfg.enable_dcr:
        rec = store.get_dcr_client(client_id)
        if rec:
            return _hmac.compare_digest(client_secret, rec.get("client_secret", ""))
    return False
