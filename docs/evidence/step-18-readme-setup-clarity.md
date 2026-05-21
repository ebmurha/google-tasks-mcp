# Step 18 Evidence: README setup clarity

Date: 2026-05-21

## Docs Audited

- `README.md`
- `MCP_SERVER_GUIDE.md`
- `DISTRIBUTION.md`
- `.env.example`
- `docs/samples/slack-mcp-readme.md`
- `server.json`
- `manifest.json`
- `metadata/glama.json`

## Manual README Check

Reviewed the README flow from a clean install perspective:

1. Clone repository.
2. Create virtual environment.
3. Install editable package.
4. Copy `.env.example` to `.env`.
5. Configure Google OAuth placeholders.
6. Generate an HTTP bearer token.
7. Run OAuth bootstrap command.
8. Start local HTTP server.
9. Connect an MCP client to `/mcp`.

The README keeps real user-provided secrets out of examples and uses only placeholders.

Executed a placeholder-safe local configuration check and HTTP health check with dummy OAuth values, a dummy bearer token, and a temporary SQLite path:

```powershell
python -m google_tasks_mcp --check
python -m google_tasks_mcp --transport http
Invoke-RestMethod -Uri 'http://127.0.0.1:8877/healthz'
```

Observed:

- `--check` reported configuration loaded and database ready.
- `/healthz` returned `{"ok":true}`.
- Temporary SQLite file was removed after the check.

OAuth bootstrap was reviewed from the README command path but not completed, because it requires a real Google OAuth client and a real Google account authorization.

## Commands Run

```powershell
pytest tests/test_release_artifacts.py -x
pytest -x
git diff --check
```

## Results Observed

- Release artifact tests: 7 passed.
- Full suite: 133 passed.
- `git diff --check`: no whitespace errors.

## Notes

- The `mcp-name: io.github.ebmurha/google-tasks-mcp` marker remains in README for registry metadata.
- README word count was reduced from 1377 to 1253 words while adding clearer setup structure.
- Deep hosting and distribution detail remains linked through `MCP_SERVER_GUIDE.md` and `DISTRIBUTION.md`.
