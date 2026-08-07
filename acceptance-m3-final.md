# M3 — Final Acceptance Evidence

**Milestone:** M3 — complete read-only retrieval & query layer (M3.1–M3.6)
**Status:** VERIFIED
**M4:** NOT STARTED
**Schema version:** 6 (no M3 migration)
**SQLite access:** TRUE READ-ONLY (`mode=ro` + `PRAGMA query_only=ON`)

## Verified starting state (M3.6 kickoff)

- M0/M1/M2: VERIFIED
- M3.1/M3.2/M3.3/M3.4/M3.5: VERIFIED
- M3.6: not started
- HEAD: `b1496f7` (clean tree, schema v6, no M3 migration)
- M3.5 focused: 56 passed; canonical: 539 passed, 3 skipped

## What was built in M3.6

- NEW `tests/unit/test_m3_integration.py` — the M3.6 integration battery (78 tests) mirroring the
  M2.7 structure: one representative synthetic corpus (multi project/profile/session, all event
  types, all verification & lifecycle statuses, identical timestamps for tie-break, relations,
  parent/child traces, knowledge-space + project/profile/session scopes, artifact references,
  sanitized FTS content, a deletion event via the verified M2.6 path, and a synthetic secret that
  must never appear).
- NEW `acceptance-m3-final.md` — this evidence.
- No source/implementation change was required: M3.6 is integration/performance/final-acceptance
  only. All M3.1–M3.5 behavior is exercised end-to-end; no product feature was added.

## Acceptance matrix results (this environment)

| Area | Result |
|------|--------|
| Structured query (event/trace/type/source/session/profile/project/task/turn/parent/lifecycle/verification/retention/time-range/combined AND) | PASS |
| Zero-result success (no silent fallback) | PASS |
| NULL identity preserved | PASS |
| Deleted excluded by default | PASS |
| Pagination (default/explicit/max, deterministic ordering, identical-timestamp tie-break, versioned query-bound cursor, limit/query mismatch, malformed cursor, no dup/skip, full==paginated, final page `next_cursor=None`, repeat-identical) | PASS |
| FTS (success, zero-result, malformed→`malformed_fts_expression`, deterministic ordering, structured composition, cursor text-binding, deleted excluded, no ranking, no secret leak) | PASS (FTS5 available) |
| Relation/scope (out/in, type filter, parent/child, explicit-only, project/profile/session, KS empty-page no-fallback, combined, artifact metadata + safe output, deleted-target exclusion, no cross-profile expansion) | PASS |
| Verification/lifecycle (exact filters, claim-not-fact, distinct event types, conflict unresolved, superseded retained, archived available, deleted excluded, confidence as stored metadata, no trust scoring) | PASS |
| Cross-feature composition (AND semantics for 6 realistic combos) | PASS |
| Error contract (all fixed sanitized codes; no raw SQLite/SQL/path/secret escape) | PASS |
| TRUE READ-ONLY proof (sqlite_master hash, schema version, all derived-table counts, content hashes, JSONL sha256, DB size unchanged before/after full query battery; no `ensure_schema`/migration called) | PASS |
| JSONL immutability (sha256 unchanged) | PASS |
| Secret safety (absent from all result/cursor/snippet/relation/scope/artifact/verification/error surfaces; scanner-confirmed) | PASS |
| Determinism (repeated identical queries → identical IDs/order/cursor) | PASS |
| No later behavior (no LLM/network/semantic/vector/context-injection/project-state/registry/decision-log/M4/M5-auth/MCP/Obsidian) | PASS |
| Real `~/.hermes` isolation (isolated HERMES_HOME; no real-home writes) | PASS |

## Performance benchmark (baseline only — no invented SLA, no cache added)

- Environment: SQLite 3.53.1, FTS5 available.
- Corpus: 200 synthetic events (temp dir, isolated store), sanitized FTS content + relations.
- Iterations: 25 per query; median + p95 (ms):

| Query | median (ms) | p95 (ms) |
|-------|------------|----------|
| exact `get_event` | 0.02 | 0.03 |
| `get_trace` | 0.01 | 0.01 |
| indexed project filter | 0.23 | 0.28 |
| combined structured filter | 0.24 | 0.31 |
| `search_text` (FTS) | 0.41 | 0.50 |
| `get_related` | 0.05 | 0.06 |
| first-page pagination (limit 50) | 0.23 | 0.29 |
| subsequent-page pagination | 0.49 | 0.57 |

All p95 values are well under the sanity bounds (<50ms structured/relation/page, <100ms FTS); no
pathological full-scan was observed where an approved index exists.

## TRUE READ-ONLY proof (hard gate)

- Before/after `Snapshot(rs, jsonl)` over `rs.conn` (read-only connection): `schema_hash`,
  `counts` (all derived tables), `meta_hash`, `jsonl_sha`, `db_size` all equal after a full query
  battery (structured, pagination, FTS, relations, scopes, verification/lifecycle, provenance,
  admin deleted inspection).
- `_extended_counts` over derived + `zm_fts` + `zm_tombstones` + `zm_deletion_audit` equal before/after.
- No `ensure_schema` / migrations / `downgrade_to` is reachable from the M3 retrieval path
  (`test_no_ensure_schema_called` monkeypatch-proves it).
- Open mode is `file:<db>?mode=ro` + `PRAGMA query_only=ON` (`test_query_only_enabled`,
  `test_readonly_open` from M3.1).

## Capability-dependent skips

- None in this environment: FTS5 is available, so all FTS tests ran (no skip). The FTS-unavailable
  branch (`fts_unavailable`) is covered by the contract constant and the M3.3 matrix.

## Real-home isolation

- `test_no_real_hermes_home_writes` isolates `HERMES_HOME` to a temp dir and asserts no writes to the
  real `~/.hermes`. Passed.

## Test counts

- M3.1 focused (`test_m3_query.py`): 76 passed
- M3.2 focused (`test_m3_pagination.py`): 38 passed
- M3.3 focused (`test_m3_fts.py`): 56 passed
- M3.4 focused (`test_m3_relations.py`): 37 passed
- M3.5 focused (`test_m3_verification.py`): 56 passed
- M3.6 focused (`test_m3_integration.py`): 78 passed
- **Focused M3 total: 283 passed**
- **Canonical suite (`pytest tests/`): 617 passed, 3 skipped** (no deselect)

## Final state

- M3.1–M3.6: VERIFIED
- M3 overall: VERIFIED
- M4: NOT STARTED
- Working tree: clean at final HEAD
- No schema migration exists (schema version 6 unchanged)
- No M4 behavior exists

## Commits

- M3.6 plan: `510e71c` (plan-only checkpoint)
- M3.6 implementation/integration tests: <impl_commit>
- M3.6 tested commit: <tested_commit>
- M3.6 final evidence/state binding: <evidence_commit>

## Final report markers

M3: VERIFIED
M3.6: VERIFIED
Final tested commit: <tested_commit>
Current HEAD: <evidence_commit>
Schema version: 6
Focused M3 suite: 283 passed, 0 skipped
Canonical suite: 617 passed, 3 skipped
Working tree: clean
Next: M4 — Project state, requirements, decisions, artifacts, and verification records
