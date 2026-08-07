# M3.4 — Final Acceptance Evidence

**Milestone:** M3.4 — Relation / scope / artifact read queries
**Status:** VERIFIED
**M3 overall:** IN PROGRESS (M3.5 not started)

## Verified starting state

- M0/M1/M2: VERIFIED
- M3.1: VERIFIED — M3.2: VERIFIED — M3.3: VERIFIED
- M3.4: not started at increment open (HEAD `8103203`)
- SQLite schema: v6; no M3 migration (none)
- SQLite access: TRUE READ-ONLY (`mode=ro` + `PRAGMA query_only=ON`)
- Working tree: clean

## Implementation

### Files
- `src/retrieval/relations.py` — new: `get_related`, `get_parent`, `get_children`,
  `get_artifacts`, `list_knowledge_space`. SELECT-only; bounded depth=1; no writes.
- `src/retrieval/models.py` — `INVALID_RELATION_TYPE`, `INVALID_DIRECTION` error codes;
  `RelatedView`, `RelatedResult`, `ArtifactRefView`, `ArtifactResult` dataclasses.
- `src/retrieval/cursor.py` — `make_relation_fingerprint(event_id, direction, relation_type)`
  and `make_artifact_fingerprint(origin_event_id)` for query-bound cursor binding.
- `src/retrieval/__init__.py` — exported new public API + fingerprints.
- `tests/unit/test_m3_relations.py` — 37 focused tests.

### API delivered (smallest approved surface)
- `get_related(event_id, relation_type=None, direction=None, limit=None, cursor=None)` — both / outgoing / incoming; explicit edges only.
- `get_parent(event_id)` — thin wrapper (outgoing `child_of`).
- `get_children(event_id, limit=None, cursor=None)` — thin wrapper (incoming `child_of`).
- `get_artifacts(event_id, limit=None, cursor=None)` — artifact-reference metadata; safe `artifact:<id>` reference, no `stored_path`.
- `list_knowledge_space(ks_id, limit=None, cursor=None)` — returns `[]` (schema-truthful: no event-level linkage exists in verified M2; no inference / global fallback).
- Scope queries `list_project` / `list_profile` / `list_session` already delivered in M3.1; reused unchanged (caller-supplied filters only).

### Directionality (enforced, tested)
- outgoing → `from_event_id = event_id`; incoming → `to_event_id = event_id`; both → union.
- Directed edges are NEVER treated as undirected (tests `test_directionality_preserved`, `test_get_related_outgoing`/`_incoming`).

### Relation semantics
- ONLY explicitly stored edges in `zm_relations` (relation types: `child_of`, `derived_from`, `supersedes`).
- NO inference: no transitive, causal, semantic, similarity, same-project, cross-profile, or cross-project edges (`test_no_inferred_relation`).
- No explicit relation → empty successful result (`test_no_explicit_relation_empty_success`).

### Scope queries
- project / profile → `zm_meta.project_id` / `profile_id`; session → `zm_meta.session_id`; all via M3.1 `query_events` (deleted-excluded, paginated).
- Zero-match scope → `[]`, no global fallback (`test_zero_result_scope_no_global_fallback`,
  `test_knowledge_space_returns_empty_no_inference`).
- No authorization: caller-supplied filters only; no allow/deny/identity logic
  (`test_no_authorization_behavior`).

### Knowledge-space behavior
- `knowledge_space_id` is projected ONLY into `zm_scopes` (scope_type='knowledge_space') in the
  verified M2 schema; there is NO `zm_meta` column and NO event→knowledge_space link. `list_knowledge_space`
  therefore returns `[]` with `error=None` and does NOT invent membership from project/profile/file/relation/name.

### Artifact references
- `get_artifacts` returns `zm_artifacts` metadata (artifact_id, content_hash, kind, retention,
  origin_event_id, created_at) + a safe `reference = "artifact:<id>"`.
- `stored_path` (internal filesystem pointer) is NEVER exposed (`test_artifact_safe_reference_no_path_leak`).
- No artifact content is opened/fetched; no local paths leaked.

### Deleted-state behavior
- Normal relation/scope queries exclude deleted TARGETS via the same derived-state subquery as M3.1–M3.3
  (`event_id NOT IN (SELECT event_id FROM zm_lifecycle WHERE current_state='deleted')`).
- A relation whose resolved target is deleted does NOT surface it (`test_deleted_related_target_excluded`).
- Non-deleted related targets remain included (`test_non_deleted_related_target_included`).
- Decision B preserved.

