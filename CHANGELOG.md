# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- OAuth 2.0 authorization-server gateway (`mcp_oauth_gateway`) wraps the HTTP app, enabling Claude.ai web and other OAuth clients to authenticate without a static bearer token. Legacy `MCP_BEARER_TOKEN` continues to work alongside OAuth-issued tokens.
- `MCP_OAUTH_REDIRECT_URIS` env var controls which redirect URIs are accepted; unset means Bearer-only mode with no startup error.
- `python-multipart` added as a runtime dependency (required for OAuth form parsing).

## [0.2.0] - 2026-05-07

### Added
- Added an in-memory tasklist resolver cache, timezone resolver, mutation response builder, and structured MCP errors.
- Mutation tools now return rich self-describing responses with `human_summary`.
- Task tools can now find tasks by exact title, with structured not-found and ambiguity errors.
- Tasklist create, read, rename, and delete tools are now available with compact responses.
- A general task listing tool now supports Google Tasks filters and timezone-aware date ranges.
- Completed tasks can now be cleared from a tasklist after explicit confirmation.
- Task creation now supports subtasks and sibling positioning with optional parent and previous references.
- Task moves now support destination tasklists, parent changes, sibling ordering, and top-level moves.
- Completed tasks can now be reopened with `update.status` or the `uncomplete` tool.
- Task listing now auto-paginates up to 1000 tasks and returns a continuation token when truncated.
- Partial task updates are now covered so unchanged fields remain preserved.
- Single-task fetches now include parent, position, and web link details.

### Compatibility
- This release is additive and preserves existing tool names and parameters.

## [0.1.0] - 2026-05-05

### Added
- Initial public release
- Google Tasks MCP server
