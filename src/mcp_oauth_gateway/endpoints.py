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
import html
import json
import time
import urllib.parse
from typing import Optional

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route, Router

from .config import GatewayConfig, well_known_url
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
  <title>Authorize MCP access</title>
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
    button.deny{{margin-top:8px;background:#fff;color:#475569;border:1px solid #cbd5e1}}
    button.deny:hover{{background:#f8fafc}}
    .err{{color:#dc2626;font-size:14px;margin-bottom:12px}}
    .meta{{font-size:12px;color:#94a3b8;margin-top:16px;text-align:center}}
  </style>
</head>
<body>
<div class="card">
  <h2>Authorize MCP access</h2>
  <p><strong>{client_name}</strong> is requesting access. Enter the admin password to approve.</p>
  {error_block}
  <form method="POST" action="{authorization_endpoint}">
    <input type="hidden" name="state"          value="{state}">
    <input type="hidden" name="client_id"      value="{client_id}">
    <input type="hidden" name="redirect_uri"   value="{redirect_uri}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="code_challenge_method" value="S256">
    <input type="hidden" name="resource"       value="{resource}">
    <input type="hidden" name="response_type"  value="code">
    <label for="pw">Admin password</label>
    <input type="password" id="pw" name="password" autofocus placeholder="password">
    <button type="submit" name="decision" value="approve">Approve access</button>
    <button class="deny" type="submit" name="decision" value="deny">Deny</button>
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
  <title>Authorize MCP access</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:420px;margin:80px auto;padding:0 20px;color:#111}}
    .card{{border:1px solid #e2e8f0;border-radius:12px;padding:28px}}
    h2{{margin-bottom:8px}}p{{color:#555;margin-bottom:24px}}
    button{{width:100%;padding:12px;background:#2563eb;color:#fff;border:none;
      border-radius:8px;font-size:15px;cursor:pointer;font-weight:600}}
    button:hover{{background:#1d4ed8}}
    button.deny{{margin-top:8px;background:#fff;color:#475569;border:1px solid #cbd5e1}}
    button.deny:hover{{background:#f8fafc}}
    .meta{{font-size:12px;color:#94a3b8;margin-top:16px;text-align:center}}
  </style>
</head>
<body>
<div class="card">
  <h2>Authorize MCP access</h2>
  <p><strong>{client_name}</strong> is requesting access.</p>
  <form method="POST" action="{authorization_endpoint}">
    <input type="hidden" name="state"          value="{state}">
    <input type="hidden" name="client_id"      value="{client_id}">
    <input type="hidden" name="redirect_uri"   value="{redirect_uri}">
    <input type="hidden" name="code_challenge" value="{code_challenge}">
    <input type="hidden" name="code_challenge_method" value="S256">
    <input type="hidden" name="resource"       value="{resource}">
    <input type="hidden" name="response_type"  value="code">
    <button type="submit" name="decision" value="approve">Approve access</button>
    <button class="deny" type="submit" name="decision" value="deny">Deny</button>
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


def _consent_response(
    template: str,
    *,
    state: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    resource: str,
    issuer: str,
    client_name: str,
    error_block: str = "",
    status: int = 200,
) -> HTMLResponse:
    authorization_endpoint = f"{issuer.rstrip('/')}/authorize"
    rendered = template.format(
        state=html.escape(state, quote=True),
        client_id=html.escape(client_id, quote=True),
        redirect_uri=html.escape(redirect_uri, quote=True),
        code_challenge=html.escape(code_challenge, quote=True),
        resource=html.escape(resource, quote=True),
        issuer=html.escape(issuer, quote=True),
        client_name=html.escape(client_name, quote=True),
        authorization_endpoint=html.escape(authorization_endpoint, quote=True),
        error_block=error_block,
    )
    return HTMLResponse(
        rendered,
        status_code=status,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                f"form-action {authorization_endpoint}; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _pkce_verify(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == challenge


def _authorization_redirect(
    redirect_uri: str,
    *,
    issuer: str,
    state: str,
    code: str | None = None,
    error: str | None = None,
    description: str | None = None,
) -> RedirectResponse:
    params = {"iss": issuer}
    if state:
        params["state"] = state
    if code:
        params["code"] = code
    if error:
        params["error"] = error
    if description:
        params["error_description"] = description
    separator = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        redirect_uri + separator + urllib.parse.urlencode(params),
        status_code=302,
    )


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


def _client_display_name(store: TokenStore, client_id: str) -> str:
    record = store.get_dcr_client(client_id)
    if record:
        name = record.get("client_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "MCP client"


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def build_oauth_router(cfg: GatewayConfig, store: TokenStore) -> Router:
    authorization_metadata_path = urllib.parse.urlsplit(
        well_known_url(cfg.issuer, "oauth-authorization-server")
    ).path
    protected_resource_metadata_path = urllib.parse.urlsplit(
        well_known_url(cfg.resource, "oauth-protected-resource")
    ).path

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
            "authorization_response_iss_parameter_supported": True,
        }
        if cfg.enable_dcr:
            meta["registration_endpoint"] = f"{base}/register"
        return _json(meta)

    async def protected_resource(_request: Request) -> JSONResponse:
        return _json({
            "resource": cfg.resource,
            "authorization_servers": [cfg.issuer.rstrip("/")],
            "scopes_supported": ["mcp"],
        })

    # ---- /authorize GET (show consent) ------------------------------------

    async def authorize_get(request: Request) -> Response:
        params = dict(request.query_params)
        client_id    = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state        = params.get("state", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "")
        resource = params.get("resource", "")
        response_type  = params.get("response_type", "code")

        if not _validate_client_and_redirect(cfg, store, client_id, redirect_uri):
            return _error("unauthorized_client",
                          f"client_id or redirect_uri not recognised: {client_id} / {redirect_uri}",
                          status=401)

        if response_type != "code":
            return _authorization_redirect(
                redirect_uri, issuer=cfg.issuer, state=state,
                error="unsupported_response_type", description="Only 'code' is supported",
            )
        if resource != cfg.resource:
            return _authorization_redirect(
                redirect_uri, issuer=cfg.issuer, state=state,
                error="invalid_target", description="resource must identify this MCP server",
            )
        if not code_challenge or code_challenge_method != "S256":
            return _authorization_redirect(
                redirect_uri, issuer=cfg.issuer, state=state,
                error="invalid_request", description="PKCE S256 is required",
            )

        if cfg.admin_password:
            return _consent_response(
                CONSENT_HTML,
                state=state, client_id=client_id, redirect_uri=redirect_uri,
                code_challenge=code_challenge, resource=resource,
                issuer=cfg.issuer, client_name=_client_display_name(store, client_id),
                error_block="")
        return _consent_response(
            AUTOAPPROVE_HTML,
            state=state, client_id=client_id, redirect_uri=redirect_uri,
            code_challenge=code_challenge, resource=resource, issuer=cfg.issuer,
            client_name=_client_display_name(store, client_id))

    # ---- /authorize POST (form submit) ------------------------------------

    async def authorize_post(request: Request) -> Response:
        form = await request.form()
        client_id      = str(form.get("client_id", ""))
        redirect_uri   = str(form.get("redirect_uri", ""))
        state          = str(form.get("state", ""))
        code_challenge = str(form.get("code_challenge", ""))
        code_challenge_method = str(form.get("code_challenge_method", ""))
        resource       = str(form.get("resource", ""))
        password       = str(form.get("password", ""))
        decision       = str(form.get("decision", "approve"))

        if not _validate_client_and_redirect(cfg, store, client_id, redirect_uri):
            return _error("unauthorized_client", "client_id or redirect_uri not recognised", 401)
        if resource != cfg.resource:
            return _authorization_redirect(
                redirect_uri, issuer=cfg.issuer, state=state,
                error="invalid_target", description="resource must identify this MCP server",
            )
        if not code_challenge or code_challenge_method != "S256":
            return _authorization_redirect(
                redirect_uri, issuer=cfg.issuer, state=state,
                error="invalid_request", description="PKCE S256 is required",
            )
        if decision == "deny":
            return _authorization_redirect(
                redirect_uri, issuer=cfg.issuer, state=state,
                error="access_denied", description="The user denied the request",
            )
        if decision != "approve":
            return _authorization_redirect(
                redirect_uri, issuer=cfg.issuer, state=state,
                error="invalid_request", description="Unknown authorization decision",
            )

        # Password gate
        if cfg.admin_password:
            import hmac as _hmac
            if not _hmac.compare_digest(password, cfg.admin_password):
                return _consent_response(
                    CONSENT_HTML,
                    state=state, client_id=client_id, redirect_uri=redirect_uri,
                    code_challenge=code_challenge, resource=resource, issuer=cfg.issuer,
                    client_name=_client_display_name(store, client_id),
                    error_block='<p class="err">Incorrect password. Try again.</p>',
                    status=401)

        code = store.issue_code(client_id, redirect_uri, code_challenge or None, resource,
                                cfg.auth_code_ttl)
        return _authorization_redirect(
            redirect_uri, issuer=cfg.issuer, state=state, code=code,
        )

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
            resource     = str(form.get("resource", ""))

            rec = store.get_code(code)
            if not rec:
                return _error("invalid_grant", "Code invalid or expired")
            if rec["client_id"] != req_client_id:
                return _error("invalid_grant", "client_id mismatch")
            if rec["redirect_uri"] != redirect_uri:
                return _error("invalid_grant", "redirect_uri mismatch")
            if resource != cfg.resource or rec["resource"] != resource:
                return _error("invalid_target", "resource mismatch")
            if rec["code_challenge"]:
                if not verifier:
                    return _error("invalid_grant", "code_verifier required")
                if not _pkce_verify(verifier, rec["code_challenge"]):
                    return _error("invalid_grant", "PKCE verification failed")

            rec = store.consume_code(
                code,
                client_id=req_client_id,
                redirect_uri=redirect_uri,
                resource=resource,
                code_challenge=rec["code_challenge"],
            )
            if not rec:
                return _error("invalid_grant", "Code invalid, expired, or already used")

            access_token  = store.issue_access_token(req_client_id, resource, cfg.access_token_ttl)
            refresh_token = store.issue_refresh_token(req_client_id, resource, cfg.refresh_token_ttl)
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
            resource = str(form.get("resource", ""))
            if resource != cfg.resource:
                return _error("invalid_target", "resource mismatch")
            rec = store.consume_refresh_token(rt, req_client_id, resource)
            if not rec:
                return _error("invalid_grant", "Refresh token invalid or expired")

            access_token  = store.issue_access_token(req_client_id, resource, cfg.access_token_ttl)
            new_refresh   = store.issue_refresh_token(req_client_id, resource, cfg.refresh_token_ttl)
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
        record["client_id_issued_at"] = int(time.time())
        record["client_secret_expires_at"] = 0
        return _json(record, status=201)

    # ---- routing -----------------------------------------------------------

    routes = [
        Route("/.well-known/oauth-authorization-server", discovery),
        Route("/.well-known/oauth-protected-resource", protected_resource),
        Route("/authorize", authorize_get,  methods=["GET"]),
        Route("/authorize", authorize_post, methods=["POST"]),
        Route("/token",     token,          methods=["POST"]),
        Route("/revoke",    revoke,         methods=["POST"]),
        Route("/register",  register,       methods=["POST"]),
    ]
    if authorization_metadata_path != "/.well-known/oauth-authorization-server":
        routes.insert(1, Route(authorization_metadata_path, discovery))
    if protected_resource_metadata_path != "/.well-known/oauth-protected-resource":
        routes.insert(2, Route(protected_resource_metadata_path, protected_resource))
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
        return store.authenticate_dcr_client(client_id, client_secret)
    return False
