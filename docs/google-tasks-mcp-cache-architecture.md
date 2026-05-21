# Google Tasks MCP — Cache & Persistence Architecture

**Audience:** anyone modifying the persistence boundary (`db.py`, `resolver.py`, anything that touches the SQLite schema or in-memory caches).
**Purpose:** the design lens for what this server caches, what it doesn't, and why. Pair with `google-tasks-mcp-specifications.md` §5 for the literal schema; this doc explains the reasoning so future drift gets caught.

---

## 1. Design lens

The only question that matters for a proxy-style MCP wrapping a remote API is:

> **What is the cost of staleness vs. the cost of latency, for each kind of data?**

Every persistence and caching decision in this server falls out of that one question. Apply it per data class — auth, lookups, content — not globally.

| Data class | Cost of staleness | Cost of latency | Verdict |
|---|---|---|---|
| OAuth tokens | High (re-bootstrap) | High (no UX without auth) | **Persist.** |
| Tasklist id ↔ title | Low (rename is rare; invalidate on mutation) | Hot path — every tool call resolves it | **Cache, two-tier.** |
| Individual tasks | High (user marks done in app, agent shows stale "needsAction") | Tolerable (~200ms / call) | **Never cache.** |
| Filtered views (today, overdue, search) | High (same reason) | Tolerable | **Never cache.** |

## 2. Three architectures, one pick

| Option | What it does | When it's right | When it's wrong |
|---|---|---|---|
| **A. Pure proxy** | Cache nothing; every call hits upstream | Smallest possible system, freshness-critical, low traffic | Hot lookups (tasklist resolution) become expensive |
| **B. Cache stable lookups only** | Persist auth + tasklist id↔title; nothing else | This server | Apps where user expects offline / bulk ops |
| **C. Full local mirror + sync** | Bidirectional sync, conflict resolution, ETag tracking, deletion tombstones | Desktop-class clients (e.g. a Tasks app built on Google Tasks) | An MCP server. Wrong tier of complexity. |

**This server is Option B.** Justification:

- Single-account, personal-scale. No multi-user invalidation headaches.
- Task-level data is freshness-critical: the user toggles state in the Google Tasks app and expects the agent to see it on the next call. Staleness here is a user-visible bug.
- The only repeatedly-read piece of data is the tasklist id↔title map — read on every tool call (to resolve `tasklist:` parameters and label responses), written rarely (when a list is created/renamed/deleted).
- Filtered queries (`today`, `overdue`, `upcoming`, `search`) are cheap enough at upstream that caching them isn't worth the staleness risk.

## 3. Rules for Option B

These are the load-bearing rules. Violating any one of them re-introduces a staleness or correctness bug.

1. **Upstream is always the single source of truth.** Local data is *derived* and *invalidated*, never authoritative. Mutations must complete against upstream before returning success — no write-behind, no offline queue, no "eventually consistent" handwaving.

2. **Two-tier cache for hot lookups, single tier for everything else.** In-process (fast, ephemeral) on top of SQLite (persistent, survives restart). Daemon/HTTP servers earn the persistent tier on every restart; stdio-spawned-per-conversation servers can skip tier 2 since the process dies anyway.

3. **TTL + write-through invalidation.** Short TTL (5 min) on the in-memory tier. On *any* mutation that touches a cached entity, invalidate **both tiers synchronously** — no background refresh, no lazy expiry. The cache must never lie.

4. **Single-flight refresh.** Concurrent cache misses for the same key must coalesce into one upstream call. Without this, a cold cache + N concurrent tools = N redundant `tasklists.list` requests against quota.

5. **Auth tokens are credentials, not cache entries.** SQLite at rest is the floor. OS keyring (Keychain / Secret Service / DPAPI) or envelope encryption (sqlcipher, or AES-GCM with a server-side master key) is the ceiling. For a personal VPS this server runs on, plaintext SQLite is acceptable but the threat model belongs in the operator's `SECURITY.md`.

6. **Never cache content data.** Tasks themselves, filtered views, search results — none of it. Even with short TTLs, "I marked it done in the app, why does the agent still see it?" is the bug class you cannot recover from once users hit it.

7. **Expose cache state.** At minimum a `clear_cache` admin tool or env flag that bypasses the cache for one call. You will need this the first time you debug a phantom tasklist or a stuck rename.

8. **Idempotency where upstream supports it.** Google Tasks exposes ETags. `If-Match` headers on `update`/`delete` prevent silent overwrites on retries. Optional, but the cleanest way to add safety. Defer until a real concurrency bug shows up.

## 4. What this server does today vs. target state

| Concern | Today | Target | Action |
|---|---|---|---|
| OAuth refresh token persistence | Plaintext SQLite ✓ | Plaintext SQLite (acceptable for personal VPS) | None. Note threat model in `SECURITY.md`. |
| Tasklist id↔title — tier 1 (in-memory) | ✓ `resolver.py`, 5-min TTL, single-flight | Same | None. |
| Tasklist id↔title — tier 2 (SQLite) | ✓ Wired through `resolver.py`: seeds memory on cold start, replaces the full SQLite set after upstream refresh, invalidates on tasklist mutation | Same | None. |
| Task content caching | ✗ Not cached | ✗ Never cache | None. Already correct. Resist any "performance" PRs that propose otherwise. |
| Filtered view caching | ✗ Not cached | ✗ Never cache | None. Same as above. |
| ETag / If-Match on mutations | ✗ Not used | Optional future improvement | Defer. |
| Cache bypass / clear_cache surface | ✗ Not exposed | At least an env flag | Defer. |
| Refresh-token encryption at rest | ✗ Plaintext | Optional upgrade for shared/multi-user hosting | Defer; not in scope for personal use. |

## 5. Anti-patterns (do not introduce)

- **Caching individual tasks.** Even with a 30-second TTL, the user-visible staleness window is a bug. The cost of a `tasks.list` round-trip is not worth it.
- **Caching filtered views (`today`, `overdue`, etc.).** These are derived from `tasks.list`. Caching them creates two staleness windows (raw + derived) instead of zero.
- **Write-behind / queued mutations.** A tool returning success before upstream confirms is a lie. Always block the response on upstream completion.
- **Background sync.** Turns this server into Architecture C (full mirror) by accident. The complexity grows fast and never stops.
- **Long-lived in-memory state with no invalidation hook.** Every cache layer must have an `invalidate()` callable from mutation paths. If a new mutation tool is added without wiring invalidation, it's a bug — surface it in code review.
- **Cross-cache bleeding.** The auth cache and the tasklist cache must not share TTLs, lifetimes, or invalidation triggers. They are different data with different policies.

## 6. Threat model notes (brief)

- Plaintext refresh token at `DB_PATH` is one filesystem-level compromise away from indefinite Google Tasks access. For a personal VPS with restricted SSH, this is acceptable. For shared hosting or multi-user, encrypt at rest.
- The bearer-token gate in `http_app.py` is the only thing between a public `/mcp` endpoint and the user's Google account. Treat it like a production secret. Rotate on any suspicion of leak.
- SQLite file permissions should be 0600 (owner-only). The DB lives next to the server process and should be owned by it.

## 7. When to revisit this doc

- A new tool is proposed that wants to cache content data. Re-read §5; the answer is no.
- A second user / multi-account support is added. §3 rule 5 (auth-as-credential) tightens — encryption-at-rest moves from optional to required.
- The server transport changes from HTTP (long-lived) to stdio (per-conversation). Tier-2 SQLite cache for tasklists becomes pointless; rip it out.
- Google Tasks adds new resource types (subtasks, assignments, etc.) that change the staleness profile. Re-run the table in §1.
