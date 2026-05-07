# Google Tasks MCP Server

<!-- mcp-name: io.github.ebmurha/google-tasks-mcp -->

A self-hosted MCP server that connects any MCP-compatible client to Google Tasks. Tools return only what the model needs — compact task objects, no Google API envelope fields.

## Quickstart

```bash
git clone https://github.com/ebmurha/google-tasks-mcp.git
cd google-tasks-mcp
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e .
cp .env.example .env   # set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, MCP_BEARER_TOKEN
```

Generate `MCP_BEARER_TOKEN` with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Use it on HTTP MCP requests as `Authorization: Bearer <token>`.

Bootstrap OAuth (once):

```bash
google-tasks-mcp-bootstrap
# Open the printed URL, approve, paste back the code.
```

Start the server:

```bash
python -m google_tasks_mcp
```

Health check: `curl http://127.0.0.1:8787/healthz` → `{"ok":true}`

## Connect your MCP client

**Remote HTTP** (server on a VPS or local machine):

```
URL:  http://127.0.0.1:8787/mcp
Auth: Bearer <MCP_BEARER_TOKEN>
```

**Local stdio** (MCP client spawns the process directly):

```
command: /path/to/.venv/bin/python
args:    ["-m", "google_tasks_mcp", "--transport", "stdio"]
```

`MCP_BEARER_TOKEN` is not required for stdio.

## Tools

| Tool | What it does |
|------|--------------|
| `list_tasklists` | List your task lists |
| `create_tasklist` | Create a task list and return compact metadata with `human_summary` |
| `get_tasklist` | Get a task list by ID or exact title |
| `update_tasklist` | Rename a task list by ID only |
| `delete_tasklist` | Delete a task list by ID after `confirm: true`; non-empty lists require `force: true` |
| `list_tasks` | List tasks with date, completion, deleted, hidden, assigned, pagination, and timezone filters |
| `today` | Incomplete tasks due today |
| `overdue` | Incomplete overdue tasks |
| `upcoming` | Tasks due within N days (default 7) |
| `search` | Case-insensitive title + notes search |
| `get_task` | Single task by ID or exact title, with full notes |
| `digest` | Short text summary (~30–100 tokens) |
| `add` | Create a task and return a rich mutation response with `human_summary` |
| `complete` | Mark a task done by ID or exact title and return title, due date, tasklist, and `human_summary` |
| `update` | Edit a task by ID, or by exact title for non-title fields, and return changed fields in `human_summary` |
| `delete` | Delete a task by ID or exact title and return pre-deletion task details with `deleted: true` |
| `move` | Move a task by ID or exact title to another list and return the moved task details |

All `tasklist` arguments accept both a list ID and a friendly title. Task title lookup is exact after trimming whitespace and ignores case; if more than one active task matches, the server returns a structured ambiguity error with candidate IDs. When `tasklist` is omitted, the server uses `DEFAULT_TASKLIST` from `.env`, or the first list returned by Google. Task list rename and delete tools require an ID to reduce accidental destructive changes.

### Limitations

These are Google Tasks REST API limits, not MCP gaps — no workaround exists in this server:

- **Due dates are date-only.** Any time-of-day component on `due` is silently dropped by Google.
- **No recurrence.** The REST API has no `recurrence` field; recurring tasks created in the Google Tasks UI cannot be created or read through the API.
- **`clear` hides, doesn't delete.** Cleared completed tasks are marked hidden — they survive in the account and reappear when listed with `show_hidden`.

## Google Cloud setup

1. Create a project → enable the **Google Tasks API** → configure the OAuth consent screen.
2. Create an **OAuth 2.0 Client ID**.

**Recommended: Web application**

- Use this for normal local, VPS, Docker, and other server-style installs.
- Add the exact callback URL to **Authorized redirect URIs**.
- For local installs, use `http://127.0.0.1:8787/callback`.
- For remote servers, use `https://your-domain.example/callback`.
- Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` in `.env`.
- `GOOGLE_REDIRECT_URI` must exactly match one of the authorized redirect URIs.

Example `.env` values for a local Web application OAuth client:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8787/callback
```

**Local-only alternative: Desktop app**

- Choose **Desktop app** as the OAuth client application type.
- Use this only for a personal local install where the app runs on your own machine.
- Download the client JSON, store it outside the repo, and point `GOOGLE_OAUTH_KEYS_PATH` to the file.
- You may leave `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` empty when using the JSON file.
- You may omit `GOOGLE_REDIRECT_URI` if the JSON contains `redirect_uris`; otherwise set it to one of the JSON file's redirect URIs.

Example `.env` values for a Desktop app OAuth client:

```env
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
GOOGLE_OAUTH_KEYS_PATH=/home/you/.config/google-tasks-mcp/gcp-oauth.keys.json
```

The repo-root fallback name `gcp-oauth.keys.json` is supported for convenience, but keeping OAuth credential JSON outside the repo is preferred.

If the consent screen is in testing mode, add your Google account as a test user or refresh tokens will expire after 7 days.

## Docker

```bash
docker compose up --build
```

Keep `.env`, `gcp-oauth.keys.json`, and database files outside the image — mount a named volume for the database directory.

## VPS / systemd

Template files are in `deploy/`:

- `deploy/caddy/Caddyfile` — Caddy reverse proxy with HTTPS
- `deploy/systemd/google-tasks-mcp.service` — systemd unit

Replace all placeholder domains, paths, and users before deploying.

## Tests

```bash
pytest
```
