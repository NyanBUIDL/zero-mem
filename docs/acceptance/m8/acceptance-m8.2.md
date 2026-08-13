# Acceptance — M8.2: Explicit Graph Projection and Deterministic Rebuild

**Status: STRICT VERIFIED**

Milestone: M8.2 (Graph / Temporal / Calibration — increment 2 of 6)
Schema version: **9** (unchanged; no v10 created)
M8 overall: **IN PROGRESS**

---

## 1. Starting state (reconciled)

| Item | Value |
|---|---|
| Expected starting HEAD | `de0de0f3b1bd645c05327dca806fdc0a8477a24e` |
| Actual starting HEAD | `de0de0f3b1bd645c05327dca806fdc0a8477a24e` ✅ |
| Working tree at start | clean ✅ |
| Branch | `master` |
| Schema at start | v9 |
| M0–M7 | VERIFIED |
| M8.1 | STRICT VERIFIED |
| M8.2 at start | NOT STARTED |

Reconciliation performed with `git rev-parse HEAD`, `git status --short --branch`,
`git log -12 --oneline --decorate`. No mismatch; no reconciliation stop triggered.

---

## 2. Files changed

### Added — implementation (3 modules, `src/m8/`)

| File | Purpose |
|---|---|
| `src/m8/graph_projection.py` | Pure deterministic projection: source record → typed M8.1 contract. No I/O. |
| `src/m8/graph_sources.py` | Read-only scanners over approved M2/M4 tables → typed `EdgeSourceRecord`. |
| `src/m8/projection_store.py` | Idempotent persistence into v9 derived tables + transactional rebuild. |

### Added — tests (3 files, `tests/unit/`)

| File | Tests |
|---|---|
| `tests/unit/test_m8_2_projection.py` | Deterministic entity/mention/edge projection, closed vocabulary, provenance, fail-closed. |
| `tests/unit/test_m8_2_rebuild.py` | Source readers, persistence, idempotence, clear/rebuild equivalence, canonical preservation. |
| `tests/unit/test_m8_2_security.py` | Zero LLM/network, no authorization reach, scope + resource_type preservation, authority safety, non-scope. |

### Modified — objectively required

| File | Change | Why |
|---|---|---|
| `src/m8/derived_index.py` | `describe_derived_foundation()["projection_implemented"]` → `True` | M8.2 implements projection; the flag was a truthful M8.1-time statement that is now stale. All later flags (`traversal`, `temporal_query`, `calibration_scoring`) remain `False`. |
| `tests/unit/test_m8_1_rebuild.py` | Assertion updated to match the flag above. | Same reason. |
| `tests/unit/test_m8_1_security.py` | Removed `test_no_m8_2_projection_module`. | That test asserted M8.2 modules do NOT exist — it was an M8.1 non-scope guard whose entire purpose was to fail once M8.2 landed. All M8.3+ non-scope guards are untouched and still pass. |

No other file in the repository was modified. Hermes core: **untouched**.

---

## 3. Graph projection model

```
approved canonical/project source row   (M2/M4 derived projections; read-only)
        ↓   graph_sources.py            deterministic scan, fixed ORDER BY
typed EdgeSourceRecord / EntitySourceRecord / MentionSourceRecord
        ↓   graph_projection.py         pure, no I/O, frozen M8.1 contracts
GraphEdge / EntityRecord / MentionProjection
        ↓   projection_store.py         idempotent INSERT ... ON CONFLICT DO NOTHING
derived v9 tables: zm_graph_edges / zm_entities / zm_entity_mentions
```

No second source of truth is created. Canonical JSONL is never opened by any
M8.2 module.

### Approved edge classes

| `relation_source` | Source | Projected relation |
|---|---|---|
| `m2_relation` | `zm_relations` (mapped names only) | `derived_from`, `supersedes` |
| `m2_artifact` | `zm_artifacts.origin_event_id` | `event source_of artifact` |
| `m4_supersession` | `zm_decisions.supersedes_id`, `zm_requirements.supersedes` | `supersedes` |
| `m4_project_link` | `linked_requirement_ids`, `linked_decision_ids` | `decision_for`, `artifact_of` |
| `m4_verification` | `zm_verifications` subject linkage | `verifies` |

**Deliberately not projected:** `m2_scope`. Profile / project / knowledge-space
are authorization coordinates, not content nodes; promoting them to nodes would
invite "shares a project therefore reachable" inference. They are preserved as
scope **metadata** on every derived row instead.

---

## 4. Determinism

| Property | Result |
|---|---|
| Same source → same `edge_id` / `entity_id` / `mention_id` | ✅ digest-derived, from the frozen M8.1 identity contract |
| Random UUIDs | none |
| Python `hash()` / set iteration in identity | none (canonical JSON + sorted keys) |
| Insertion-order dependence | none — proven by rebuilding two independent DBs seeded in **different order** and asserting identical `derived_state_snapshot()` |
| Wall-clock in identity or build stamps | none — `built_at` / `source_cutoff` derive from `MAX(zm_meta.created_at)`; when no source timestamp exists the rebuild **fails closed** rather than inventing one |
| Scan order | fixed `ORDER BY` on every query; fixed reader sequence |

