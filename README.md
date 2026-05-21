# Google Tasks MCP Server

<!-- mcp-name: io.github.ebmurha/google-tasks-mcp -->

Connect an MCP-compatible client to Google Tasks through a private server you run yourself. The server exposes compact tools for reading, searching, summarizing, creating, completing, updating, deleting, and moving Google Tasks.

This project is for self-hosted use. You provide your own Google Cloud OAuth credentials, connect your own Google account, and keep tokens in your own SQLite database.

## What You Get

- 19 MCP tools for Google Tasks.
- Local stdio mode for desktop/client-launched setups.
- Streamable HTTP mode for local HTTP or VPS hosting.
- Bearer-token HTTP auth, plus optional OAuth 2.0 gateway mode for MCP clients that support OAuth.
- Compact responses designed for low-context assistant workflows.
- Optional operator-managed multi-account bearer-token routing, for familiar setups such as one personal account and one work account.

## Choose A Transport

| Use case | Transport | Auth |
| --- | --- | --- |
| MCP client starts the process directly | `stdio` | No `MCP_BEARER_TOKEN` needed |
| Local HTTP server | Streamable HTTP at `http://127.0.0.1:8787/mcp` | Bearer token |
| VPS or other host | Streamable HTTP at `https://your-domain.example/mcp` | Bearer token or OAuth gateway |

For deeper hosting and distribution guidance, see [MCP_SERVER_GUIDE.md](./MCP_SERVER_GUIDE.md) and [DISTRIBUTION.md](./DISTRIBUTION.md).

## Install

```bash
git clone https://github.com/ebmurha/google-tasks-mcp.git
cd google-tasks-mcp
python3.11 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
```

Generate a bearer token if you will run HTTP mode:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value in `.env` as `MCP_BEARER_TOKEN`. Do not commit `.env`.

## Google Cloud Setup

1. Create or open a Google Cloud project.
2. Enable the Google Tasks API.
3. Configure the OAuth consent screen.
4. Create an OAuth 2.0 Client ID.

Recommended for local HTTP, VPS, Docker, and other server-style installs:

- Application type: **Web application**
- Local redirect URI: `http://127.0.0.1:8787/callback`
- Hosted redirect URI: `https://your-domain.example/callback`
- `.env`: set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI`

Local-only alternative:

- Application type: **Desktop app**
- Download the OAuth client JSON outside this repo.
- Set `GOOGLE_OAUTH_KEYS_PATH` to that file path.
- Leave `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` empty unless you want env vars to override the JSON file.

Example `.env` for a local web OAuth client:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8787/callback
MCP_BEARER_TOKEN=generated-local-bearer-token
DB_PATH=./google-tasks.db
BIND_HOST=127.0.0.1
BIND_PORT=8787
```

If the Google OAuth app is in Testing mode, add every Google account you bootstrap as a test user, such as both personal and work accounts.

`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_OAUTH_KEYS_PATH` identify the Google Cloud OAuth app, not the Google Tasks user account. One OAuth client JSON can be reused for several Google users. Each bootstrap run stores a separate refresh token for the Google account you authorize in the browser.

## Bootstrap Google OAuth

Run this once per Google account you want the server to access:

```bash
google-tasks-mcp-bootstrap
```

Open the printed URL, approve access, and paste the authorization code back into the terminal.

For multiple trusted accounts on one HTTP server, create one stored bearer token per account and bootstrap each account separately:

```bash
google-tasks-mcp-create-bearer-token --account-id personal --label "Personal account"
google-tasks-mcp-bootstrap --account-id personal

google-tasks-mcp-create-bearer-token --account-id work --label "Work account"
google-tasks-mcp-bootstrap --account-id work
```

Use each printed bearer token only in the matching account's MCP client. The server stores only bearer-token hashes.

## Start The Server

HTTP mode:

```bash
python -m google_tasks_mcp --transport http
```

Health check:

```bash
curl http://127.0.0.1:8787/healthz
```

Expected response:

```json
{"ok": true}
```

Stdio mode:

```bash
python -m google_tasks_mcp --transport stdio
```

Configuration check:

```bash
python -m google_tasks_mcp --check
```

## Connect An MCP Client

Remote or local HTTP:

```text
URL:  http://127.0.0.1:8787/mcp
Auth: Bearer <MCP_BEARER_TOKEN>
```

For a VPS, replace the URL with your HTTPS endpoint:

```text
URL:  https://your-domain.example/mcp
Auth: Bearer <MCP_BEARER_TOKEN>
```

Local stdio:

```json
{
  "command": "/path/to/google-tasks-mcp/.venv/bin/python",
  "args": ["-m", "google_tasks_mcp", "--transport", "stdio"]
}
```

`MCP_BEARER_TOKEN` is not required for stdio because the MCP client launches the process locally.

## Authentication Modes

