# Implementation Plan — Next Release

This is the working plan for the next release cycle. Keep the current source of truth in `google-tasks-mcp-specifications.md`, and update the spec before changing the MCP tool contract.

The v0.2.0 plan is archived at `docs/archive/implementation-plan-v0.2.0.md`.

## Rules

- Keep changes additive unless the spec is explicitly updated first.
- Preserve the exact MCP tool names and response contracts documented in the spec.
- Do not leak Google envelope fields or raw API payloads through MCP responses.
- Do not print, quote, summarize, or commit secrets.
- Tests that touch Google APIs must mock at the `googleapiclient.discovery.build` boundary.
- Evidence files must contain real command output and outcomes, not restated plans.
- No internal plan scaffolding belongs in public docs, code comments, tool docstrings, or error messages. The implementation plan and evidence files are the only exceptions.
- Do not archive this plan without explicit user approval.

## Definition Of Done

Each implementation step is complete only when all applicable items hold:

- [ ] `pytest` is green for new and existing tests.
- [ ] Tool docstrings are updated for any new or changed behavior.
- [ ] `README.md` reflects user-facing tool or setup changes.
- [ ] `CHANGELOG.md` has a user-facing entry with breaking-change status.
- [ ] Release-artifact metadata remains version- and tool-list consistent.
- [ ] Manual smoke testing is documented when behavior changes.
- [ ] No raw Google API envelopes, stack traces, or secrets leak through MCP responses or logs.
- [ ] Evidence is recorded under `docs/evidence/` when a step ships.

## Step Template

```markdown
### Step N — <Title>

- **Status:** Not started | In progress | Complete | Blocked
- **Objective:** <1-2 sentence statement of intent.>
- **Tasks / Actions:**
  - [ ] <code or docs change with file path where known>
  - [ ] <next change>
- **Tests to run:**
  - `<command>`
- **Constraints / rules (step-specific):**
  - <only what is unique to this step>
- **Acceptance criteria / verification checklist:**
  - [ ] <observable condition>
  - [ ] <observable condition>
```

## Build Sequence

Add future implementation steps here when the next release scope is known. Keep Docs And Release Prep and Archive The Plan steps below as the reusable release-prep and archive gates.

### Step 13 — Wire SQLite tasklist cache as resolver tier 2

- **Status:** Complete
- **Persistence boundary (binding scope of this step):** Until a later spec-updated account/auth step explicitly changes the persistence model, `db.py` persists exactly two single-account concerns:
  1. **`oauth_token`** — single-row auth state (refresh token, access token, expiry, scope).
  2. **`tasklist_cache`** — tasklist `id ↔ title` map only. No `due`, no `notes`, no `status`, no parent/sibling links, no row-per-task data.

  Task content (titles, notes, due dates, status, completion timestamps, parent/previous, links, web view URLs) is **never persisted** — Google is the source of truth. Filtered views (`today`, `overdue`, `upcoming`, `search`, `digest`) are likewise **never persisted**. Any code path that proposes to add a task-content table, a task-row cache, or a derived-view cache to `db.py` is by definition out of scope for this step and out of scope for this server's design (see `docs/google-tasks-mcp-cache-architecture.md` §3 rule 6 and §5 anti-patterns).

  Audit at the time this step was written: `db.py` contains zero task-content code. This step must preserve that invariant. If any task-content code is found during execution, treat it as dead code and remove it.