`test_two_independent_databases_agree`, `test_clear_then_rebuild_reproduces_state`,
`test_scan_order_is_stable`, `test_missing_timestamps_fail_closed`.

---

## 5. Entity, mention, and edge results

- **Entity identity** uses only the M8.1 contract `(entity_type, normalized name, scope)`.
  No second ID scheme. No semantic auto-merge: `Ada` vs `ada` vs `A. Lovelace`
  stay three distinct entities.
- **Mentions** are deterministic in `(entity_id, source_event_id, span)`; an
  absent span stays `NULL`. Raw span text is hashed immediately and never stored
  (`test_mention_rows_store_no_raw_text`).
- **Edges** are typed on both endpoints; endpoint resource_type participates in
  identity, so `event→event` and `event→artifact` are different edges.

### Relation vocabulary enforcement

Only the closed M8.1 vocabulary is accepted. An unmapped source relation is
**reported and dropped**, never coerced:

- `child_of` (M2) has no approved M8 counterpart → skipped with reason code
  `unmapped_source_relation_type`. It is *not* mapped to `related_to`.
- Unknown `subject_type` (e.g. `session`) → `unmapped_verification_subject_type`.
- Arbitrary/user-controlled relation names raise `ProjectionError`.

---

## 6. Provenance

Every derived row carries: `relation_source`, `source_ref`, `source_event_id`,
`trace_id`, `projection_version` (`m8.2`), `identity_version`, `provenance_hash`,
`content_hash`. Nothing is fabricated — an absent `trace_id` stays `NULL`;
lifecycle, verification status, and timestamps are copied verbatim from source.

---

## 7. Scope and resource_type preservation

| Dimension | Preserved | Evidence |
|---|---|---|
| `profile_id` | ✅ | `test_scope_columns_persisted`, `test_same_name_in_two_profiles_stays_distinct` |
| `project_id` | ✅ | `test_same_name_in_two_projects_stays_distinct` |
| `knowledge_space_id` | ✅ | `test_same_name_in_two_knowledge_spaces_stays_distinct` |
| `resource_type` | ✅ | `test_artifact_and_event_endpoints_never_collapse`, `test_project_artifact_is_not_artifact` |

The same textual entity in two profiles/projects/spaces yields **different**
entity IDs — it does not flatten into one node and therefore cannot create
cross-scope visibility. Scoped and unscoped variants are also distinct.

**M6.6 permanent invariant preserved:** no generic node table exists
(`test_no_generic_node_table_created`); `artifact`, `event`, `relation`, and
`project_artifact` remain separate resource types on every endpoint.

Empty-string scope values are normalized to `NULL` rather than stored as a
forgeable `''` sentinel that could collide with the uniqueness encoding.

---

## 8. Authorization boundary

M8.2 **stores** authorization-relevant metadata and **makes no authorization
decision**. M5 remains the sole authority.

- No import of any policy/grant module (AST-verified over all three modules).
- No `GrantAdmin`, `authorize`, `check_access`, `is_authorized`, `can_read`,
  `filter_authorized`, `has_permission` symbol anywhere.
- `authorization_metadata()` output is per-endpoint **input** for M5 and contains
  no decision token (`authorized`, `allowed`, `grant`, `permission`, `access`).
- Nothing derives access from shared entity, shared project, shared edge,
  node degree, connected component, or relation type.

---

## 9. Authority safety (graph ≠ truth)

| Guarantee | Evidence |
|---|---|
| `assistant_claim` is not promoted | `test_assistant_claim_is_not_promoted` — lifecycle stays `candidate`, verification stays `none` |
| A `verifies` edge does not verify its subject | `test_verifies_edge_does_not_verify_subject` — subject row untouched |
| Conflicts are not resolved | `test_conflict_is_not_resolved` — both directions of a mutual `supersedes` survive; no winner picked |
| Recency is not authority | `test_newer_timestamp_does_not_change_lifecycle` |
| Degree/frequency is not confidence | `test_high_degree_does_not_promote_authority`; `test_no_confidence_or_score_column_written` |

M4 supersession semantics are preserved as-recorded; no competing supersession
model is introduced.

---

## 10. Idempotence

| Check | Result |
|---|---|
| Project same source twice | `edges_written == 0` on the second pass; row count unchanged |
| Rebuild twice | identical `derived_state_snapshot()` |
| Duplicate entities | none (`ON CONFLICT(entity_id) DO NOTHING`) |
| Duplicate mentions | none |
| Duplicate index/version records | none — registry keyed per index name |
| **NULL/unscoped edge duplicate regression** | ✅ preserved — `TestUnscopedDuplicateRegression`; the M8.1 NULL-safe uniqueness fix remains protected |

---

## 11. Rebuild

