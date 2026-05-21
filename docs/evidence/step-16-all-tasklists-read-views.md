# Step 16 Evidence: Default read views to all tasklists

Date: 2026-05-21

## Commands Run

```powershell
pytest tests/test_tools.py -x
pytest tests/test_tasks_wrapper.py tests/test_resolver.py -x
pytest -x
git diff --check
```

## Results Observed

- `tests/test_tools.py tests/test_tasks_wrapper.py tests/test_resolver.py`: 82 passed.
- Full suite: 133 passed.
- `git diff --check`: no whitespace errors.

## Implementation Notes

- `today`, `overdue`, `upcoming`, `search`, and `digest` aggregate across every tasklist when `tasklist` is omitted.
- Explicit `tasklist` ID/title still scopes those tools to one list.
- `list_tasks`, `clear_completed`, single-task tools, and write tools keep the existing default-tasklist behavior.
- Aggregated compact tasks include `tasklist_id` and `tasklist_title`.
- Aggregated digest text labels tasks with the tasklist title and caps the merged input to 100 tasks.
- Search applies `limit` after matches from all tasklists are merged.