- **Objective:** Wire the existing SQLite `tasklist_cache` table into the in-memory resolver as a write-through second tier so a server restart no longer forces a `tasklists.list` round-trip on the next lookup. Closes the drift between the spec / cache architecture doc and the running code, while preserving the single-account task-content boundary above.
- **Tasks / Actions:**
  - [x] In `src/google_tasks_mcp/resolver.py`, on cold-cache lookups, seed the in-memory forward and reverse maps from `db.list_tasklists_cached()` before deciding whether to call `tasklists.list`. The SQLite seed is usable only when it is non-empty and every row's `updated_at` age is below `TASKLIST_CACHE_SECONDS`; set the in-memory `fetched_at` to the oldest cached `updated_at` so the normal 5-minute TTL still expires at the right time. Otherwise fall back to a fresh upstream fetch.
  - [x] Replace the current per-row write-through idea with an atomic full-set write after every successful upstream fetch. Add `db.replace_tasklist_cache(entries: Iterable[tuple[str, str]]) -> None` (or equivalent typed helper) that clears `tasklist_cache` and inserts the complete fetched `id/title` set in one transaction. This prevents tasklists deleted outside this server from surviving indefinitely in SQLite after refresh. Write-through remains synchronous inside the same single-flight critical section; no background queue.
  - [x] Keep or remove `db.upsert_tasklist` intentionally: if it remains public, it must have a production caller; otherwise replace tests that seed the cache with `replace_tasklist_cache` and remove the unused public helper.
  - [x] Add `db.delete_tasklist_cached(id: str) -> None` and `db.clear_tasklist_cache() -> None`. Call the per-id delete when `delete_tasklist` removes a specific list; call the full-table clear on `create_tasklist` / `update_tasklist` (table is tiny, whole-table flush is fine). Both paths must also clear the in-memory resolver cache.
  - [x] Add a one-line comment at the top of `resolver.py` stating the contract: "SQLite tier is write-through; never authoritative; invalidate on every tasklist mutation."
  - [x] Tests in `tests/test_resolver.py`:
    - [x] Cold-start seed: populate `tasklist_cache` directly via the production DB cache helper, instantiate a fresh resolver, perform a lookup — assert zero `tasklists.list` mock calls and correct id/title returned.
    - [x] Stale-seed refresh: same setup but with `updated_at` older than 5 minutes — assert one `tasklists.list` call and that the SQLite row is overwritten with fresh data.
    - [x] Write-through replacement: a fresh `tasklists.list` fetch results in `db.list_tasklists_cached()` returning exactly the fetched set, including removal of any stale SQLite rows not returned by Google.
    - [x] Mutation invalidation: invoking the create/update/delete invalidation paths clears both the in-memory maps and the corresponding SQLite row(s).
- **Tests to run:**
  - `pytest tests/test_resolver.py tests/test_db.py tests/test_tasks_wrapper.py -x`
  - Manual smoke: start server, call any tool that resolves a tasklist, stop server, restart, call the same tool again — assert via logs / mocks that the second call issues zero `tasklists.list` requests.
- **Constraints / rules (step-specific):**
  - SQLite tier is **never authoritative**. On any disagreement between in-memory and SQLite after a refresh, the fresh upstream result wins and gets written to SQLite.
  - Single-flight invariant from Step 0 must hold across the new SQLite reads/writes — no parallel duplicate `tasklists.list` calls when multiple tools race on a cold cache.
- **Acceptance criteria / verification checklist:**
  - [x] `db.py` contains code for exactly two persisted concerns — `oauth_token` and `tasklist_cache (id, title, updated_at)`. No task-content table, no task-row functions, no derived-view caches.
  - [x] Every public function in `db.py` has at least one production caller (no dead code).
  - [x] A server restart followed by a tasklist-resolving tool call issues zero `tasklists.list` API calls when the SQLite row is fresh (verified via mock call count).
  - [x] `create_tasklist` / `update_tasklist` / `delete_tasklist` invalidate the SQLite cache synchronously; the next lookup refetches from upstream and rewrites SQLite.
  - [x] `docs/google-tasks-mcp-cache-architecture.md` §4 no longer shows a drift row for the SQLite tier.
  - [x] No regression in the rest of the test suite.

### Step 14 — Multi-account bearer-token routing

