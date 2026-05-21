# Bug: `overdue`, `today`, `upcoming`, `search` default to "General" tasklist only

**Filed:** 2026-05-21
**Resolved:** 2026-05-21
**Severity:** High — silently hides tasks, produces false "0 overdue" reads
**Affects:** All scheduled briefs that rely on task state

---

## What happened

`overdue` called with no `tasklist` param returned `{"count":0,"tasks":[]}`.

Reality: overdue tasks existed in another tasklist. They were completely invisible until `list_tasklists` was called first and each list ID was passed explicitly.

## Root cause

The `overdue`, `today`, `upcoming`, and `search` tools accept an optional `tasklist` param. When omitted, they silently default to the user's primary/default list ("General"). No warning. No error. Just a clean-looking empty result.

## Why it's dangerous

A "0 overdue" result looks correct. There's no signal that other lists weren't checked. Every brief, nudge, escalation check, and review was reading task state from one list out of several — and reporting it as the full picture.

## Ideal fix (two options, pick one)

**Option A — Default to ALL lists (preferred)**
When `tasklist` is omitted, query all lists and aggregate. Behaviour: `overdue()` with no param = `overdue()` across every list the user has. Matches the mental model of "show me what's overdue" with no qualifier.

**Option B — Require explicit param or raise**
When `tasklist` is omitted, return an error or warning: `"tasklist required — use list_tasklists to enumerate IDs, or pass tasklist='all'."` Forces the caller to be explicit. Less convenient but eliminates silent failures.

**Recommendation:** Option A. The common-case intent of `overdue()` with no argument is always "everything overdue," not "everything overdue in General." There is no valid use case for silently scoping to one list without the caller knowing.

## Affected tools (same fix needed in all)

- `overdue`
- `today`
- `upcoming`
- `search`
- `digest`

## Resolution

Implemented Option A. When `tasklist` is omitted, `overdue`, `today`, `upcoming`, `search`, and `digest` now enumerate all tasklists for the authenticated account and aggregate the results.

Passing an explicit tasklist ID or title still scopes those tools to one list. `list_tasks`, `clear_completed`, single-task tools, and write tools keep the default-tasklist behavior so unqualified mutations do not fan out across every list.

Aggregated task results include `tasklist_id` and `tasklist_title`, and aggregated digest text labels tasks with their tasklist title. Results are ordered deterministically by due date, tasklist title, position, title, and ID; `search.limit` is applied after matches from all tasklists are merged.