### Lifecycle / verification
- No new lifecycle ranking or trust policy. Stored `verification_status` is returned as-is
  (`test_no_m3_5_behavior`); no re-scoring / `trust_score`.

### Pagination / cursor binding
- Reuses M3.2 deterministic `(created_at ASC, event_id ASC)` keyset pagination + versioned cursor.
- Relation cursor fingerprint binds `event_id` + `direction` + `relation_type`; artifact cursor binds
  `origin_event_id`. Cross-query reuse is rejected (`test_relation_cursor_query_binding`,
  `test_relation_cursor_limit_binding`, `test_relation_invalid_limit`).
- No duplicates / no skipped rows across pages (`test_relation_pagination_no_duplicates`).

### Deterministic ordering
- Event results ordered `(created_at ASC, event_id ASC)` (`test_deterministic_relation_ordering`,
  `test_deterministic_scope_ordering`). No reliance on rowid / insertion order.

### Result contract
- `RelatedResult` / `ArtifactResult` / `QueryResult` wrap results; no raw rows, JSONL, payloads,
  secrets, paths, or exceptions leak. Errors are fixed sanitized codes.

### Error contract (fixed sanitized codes)
- `invalid_query`, `invalid_relation_type`, `invalid_direction`, `invalid_limit`,
  `cursor_query_mismatch`, `cursor_limit_mismatch`, `database_unavailable`.
- A valid relation query with no relations is NOT an error.

### Secret safety
- Synthetic secrets inserted only into `sanitized_content` (never into `zm_relations`/`zm_scopes`/
  `zm_artifacts`). Tests assert outputs and cursors contain no secret
  (`test_relation_output_no_secret`, `test_scope_output_no_secret`, `test_artifact_safe_reference_no_path_leak`).

### TRUE READ-ONLY proof
- Before/after M3.4 operations: `sqlite_master`/schema DDL hash, derived-table row counts
  (`zm_meta`, `zm_lifecycle`, `zm_provenance`, `zm_relations`, `zm_scopes`, `zm_artifacts`,
  `zm_ingest_checkpoint`, `zm_ingest_log`), `zm_meta` content hash, and JSONL sha256 are unchanged
  (`test_sqlite_unchanged_after_relation_queries`, `test_relation_tables_unchanged`,
  `test_jsonl_unchanged`).
- No `ensure_schema` / migration / write transaction is called by M3.4.

### Exclusions honored
- No relation writes, inference, graph traversal beyond direct edges, authorization, access control,
  permission inheritance, cross-profile/project auto-expansion, M3.5 trust policy, ranking, scoring,
  semantic/vector search, LLM query rewriting, context injection, M4 project-memory, MCP, Obsidian,
  or schema migration. (`test_no_authorization_behavior`, `test_no_m3_5_behavior`, `test_no_m4_behavior`,
  full canonical suite green.)

## Test results

- M3.4 focused (`tests/unit/test_m3_relations.py`): **37 passed**
- M3.1 + M3.2 + M3.3 + M3.4 combined: **149 passed**
- Full canonical suite (`tests/ -q`, no deselect): **483 passed, 3 skipped**
  - The 3 skipped are the pre-existing environment-bound baselines (not M3.4-attributable).
  - `test_m2_indexes::test_no_real_hermes_home_writes` passes independently (M3.4 carries its own
    `test_no_real_hermes_home_writes_during_relations` proving no real `~/.hermes` writes).

## Acceptance criteria

- [x] all M3.4 acceptance criteria pass
- [x] M3.1–M3.3 remain VERIFIED
- [x] focused M3.4 passes (37)
- [x] combined M3.1–M3.4 passes (149)
- [x] canonical suite passes (483 passed, 3 skipped) — no deselect
- [x] relation queries explicit-only; no inferred edges
- [x] scopes do not fall back globally
- [x] artifact references safe (no `stored_path` / path leak)
- [x] deleted targets remain excluded
- [x] pagination deterministic; cursor binding enforced
- [x] TRUE READ-ONLY proof passes
- [x] no schema migration exists
- [x] no M3.5+ behavior; no M4 behavior
- [x] working tree clean after commit

## Conclusion

M3.4: VERIFIED. M3 overall: IN PROGRESS. Next: M3.5 — Verification and lifecycle-aware retrieval.

## Files changed

- src/retrieval/relations.py (new)
- src/retrieval/models.py (added codes + dataclasses)
- src/retrieval/cursor.py (added fingerprints)
- src/retrieval/__init__.py (exports)
- tests/unit/test_m3_relations.py (new, 37 tests)