`rebuild_graph()` runs in **one transaction**: begin index build → clear derived
M8 state → re-project all approved sources → publish.

- Populated graph → `clear_m8_derived_state()` → `m8_derived_state_is_empty()` is
  `True` → rebuild → **identical** snapshot (`test_rebuild_from_empty_derived_state`).
- Canonical projections (`zm_meta`, `zm_relations`, `zm_decisions`) row counts
  unchanged across rebuild.
- Canonical JSONL byte-identical across rebuild (`test_rebuild_does_not_touch_canonical_jsonl`).
- `canonical_fingerprint` tracks source state and changes when sources change.

### Failure safety

Malformed source data (e.g. truncated JSON in `linked_requirement_ids`) aborts
the rebuild, rolls back, leaves **0 rows**, and marks the index version `failed`
— never `published`. No partial promotion into trusted graph state.
Projection against a pre-v9 schema is refused.

---

## 12. Zero LLM / zero network

| Check | Result |
|---|---|
| LLM calls | **0** |
| External network calls | **0** |
| Banned imports (openai, anthropic, transformers, torch, requests, httpx, aiohttp, urllib, socket, grpc, boto3, faiss, chromadb, qdrant, pinecone, weaviate, neo4j, networkx, …) | none — AST-verified |
| Network literals (`http://`, `https://`, `urlopen`, `.connect(`) | none |
| `subprocess` / `eval` / `exec` / `__import__` | none |
| Embeddings / vectors / cosine / kNN | none |
| Hardcoded HOME (`/home/`, `/Users/`, `expanduser`, `Path.home()`, `.hermes`) | none |

---

## 13. Preservation of prior milestones

| Milestone | Status |
|---|---|
| M2 canonical/rebuild | ✅ unchanged |
| M4 relations/conflicts/supersession | ✅ unchanged, semantics preserved |
| M5 scope and authorization metadata | ✅ unchanged; M5 remains sole authority |
| M6.6 resource_type isolation | ✅ preserved; no M6 tool added or modified |
| M7 EvidenceSet / routing / injection | ✅ untouched — 5 primary + 3 supporting = 8 total |
| M8.1 contracts/schema/rebuild/security | ✅ preserved (two stale M8.1-time assertions updated, §2) |

---

## 14. Non-scope confirmation

Not implemented, and statically asserted absent: graph traversal / neighbor
expansion / BFS / DFS / shortest-path / degree / centrality (M8.3), as-of and
history queries / latest-wins / temporal precedence (M8.4), calibration scoring
and ranking (M8.5), EvidenceSet integration and automatic injection (M8.6),
Obsidian projection (M9), corpus expansion (M10). No `migrate_10.py` exists.

---

## 15. Test evidence

All runs used the normal repository interpreter `.venv/bin/python3` under an
isolated `HOME` (`HOME="$(mktemp -d)"`). No symlink, wrapper, alternate
interpreter, `execute_code` subprocess, or scanner modification was used for any
authoritative run.

### Focused M8.2

```
.venv/bin/python3 -m pytest tests/unit/test_m8_2_projection.py \
  tests/unit/test_m8_2_rebuild.py tests/unit/test_m8_2_security.py -q
108 passed in 0.36s
```

**0 failed** ✅

### Pre-binding canonical

```
.venv/bin/python3 -m pytest tests/ -q
2121 passed, 3 skipped in 11.81s
```

**0 failed, no deselection, no new skip/xfail.** ✅
The 3 skips are the unchanged historical M2 FTS5 skips (2014 → 2121 passed;
+107 net from the M8.2 suite, minus the one removed M8.1 non-scope guard).

### Final-head canonical

Recorded in the closure report after state binding; run on the exact final HEAD.

---

## 16. Commits

| Role | Commit |
|---|---|
| Implementation / tested | `1cc76cdfecaf54a199258eaa61058777a284b3b7` |
| Evidence / state binding | recorded in the closure report |

---

## 17. Acceptance criteria

- [x] starting HEAD reconciled
- [x] only M8.2 implemented
- [x] schema remains v9
- [x] graph projection deterministic
- [x] entity projection deterministic
- [x] mentions deterministic
- [x] edges deterministic
- [x] provenance preserved
- [x] profile / project / space / resource_type preserved
- [x] graph remains derived
- [x] JSONL remains canonical
- [x] rebuild deterministic
- [x] repeated rebuild idempotent
- [x] no duplicate unscoped edges
- [x] no auth decisions in M8.2
- [x] M5 preserved
- [x] M6.6 preserved
- [x] graph ≠ truth
- [x] assistant_claim not promoted
- [x] conflict not auto-resolved
- [x] temporal recency not truth
- [x] no calibration integration
- [x] zero LLM
- [x] zero external network
- [x] no Hermes core changes
- [x] M6 tools unchanged
- [x] M7 unchanged
- [x] no M8.3+
- [x] no M9/M10
- [x] focused tests 0 failed
- [x] pre-binding canonical 0 failed
- [x] implementation commit created
