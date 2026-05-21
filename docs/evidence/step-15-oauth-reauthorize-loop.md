# Step 15 Evidence — OAuth re-authorize loop and auth bypass

Date: 2026-05-21

## Commands Run

```bash
pytest tests/test_http_app.py tests/test_db.py src/mcp_oauth_gateway/test_gateway.py -x
```

Result:

```text
31 passed, 1 warning in 4.59s
```

Warning observed: `src/mcp_oauth_gateway/test_gateway.py::test_full_authorization_code_flow` returns a token dict for reuse by sibling tests. Existing behavior; not introduced by this change.

```bash
pytest tests/test_release_artifacts.py -x
```

Result:

```text
7 passed in 0.20s
```

```bash
pytest -x
```

Result:

```text
129 passed in 8.25s
```

## Behavior Verified

- OAuth gateway mode returns 401 for unauthenticated `/mcp` requests.
- The unauthenticated `/mcp` probe does not expose MCP tool names.
- The 401 response includes a `WWW-Authenticate` header with OAuth authorization-server metadata.
- MCP OAuth refresh tokens are persisted by hash in SQLite.
- A refresh token issued by one app instance can be consumed by a new app instance after restart.
- Refresh-token rotation invalidates the old refresh token.
- Access tokens remain signed self-verifying tokens and are not persisted.
- Non-secret debug logs identify auth accept/reject decisions without logging token values.