- **Status:** Complete
- **Enhancement source:** `docs/planning/enhancements.md` bullet: "implement multi-user bearer token approach: so we support several accounts"
- **Objective:** Let one running HTTP server serve multiple Google Tasks accounts by mapping each incoming bearer token to an isolated account context. Preserve the existing single-account `MCP_BEARER_TOKEN` behavior as the default compatibility path.
- **Tasks / Actions:**
  - [x] Update `google-tasks-mcp-specifications.md` before code changes. If the spec file is absent, restore or recreate it as the source of truth first; do not change the account model only in code/docs.
  - [x] Define the account model in the spec and public docs: bearer token authenticates a caller and selects an `account_id`; MCP tool inputs do not gain an `account` parameter unless the spec explicitly chooses that contract.
  - [x] Add an account-aware request context, most likely via `contextvars`, that is set by HTTP auth middleware and read by `auth.py`, `tasks.py`, and `resolver.py`. Local stdio should continue to use one configured default account.
  - [x] Extend SQLite with account-scoped auth and cache storage: Google OAuth token rows keyed by `account_id`, tasklist cache rows keyed by `(account_id, tasklist_id)`, and a migration path from the legacy single-row `oauth_token` / tasklist cache to account `default`.
  - [x] Implement bearer-token registration without storing or logging raw tokens. Store only a stable secret hash plus `account_id`, label, enabled/revoked status, and timestamps. Provide an operator command or documented workflow that prints a newly generated token once and stores only its hash.
  - [x] Update `BearerAuthMiddleware` and OAuth-gateway static bearer compatibility so a valid bearer token sets the right `account_id`; invalid, missing, disabled, or revoked tokens return compact 401 errors with no token echoes.
  - [x] Update OAuth bootstrap and refresh-token setup scripts to accept an `--account-id` and write the Google refresh token for that account only.
  - [x] Thread `account_id` through Google credential loading, tasklist resolver cache, default tasklist fallback, and tasklist title lookup. No task data or filtered views may be persisted as part of this work.
  - [x] Update `README.md`, `MCP_SERVER_GUIDE.md`, `.env.example`, and deployment templates with placeholder-only multi-account configuration examples.
- **Tests to run:**
  - `pytest tests/test_db.py tests/test_auth.py tests/test_http_app.py tests/test_resolver.py -x`
  - `pytest -x`
- **Constraints / rules (step-specific):**
  - This step intentionally changes the single-account model; the spec must be updated first.
  - Do not add new MCP tools for account switching unless the spec explicitly changes the tool contract.
  - Do not store, print, snapshot, or return raw bearer tokens, Google refresh tokens, access tokens, client secrets, or OAuth codes.
  - Cross-account leakage is a release blocker: tasklists, tasks, defaults, OAuth tokens, and resolver caches must be isolated by `account_id`.
- **Acceptance criteria / verification checklist:**
  - [x] Existing single-account installs using `MCP_BEARER_TOKEN` and one bootstrapped Google account still work without migration instructions beyond normal upgrade notes.
  - [x] Two different bearer tokens in the same process resolve to two different Google OAuth token rows and cannot see each other's tasklists or cached tasklist titles.
  - [x] Revoking or disabling one bearer token does not affect other accounts.
  - [x] Logs include only non-sensitive account labels/IDs and never raw tokens.
  - [x] All account-model changes are documented in the spec, README, guide, changelog, and migration notes.

### Step 15 — Fix MCP OAuth re-authorize loop and auth bypass

- **Status:** Complete
- **Enhancement source:** `docs/planning/enhancements.md` bullet referencing `docs/open-issues/mcp-auth-reauthorize-loop.md`.
- **Objective:** Make the OAuth 2.0 gateway secure and durable for remote HTTP MCP clients by enforcing auth on `/mcp`, returning the discovery 401 expected by MCP clients, and persisting MCP OAuth refresh tokens across restarts.
- **Tasks / Actions:**
  - [x] Reproduce the unauthenticated `/mcp` behavior with an ASGI test before fixing it: a `POST /mcp` without `Authorization` must currently reach the MCP app in the failing case described by the issue.
  - [x] Fix the ASGI composition in `src/google_tasks_mcp/http_app.py` / `src/mcp_oauth_gateway/gateway.py` so every `/mcp` request passes through `MCPAuthMiddleware` in OAuth gateway mode. Investigate the current `Route("/mcp", endpoint=mcp_route.endpoint)` wrapping and replace it with the correct Starlette mounting/routing shape if needed.
  - [x] Update `MCPAuthMiddleware` unauthorized responses to return 401 with an MCP/OAuth discovery-friendly `WWW-Authenticate` header, using placeholder issuer values in docs and tests.
  - [x] Persist MCP OAuth refresh tokens used by `src/mcp_oauth_gateway/store.py`. Access tokens can remain signed self-verifying tokens; refresh tokens must survive process restarts, rotate on use, expire, and be revocable.
  - [x] Keep Google OAuth tokens separate from MCP OAuth tokens in naming, schema, docs, and errors. A Google token refresh failure must still surface as a compact tool error, not an MCP transport auth success/failure confusion.
  - [x] Add non-secret debug logging that can confirm middleware participation (`path`, auth status as present/missing, result code) without logging token values.
  - [x] Update `README.md`, `MCP_SERVER_GUIDE.md`, `.env.example`, and `docs/open-issues/mcp-auth-reauthorize-loop.md` status/outcome notes after the fix.
