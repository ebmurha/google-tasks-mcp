# Google Tasks MCP Specifications

This document is the source of truth for server behavior. Keep the MCP tool contract stable unless this file is updated first.

## MCP Tool Contract

The server exposes exactly these 19 tools:

- `list_tasklists`
- `create_tasklist`
- `get_tasklist`
- `update_tasklist`
- `delete_tasklist`
- `list_tasks`
- `clear_completed`
- `today`
- `overdue`
- `upcoming`
- `search`
- `get_task`
- `digest`
- `add`
- `complete`
- `update`
- `uncomplete`
- `delete`
- `move`

Tool inputs and response shapes remain compact and provider-neutral. MCP responses must not expose raw Google API envelopes such as `kind`, `etag`, `selfLink`, pagination envelopes, or stack traces.

## Account Model

The server supports two HTTP bearer-token account modes:

- Legacy single-account mode: `MCP_BEARER_TOKEN` routes to account `default`.
- Multi-account bearer-token mode: operator-created bearer tokens route to a configured `account_id`.

Account selection is a transport/auth concern, not an MCP tool argument. MCP tools do not accept an account selector. A valid bearer token sets the request-local `account_id`; all Google OAuth token reads/writes, tasklist title cache reads/writes, and default tasklist fallback happen inside that account namespace.

Local stdio mode uses account `default` unless a future spec update defines another operator-controlled selection mechanism.

Google Cloud OAuth client configuration is not the account selector. `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` and `GOOGLE_OAUTH_KEYS_PATH` identify the OAuth client app. One OAuth client JSON can be reused for several Google users, such as `personal` and `work`, as long as those users are allowed by the Google OAuth consent screen. Each `google-tasks-mcp-bootstrap --account-id ...` run stores a separate refresh token for whichever Google account the operator authorizes in the browser.

## Persistence Boundary

SQLite may persist:

- Google OAuth tokens scoped by `account_id`.
- Tasklist `id` / `title` cache rows scoped by `account_id`.
- Hashed MCP bearer tokens mapped to `account_id`.
- Legacy single-account compatibility rows used for upgrade/fallback.

SQLite must not persist task content: task titles, notes, due dates, statuses, completion timestamps, parent/sibling links, web links, or derived filtered views.

## Bearer Token Rules

Stored bearer tokens are generated for operators and displayed once. The database stores only a stable hash, account id, optional label, enabled/revoked state, and timestamps.

Logs, tests, docs, and MCP responses must not print raw bearer tokens except for the one-time operator command that creates a new token.

## Tasklist Cache Rules

The tasklist `id` / `title` map has two tiers:

- In-memory cache, scoped by `account_id`, with a 5-minute TTL.
- SQLite cache, scoped by `account_id`, used to seed the in-memory cache after restart.

Google Tasks remains the source of truth. Successful upstream tasklist fetches replace the full SQLite tasklist cache for that account. Tasklist create/update/delete operations synchronously invalidate the affected account cache.
