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
| `today` | Incomplete tasks due today |
| `overdue` | Incomplete overdue tasks |
| `upcoming` | Tasks due within N days (default 7) |
| `search` | Case-insensitive title + notes search |
| `get_task` | Single task with full notes |
| `digest` | Short text summary (~30–100 tokens) |
| `add` | Create a task |
| `complete` | Mark a task done |
| `update` | Edit title, notes, or due date |
| `delete` | Delete a task |
| `move` | Move a task to another list |

All `tasklist` arguments accept both a list ID and a friendly title. When omitted, the server uses `DEFAULT_TASKLIST` from `.env`, or the first list returned by Google.

Cross-list `move` is emulated via insert + delete. The moved task gets a new Google task ID.

## Google Cloud setup

1. Create a project → enable the **Google Tasks API** → configure the OAuth consent screen.
2. Create an **OAuth 2.0 Client ID** → add your callback URL as an authorized redirect URI.
3. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` in `.env`.

Use `http://localhost:8787/callback` for local installs. Use `https://your-domain.example/callback` for remote servers.

If the consent screen is in testing mode, add your Google account as a test user or refresh tokens will expire after 7 days.

Alternatively, place the downloaded OAuth JSON file at `gcp-oauth.keys.json` in the repo root instead of setting env vars.

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

## More

- [MCP_SERVER_GUIDE.md](./MCP_SERVER_GUIDE.md) — local vs remote vs packaged client setup, single-account boundary
- [DISTRIBUTION.md](./DISTRIBUTION.md) — packaging, registries, and marketplace strategy