- **Tests to run:**
  - `pytest tests/test_http_app.py tests/test_oauth_gateway.py -x`
  - `pytest -x`
  - Manual smoke: start OAuth gateway mode, call unauthenticated `/mcp` and verify 401 + `WWW-Authenticate`; complete OAuth flow, restart the server, refresh the MCP access token, and verify no forced re-authorize.
- **Constraints / rules (step-specific):**
  - Do not weaken the legacy static bearer-token path; valid `MCP_BEARER_TOKEN` must still work when OAuth gateway mode explicitly allows it.
  - Do not expose stack traces or token diagnostics to MCP clients.
  - Use generic placeholder domains in docs and tests; no maintainer-specific hostnames.
- **Acceptance criteria / verification checklist:**
  - [x] Unauthenticated `/mcp` requests never list tools, resources, prompts, or invoke tools.
  - [x] The first unauthenticated MCP probe receives 401 with a useful `WWW-Authenticate` discovery header.
  - [x] OAuth-issued access tokens authorize `/mcp`; expired/invalid tokens do not.
  - [x] MCP OAuth refresh tokens remain valid after server restart until expiry or revocation, and rotation invalidates the old refresh token.
  - [x] The open issue documents the fix and no longer describes the current behavior as unresolved.

### Step 16 — Default read views to all tasklists

- **Status:** Complete
- **Enhancement source:** `docs/planning/enhancements.md` bullet: `docs/open-issues/mcp-bug-default-tasklist.md - go for option A.`
- **Objective:** Fix silent false-empty reads by making `today`, `overdue`, `upcoming`, `search`, and `digest` query all tasklists when `tasklist` is omitted. Explicit `tasklist` values must continue to scope to one list.
- **Tasks / Actions:**
  - [x] Update the spec before implementation: omitted `tasklist` for the five read-summary tools means all tasklists; write tools and single-task operations keep their current default-tasklist behavior unless the spec explicitly changes them.
  - [x] Add a shared read-scope helper in `server.py` or a small dedicated module: `tasklist=None` returns all tasklist IDs/titles from `tasks_api.list_tasklists()`, while a non-empty tasklist title/ID resolves to exactly one list. Consider accepting `tasklist="all"` only if the spec documents it.
  - [x] Update `today_tool`, `overdue_tool`, `upcoming_tool`, `search_tool`, and `digest_tool` to aggregate across the read scope. Keep Google as source of truth; do not cache task contents or filtered views.
  - [x] Preserve enough tasklist context in aggregated responses to disambiguate results from different lists. At minimum, aggregated task objects should include `tasklist_id` and `tasklist_title`; update compact response helpers only as the spec allows.
  - [x] Define deterministic ordering for aggregated results: due date first when present, then tasklist title, then Google `position`/title as appropriate. Apply `search.limit` after merging all matches so one list cannot starve later lists.
  - [x] Ensure partial failures return compact structured errors. If one tasklist fails, either fail the whole tool with a clear `tasklist_id`/`tasklist_title` hint or implement a documented partial-failure shape; choose in the spec before coding.
  - [x] Update README and open issue notes so users understand that unqualified read summaries mean "all lists."
