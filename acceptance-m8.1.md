# M8.1 — Contract Freeze and Derived-Index Foundation

Status: VERIFIED (pre-binding) — repository state binding recorded; final-head strict closure pending external canonical
Milestone: M8 (Graph / Temporal / Calibration) — increment 1 of 6
Schema version: 9 (derived foundation only)

## Scope

M8.1 freezes the M8 contracts and establishes the minimal derived-index foundation
later M8 increments build on. It implements NO later behavior:

- NO M8.2 graph projection / traversal
- NO M8.3 authorization-first graph read service
- NO M8.4 as-of / history temporal query
- NO M8.5 calibration ranking integration
- NO M8.6 M7 EvidenceSet integration
- NO M9 Obsidian projection
- NO M10 corpus expansion
- NO vectors / embeddings

## Starting planning HEAD

3b0d4fe0e6f9bba3e3579b9a3872a54963c4173d

## Implementation / Tested commit

bbc304183abdaff72fd8a65fccef6551190a520f

## Execution environment

- Normal external Ubuntu terminal (outside Hermes)
- Repository `.venv/bin/python3` -> `pytest`
- Clean isolated temporary HOME

## Focused external result

188 passed, 0 failed (0.65s)

Files:
- tests/unit/test_m8_1_contracts.py
- tests/unit/test_m8_1_temporal_provenance.py
- tests/unit/test_m8_1_schema_v9.py
- tests/unit/test_m8_1_rebuild.py
- tests/unit/test_m8_1_security.py

## Pre-binding canonical

2014 passed, 3 skipped, 0 failed (11.93s)

The 3 skips are the established historical M2 FTS5 availability skips (unchanged).
No deselection was used.

## Files / modules introduced

Frozen contracts (src/m8/):
- `__init__.py` — package boundary; declares M8.1 scope and deferred behavior
- `identity.py` — deterministic entity/relation identity (zero randomness, rebuildable)
- `vocabulary.py` — CLOSED entity / relation / resource_type vocabularies (fail-closed)
- `temporal_contract.py` — transaction/history time + explicit valid/effective time; no invented timestamps
- `provenance.py` — deterministic provenance; relation existence != truth
- `graph_contract.py` — typed node/edge contracts; graph != truth; resource_type preserved
- `calibration_contract.py` — input/output structure only; calibration != truth/verification/authorization
- `derived_index.py` — clear+rebuild lifecycle, canonical fingerprint, index-version registry (building/published/failed states)

Schema migration:
- `src/storage/migrations/migrate_9.py` — schema v9 derived foundation
- `src/storage/migrations/__init__.py` — migration registration

Storage integration:
- `src/storage/ingest.py` — `DERIVED_TABLES` extended to include the v9 derived tables

## Five v9 derived tables

| Table | Responsibility |
|-------|----------------|
| `zm_entities` | Frozen derived entity nodes (typed, resource_type-scoped, deterministic id) |
| `zm_entity_mentions` | Source span -> entity references (provenance-linked) |
| `zm_graph_edges` | Typed, scope-aware derived relations; NOT truth; authorization-aware by column |
| `zm_temporal_index` | Narrow transaction/effective time projection (actual timestamps only) |
| `zm_m8_index_versions` | Build-version registry enforcing building/published/failed lifecycle |

All five are DERIVED, disposable, and rebuildable from canonical JSONL + approved
M4/project records. None becomes canonical truth.

## Canonical vs derived classification

- CANONICAL (unchanged): JSONL traces, artifacts, M0–M7 SQLite projection tables. M8.1
  reads these; it never mutates canonical data.
- DERIVED (new): the five v9 tables above. Fully rebuildable; dropped and recreated by
  `rebuild_from_jsonl` via the extended `DERIVED_TABLES` list.

## Deterministic identity contracts

- Entity id = `identity_version || ':' || entity_type || ':' || canonical_name || ':' || (project_id or '')`
- Edge logical identity = typed endpoints + relation_type + source_ref + scope coordinates
- No Python object identity, no insertion order, no random UUID during rebuild.

## Relation vocabulary

CLOSED finite set in `vocabulary.py`. Unknown relation types raise `VocabularyError`
and are never coerced or silently accepted. Resource_type values are also closed and
preserve the M6.6 artifact/event/relation/decision distinction.

## Provenance contract

Every derived record carries: relation_source, source_ref, projection_version,
identity_version, provenance_hash, content_hash, and scope (profile_id / project_id /
knowledge_space_id). Serialization is deterministic (sorted keys).

## Temporal contract

- Transaction/history time: real observed_at/created_at strings only.
- Valid/effective time: accepted only when actually present and timezone-aware (ISO 8601).
- Malformed (timezone-naive, non-parseable) timestamps are rejected.
- No `valid_from`/`valid_to` invented.

## Calibration contract

- Structures only: `CalibrationInput` (candidate + factors) and `CalibrationResult`
  (score + lifecycle_status + provenance). NO scoring formula, NO weights, NO ranking.
- `CalibrationResult` payload contains no authorization vocabulary (authorized/allowed/
  grant/permission/access), proving calibration != authorization.

## v8 -> v9 migration

- Additive: creates the five derived tables + indexes; modifies no existing table/column/row.
- `IF NOT EXISTS` + index `IF NOT EXISTS` for idempotence.
- v8 data preserved; fresh v9 initialization supported.
- Downgrade to 8 drops the v9 tables (verified).

## Fresh v9 initialization

