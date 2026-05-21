# Open Issue: MCP auth failures — two distinct problems, one misleading symptom

**Date opened:** 2026-05-18
**Reported by:** Server team / user
**Investigated by:** Claude Sonnet 4.6 (claude-sonnet-4-6)
**Status:** Fixed in `feature/oauth-reauthorize-loop` / next release. Google OAuth revocation remains an external operational condition.
**Connectors affected:** `mcp__c62db9d5` (primary), `mcp__google-tasks-vps` (backup)

---

## The misleading surface symptom

Claude reports "fails to connect" or shows a re-authorize prompt. Both connectors are affected simultaneously. No task operations execute. This looks like a single connection failure, but it is not. There are **two completely separate auth failures at two different layers**, and they present identically to the user. They must be diagnosed and fixed independently.

---

## Three auth layers in this system

This is the most important thing to understand before reading anything else. There are three separate token/auth systems stacked on top of each other:

```
Claude.ai UI
    │
    │  Layer 1: MCP OAuth (Claude.ai ↔ this server)
    │  Tokens: MCP access token (1h TTL) + MCP refresh token (30d TTL)
    │  Validated by: MCPAuthMiddleware / BearerAuthMiddleware
    │  Persisted: NO — in-memory TokenStore, lost on server restart
    ▼
/mcp endpoint (FastMCP)
    │
    │  Layer 2: MCP bearer token (Codex path only)
    │  Tokens: static MCP_BEARER_TOKEN
    │  Validated by: BearerAuthMiddleware
    │  Persisted: env var, always valid
    ▼
MCP tool handler (server.py)
    │
    │  Layer 3: Google Tasks OAuth (this server ↔ Google API)
    │  Tokens: Google access token (1h TTL) + Google refresh token (long-lived)
    │  Validated by: Google's OAuth2 server
    │  Persisted: YES — SQLite via db.py
    ▼
Google Tasks API
```

**Claude "fails to connect" when either Layer 1 or Layer 3 fails.** The HTTP response code from `/mcp` does not distinguish them. A broken Layer 3 still returns HTTP 200/202 from `/mcp` — the failure surfaces as a structured error payload inside the MCP tool response.

---

## Failure Mode A: Google Tasks OAuth token expired or revoked (Layer 3)

### What happened

Both connectors (`mcp__c62db9d5` and `mcp__google-tasks-vps`) returned:

```
"Google Tasks API request failed"
```

No task operations executed. Both connectors failed simultaneously.

### Why both connectors fail at the same time

Both connectors run on the same server process and share the same SQLite database at `/var/lib/google-tasks-mcp/google-tasks.db`. They share one Google OAuth refresh token. When that token is revoked by Google, both fail at the same instant.

### What the server does (from `auth.py:133–157`)

```python
def get_credentials() -> Credentials:
    token = db.get_token()          # reads Google refresh token from SQLite
    credentials = Credentials(...)
    if _needs_refresh(token):
        credentials.refresh(Request())   # calls Google's token endpoint
        db.update_access_token(...)      # saves new access token back to SQLite
    return credentials
```

If `credentials.refresh(Request())` fails, a `RefreshError` is raised, caught as `AuthRequired`, and the MCP tool returns `{"error": "Google access token refresh failed; run bootstrap_oauth.py", "hint": "..."}`. The MCP session itself stays open (HTTP 200/202 still returned). Claude surfaces this tool error as "fails to connect."

### Is this a persistence problem?

**No.** The Google refresh token IS persisted in SQLite. `db.py` correctly writes and reads it across restarts. The token is in the database — it is simply no longer accepted by Google.

### Is this an architecture problem?

**No.** The pattern (persist refresh token in DB, auto-refresh access token at call time) is correct OAuth2 design. There is nothing wrong with how the code manages this.

### What actually caused the token to become invalid

Google can revoke refresh tokens for several reasons. The most common for self-hosted OAuth apps:

