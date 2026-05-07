# Implementation Plan — v0.2.0

This release closes the gaps surfaced by real-world Claude Cowork use (`docs/google-tasks-mcp-improvements-from-claude-cowork.md`, tickets T1–T10 + §8 handoff) and verified against the live Google Tasks REST docs at <https://developers.google.com/workspace/tasks/reference/rest>.

The previous plan (v0.1.0) is archived at `docs/archive/implementation-plan-v0.1.0.md`. This plan will be archived to `docs/archive/implementation-plan-v0.2.0.md` once Step 12 is approved.

**Primary implementing agent:** Codex does most of the development on this release. Claude Code is used for planning, review, and spot fixes. Either agent must follow the same step template and DoD.

**Per-step evidence:** after finishing each step, the implementing agent must create an evidence file at `docs/evidence/step-<N>-<slug>.md` (e.g. `docs/evidence/step-0-foundation-utilities.md`) documenting commands run, test output, and any deviations. Match the format of existing files in `docs/evidence/`. The step is not "Complete" until its evidence file lands. Evidence files stay in `docs/evidence/` when the plan is archived in Step 12.

**Commit messages:** describe the actual change shipped — never reference plan scaffolding like "step", "pass", "phase", or ticket numbers in the subject line. Good: `Add tasklist resolver cache with single-flight refresh`. Bad: `Step 0: foundation utilities`.

**No plan scaffolding outside the plan:** never include internal plan scaffolding — step/pass/phase numbers, ticket ids, section references like `§8.4`, or any other token that only makes sense to someone holding the plan — in any markdown file or code comment (including docstrings and error messages). Describe the change itself. Good: *"Mutation tools now return rich self-describing responses with `human_summary`."* Bad: *"T1 response shape overhaul."* The only exceptions are the implementation plan itself and its evidence files — those are where scaffolding lives.

**Never ignore .gitignore content** even when you are tasked to produce elements that sit under git-ignored folders.

Supporting docs unchanged: `README.md`, `MCP_SERVER_GUIDE.md`, `DISTRIBUTION.md`, `docs/AGENTS.md`, `docs/google-tasks-mcp-specifications.md`.

## Scope of this release

In scope:

- Rich, self-describing mutation responses with `human_summary` (T1).
- Lookup-by-title on every ID-taking tool, with structured ambiguity errors (T2).
- Tasklist CRUD: `create_tasklist`, `get_tasklist`, `update_tasklist`, `delete_tasklist` (T3).
- A general `list_tasks` filter tool with `today`/`overdue`/`upcoming`/`search`/`digest` rewired as wrappers (T4).
- `clear_completed` (T5).
- Subtask support on `add` via `parent` / `previous` (T6).
- `move` completeness: re-parent, re-order, cross-list (T7).
- Un-complete via `update.status` and a thin `uncomplete` wrapper (T8).
- Auto-pagination on list-style tools with a 1000-task hard cap (T9).
- Patch-semantics regression test on `update` (T10).
- Foundation utilities: tasklist resolver cache (§8.4), timezone helper (§8.5), shared mutation-response builder, expanded structured error codes.

### Items intentionally not in scope

- **Time-of-day on `due` and recurrence** (improvements brief §1, "Confirmed API-level limits"). Document as limitations in `README.md`; cannot be fixed at the MCP layer.
- **Switching `update` to `tasks.patch`** — already correct: `tasks.py:166` calls `service.tasks().patch(...)`. Step 10 only adds a regression test to lock that in.
- **Calendar integration** (improvements brief §7) — explicitly out of scope.

## API verification notes

Cross-checked each item against <https://developers.google.com/workspace/tasks/reference/rest> on 2026-05-07. Confirmed:

- `tasks.list` accepts `dueMin`, `dueMax`, `completedMin`, `completedMax`, `updatedMin`, `showCompleted` (default **true**), `showDeleted`, `showHidden`, `showAssigned`, `maxResults` (default **20**, max **100**), `pageToken`. Response includes `nextPageToken` and `items[]`.
- `tasks.move` accepts `parent`, `previous`, `destinationTasklist` (all optional query params). Recurring tasks cannot be moved across lists.
- `tasks.insert` accepts `parent` and `previous` query params.
- `tasks.clear` is `POST /lists/{tasklist}/clear` with no body. **It marks completed tasks as hidden, not deleted** — they reappear if listed with `show_hidden=true`. Surface this in the tool docstring.
- Tasklists resource supports `list/get/insert/update/patch/delete`. Only writable field is `title` (max **1024 chars**). Read-only fields: `id`, `updated`, `kind`, `etag`, `selfLink`.
- Read-only Task fields confirmed real: `webViewLink`, `parent`, `position`, `links`, `assignmentInfo`, `completed`.

## Definition of Done (applies to every step)

Each step is mergeable only when all of these hold. Step-specific acceptance criteria stack on top of these.

- [ ] `pytest` is green for new and existing tests.
- [ ] All Google API calls in tests are mocked at the `googleapiclient.discovery.build` boundary — no live network in CI.
- [ ] Tool docstrings (the LLM-facing description text) are updated for any new or modified tool.
- [ ] `README.md` "Tools" section reflects new/modified tools and their parameters.
- [ ] `CHANGELOG.md` entry added: one-line user-facing summary of the change (no ticket id, no step number) and `breaking-change: false`.
- [ ] At least one manual smoke test against the live Google account, with the result pasted into the PR description.
- [ ] Backward compatibility: additive only — no removed or renamed parameters; new params are optional with safe defaults.
- [ ] No raw Google envelope fields (`kind`, `etag`, `selfLink`, raw pagination tokens, full `items[]` envelopes) leak through MCP responses.
- [ ] No secrets in logs (OAuth codes, access/refresh tokens, bearer tokens, credential file contents).
- [ ] Errors are structured `{error, code, message, ...}` payloads, never stack traces.
- [ ] No internal plan scaffolding (step/pass/phase numbers, ticket ids, internal section references) in any markdown file or code comment touched by this step. The implementation plan and its evidence files are the only allowed exception.
- [ ] Evidence file written at `docs/evidence/step-<N>-<slug>.md` (commands run, test output, deviations) before the step is marked Complete.

## Step template

Every step uses this shape. Copy it when adding a new step. Drop the **Constraints / rules** block if no step-specific constraints apply (universal rules live in the DoD and the Guardrails section).

```markdown
### Step N — <Title> (<TicketIds, if any>)

- **Status:** Not started | In progress | Complete | Blocked
- **Objective:** <1–2 sentence statement of intent.>
- **Tasks / Actions:**
  - [ ] <code change with file path where known>
  - [ ] <next change>
- **Tests to run:**
  - `pytest tests/test_xyz.py -x`
  - <or other commands>
- **Constraints / rules (step-specific):** *(omit this block if none)*
  - <only what is unique to this step>
- **Acceptance criteria / verification checklist:**
  - [ ] <observable condition>
  - [ ] <observable condition>
```

## Build sequence

### Step 0 — Foundation utilities (prereq for T1, T2, T4)

- **Status:** Complete
- **Objective:** Land the shared helpers that every later step depends on so T1–T9 are mostly mechanical: tasklist resolver cache, timezone helper, mutation-response builder, and expanded error codes.
- **Tasks / Actions:**
  - [x] Add `src/google_tasks_mcp/resolver.py` implementing the in-process tasklist cache per improvements §8.4: `{id → {title, updated}}` forward map, `{lower(trim(title)) → [ids]}` reverse map, lazy first-call population via `tasklists.list`, 5-min TTL, single-flight refresh lock, public `invalidate()` hook called by Step 3 mutations. On a cache miss for a queried title, force one refresh and retry once before raising `404 NOT_FOUND`. If reverse-map list length > 1, raise `409 AMBIGUOUS_TITLE`. The existing 5-minute cache in `tasks.py` (`clear_tasklist_cache()` in tests) is consolidated into this module.
  - [x] Add `src/google_tasks_mcp/timezones.py` implementing tz resolution per improvements §8.5: explicit `timezone` arg > `GOOGLE_TASKS_MCP_DEFAULT_TZ` env (read once at server start) > UTC pass-through. Validate IANA names against `zoneinfo.available_timezones()`; bad values raise `INVALID_INPUT`.
  - [x] Extend `src/google_tasks_mcp/errors.py` with `NotFoundError`, `AmbiguousTitleError`, `InvalidInputError`, all subclassing `GoogleTasksMcpError` and carrying a numeric code (`404`, `409`, `400`).
  - [x] Extend `src/google_tasks_mcp/digest.py` with `build_mutation_response(task, tasklist_id, tasklist_title, *, operation, deleted=False, changes=None) → dict` producing the exact T1 shape (improvements §8.2), including `human_summary` for `add`/`complete`/`update`/`delete`/`move`. Date-only output for `due` (`YYYY-MM-DD`).
  - [x] Wire all four new error types into `server._error_payload` so they surface as `{error, code, message, ...}`.
  - [x] Add tests: `tests/test_resolver.py`, `tests/test_timezones.py`, additions to `tests/test_digest.py` and `tests/test_tools.py` covering the new error envelopes.