- **Tests to run:**
  - `pytest tests/test_tools.py tests/test_tasks_wrapper.py tests/test_resolver.py -x`
  - `pytest -x`
- **Constraints / rules (step-specific):**
  - Do not change the 19 MCP tool names.
  - Do not change write-tool defaults by accident; `add`, `complete`, `update`, `uncomplete`, `delete`, `move`, `clear_completed`, and `list_tasks` need explicit spec approval before their default scope changes.
  - Do not return raw Google envelopes or raw task metadata.
- **Acceptance criteria / verification checklist:**
  - [x] `overdue()` with no `tasklist` returns overdue tasks from every tasklist, including tasks outside the configured/default list.
  - [x] `today()`, `upcoming()`, `search()`, and `digest()` show the same all-list behavior when `tasklist` is omitted.
  - [x] Passing an explicit tasklist ID or title scopes the result to that one list.
  - [x] Aggregated results include tasklist context and remain compact enough for low-context use.
  - [x] `docs/open-issues/mcp-bug-default-tasklist.md` is marked resolved or updated with implementation evidence.

### Step 17 — Improve MCP tool discoverability and grouping metadata

- **Status:** Not started
- **Enhancement source:** `docs/planning/enhancements.md` bullet about tools being categorized as "Other tools" in LLM clients and needing grouping/discoverability without adding unnecessary tools.
- **Objective:** Make the existing 19 tools easier for MCP clients and humans to browse without renaming tools or changing their input/output contracts.
- **Tasks / Actions:**
  - [ ] Research the currently installed MCP Python SDK / FastMCP support for tool metadata, annotations, titles, descriptions, and safety hints. Prefer official SDK/protocol behavior over client-specific hacks.
  - [ ] Document the intended tool groups in the spec and README: Tasklists, Task reads, Task summaries, and Task mutations. This is documentation and metadata only; it must not add tools.
  - [ ] Update `create_mcp_server()` registration so each tool has the best-supported metadata the SDK can expose, such as human-readable title/description and read-only/destructive/idempotent/open-world hints where available.
  - [ ] Tighten function docstrings so `list_tools` output is concise, action-oriented, and clear about defaults, confirmation flags, destructive behavior, and whether the tool reads one list or all lists.
  - [ ] If the MCP protocol/SDK has no first-class grouping field, do not invent a non-standard wire contract. Instead, use supported titles/descriptions consistently and document the limitation.
  - [ ] Add tests that inspect the MCP `list_tools` response or FastMCP registered tool objects and assert names remain the exact 19-tool set while metadata is populated.
  - [ ] Update README tool table to show the same grouping users will see conceptually in clients.
- **Tests to run:**
  - `pytest tests/test_server.py tests/test_release_artifacts.py -x`
  - `pytest -x`
- **Constraints / rules (step-specific):**
  - Preserve exact tool names and input schemas unless the spec is changed first.
  - Do not add wrapper/category tools.
  - Do not make provider-specific clients architectural requirements; client-specific notes may be examples only.
- **Acceptance criteria / verification checklist:**
  - [ ] `list_tools` still exposes exactly the 19 spec tool names.
  - [ ] Every tool has a concise description and appropriate safety/read-only metadata where the SDK supports it.
  - [ ] Destructive tools are clearly marked or described as destructive and retain confirmation requirements.
  - [ ] README and spec present tools in stable groups without changing the MCP contract.

### Step 18 — Rewrite README for fast user comprehension