1. **Google Cloud OAuth app in "Testing" mode** — tokens issued to test users expire after **7 days**, hard limit enforced by Google, regardless of what the code does. This is the most likely cause of a recurring ~7-day or ~48-hour cycle.
2. **User revoked access** in their Google Account settings.
3. **Too many active refresh tokens** (Google limits per user per app; older tokens are invalidated).
4. **Client secret rotated** in Google Cloud Console without updating `GOOGLE_CLIENT_SECRET` in the `.env` file.

### The fix (immediate)

```bash
google-tasks-mcp-bootstrap
# or
python scripts/bootstrap_oauth.py
```

This runs a fresh OAuth2 authorization code flow and writes a new Google refresh token to SQLite. Everything works again until the next revocation event.

### The durable fix

Go to [Google Cloud Console → APIs & Services → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent) and check the publishing status. If it says **"Testing"**, publish to **"Production"**. This removes the 7-day token expiry. Tokens then last until explicitly revoked and are automatically refreshed by the existing `auth.py` code.

If the app cannot be published (e.g., it hasn't passed Google verification), a workaround is to schedule `bootstrap_oauth.py` every 6 days via cron. This is ugly but functional.

---

## Failure Mode B: MCP OAuth 2.0 handshake broken — re-authorize loop (Layer 1)

### Symptom

Claude.ai (web connector) prompts "re-authorize" approximately every 48 hours. The OAuth flow appears to succeed (`/token` returns 200), but the re-authorize prompt returns within the same session or on next connection.

### Server evidence

**Caddy log (`/var/log/caddy/google-tasks-mcp.log`):**

```
Mon, 18 May 2026 19:17:06 GMT
POST /token    status: 200    User-Agent: python-httpx/0.28.1
```

Immediately after:

```
Mon, 18 May 2026 19:17:06–19:17:13 GMT
POST /mcp      status: 200    User-Agent: Claude-User
POST /mcp      status: 202    User-Agent: Claude-User
POST /mcp      status: 200    User-Agent: Claude-User  (×4)
Authorization: []
```

**Python/uvicorn log (same window):**

```
POST /token HTTP/1.1  200 OK
POST /mcp   HTTP/1.1  200 OK
POST /mcp   HTTP/1.1  202 Accepted
POST /mcp   HTTP/1.1  200 OK  (×4)

Processing request of type ListToolsRequest
Processing request of type ListResourcesRequest
Processing request of type ListPromptsRequest
```

No 401, 403, or authentication error in either log.

### Two different User-Agents — critical observation

```
python-httpx/0.28.1  →  POST /token   (Claude.ai's OAuth backend service)
Claude-User          →  POST /mcp     (Claude.ai's MCP connector service)
```

These are separate Claude.ai microservices. The access token is issued to the OAuth service. The MCP connector makes the `/mcp` calls. They appear not to share the token — the MCP connector sends `Authorization: []` (absent/empty) on every `/mcp` call.

### How MCP OAuth 2.0 discovery is supposed to work

Per the MCP Streamable HTTP spec (`Mcp-Protocol-Version: 2025-11-25`):

1. MCP connector sends `POST /mcp` **with no auth** — this is intentional protocol behavior, a probe
2. Server returns **401** + `WWW-Authenticate: Bearer` pointing to OAuth metadata endpoint
3. OAuth service discovers the auth server, runs the authorization code flow, calls `/token` → receives access token
4. MCP connector retries `POST /mcp` **with** `Authorization: Bearer {token}` → 200 → session established

**The server is returning 200 at step 1 instead of 401.** The discovery handshake never completes. The MCP connector gets MCP responses without ever obtaining a token. Its internal auth state is "unauthenticated." Claude.ai correctly shows "re-authorize" because from its perspective, the OAuth loop never completed.

The `ListToolsRequest` / `ListResourcesRequest` processing in the Python logs confirms the MCP session is open and functional without any auth token being validated. This is simultaneously the explanation for the re-authorize loop AND a security gap.

### The security gap

Any client can call `POST /mcp` without credentials and receive full MCP tool access. This is not theoretical — the logs prove it is happening.

### Why `MCPAuthMiddleware` is not blocking this (unresolved)

The middleware code at `middleware.py:54–57` is unambiguous:

```python
auth = headers.get(b"authorization", b"").decode("utf-8", errors="replace")
if not auth.lower().startswith("bearer "):
    resp = _unauthorized("Missing Bearer token")   # returns 401
    await resp(scope, receive, send)
    return
```

This **should** return 401 for `Authorization: []`. The Python logs confirm it does not. The discrepancy between code and runtime behavior is the unresolved core of this issue. Possible causes:

- **Middleware not in ASGI chain at runtime**: `EnvironmentApp._get_app()` creates the chain lazily on first request. If something goes wrong during `create_app()` (import error, exception swallowed), the fallback or a bare inner app might be served instead. Not confirmed.
- **FastMCP `Route` vs `Mount` interaction**: `_build_starlette_app()` does `Route("/mcp", endpoint=mcp_route.endpoint)` where `mcp_route.endpoint` may be an ASGI app rather than a plain handler. Starlette's `Route` handles plain callables differently from ASGI apps. This could cause certain request types (streaming POST, SSE) to reach the FastMCP handler without passing through `MCPAuthMiddleware`. This is the most architecturally plausible explanation and has not been ruled out.
- **Deployed code does not match git HEAD**: Cannot rule out. The `.venv` editable install shows version `0.2.0`; current git HEAD is `0.3.0`. If the server is running `0.2.0` code, `MCPAuthMiddleware` may not exist or may differ.

### The secondary bug: in-memory MCP refresh tokens lost on restart

`store.py:49–50`:
```python
self._codes:   Dict[str, Dict[str, Any]] = {}
self._refresh: Dict[str, Dict[str, Any]] = {}
```

MCP OAuth refresh tokens (issued by `/token`, used by Claude.ai to renew its 1-hour access token) are stored only in this dict. On server restart, `self._refresh` is empty. The next time Claude.ai calls `/token` with `grant_type=refresh_token`, the server returns `invalid_grant` and Claude.ai is forced to re-authorize.

This is **not the same token** as the Google Tasks refresh token (which is correctly persisted in SQLite). These are entirely separate systems.

The ~48-hour re-auth cycle likely correlates with the server restart cadence (systemd `Restart=on-failure`, OS updates, etc.).

---

## Dead ends investigated

1. **Caddy header redaction** — eliminated. Caddyfile has no `header_filter`, no `header_up Authorization`. Authorization passes verbatim.
2. **Wrong app mode** — eliminated. `MCP_OAUTH_ISSUER=https://zoe-tasks.riseos.work` is confirmed set; `create_app()` / `MCPAuthMiddleware` is the active code path.
3. **`MCP_BEARER_TOKEN` unset** — eliminated. `__main__.py` requires it non-empty for `--transport http`; server would not start otherwise.
4. **`hmac.compare_digest` returning True for empty string** — eliminated. Returns `False` for mismatched lengths. Empty auth still produces 401 in the code.
5. **`signing_secret` randomly regenerated on restart** — eliminated. `MCP_OAUTH_SIGNING_SECRET` is a required env var; it is stable across restarts.
6. **Standalone `google_tasks_http_app.py` entry point** — confirmed not used. Systemd ExecStart uses `python -m google_tasks_mcp`.
7. **Deployed code version mismatch** — not eliminated. The venv editable install is `0.2.0`, git HEAD is `0.3.0`. Worth verifying on the server.

---

## Answers to the key questions

**Is the Google Tasks token failure a persistence problem?**
No. The token is correctly persisted in SQLite. The problem is that Google revoked it externally, most likely because the OAuth app is in "Testing" mode (7-day token lifetime). Fix: publish the OAuth app to Production in Google Cloud Console.

**Is the Google Tasks token failure an architecture problem?**
No. The architecture is correct. `auth.py` auto-refreshes the access token using the stored refresh token. When Google revokes the refresh token itself, no amount of code can prevent re-authentication — `bootstrap_oauth.py` must be run.

**Why does "Claude fails to connect" appear when `/mcp` returns 200?**
There are two completely separate failure modes. Layer 3 (Google API) fails inside the MCP tool handler, returning a structured error payload over an already-established MCP session. Claude.ai surfaces this as a connection failure. The HTTP 200/202 from `/mcp` is correct — the MCP session is open. The failure is deeper, at the Google API call.

**Why does Claude show re-authorize when `/mcp` returns 200?**
The MCP OAuth 2.0 discovery handshake was never completed. The server accepted the probe request (step 1) with 200 instead of 401, so Claude.ai's MCP connector never received the signal to start the OAuth flow. Claude.ai knows it has no token and shows re-authorize.

---

## What needs to be fixed

### Fix A (immediate, operational): Google OAuth token

Run `google-tasks-mcp-bootstrap` and then in Google Cloud Console, publish the OAuth app to Production status.

### Fix B1 (critical — security): enforce auth on `/mcp`

**Implemented:** OAuth gateway mode now returns 401 for unauthenticated `/mcp` requests before MCP tool handling. Regression coverage asserts that a no-auth `tools/list` probe does not expose tool names.

Find and fix why `MCPAuthMiddleware` is not blocking unauthenticated `/mcp` requests.

First, add debug logging to confirm whether the middleware is in the chain at all:

```python
# middleware.py — top of MCPAuthMiddleware.__call__, before auth check
import logging
logging.getLogger("mcp_oauth_gateway.middleware").warning(
    "MCPAuth invoked — path=%s auth=%r",
    scope.get("path"),
    dict(scope.get("headers", [])).get(b"authorization"),
)
```

If this log line never appears for `/mcp` requests → middleware is not in the ASGI chain.
If it appears with `auth=b''` → 401 branch fires but something overrides the response.

Second, investigate `_build_starlette_app()` in `http_app.py`. The line:

```python
Route("/mcp", endpoint=mcp_route.endpoint)
```

If `mcp_route.endpoint` is an ASGI callable (not a plain Starlette handler), this may need to be a `Mount` instead of a `Route`, or the endpoint needs to be passed differently. A `Route`-wrapped ASGI app may not pass the full ASGI scope through `MCPAuthMiddleware` correctly for streaming requests.

### Fix B2 (correctness): `WWW-Authenticate` for MCP OAuth discovery

**Implemented:** the 401 response includes `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-authorization-server", error="invalid_token"` so MCP clients can discover the authorization server.

The 401 response from `_unauthorized()` must advertise the OAuth metadata URL for Claude.ai to auto-discover the auth server on the probe request:

```python
# middleware.py:_unauthorized()
headers={
    "WWW-Authenticate": 'Bearer realm="https://zoe-tasks.riseos.work", '
                        'error="invalid_token"',
    "Cache-Control": "no-store",
}
```

Per RFC 9728, the preferred form is:
```
WWW-Authenticate: Bearer resource_metadata="https://zoe-tasks.riseos.work/.well-known/oauth-authorization-server"
```

### Fix B3 (reliability): persist MCP OAuth refresh tokens to SQLite

**Implemented:** MCP OAuth refresh tokens are persisted by hash in SQLite, rotate on use, and survive server restarts. Access tokens remain signed self-verifying tokens and are not persisted.

`TokenStore._refresh` must survive server restarts. Extend `db.py` with an `mcp_oauth_tokens` table. `issue_refresh_token` inserts a row; `consume_refresh_token` reads and deletes (token rotation); `revoke_refresh_token` deletes. Access tokens are self-verifying JWTs and do not need persistence.

---

## Files the fixing model should focus on

| File | Why |
|------|-----|
| `src/mcp_oauth_gateway/middleware.py` | Auth bypass — primary bug; also WWW-Authenticate header |
| `src/google_tasks_mcp/http_app.py` | `_build_starlette_app()` — Route vs Mount for FastMCP; ASGI chain construction |
| `src/mcp_oauth_gateway/gateway.py` | `_CombinedApp` routing — confirm it doesn't short-circuit middleware for any path/method |
| `src/mcp_oauth_gateway/store.py` | `TokenStore` — add SQLite persistence for refresh tokens |
| `src/google_tasks_mcp/db.py` | Add `mcp_oauth_tokens` table |
| `src/google_tasks_mcp/auth.py` | Reference only — Google OAuth layer is correct, no changes needed |