`SQLiteStore.ensure_schema()` applies 1..9 from a blank DB; ledger rows 1..9 present.

## Migration / rebuild semantics

- `clear_m8_derived_state()` deletes all five derived tables; `m8_tables_present()` gates it to v9.
- Deterministic rebuild: clear -> replay projection -> byte-stable snapshot (order-independent).
- `DERIVED_TABLES` (ingest.py) ensures `rebuild_from_jsonl` drops v9 tables so no stale
  derived rows survive a canonical rebuild and migration 9 never collides on re-apply.

## Defect 1 — DERIVED_TABLES omission (FIXED, permanent)

M2 `rebuild_from_jsonl` drops derived tables then replays migrations. The new M8
derived tables were initially absent from `DERIVED_TABLES`, allowing stale derived M8
rows to survive rebuild and `CREATE TABLE` to collide on re-apply.

Fix: added `zm_entity_mentions, zm_graph_edges, zm_temporal_index, zm_m8_index_versions,
zm_entities` to the derived-table drop list in safe dependency order (child before parent).

Permanent regression coverage: tests assert rebuild clears v9 tables and re-projection
restores an equivalent deterministic state.

## Defect 2 — NULL-unsafe graph-edge uniqueness (FIXED, permanent)

SQLite treats each NULL as distinct, so two identical unscoped edges would both be
admitted and the derived index would duplicate on rebuild. A plain `COALESCE`-to-sentinel
index was forgeable (a real scope id equal to the sentinel would collide).

Fix: the logical-identity unique index uses explicit `(scope_col IS NULL)` flags plus
`COALESCE(scope_col, '')`, so NULL occupies a coordinate no literal string can reach, and
stored columns keep a real NULL.

Permanent regression coverage:
- duplicate identical unscoped edge rejected (IntegrityError);
- real empty-string project_id stays distinct from unscoped;
- genuine different-scope edge of identical logical identity is allowed.

## resource_type preservation

Both edge endpoints carry `from_resource_type` / `to_resource_type`; every derived table
carries `profile_id`, `project_id`, `knowledge_space_id`. No generic `zm_nodes` table is
created (resource_type identity is never erased).

## Profile / project / knowledge-space preservation

Scope columns present on all five v9 tables. No cross-profile flattening, no
cross-project flattening. No graph-derived authorization.

## M5 preservation

M5 authorization model untouched. M8.1 imports only the M5 resource_type literal set
(contract-only), not any policy/decision surface. No new grants, no linked-auth widening.

## M6.6 preservation

The permanent resource_type isolation invariant holds: artifact-only grant != event
access != relation access != arbitrary project-resource access. No generic graph node
collapses resource_type identity.

## M7 preservation

M7 EvidenceSet budget (5 primary / 3 supporting / 8 total) untouched. M8.1 does not
import or modify any M7 injection module. ZERO_MEM_ENABLED behavior unchanged.

## Zero LLM proof

AST import analysis of all new M8 modules: no `openai`, `anthropic`, `httpx`, `requests`,
`aiohttp`, `socket`, `urllib`, `transformers`, `sentence_transformers`, `torch`,
`tiktoken`, `langchain`, `llama_index`, `faiss`, `chromadb`, `neo4j`, `networkx`, etc.
No `eval`/`exec`/`subprocess`/`__import__`.

## Zero network proof

No external HTTP clients, no `http://`/`https://`, no `socket.connect`, no `urlopen`.
Routine M8.1 LLM calls = 0; external network calls = 0.

## No GrantAdmin

No `GrantAdmin` / `grant_admin` token anywhere in M8 source. No `AuthorizedWriteService`
in any read path. No policy-engine import.

## No Hermes core change

All M8.1 code lives under `src/m8/` plus one additive migration and the `DERIVED_TABLES`
list extension. No Hermes core module was modified.

## No M8.2+ / M9 / M10

Static audit confirms absence of traversal (`traverse`/`neighbors`/`bfs`/`dfs`/`degree`/
`centrality`/`hop_limit`), temporal query (`as_of`/`query_history`), calibration scoring
(`calibrate`/`compute_score`/`score(`/`FACTOR_WEIGHTS`/`rank_`/`rerank`), EvidenceSet
integration, Obsidian, corpus expansion, vectors/embeddings. Deferred modules
(`graph_projection.py`, `graph_read_service.py`, `traversal.py`, etc.) do not exist.

## Skip reconciliation

3 skips = historical M2 FTS5 availability skips (tests/unit/test_m2_indexes.py:123, :143,
:231). Unchanged from M7 closure. No new skip/xfail introduced by M8.1.

## Security-scanner external-verification policy

Per M8.1 directive, authoritative Python acceptance is performed externally from a normal
Ubuntu terminal using the actual repository `.venv/bin/python3`. No alternate interpreter
paths, symlinks, wrappers, renamed binaries, system-python substitutes, or
`execute_code -> subprocess` were used for acceptance. Internal Hermes execution is NOT
treated as authoritative.

## Tests / acceptance summary

- M8.1 focused: 188 passed, 0 failed
- Pre-binding canonical: 2014 passed, 3 skipped, 0 failed

## Deferred (NOT implemented in M8.1)

M8.2 graph projection, M8.3 read service, M8.4 temporal query, M8.5 calibration ranking,
M8.6 EvidenceSet integration, M9 Obsidian, M10 corpus expansion, vectors/embeddings.

## Next

M8.2 — Explicit Graph Projection and Deterministic Rebuild (requires external final-head
canonical pass + explicit user approval to begin).
