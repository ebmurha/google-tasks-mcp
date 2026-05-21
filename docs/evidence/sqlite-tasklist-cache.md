# SQLite tasklist cache evidence

Date: 2026-05-21

## Commands Run

```bash
pytest tests/test_resolver.py tests/test_db.py tests/test_tasks_wrapper.py -x
```

Result:

```text
33 passed in 1.22s
```

```bash
pytest -x
```

Result:

```text
117 passed in 4.38s
```

## Failure Encountered

Initial targeted test run failed before tests executed because `tests/conftest.py` calls `clear_tasklist_cache()` before OAuth settings are configured. After the SQLite cache change, that helper touched SQLite, which required settings and raised:

```text
ConfigError: Missing Google OAuth credentials: set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or provide gcp-oauth.keys.json
```

## Fix Applied

`resolver.clear_tasklist_cache()` and `resolver.delete_tasklist_cached()` now always clear the in-memory tier and skip the SQLite operation only when settings are not yet available. Normal configured runtime paths still clear SQLite synchronously.

## Behavior Verified

- Fresh SQLite `tasklist_cache` rows seed the resolver after a cold start with zero `tasklists.list` calls.
- Stale SQLite rows older than the 5-minute TTL trigger one upstream `tasklists.list` refresh.
- Upstream refresh replaces the full SQLite tasklist set, removing rows for tasklists deleted outside this server.
- SQLite reads preserve fetched tasklist order so default fallback remains aligned with the first Google tasklist.
- `create_tasklist` and `update_tasklist` clear both cache tiers.
- `delete_tasklist` removes the deleted tasklist from SQLite and clears the in-memory tier.
- Full suite passed after the fix.
