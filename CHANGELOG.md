# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Added an in-memory tasklist resolver cache, timezone resolver, mutation response builder, and structured MCP errors; breaking-change: false.
- Mutation tools now return rich self-describing responses with `human_summary`; breaking-change: false.
- Task tools can now find tasks by exact title, with structured not-found and ambiguity errors; breaking-change: false.
- Tasklist create, read, rename, and delete tools are now available with compact responses; breaking-change: false.
- A general task listing tool now supports Google Tasks filters and timezone-aware date ranges; breaking-change: false.
- Completed tasks can now be cleared from a tasklist after explicit confirmation; breaking-change: false.
- Task creation now supports subtasks and sibling positioning with optional parent and previous references; breaking-change: false.
- Task moves now support destination tasklists, parent changes, sibling ordering, and top-level moves; breaking-change: false.
- Completed tasks can now be reopened with `update.status` or the `uncomplete` tool; breaking-change: false.
- Task listing now auto-paginates up to 1000 tasks and returns a continuation token when truncated; breaking-change: false.
- Partial task updates are now covered so unchanged fields remain preserved; breaking-change: false.

## [0.1.0] - 2026-05-05

### Added
- Initial public release
- Google Tasks MCP server