- **Tests to run:**
  - `pytest tests/test_resolver.py tests/test_timezones.py tests/test_digest.py tests/test_tools.py -x`
- **Constraints / rules (step-specific):**
  - Resolver is memory-only — no DB persistence, no on-disk cache. Server restart must safely re-warm.
  - Single-flight: concurrent resolver calls must share one in-flight `tasklists.list`; do not fan out parallel requests.
  - Do not change existing tool signatures in this step. This step is purely additive infrastructure.
- **Acceptance criteria / verification checklist:**
  - [x] `resolve_tasklist_by_title("EB Tasks")` returns the same id on first and second call, and the second call issues no API request (mock asserts call count == 1).
  - [x] Two concurrent resolver calls trigger exactly one `tasklists.list` mock call (single-flight verified).
  - [x] `invalidate()` clears the cache; the next read refetches.
  - [x] Bad timezone string returns `400 INVALID_INPUT` with a message naming the bad value.
  - [x] `build_mutation_response` produces all 14 fields from improvements §8.2 for an `add` payload, with `due` rendered as `YYYY-MM-DD`.
  - [x] No regression in the existing `pytest` suite.

### Step 1 — Response shape overhaul (T1)

- **Status:** Complete
- **Objective:** Make `add`, `complete`, `delete`, `update`, and `move` return the rich self-describing object so consumers never have to re-fetch to know what happened or display an opaque ID.
- **Tasks / Actions:**
  - [x] Refactor each of the five mutation tools in `server.py` to call `digest.build_mutation_response(...)` instead of the current `shrink_task` path.
  - [x] For `delete`: pre-fetch the task with `tasks.get` before calling `tasks.delete`, cache the resource locally, then issue delete and return the cached fields with `deleted: true`. Accept the extra round trip — it's the readability win.
  - [x] For `update`: compute and pass the changed-field list into `build_mutation_response` so `human_summary` reads "Updated 'X': due, notes" (delta-aware).
  - [x] For `move`: pass enough context that `human_summary` can pick the right phrasing — "to <new_tasklist_title>", "to <new_parent_title>", or "after <previous_title>".
  - [x] Update tool docstrings to describe the new response fields.
- **Tests to run:**
  - `pytest tests/test_tools.py -x`
- **Acceptance criteria / verification checklist:**
  - [x] `add` response contains all 14 fields from improvements §8.2, including `human_summary`, `tasklist_title`, `web_view_link`.
  - [x] `complete` response contains the original `title` and pre-completion `due`.
  - [x] `delete` response contains pre-deletion `title` sourced from the pre-fetch, plus `deleted: true`.
  - [x] `update` with only `due` changed produces `human_summary` mentioning only the due-date change.
  - [x] `move` `human_summary` correctly picks list/parent/sibling phrasing depending on inputs.
  - [x] No `kind`, `etag`, or `selfLink` appears in any mutation response.

### Step 2 — Lookup-by-title for ID-taking tools (T2)

