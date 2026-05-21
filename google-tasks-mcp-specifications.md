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

## Tool Groups And Discovery Metadata

Tools are conceptually grouped for documentation and client display:

- **Tasklists:** `list_tasklists`, `create_tasklist`, `get_tasklist`, `update_tasklist`, `delete_tasklist`
- **Task reads:** `list_tasks`, `get_task`
- **Task summaries:** `today`, `overdue`, `upcoming`, `search`, `digest`
- **Task mutations:** `clear_completed`, `add`, `complete`, `update`, `uncomplete`, `delete`, `move`

The MCP Python SDK exposes standard tool titles, descriptions, and annotations for read-only, destructive, idempotent, and open-world hints. This server must populate those standard fields for all tools. It must not add provider-specific grouping fields or wrapper/category tools unless the MCP SDK/protocol gains a first-class grouping mechanism and this spec is updated.

## Tasklist Scope Defaults

Tasklist-scoped inputs accept either a Google tasklist ID or an exact tasklist title.

When `tasklist` is omitted for read-summary tools, the server reads all tasklists for the authenticated account and aggregates the compact result:

- `today`
- `overdue`
- `upcoming`
- `search`
- `digest`

Aggregated task objects include `tasklist_id` and `tasklist_title` so callers can disambiguate tasks from different lists. Aggregated `digest` text labels tasks with their tasklist title. Aggregated results are ordered deterministically by due date when present, then tasklist title, then Google position/title. `search.limit` is applied after matches from all tasklists are merged.

When `tasklist` is provided for those read-summary tools, the result is scoped to exactly that one tasklist. The literal value `all` has no special meaning unless it is also the title or ID of a real tasklist.

All write tools, single-task tools, `list_tasks`, and `clear_completed` keep the default-tasklist behavior: when `tasklist` is omitted, they use `DEFAULT_TASKLIST`, or the first tasklist returned by Google for the authenticated account. This avoids accidental writes across every list.

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
- Hashed MCP OAuth refresh tokens issued by the HTTP OAuth gateway.
- Legacy single-account compatibility rows used for upgrade/fallback.

SQLite must not persist task content: task titles, notes, due dates, statuses, completion timestamps, parent/sibling links, web links, or derived filtered views.

## Bearer Token Rules

Stored bearer tokens are generated for operators and displayed once. The database stores only a stable hash, account id, optional label, enabled/revoked state, and timestamps.

Logs, tests, docs, and MCP responses must not print raw bearer tokens except for the one-time operator command that creates a new token.

## MCP OAuth Gateway Rules

When OAuth gateway mode is enabled, unauthenticated `/mcp` requests must return 401 and include a `WWW-Authenticate` header that points clients at the OAuth authorization metadata endpoint. Unauthenticated probe requests must not reach MCP tool, resource, or prompt handling.

MCP OAuth access tokens are signed and self-verifying. MCP OAuth refresh tokens are opaque, rotated on use, revocable, and persisted by hash so they survive server restarts without storing raw token values.

## Tasklist Cache Rules

The tasklist `id` / `title` map has two tiers:

- In-memory cache, scoped by `account_id`, with a 5-minute TTL.
- SQLite cache, scoped by `account_id`, used to seed the in-memory cache after restart.

Google Tasks remains the source of truth. Successful upstream tasklist fetches replace the full SQLite tasklist cache for that account. Tasklist create/update/delete operations synchronously invalidate the affected account cache.