- **Status:** Not started
- **Enhancement source:** `docs/planning/enhancements.md` bullet asking for a clearer, more user-friendly README using `docs/samples/slack-mcp-readme.md` as a clarity reference only.
- **Objective:** Turn the README into a short, readable setup and usage guide that explains what the server does, who it is for, and how to connect it without burying users in implementation details.
- **Tasks / Actions:**
  - [ ] Audit the current README, `MCP_SERVER_GUIDE.md`, `DISTRIBUTION.md`, `.env.example`, and the Slack sample. Use the Slack sample as a clarity benchmark, not as content to copy.
  - [ ] Restructure README around the user journey: what this is, supported transports, quickstart, Google Cloud setup, OAuth bootstrap, connect an MCP client, tools by group, authentication modes, limitations, deployment pointers, and troubleshooting links.
  - [ ] Move deep architecture/distribution material out of README into `MCP_SERVER_GUIDE.md`, `DISTRIBUTION.md`, or focused docs. README should link to those docs instead of duplicating them.
  - [ ] Keep all examples self-hostable and placeholder-only. No private domains, bearer tokens, OAuth client secrets, refresh tokens, database paths containing maintainer identity, or shared hosted endpoint language.
  - [ ] Update the tool table to reflect Steps 16-17 if they have landed: grouped tools, all-list default read summaries, confirmation requirements, and compact response behavior.
  - [ ] Add a short troubleshooting section for the common failures: missing bearer token, Google OAuth app still in Testing mode, callback URI mismatch, expired/revoked Google refresh token, and OAuth gateway re-authorize loop if Step 15 is not yet shipped.
  - [ ] Check package/registry metadata still finds the `mcp-name` marker and that docs referenced from `DISTRIBUTION.md` remain accurate.
- **Tests to run:**
  - `pytest tests/test_release_artifacts.py -x`
  - `pytest -x`
  - Manual docs check: follow the README from a clean clone through install, bootstrap, and local HTTP startup using placeholder-safe notes in an evidence file.
- **Constraints / rules (step-specific):**
  - Public docs must describe users running their own instance with their own Google credentials.
  - Do not publish or imply a shared hosted endpoint connected to the maintainer's Google account.
  - Keep provider-specific MCP clients as examples, not assumptions.
- **Acceptance criteria / verification checklist:**
  - [ ] A first-time user can understand the server, install path, auth model, and connection options in one read.
  - [ ] README is shorter and clearer, with deep details moved to linked docs.
  - [ ] All commands and config snippets use placeholders and avoid secrets.
  - [ ] README, guide, distribution docs, changelog, and release metadata agree on supported transports, auth modes, and tool count.

### Release Step — Docs And Release Prep

- **Status:** Not started
- **Objective:** Prepare public-facing docs, metadata, and release artifacts.
- **Tasks / Actions:**
  - [ ] Update release version across package, registry, bundle, and metadata files.
  - [ ] Update `CHANGELOG.md`.
  - [ ] Run release-artifact tests.
  - [ ] Run the documented secret scan.
  - [ ] Follow `docs/publish/SUBSEQUENT_RELEASE_SEQUENCE.md`.
- **Tests to run:**
  - `python -m pytest tests/test_release_artifacts.py -x`
  - `python -m pytest -x`
- **Acceptance criteria / verification checklist:**
  - [ ] Versioned files agree.
  - [ ] Release checks pass.
  - [ ] Publish sequence is ready for PR.

### Post Release Step — Archive The Plan

- **Status:** Not started — awaits explicit user approval after the release is done.
- **Objective:** Archive this plan after the release is complete and reset `docs/implementation-plan.md` for the following cycle.
- **Tasks / Actions:**
  - [ ] Pause and ask the user for approval to archive.
  - [ ] Move `docs/implementation-plan.md` to `docs/archive/implementation-plan-v<version>.md`.
  - [ ] Replace `docs/implementation-plan.md` with a fresh next-release skeleton.
- **Tests to run:** *(none — docs-only step)*
- **Constraints / rules (step-specific):**
  - Never archive without explicit user approval.
- **Acceptance criteria / verification checklist:**
  - [ ] User approved archiving.
  - [ ] Archived plan exists with final statuses.
  - [ ] Working plan is reset for the next cycle.

## Guardrails

- Keep the server provider-neutral and self-hostable.
- Public distribution must never point users to a shared hosted endpoint wired to a maintainer account.
- OAuth credentials may come from env vars or `gcp-oauth.keys.json`; env vars take precedence.
- One running server connects to one Google account unless the spec is updated for multi-account support.
- `DEFAULT_TASKLIST` fallback remains: use the first Google tasklist when unset.
- Keep future hooks as boundaries only; do not implement scheduled digest output, webhook ingest, multi-account support, or database swaps unless explicitly requested.
