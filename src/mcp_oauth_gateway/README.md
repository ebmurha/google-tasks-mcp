# mcp-oauth-gateway

Reusable OAuth 2.0 front door for remote MCP servers.  
Lets Claude.ai web custom connectors authenticate against your private MCP server.

## What it does

```
Claude.ai web
  → OAuth consent at /authorize
  → receives access token from /token
  → calls /mcp with Bearer token
  → gateway validates token
  → forwards to your MCP app
  → MCP app uses its own backend credentials (Google, Notion, etc.)
```

No per-user OAuth. No changes to your MCP tools. Single-operator model.

---

## Install

```bash
pip install starlette python-multipart uvicorn[standard]
# Copy mcp_oauth_gateway/ into your project, or pip install -e /path/to/mcp-oauth-gateway
```

---

## Integration (google-tasks-mcp)

**1. Update `http_app.py`** (see `examples/google_tasks_http_app.py`):

```python
from mcp_oauth_gateway import add_mcp_oauth_gateway

def create_app():
    raw_mcp_app = mcp.streamable_http_app()   # your existing app
    return add_mcp_oauth_gateway(
        raw_mcp_app,
        issuer=os.environ["MCP_OAUTH_ISSUER"],
        client_id=os.environ["MCP_OAUTH_CLIENT_ID"],
        client_secret=os.environ["MCP_OAUTH_CLIENT_SECRET"],
        signing_secret=os.environ["MCP_OAUTH_SIGNING_SECRET"],
        admin_password=os.environ.get("MCP_OAUTH_ADMIN_PASSWORD"),
    )

app = create_app()
```

**2. Generate secrets** (run once, save to `.env.secrets`):

```bash
python -c "import secrets; print('MCP_OAUTH_CLIENT_SECRET=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('MCP_OAUTH_SIGNING_SECRET=' + secrets.token_hex(32))"
```

**3. Set environment variables** in systemd / `.env.secrets`:

```ini
MCP_OAUTH_ISSUER=https://zoe-tasks.riseos.work
MCP_OAUTH_CLIENT_ID=claude-connector
MCP_OAUTH_CLIENT_SECRET=<from step 2>
MCP_OAUTH_SIGNING_SECRET=<from step 2>
MCP_OAUTH_ADMIN_PASSWORD=<your-consent-screen-password>   # optional
```

**4. Restart the service**:

```bash
sudo systemctl restart google-tasks-mcp
```

**5. Verify the discovery endpoint**:

```bash
curl https://zoe-tasks.riseos.work/.well-known/oauth-authorization-server | jq .
```

Expected response:
```json
{
  "issuer": "https://zoe-tasks.riseos.work",
  "authorization_endpoint": "https://zoe-tasks.riseos.work/authorize",
  "token_endpoint": "https://zoe-tasks.riseos.work/token",
  "response_types_supported": ["code"],
  "code_challenge_methods_supported": ["S256"]
}
```

---

## Add to Claude.ai web

1. Go to **Settings → Connectors → Add custom connector**
2. **Server name**: Google Tasks
3. **URL**: `https://zoe-tasks.riseos.work/mcp`
4. Open **Advanced settings**:
   - **OAuth Client ID**: `claude-connector`  (your `MCP_OAUTH_CLIENT_ID`)
   - **OAuth Client Secret**: `<your MCP_OAUTH_CLIENT_SECRET>`
5. Click **Add**
6. Click **Connect** → browser opens your consent screen → enter admin password (if set) → **Approve**

Done. The connector is live.

---

## OAuth flow reference

| Endpoint | Purpose |
|----------|---------|
| `GET /.well-known/oauth-authorization-server` | RFC 8414 metadata discovery |
| `GET /authorize` | Show consent screen to user |
| `POST /authorize` | Submit consent, issue auth code, redirect |
| `POST /token` | Exchange code for access+refresh tokens |
| `POST /revoke` | Revoke a refresh token |
| `POST /register` | DCR (disabled by default, enable with `enable_dcr=True`) |

Tokens are HMAC-SHA256 signed JWTs (no external dependency).  
Refresh tokens are opaque and stored in-memory (restart = re-auth).

---

## Reuse for other projects

```python
from mcp_oauth_gateway import add_mcp_oauth_gateway

app = add_mcp_oauth_gateway(
    your_other_mcp_app,
    issuer="https://notion.example.com",
    client_id="claude-connector",
    client_secret="...",
    signing_secret="...",
)
```

Each project gets its own issuer, client, and secrets. The package has zero knowledge of what the MCP app does.

---

## Notes

- **Persistent tokens**: Current store is in-memory. If you need tokens to survive restarts, swap `TokenStore` for a SQLite or Redis-backed implementation.
- **Multi-user**: Not designed for it. Single-operator: one set of backend credentials, one consent-screen password.
- **Claude code / Claude Desktop**: Still works via your existing `mcp-remote` + Bearer token setup. This gateway only adds the OAuth path for Claude.ai web.