- **Status:** Not started
- **Objective:** Let every ID-taking tool also accept `title`, with safe ambiguity handling, so callers don't need to display or shuttle opaque IDs.
- **Tasks / Actions:**
  - [ ] Add an optional `title` parameter to `complete`, `delete`, `update`, `get_task`, `move` (mutually exclusive with `id`; if both provided, prefer `id`).
  - [ ] Implement title resolution per improvements §4-T2 in a shared helper in `tasks.py` or `resolver.py`: trim whitespace, case-insensitive exact match against active tasks (exclude `status=completed` and `deleted=true` by default).
  - [ ] Add an optional `include_completed: bool` flag (default `false`) for the rare case where the caller wants to look up a completed task by title.
  - [ ] On zero matches, raise `NotFoundError` with `{searched_tasklist, query}` payload.
  - [ ] On multiple matches, raise `AmbiguousTitleError` with `candidates: [{id, title, due, tasklist_title}, ...]`.
  - [ ] Apply the same logic to the `tasklist` parameter wherever it appears (already partly there in `resolve_tasklist`; consolidate via Step 0's resolver).
- **Tests to run:**
  - `pytest tests/test_tools.py tests/test_tasks_wrapper.py -x`
- **Constraints / rules (step-specific):**
  - **Do not** implement fuzzy/Levenshtein matching. Predictability beats magic.
  - Tasklist titles can collide too; surface `AMBIGUOUS_TITLE` for tasklists the same way as for tasks.
- **Acceptance criteria / verification checklist:**
  - [ ] `complete({title: "Friday ship"})` succeeds with no `id`.
  - [ ] `delete({title: "Friday ship", tasklist: "EB Tasks"})` succeeds.
  - [ ] Two active tasks with the same title in the same list → `complete({title})` returns `409 AMBIGUOUS_TITLE` with both candidates.
  - [ ] After completing one of the two, repeat → succeeds (only one active match).
  - [ ] `tasklist: "EB Tasks"` and `tasklist: "<id>"` produce identical results.
  - [ ] `get_task({title: "missing"})` returns `404 NOT_FOUND` with `searched_tasklist` and `query` echoed.

### Step 3 — Tasklist CRUD (T3)

- **Status:** Not started
- **Objective:** Add the four missing tasklist operations as new tools.
- **Tasks / Actions:**
  - [ ] Add `create_tasklist({title})` → calls `tasklists.insert`, returns full tasklist object + `human_summary`.
  - [ ] Add `get_tasklist({id|title})` → calls `tasklists.get` with title lookup via Step 0's resolver.
  - [ ] Add `update_tasklist({id, new_title})` → calls `tasklists.patch`. Per project guardrail, this tool requires `id` (not title) for safety; surface that in the docstring.
  - [ ] Add `delete_tasklist({id, confirm, force=false})` → pre-fetch list metadata, then call `tasklists.delete`. Per project guardrail, this tool requires `id`. Reject when the list is non-empty unless `force: true`. Always include implicit `tasks_deleted_count` in the response.
  - [ ] After every successful create/update/delete, call `resolver.invalidate()`.
  - [ ] Register all four tools in `server.tool_map`. Update `_logged_tool` wrapping.
  - [ ] Update `docs/google-tasks-mcp-specifications.md` to bump the tool count from 12 to 16 and list the new tools (binding spec change, per CLAUDE.md invariant).
  - [ ] Update `docs/AGENTS.md` and the README to reflect the new tools.
- **Tests to run:**
  - `pytest tests/test_tools.py tests/test_release_artifacts.py -x`
- **Constraints / rules (step-specific):**
  - `update_tasklist` and `delete_tasklist` take `id` only (not title) — project guardrail. Rename/delete by title is too easy to mis-target. This intentionally diverges from improvements §4-T3.
  - `delete_tasklist` requires `confirm: true`; without it return `400 INVALID_INPUT`.
- **Acceptance criteria / verification checklist:**
  - [ ] Round-trip: `create_tasklist` → `get_tasklist` → `update_tasklist` → `delete_tasklist` all succeed in one test.
  - [ ] `delete_tasklist` on a non-empty list without `force: true` returns `400 INVALID_INPUT`; with `force: true` it succeeds and reports `tasks_deleted_count`.
  - [ ] After `create_tasklist`, the resolver's next title lookup includes the new list (cache invalidation verified).
  - [ ] `tools/list` returns 16 tools.
  - [ ] No `kind`, `etag`, or `selfLink` in tasklist responses.

### Step 4 — General `list_tasks` + helper rewire (T4)

- **Status:** Not started
- **Objective:** Add a single general filter tool that exposes the full Google `tasks.list` parameter set, and rewire the existing helpers as thin wrappers without changing their public signatures.
- **Tasks / Actions:**
  - [ ] Add `list_tasks(tasklist?, due_min?, due_max?, completed_min?, completed_max?, updated_min?, show_completed=true, show_deleted=false, show_hidden=false, show_assigned=false, max_results=1000, page_token?, timezone?)` tool. Schema per improvements §8.3.
  - [ ] When `due_min`/`due_max`/`completed_min`/`completed_max` arrive as bare `YYYY-MM-DD`, attach the resolved tz (Step 0 helper) before sending to Google.
  - [ ] Response shape: `{tasks: [<full_task_objects>], next_page_token?, count, tasklist_title, truncated?}`. Each task carries the same fields as Step 1's response (minus `human_summary`).
  - [ ] Rewire `today`, `overdue`, `upcoming` to compute `due_min`/`due_max` in the resolved tz and call `list_tasks` internally. Keep their public signatures unchanged.
  - [ ] Rewire `search` to call `list_tasks` then client-side filter `title`/`notes` against the query.
  - [ ] Rewire `digest` as a composite of `today` + `overdue` + counts; preserve current external behavior.
  - [ ] Add tests verifying helpers still return the same results as before (regression suite).
- **Tests to run:**
  - `pytest tests/test_tools.py -x`
- **Acceptance criteria / verification checklist:**
  - [ ] `list_tasks({due_min: "2026-05-10", due_max: "2026-05-17", show_completed: false})` returns next-week active tasks.
  - [ ] `today`/`overdue`/`upcoming`/`search`/`digest` regression tests still pass on identical fixtures.
  - [ ] Range query across week boundaries returns expected items.
  - [ ] `show_completed: true` includes completed tasks; default excludes them.
  - [ ] Querying a tasklist by title vs. id returns identical results.
  - [ ] Bare `YYYY-MM-DD` with explicit `timezone: "Africa/Nairobi"` produces a different bucket than the same date with `timezone: "America/Los_Angeles"`.

### Step 5 — `clear_completed` (T5)

- **Status:** Not started
- **Objective:** Expose `tasks.clear` so users can wipe completed tasks from a list in one call, with a count.
- **Tasks / Actions:**
  - [ ] Add `clear_completed({tasklist?, confirm})` tool. `confirm` is required.
  - [ ] Implementation: list completed tasks first to get the count, then call `tasks.clear`, then return `{cleared_count, tasklist_title, human_summary: "Cleared <n> completed tasks from <tasklist_title>"}`.
  - [ ] Document in the tool docstring that `tasks.clear` **hides** rather than deletes — completed tasks reappear if listed with `show_hidden=true`.
  - [ ] Tests cover: success path, `confirm: false` rejection, empty-list path (`cleared_count: 0`).
- **Tests to run:**
  - `pytest tests/test_tools.py -x`
- **Constraints / rules (step-specific):**
  - `confirm: false` (or missing) returns `400 INVALID_INPUT`. The tool is destructive enough that opt-in must be explicit.
- **Acceptance criteria / verification checklist:**
  - [ ] After marking 3 tasks complete, `clear_completed({confirm: true})` returns `cleared_count: 3`.
  - [ ] Subsequent `list_tasks({show_completed: true})` shows zero completed in that list.
  - [ ] `list_tasks({show_hidden: true})` still returns the cleared tasks (proves the "hidden, not deleted" docstring claim).
  - [ ] `confirm: false` returns `400 INVALID_INPUT`.

### Step 6 — Subtask support on `add` (T6)

- **Status:** Not started
- **Objective:** Allow creating a task as a child of an existing task, and positioning it among siblings.
- **Tasks / Actions:**
  - [ ] Add optional `parent` parameter to `add` (id or title via Step 2).
  - [ ] Add optional `previous` parameter to `add` (id or title via Step 2) — positions the new task immediately after this sibling.
  - [ ] Pass both as query params on `tasks.insert`.
  - [ ] Verify the response from Step 1 reflects `parent` correctly in the rich response object.
- **Tests to run:**
  - `pytest tests/test_tools.py -x`
- **Acceptance criteria / verification checklist:**
  - [ ] `add({title: "subtask", parent: "Friday ship"})` creates a child of the Friday task; response shows `parent: "<id>"`.
  - [ ] `add({title: "second", previous: "first"})` positions correctly under the same parent.
  - [ ] Creating a parent then three children with explicit `previous` chaining produces the expected order via `list_tasks`.

### Step 7 — `move` completeness (T7)

- **Status:** Not started
- **Objective:** Expose all three positioning controls of `tasks.move` — re-parent, re-order, cross-list.
- **Tasks / Actions:**
  - [ ] Update `move` schema per improvements §8.3: `task` (id or title, required), `from_tasklist?`, `destination_parent?` (nullable — `null` moves to top level), `destination_previous?`, `destination_tasklist?`.
  - [ ] Same-list move calls the real `tasks.move` endpoint with the appropriate query params.
  - [ ] Cross-list move continues to be emulated as insert-then-delete (per CLAUDE.md MCP contract — the moved task gets a new Google task ID).
  - [ ] Document the cross-list ID-change behavior in the tool docstring so consumers know not to cache the old id.
- **Tests to run:**
  - `pytest tests/test_tools.py -x`
- **Acceptance criteria / verification checklist:**
  - [ ] Cross-list move: task disappears from source, appears in destination, response carries the **new** id.
  - [ ] Re-parent: `destination_parent` makes the task a child of another within the same list.
  - [ ] Re-order: `destination_previous` positions the task correctly among siblings.
  - [ ] Move to top level: `destination_parent: null` clears the parent.
  - [ ] All three controls combinable in a single call (cross-list + re-parent + re-order in destination).

### Step 8 — Status flip / un-complete (T8)

- **Status:** Not started
- **Objective:** Allow re-opening a completed task without forcing the caller to use a raw API call.
- **Tasks / Actions:**
  - [ ] Add `status` parameter to `update` (enum `"needsAction" | "completed"`).
  - [ ] Add a thin `uncomplete` tool that calls `update` internally with `status: "needsAction"` for symmetry with `complete`.
  - [ ] On reopening, clear the `completed` timestamp on the API side (verify Google does this automatically; if not, send a patch that nulls it).
- **Tests to run:**
  - `pytest tests/test_tools.py -x`
- **Acceptance criteria / verification checklist:**
  - [ ] `update({title: "X", status: "needsAction"})` reopens a completed task; response shows `status: "needsAction"` and `completed: null`.
  - [ ] `uncomplete({title: "X"})` does the same.
  - [ ] `complete` then `uncomplete` round-trip preserves `title`, `notes`, `due`, `parent`, and `position`.

### Step 9 — Pagination on list-style tools (T9)

- **Status:** Not started
- **Objective:** Stop silently truncating output for users with many tasks; auto-paginate inside the MCP up to a hard cap.
- **Tasks / Actions:**
  - [ ] In `list_tasks` (Step 4), loop on `pageToken` until either `nextPageToken` is empty or `max_results` (default and cap **1000**) is reached.
  - [ ] If the cap is hit, set `truncated: true` and include `next_page_token` in the response so an explicit caller can continue.
  - [ ] Document the 1000-task cap in the `list_tasks` tool description.
  - [ ] Apply the same internal loop wherever helpers wrap `list_tasks` (today/overdue/upcoming/search/digest).
- **Tests to run:**
  - `pytest tests/test_tools.py -x`
- **Acceptance criteria / verification checklist:**
  - [ ] A list with 150 mocked tasks → `list_tasks` returns all 150 across ≥2 internal API calls; `truncated` is absent or `false`.
  - [ ] A list with 1500 mocked tasks → `list_tasks` returns 1000 with `truncated: true` and a non-empty `next_page_token`.
  - [ ] `next_page_token` from a truncated response can be passed back in to fetch the next page.

### Step 10 — Patch semantics regression test (T10)

- **Status:** Not started
- **Objective:** Lock in the existing correct behavior — `update` calls `tasks.patch`, not `tasks.update` — so a future refactor cannot silently regress to a full PUT-style replace.
- **Tasks / Actions:**
  - [ ] Add a regression test that creates a task with `notes`, calls `update` with only `due` changed, and asserts that `notes` is preserved on the returned object and on a follow-up `get_task`.
  - [ ] Add a code-level assertion in the test that the mocked `service.tasks().patch` (not `update`) was the method called.
- **Tests to run:**
  - `pytest tests/test_tools.py::test_update_is_partial_patch -x`
- **Acceptance criteria / verification checklist:**
  - [ ] Test passes against current implementation (`tasks.py:166`).
  - [ ] Test fails if `update` is mistakenly switched to `service.tasks().update(...)` (verified by temporarily flipping the call locally).
  - [ ] No field is reset to its default after a partial update.

### Step 11 — Docs and release prep

- **Status:** Not started
- **Objective:** Land all version-bump and distribution metadata changes in one batch so release artifacts stay consistent.
- **Tasks / Actions:**
  - [ ] Bump version to `0.2.0` in `pyproject.toml`, `manifest.json`, `server.json`, `metadata/glama.json`, `src/google_tasks_mcp/__init__.py`.
  - [ ] Update README "Tools" section to list all tools (now 17: original 12 + 4 tasklist CRUD + `list_tasks` + `clear_completed` + `uncomplete`; confirm final count after Steps 3–8 land).
  - [ ] Update `docs/google-tasks-mcp-specifications.md` tool count and the binding tool list.
  - [ ] Update `docs/AGENTS.md` if any rule changed (it shouldn't — tool list grew, contract didn't).
  - [ ] Verify `tests/test_release_artifacts.py` still passes after version + tool-count changes.
  - [ ] Run the live-account smoke checklist in `docs/real-world-test-checklist.md` end-to-end; paste results into the PR description.
- **Tests to run:**
  - `pytest -x`
  - Manual smoke run against the live Google account (every new and modified tool exercised once).
- **Acceptance criteria / verification checklist:**
  - [ ] Full `pytest` suite green.
  - [ ] All four release-artifact files reference the same version `0.2.0` and the same tool list.
  - [ ] README's `mcp-name:` HTML comment marker still matches `server.json` (PyPI registry verification rule, per CLAUDE.md).
  - [ ] CHANGELOG has one entry per ticket (T1–T10) and one for the foundation step.
  - [ ] Live smoke results pasted into the PR.

### Step 12 — Archive the plan (awaits user approval)

- **Status:** Not started — awaits explicit user approval after Step 11 merges.
- **Objective:** Move this plan into the archive so the working `docs/implementation-plan.md` is ready for the next release cycle.
- **Tasks / Actions:**
  - [ ] **Pause and ask the user for approval to archive.** Do not proceed without explicit confirmation.
  - [ ] On approval: move `docs/implementation-plan.md` to `docs/archive/implementation-plan-v0.2.0.md` (preserve the file with all final statuses marked `Complete`).
  - [ ] Replace `docs/implementation-plan.md` with a fresh skeleton (header + Step Template + DoD section) for the next release cycle.
- **Tests to run:** *(none — docs-only step)*
- **Constraints / rules (step-specific):**
  - **Never archive without user approval.** The user has explicitly required a confirmation gate here.
- **Acceptance criteria / verification checklist:**
  - [ ] User has explicitly said "go ahead and archive" (or equivalent).
  - [ ] `docs/archive/implementation-plan-v0.2.0.md` exists and contains the final state of every step.
  - [ ] `docs/implementation-plan.md` either contains a fresh skeleton for the next release or is removed pending the next planning session — confirm with the user which they prefer.

## Guardrails (update if needed)

- The 12-tool minimum is preserved; new tools in this release are **additions**, not renames or removals. Final tool count is recorded in Step 11.
- No raw Google API payloads through tool responses — extend `digest.shrink_*` / `build_mutation_response` for any new field.
- No `etag`, `kind`, `selfLink`, raw pagination wrappers, or unrequested notes in responses.
- No secrets in logs.
- New tools must accept friendly tasklist titles wherever the existing tools do, **except** `delete_tasklist` and `update_tasklist` which take an ID for safety (rename/delete by title is too easy to mis-target). This is a deliberate deviation from improvements §4-T3.
- Backward compatibility is non-negotiable: no removed or renamed parameters on existing tools; new params are optional with safe defaults.
