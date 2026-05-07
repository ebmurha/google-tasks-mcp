# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Added an in-memory tasklist resolver cache, timezone resolver, mutation response builder, and structured MCP errors; breaking-change: false.
- Mutation tools now return rich self-describing responses with `human_summary`; breaking-change: false.
- Task tools can now find tasks by exact title, with structured not-found and ambiguity errors; breaking-change: false.

## [0.1.0] - 2026-05-05

### Added
- Initial public release
- Google Tasks MCP server