Bearer-token mode is the default HTTP mode. `/mcp` requires `Authorization: Bearer <token>`.

- `MCP_BEARER_TOKEN` routes to account `default`.
- Tokens created with `google-tasks-mcp-create-bearer-token` can route different clients to different `account_id` values.
- Bearer tokens are displayed once and stored only as hashes.

OAuth 2.0 gateway mode is optional. Enable it when your HTTP MCP client supports OAuth authorization metadata and token refresh.

- Set `MCP_OAUTH_ISSUER`, `MCP_OAUTH_CLIENT_ID`, `MCP_OAUTH_CLIENT_SECRET`, and `MCP_OAUTH_SIGNING_SECRET`.
- Set `MCP_OAUTH_REDIRECT_URIS` to the callback URI values accepted by your MCP client.
- `/mcp` accepts OAuth-issued access tokens and the legacy bearer token.
- OAuth gateway refresh tokens are stored by hash and rotate on use, so clients can reconnect after server restart.

Leave `MCP_OAUTH_REDIRECT_URIS` empty to keep OAuth gateway mode disabled.

## Tools

The same 19 tools are available over stdio, bearer-token HTTP, and OAuth gateway HTTP modes. Tools expose standard MCP titles, descriptions, and safety hints where the client supports them.

| Group | Tools | Notes |
| --- | --- | --- |
| Tasklists | `list_tasklists`, `create_tasklist`, `get_tasklist`, `update_tasklist`, `delete_tasklist` | Tasklist delete requires `confirm: true`; non-empty lists require `force: true`. |
| Task reads | `list_tasks`, `get_task` | Read from one tasklist. If `tasklist` is omitted, uses `DEFAULT_TASKLIST` or Google's first list. |
| Task summaries | `today`, `overdue`, `upcoming`, `search`, `digest` | If `tasklist` is omitted, reads all tasklists and includes tasklist context. |
| Task mutations | `clear_completed`, `add`, `complete`, `update`, `uncomplete`, `delete`, `move` | Mutate one tasklist/task at a time. `clear_completed` requires `confirm: true`. |

All `tasklist` arguments accept a tasklist ID or exact title. Task title lookup is exact after trimming whitespace and ignores case.

For `today`, `overdue`, `upcoming`, `search`, and `digest`, omitting `tasklist` reads every tasklist. Returned task objects include `tasklist_id` and `tasklist_title`; `digest` labels items with tasklist context.

For `list_tasks`, `clear_completed`, single-task tools, and write tools, omitting `tasklist` uses `DEFAULT_TASKLIST`, or the first list returned by Google. This prevents unqualified writes from touching every list.

## Limitations

These are Google Tasks REST API limits:

- Due dates are date-only. Google drops time-of-day values on task due dates.
- Recurring tasks cannot be created or read through the Google Tasks REST API.
- `clear_completed` hides completed tasks; it does not permanently delete them.

## Docker And VPS

Docker:

```bash
docker compose up --build
```

Keep `.env`, OAuth JSON files, and SQLite databases outside images and public bundles.

VPS/systemd/Caddy templates are in `deploy/`:

- [deploy/caddy/Caddyfile](./deploy/caddy/Caddyfile)
- [deploy/systemd/google-tasks-mcp.service](./deploy/systemd/google-tasks-mcp.service)

Replace every placeholder domain, path, and user before deploying.

## Troubleshooting

Missing bearer token:

- HTTP `/mcp` requires `Authorization: Bearer <token>` unless OAuth gateway mode is handling the client.
- Stdio mode does not use `MCP_BEARER_TOKEN`.

Google OAuth app is in Testing mode:

- Add every bootstrapped Google user as a test user.
- Testing-mode refresh tokens can expire after 7 days.

Callback URI mismatch:

- `GOOGLE_REDIRECT_URI` must exactly match an Authorized redirect URI in Google Cloud.
- For local web OAuth, use `http://127.0.0.1:8787/callback` consistently.

Expired or revoked Google refresh token:

- Run `google-tasks-mcp-bootstrap` again for the affected account.
- For multi-account mode, include the same `--account-id` you used before.

OAuth MCP client keeps re-authorizing:

- Ensure the server is running a version with persisted MCP OAuth refresh tokens.
- Check that `DB_PATH` points to persistent storage and survives restarts.
- Verify `MCP_OAUTH_ISSUER` is the public HTTPS base URL with no trailing slash.

## More Docs

- [MCP_SERVER_GUIDE.md](./MCP_SERVER_GUIDE.md) explains hosting models, credential boundaries, and public project vs public service choices.
- [DISTRIBUTION.md](./DISTRIBUTION.md) explains registry, bundle, and directory publishing.
- [.env.example](./.env.example) lists every supported environment variable.
- [google-tasks-mcp-specifications.md](./google-tasks-mcp-specifications.md) is the behavioral source of truth.

## Tests

```bash
pytest
```
