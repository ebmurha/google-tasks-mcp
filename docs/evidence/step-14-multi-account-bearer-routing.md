# Step 14 Evidence — Multi-account bearer-token routing

Date: 2026-05-21

## Commands Run

```bash
pytest tests/test_db.py tests/test_auth.py tests/test_http_app.py tests/test_resolver.py tests/test_scripts.py -x
```

Result:

```text
36 passed in 3.71s
```

```bash
pytest -x
```

Result:

```text
125 passed in 6.44s
```

## Behavior Verified

- Legacy `MCP_BEARER_TOKEN` still routes HTTP requests to account `default`.
- Stored hashed bearer tokens route HTTP requests to their configured `account_id`.
- Google OAuth token rows are isolated by `account_id`.
- Tasklist cache rows are isolated by `account_id`.
- Resolver in-memory caches are isolated by `account_id`.
- Bearer tokens are stored as hashes with enabled/revoked state; raw stored-token values are not persisted.
- OAuth bootstrap and refresh-token setup commands accept `--account-id`.
- The bearer-token creation command prints the raw token once and stores only its hash.
