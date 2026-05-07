# Evidence: Foundation Utilities

Date: 2026-05-07

## Scope Completed

- Added `src/google_tasks_mcp/resolver.py` with in-memory tasklist ID/title maps, 5-minute TTL, refresh-on-miss, duplicate title errors, and a lock-backed single-flight refresh path.
- Consolidated `tasks.list_tasklists()`, `tasks.resolve_tasklist()`, and `tasks.clear_tasklist_cache()` onto the new resolver without changing their public signatures.
- Added `src/google_tasks_mcp/timezones.py` with explicit timezone, `GOOGLE_TASKS_MCP_DEFAULT_TZ`, and pass-through resolution.
- Added structured `NotFoundError`, `AmbiguousTitleError`, and `InvalidInputError` classes and wired them through `server._error_payload`.
- Added `digest.build_mutation_response(...)` for the rich mutation response shape.
- Added resolver, timezone, digest, tool-error, and wrapper regression tests.
- Added the required changelog entry with `breaking-change: false`.

## Commands Run

```powershell
python -m pytest tests/test_resolver.py tests/test_timezones.py tests/test_digest.py tests/test_tools.py -x
```

Observed result:

```text
25 passed
```

```powershell
python -m pytest -x
```

Observed result:

```text
56 passed
```

## Notes

- All Google API behavior in the new tests is mocked at the `googleapiclient.discovery.build` boundary by patching the resolver module's imported `build` callable.
- No live Google account smoke test was run; the change is additive infrastructure and no secrets or live OAuth credentials were used.
- README tool documentation was not changed because this work adds no tools and does not change tool signatures.

## Result

Foundation utilities are complete and verified.
