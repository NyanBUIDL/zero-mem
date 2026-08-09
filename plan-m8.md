# M8 — Graph / Temporal / Calibration Plan

**Status:** PLAN READY — awaiting explicit approval; M8 implementation has not started.

**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (the repository contains the authoritative DOCX; the older Markdown path named by `IDEA.md` is absent).

**Scope:** deterministic, local, derived graph/temporal/calibration capability composed with the verified M0–M7 sidecar. This plan does not implement code, tests, migrations, M8.1, M9, or M10.

---

## 1. Reconciled starting state

Repository reconciliation was performed before planning:

- Repository root: `/home/brian-nguyen/Hermes Workplace/Zero-mem`
- HEAD: `1f9b647575f89fc944fa854dd29dbcb8ef5c7ab6`
- Branch: `master`
- Working tree: clean
- Schema: v8
- M0–M6: VERIFIED
- M7.1–M7.6: VERIFIED
- M7 overall: VERIFIED
- M8: NOT STARTED
- M9: NOT STARTED
- M10: NOT STARTED
- Final M7 evidence: `acceptance-m7.6.md`
- Final M7 focused result: 78 passed, 0 failed
- Final canonical result: 1826 passed, 3 historical M2 FTS5 skips, 0 failed
- Final M7 performance target: p95 < 2 seconds, met
- Final M7 continuation benchmark: 5/5, 100%, target >=90%, met
- Routine Zero-Mem LLM calls: 0
- Routine Zero-Mem external network calls: 0

The final M7 evidence is authoritative for the M7 boundary. No stale planning snapshot is used.

### Repository/specification discrepancy

`IDEA.md` refers to `docs/Hermes-External-ZeroMem-Specification.md`, but that file is not present. The authoritative `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` is present and was extracted/read in full for this plan. This discrepancy is recorded, not silently resolved.

No separate ADR directory or standalone ADR files were found. Relevant architecture decisions are recorded in `ARCHITECTURE.md`, acceptance documents, and the verified source contracts. Those are treated as the available project decision record pending any later ADR convention decision.

---

## 2. M8 objective

M8 will add a deterministic, local, rebuildable **relationship and temporal evidence layer** plus an explainable **candidate calibration score**. It will improve candidate discovery and historical filtering without changing canonical authority, M5 authorization, M6 read-tool security, or the M7 EvidenceSet boundary.

M8 is not a truth engine. It must not promote claims, resolve conflicts, grant authorization, mutate project state, or inject graph neighbors directly into prompts.

### Precise repository-specific definitions

- **Graph:** an authorization-aware derived adjacency index over explicitly stored M2/M4 relationships and explicitly approved entity/mention records. It supports bounded neighbor/bridge discovery and provenance-preserving relation inspection. It is not Obsidian Graph View, a graph database, a centrality engine, or an inferred truth store.
- **Temporal:** deterministic interpretation of already stored event/project timestamps, `valid_from`/`valid_until` where available, M4 `effective_at`, lifecycle, verification, and explicit supersession. It supports bounded current/as-of/history queries. It does not invent missing timestamps or select truth by recency.
- **Calibration:** deterministic decomposition of retrieval/evidence quality signals into a bounded candidate score and reason codes. It ranks eligible candidates only. It does not mean model confidence, authorization, verification, or automatic promotion.

---

## 3. Authoritative requirements and boundaries

The relevant master-spec material is §§6–7 (trace, provenance, lifecycle, temporal conflict), §9.2–9.3 (storage and rebuildable indexes), §11.2–11.4 (relational/temporal retrieval, score reference, controlled injection), §14 (security), §15.2–15.3 (budgets/metrics), §§16.1–16.4 (local stack, build order, definition of done), §§17.1–17.3 (tests/benchmarks), §18 (M8 roadmap), and Appendices C/E/F.

The specification requires:

- trace-first provenance;
- explicit links and temporal validity;
- verification over assistant self-report;
- visible conflicts and no silent overwrite;
- deterministic/local memory operations with zero routine LLM calls;
- bounded evidence and authorization before final evidence selection;
- rebuildable graph/temporal/index views;
- Obsidian only as the later M9 projection/workspace;
- no large corpus integration in M8.

The specification mentions `entities`, `entity_mentions`, `trace_links`, graph tables, and an illustrative score, but does not define a complete M8 schema, entity-linking algorithm, score formula, or numeric thresholds. This plan therefore freezes conservative, local contracts and marks material choices requiring approval below rather than presenting unspecified behavior as authoritative.

---

## 4. Verified architecture reused

M8 extends, and does not replace:

- **M2:** append-only canonical JSONL event history; SQLite projections/indexes are derived, disposable, and rebuildable; artifacts remain separate versioned files. Existing v8 includes `zm_meta`, lifecycle/provenance, explicit `zm_relations`, scopes, artifacts, tombstones/audit, and ingest checkpoints/logs.
- **M3:** true read-only `ReadonlyStore` (`mode=ro`, `query_only=ON`), deterministic ordering/cursors, FTS, explicit relation reads, lifecycle/verification filtering, deleted exclusion, and no inference/write during retrieval.
- **M4:** project charter/requirements/decisions/current-state/verifications/artifact substrate; explicit operation envelopes; explicit supersession; visible conflicts; verified-state selection from stored lifecycle, never MAX timestamp; rebuild from canonical operations/events.
- **M5:** authoritative policy and `AuthorizedReadService`; authorization-before-query; explicit `requesting_profile_id`; no identity inference; profile/project/knowledge-space scopes; persistent grant resolution; linked-resource independent authorization; resource-type isolation.
- **M6:** ten explicit READ tools and external plugin adapter. M8 does not add write or GrantAdmin exposure by default. Existing tool contracts remain unchanged unless a separately approved read-only extension is required.
- **M7:** one `ZERO_MEM_ENABLED` master switch; deterministic router; authorized bounded `EvidenceSet`; controlled injection; prompt-injection hardening; conflict/insufficiency signaling; maximum 5 primary + 3 supporting + 8 total; no direct graph-to-prompt path.

### Data-flow diagram

```text
canonical JSONL + versioned artifacts + approved M4/project sources
        |
        | deterministic replay; no semantic mutation
        v
M8 derived graph / temporal indexes + deterministic calibration inputs
        |
        | authorization-first candidate lookup and bounded traversal
        v
M5 AuthorizedReadService (per node/resource/edge, resource_type preserved)
        |
        v
M3/M4 read contracts + temporal/lifecycle/conflict filtering
        |
        v
M8 explainable candidate score and reason codes
        |
        v
M7 eligibility + EvidenceSet (max 5 primary, max 3 supporting, max 8 total)
        |
        v
M7 hardening / controlled injection as DATA only
        |
        v
Hermes final reasoning/action
```

No graph result bypasses M5, M7 eligibility, or M7 hardening.

---

## 5. Storage ownership and canonical/derived classification

### Canonical

- Raw append-only JSONL traces and approved canonical write-back/project operations remain source-of-record.
- Versioned artifact files remain canonical for large outputs and source material.
- Existing canonical event/provenance fields and approved M4 operation records remain authoritative for identity, lifecycle, verification, supersession, and conflict.
- M8 must never rewrite or delete canonical history to maintain an index.

### Derived

- Entity and mention index rows, if approved, are derived from canonical traces/approved structured operations.
- Graph adjacency/edge indexes are derived views of explicit canonical relation records and approved structured links.
- Temporal indexes are derived projections of existing timestamps and validity fields.
- Calibration factors/scores are derived request-time or versioned index metadata, never facts.
- Index versions, rebuild checkpoints, and metrics are derived operational records.

Large content remains in artifacts; M8 stores safe IDs/references and metadata, not duplicate unrestricted content.

### Read/write boundary

Normal M8 request-time graph, temporal, and calibration operations are read-only. Index maintenance is a local derived rebuild/update operation, not semantic memory mutation. M8 does **not** automatically confirm facts, resolve conflicts, promote lifecycle, mutate project state, alter grants, or write back to canonical memory.

Any future approved semantic write must use an explicit M4/M5 write policy and audited canonical event; it is outside this plan.

---

## 6. Schema impact analysis

### Critical answer: Q1/Q2

**Q1 — Can full M8 be implemented while preserving schema v8? PARTIAL.**

A limited M8 foundation can read existing v8 relations, lifecycle/provenance, `created_at`/`observed_at`, M4 `effective_at`, and stored confidence without a migration. Full repository-defined M8 requires entity/mention identity, relation provenance/index versioning, valid-time query support across M4 resources, and auditable calibration decomposition. Those contracts are not safely representable by overloading existing columns or by treating existing relation rows as an unrestricted entity graph.

**Q2 — Why is v8 insufficient?** Existing `zm_relations` contains explicit event-to-event edges (`from_event_id`, `to_event_id`, relation type, provenance fields), not a typed entity/mention model. `zm_meta` has event/observed timestamps but no general valid interval. M4 decisions use `effective_at`, while other project tables have different temporal columns and semantics. Existing `confidence` is source metadata and cannot be repurposed as a calibrated score. Existing indexes do not provide a versioned, bounded, authorization-aware graph/temporal projection. Adding JSON blobs or overloading `zm_relations` would make identity, provenance, rebuild, and authorization ambiguous.

**Proposed impact: schema v9, only after explicit M8 plan approval.** No migration is created in planning.

### Proposed v9 derived structures

The exact migration must be reviewed before implementation, but the smallest proposed shape is:

1. `zm_entities`
   - `entity_id TEXT PRIMARY KEY`
   - `entity_type TEXT NOT NULL` from a closed approved vocabulary
   - `canonical_name TEXT NOT NULL`
   - `profile_id TEXT NULL`, `project_id TEXT NULL`, `knowledge_space_id TEXT NULL`
   - `source_event_id TEXT NULL`, `trace_id TEXT NULL`
   - `lifecycle_status TEXT NOT NULL` using the existing closed lifecycle enum
   - `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`
   - `content_hash TEXT NOT NULL`
   - logical uniqueness over scope/type/name only where explicitly approved; no identity inference from text alone

2. `zm_entity_mentions`
   - `mention_id TEXT PRIMARY KEY`
   - `entity_id TEXT NOT NULL`
   - `source_event_id TEXT NOT NULL`
   - `trace_id TEXT NULL`
   - `span_start INTEGER NULL`, `span_end INTEGER NULL`
   - `mention_text_hash TEXT NOT NULL` (not raw secret-bearing text)
   - `profile_id TEXT NULL`, `project_id TEXT NULL`, `knowledge_space_id TEXT NULL`
   - `created_at TEXT NOT NULL`
   - foreign/logical references to derived entity/event rows; invalid targets fail closed

3. `zm_graph_edges`
   - `edge_id TEXT PRIMARY KEY`
   - `from_resource_type TEXT NOT NULL`, `from_resource_id TEXT NOT NULL`
   - `relation_type TEXT NOT NULL` from a closed approved vocabulary
   - `to_resource_type TEXT NOT NULL`, `to_resource_id TEXT NOT NULL`
   - `source_event_id TEXT NULL`, `trace_id TEXT NULL`, `provenance_hash TEXT NOT NULL`
   - `profile_id TEXT NULL`, `project_id TEXT NULL`, `knowledge_space_id TEXT NULL`
   - `created_at TEXT NOT NULL`
   - `lifecycle_status TEXT NOT NULL`
   - `valid_from TEXT NULL`, `valid_until TEXT NULL`
   - `content_hash TEXT NOT NULL`
   - uniqueness on the full logical edge/provenance identity, not `AUTOINCREMENT` order

4. `zm_temporal_index`
   - `resource_type TEXT NOT NULL`, `resource_id TEXT NOT NULL`
   - `observed_at TEXT NULL`, `created_at TEXT NULL`, `effective_at TEXT NULL`
   - `valid_from TEXT NULL`, `valid_until TEXT NULL`, `superseded_at TEXT NULL`
   - `lifecycle_status TEXT NOT NULL`, `verification_status TEXT NULL`
   - `source_event_id TEXT NULL`, `trace_id TEXT NULL`
   - composite key `(resource_type, resource_id)`
   - no fabricated timestamp; null remains null

5. `zm_m8_index_versions`
   - `index_name TEXT PRIMARY KEY`, `version TEXT NOT NULL`, `source_cutoff TEXT NOT NULL`
   - `canonical_fingerprint TEXT NOT NULL`, `built_at TEXT NOT NULL`, `build_status TEXT NOT NULL`
   - records derived rebuild identity only; no content or authority

6. `zm_calibration_factors` (only if request-time decomposition cannot remain entirely in memory)
   - `candidate_resource_type TEXT NOT NULL`, `candidate_resource_id TEXT NOT NULL`
   - `factor_version TEXT NOT NULL`, `factor_name TEXT NOT NULL`, `factor_value TEXT NOT NULL`
   - `source_fingerprint TEXT NOT NULL`, `computed_at TEXT NOT NULL`
   - primary key over candidate, version, and factor name
   - values are derived diagnostics, not verification or authorization

All proposed tables are **derived**. Exact names, enum vocabularies, constraints, and whether calibration factors need persistence are open approval items. Foreign keys must be logical/derived references that cannot make an invalid or deleted canonical source disappear from history. Indexes must support scope, resource type, relation type, validity, and deterministic ordering without exposing unauthorized aggregate counts.

### Migration/rebuild behavior required if v9 is approved

- v8 remains readable and canonical JSONL remains valid.
- `v8 -> v9` is transactional and idempotent.
- Fresh v9 initialization creates only derived structures.
- Existing canonical events/project operations are replayed deterministically.
- Derived v9 data can be deleted and rebuilt to the same canonical fingerprint.
- Rollback drops/recreates only derived v9 structures; it never deletes JSONL/artifacts or changes M0–M7 canonical semantics.
- Recovery from an interrupted rebuild leaves the prior published index version usable or fails closed; no partial version is published.
- Migration acceptance must cover v8→v9, fresh v9, idempotence, rebuild, rollback/recovery, and old-data validity.

### Vector/embedding impact

**VECTOR/EMBEDDING IMPACT: NONE.** The master specification lists local vector alternatives, but M8’s graph/temporal/calibration scope does not require embeddings or a vector database. Dense/vector retrieval remains deferred unless separately approved.

---

## 7. Graph contract

### Nodes

The initial graph node set is deliberately small:

- existing M2 event/trace resources;
- M4 requirements, decisions, project-state records, verifications, and project artifacts;
- explicitly created typed entities and their mentions, only after deterministic identity/mention contracts are approved;
- project/profile/knowledge-space scope identifiers only as authorization metadata, not as content-bearing nodes.

Do not make every session, task, research source, profile, or arbitrary object a node by default. A resource becomes traversable only when it has a stable resource type/id, provenance, scope metadata, lifecycle, and independently authorizable read path.

### Edges

Existing explicit relation classes are `child_of`, `derived_from`, and `supersedes` in `zm_relations`; M4 also has explicit project-domain links and supersession fields. M8 may expose these without inventing new semantics.

The initial proposed closed M8 relation vocabulary is:

- `supports`
- `contradicts`
- `verifies`
- `supersedes`
- `derived_from`
- `references`
- `related_to`
- `belongs_to_project`
- `belongs_to_profile`
- `belongs_to_knowledge_space`
- `artifact_of`
- `source_of`
- `decision_for`
- `requirement_for`

Only relation classes with an explicit source record or approved deterministic projection are materialized. `related_to` and entity links must not be inferred merely from co-occurrence, centrality, string similarity, or recency. Unsupported relation types fail closed.

### Edge provenance

Every exposed edge must carry:

- stable edge identity and content hash;
- source event/trace or explicit M4 operation ID;
- source schema/index version;
- relation type and typed endpoints;
- scope metadata (`profile_id`, `project_id`, `knowledge_space_id`, including explicit nulls);
- creation/validity metadata where present;
- lifecycle and source verification metadata where applicable.

An edge without sufficient provenance is not eligible for graph retrieval. Edges are rebuildable from canonical JSONL, M4 operation records, and approved structured source fields.

### Authorization-first traversal

The required order is:

```text
request and explicit scope
 -> M5 authorization for the requested resource type/scope
 -> authorized seed lookup
 -> enumerate only authorized outgoing/incoming edge candidates
 -> independently authorize each edge and target resource
 -> apply lifecycle/sensitivity/temporal eligibility
 -> bounded deterministic traversal
```

The forbidden order is global graph load, traversal, then post-filtering. A linked node never inherits authorization from its source node. Relation rows, entity rows, artifacts, verifications, source events, and project records are independently checked through the same M5 policy boundary, with `resource_type` preserved on every request.

### Bounds and cycles

Initial defaults require approval but must be fixed and enforced, not caller-unbounded:

- maximum traversal depth: 2 relation hops;
- maximum outgoing/incoming fan-out per authorized node: 20;
- maximum returned graph nodes: 40;
- maximum returned edges: 80;
- maximum graph expansion attempts per request: 1 bounded expansion;
- maximum historical versions per resource for an as-of response: 20.

The M7 EvidenceSet budget is independent and stricter at the final boundary. Cycles use a visited key `(resource_type, resource_id)` and are represented once; traversal stops at visited nodes and emits only a sanitized bounded diagnostic, never a recursive error or raw graph detail. Oversized, cyclic, malformed, or contradictory metadata fails closed for the affected branch.

### Graph retrieval surface

M8 first adds an internal read-only graph service/adapter over M3/M4/M5. It may extend an existing M6-compatible read surface only if a narrow read-only contract is approved. It must not add a write tool, GrantAdmin operation, or direct injection route. Automatic M7 consumption is a later integration increment, after the graph contract and security acceptance pass.

---

## 8. Temporal contract

### Time dimensions

M8 uses existing dimensions with explicit precedence and no redundant clocks:

- `created_at`: source/event creation time where stored;
- `observed_at`: capture/observation time for M2 events;
- `effective_at`: M4 decision/project-state effective time where stored;
- `valid_from` / `valid_until`: validity interval where present in canonical/projection data;
- `superseded_at`: only if explicitly represented by an approved source/index, never inferred;
- `ingested_at`: storage projection time, diagnostic only and never real-world validity.

M8 must normalize accepted timestamps to timezone-aware UTC for comparison while preserving the original canonical value/provenance. Missing, malformed, ambiguous, or timezone-naive values are not silently repaired; malformed temporal records are excluded from temporal eligibility with a sanitized reason.

### Transaction time vs valid time

**Required model: both, but narrowly.** Transaction/history time is represented by canonical append order/sequence and capture/ingestion provenance; valid time is represented only by existing explicit validity/effective fields. This is not a full unrestricted bitemporal database. M8 must answer as-of/history queries only where the required dimension is present, and must return `insufficient_evidence` rather than synthesize it.

### Current vs historical

- **Current:** resource is within requested scope, not deleted, lifecycle is eligible for current use, and explicit supersession/current-state rules identify it as current. M4 active selection remains stored lifecycle-based, never newest timestamp.
- **Historical/as-of:** resource/version was recorded and valid at the requested instant according to explicit fields and canonical history. It remains labeled historical; it cannot be presented as fresh external truth.
- **History:** return bounded ordered versions/traces with provenance and lifecycle, retaining superseded/conflicted records rather than flattening them.

### Supersession and conflict

M8 reads and composes existing explicit supersession chains; it does not create a competing current-state system, flatten chains, or infer supersession from time. A newer conflicting claim is not correct merely because it is newer. Verification/lifecycle/explicit resolution policy outrank timestamp. Unresolved conflict returns a conflict set; it is never silently selected.

### Supported temporal query contracts

The first approved temporal surface should be limited to:

- current eligible state/resource;
- state/resource as of an explicit timestamp where valid/effective data exists;
- bounded history of a decision/state/requirement/event;
- explicit supersession chain;
- bounded changes between `T1` and `T2` for records with comparable normalized timestamps.

No unbounded full-history retrieval or automatic historical context injection is allowed.

---

## 9. Calibration contract

### What is calibrated

M8 calibrates **candidate evidence quality for deterministic ordering**, using only evidence visible after authorization. It may combine:

- base lexical/structured retrieval match;
- explicit profile/memory-scope priority already defined by policy;
- verification strength from the existing closed verification vocabulary;
- source/provenance completeness;
- temporal validity/currentness relative to the request;
- lifecycle eligibility;
- explicit conflict penalty;
- bounded relation relevance (requested relation/path only, not centrality).

### What is not calibrated into truth

The following are never authority:

- graph centrality, degree, path count, or repetition;
- recency alone;
- frequency alone;
- number of links;
- assistant self-report;
- a numeric score;
- hidden/unauthorized evidence;
- an embedding or semantic similarity result (none is in M8 scope);
- score magnitude as a replacement for verification or lifecycle.

### Output and explainability

The output is a bounded score in a documented range plus a deterministic decomposition:

```text
CalibrationResult {
  candidate_id,
  score,
  factor_values: {factor_name: bounded_value},
  reason_codes: [stable_code, ...],
  verification_status,
  lifecycle_status,
  temporal_basis,
  conflict_basis,
  calibration_version
}
```

A score is computed only after M5 authorization and eligibility. Hard exclusions (unauthorized, secret, deleted, malformed provenance, invalid scope) occur before scoring and cannot be softened by a high score. The exact weights and threshold are an open approval item; they must be explicit, versioned, bounded, deterministic, and tested against the existing M7 fixtures rather than tuned by an LLM.

**Q14:** Can unauthorized evidence influence an observable score? **NO.** Unauthorized candidates are excluded before scoring, and hidden conflicts or hidden counts must not affect any visible score, `omitted_count`, conflict count, or explanation.

---

## 10. Interaction and precedence

For a candidate, the precedence is:

1. `ZERO_MEM_ENABLED` master switch.
2. M5 authorization and resource-type isolation.
3. M7/M3/M4 scope, sensitivity, lifecycle, deletion, provenance, and malformed-data gates.
4. Explicit verification and conflict semantics.
5. Temporal validity/current-vs-historical classification.
6. Deterministic graph relation/path relevance.
7. Calibration score for ordering among otherwise eligible candidates.
8. M7 EvidenceSet eligibility and fixed budget.
9. M7 hardening and controlled injection as DATA only.

Graph centrality never creates truth. Recency never creates truth. Calibration never creates verification or authorization. A graph neighbor never enters context directly.

---

## 11. M5/M6/M7 integration

- M5 remains the only authorization authority. No graph policy, score, profile inference, or relation inheritance is permitted.
- M6 tools remain unchanged by default: **M8 requires no changes to the 10 M6 read tools (NONE)**. If a narrow graph/as-of read is later exposed, it must be a new explicit read-only contract routed through M5, not a hidden behavior change in an existing tool.
- M7 router may identify graph/temporal need, but unsupported or insufficient paths remain explicit rather than faked.
- M8 candidate generation and expansion are internal read-only stages. Each candidate and linked resource is separately authorized before entering an `EvidenceSet`.
- M7 remains the only prompt-boundary adapter. M8 has no Hermes core changes and no direct `pre_llm_call` injection path.
- The M7 budget remains exactly max 5 primary, max 3 supporting, max 8 total. Graph expansion may increase internal candidates only; it may not multiply the EvidenceSet or silently alter `omitted_count` based on hidden unauthorized rows.
- Existing `no_memory`, `external_current`, master OFF, and failure-isolation behavior remain unchanged.

### EvidenceSet path

```text
M8 authorized candidate/neighbor
 -> independent M5 authorization
 -> lifecycle/sensitivity/provenance/temporal/conflict eligibility
 -> deterministic calibration/order
 -> M7 EvidenceSet primary/supporting classification
 -> 5+3+8 budget
 -> M7 hardening/injection
```

Forbidden: `graph neighbor -> prompt`, `score -> authorization`, `recency -> verified_state`, or `hidden conflict -> visible score change`.

---

## 12. Security threat model

M8 must test and prevent:

- **Existence leaks:** do not expose protected node/edge counts, degree, stop reason, conflict count, history length, or omitted count. Responses use fixed/sanitized bounded status and only authorized totals where already permitted.
- **Traversal bypass:** authorize seed, edge, and target independently; never retrieve global graph first.
- **Cross-profile leakage:** explicit profile scope and M5 grants remain required; graph edges do not bridge profiles implicitly.
- **Cross-project leakage:** project relation does not grant project access; target project is authorized independently.
- **Knowledge-space leakage:** space membership is a scope predicate, not inherited authority.
- **Sensitive-node leakage:** sensitivity ceiling applies to nodes, edges, artifacts, mentions, and history.
- **Temporal leakage:** unauthorized historical versions cannot be discovered by timestamps, chain length, counts, or as-of errors.
- **Calibration leakage:** only authorized evidence contributes to visible score/decomposition; hidden conflict cannot be inferred.
- **Cycles/graph bombs:** fixed depth/fan-out/node/edge/CPU/memory bounds; visited set; fail closed on overflow.
- **Malformed relation metadata:** closed enums, typed IDs, provenance checks, scope validation, and fail-closed behavior; never fallback to raw unrestricted graph reads.
- **Prompt injection:** stored graph labels/text remain DATA and pass the existing M7 escaping/delimiting hardening.
- **Canonical corruption:** derived rebuild never edits JSONL/artifacts; partial index versions are not published.

Resource-type isolation is permanent: authorization to an event does not authorize a linked artifact, verification, decision, entity, or history row.

---

## 13. Zero-LLM and zero-network proof strategy

Routine M8 operations must add exactly:

- LLM calls: **0**
- external network calls: **0**

Evidence plan for implementation:

- AST/import scan of new M8 modules rejects LLM/HTTP/remote-client imports and direct Hermes final-model calls.
- Runtime counters/monkeypatch guards prove graph build, traversal, temporal filtering, calibration, rebuild, and augmented retrieval do not call an LLM or external network.
- Static scan covers `openai`, `llm`, `httpx`, `requests`, `aiohttp`, `socket`, `urllib`, and remote graph/vector clients with allowlisted false-positive review.
- Tests run with network disabled where practical and verify only local SQLite/JSONL/artifact paths are used.
- Final M8 evidence records sanitized commands, exit codes, and exact module scope; the normal project venv and clean isolated HOME are authoritative, not an `execute_code -> subprocess` diagnostic harness.

---

## 14. Rebuild strategy

The rebuild contract is:

```text
delete only derived M8 rows
 -> replay canonical JSONL and approved M4/project operation sources
 -> rebuild entities/mentions, explicit graph edges, temporal index
 -> publish deterministic index version
 -> calculate request-time calibration from authorized candidates
```

Inputs must include source schema/version, canonical event IDs/hashes, M4 operation provenance, artifact metadata, and explicit scope/lifecycle/verification fields. Rebuild must be deterministic across repeated runs, preserve conflicts/supersession, reject malformed source records without broadening access, and produce a canonical source fingerprint. A rebuild must never use Obsidian, generated summaries, hidden assistant claims, or current wall-clock time as semantic input.

---

## 15. Performance strategy

M7’s local target remains p95 < 2 seconds. M8 must measure with deterministic local fixtures and report median, p95, sample count, fixture size, schema/index version, and environment:

- authorized direct graph lookup;
- bounded traversal at depth 1 and depth 2;
- temporal current/as-of/history filtering;
- calibration of an authorized candidate set;
- complete M8-augmented retrieval through M5 and M7 EvidenceSet.

The normal request path must avoid O(N) full-history scans through derived indexes. Bounds must make worst-case traversal finite. `no_memory` must remain zero-retrieval. Performance acceptance should require the complete augmented path to remain within the established M7 p95 target on the representative fixture; any tighter component target must be derived from measured baseline, not invented microbenchmarks. Final external model latency is excluded.

---

## 16. Test and regression strategy

### Focused graph tests

- deterministic node/edge IDs and hashes;
- explicit edge provenance and duplicate semantics;
- missing/deleted/superseded targets;
- bounded depth/fan-out/node/edge behavior;
- cycles and visited-node handling;
- malformed relation metadata and unknown relation fail closed;
- linked resource independent authorization;
- cross-profile/project/knowledge-space denial;
- resource-type isolation;
- graph rebuild determinism;
- no existence leak through counts, stop reasons, degree, or omitted count.

### Focused temporal tests

- current state and explicit as-of state;
- bounded history and supersession chains;
- changes between two timestamps;
- equal timestamp deterministic tie ordering;
- newer conflicting claim does not win;
- archived/deleted semantics;
- timezone normalization and malformed timestamp failure;
- missing valid-time field returns bounded insufficiency, not invented time;
- no unbounded history context.

### Focused calibration tests

- deterministic input/output and bounded score;
- exact score decomposition/reason codes;
- verification policy outranks assistant claim;
- recency, repetition, centrality, and link count cannot override verification;
- unauthorized evidence cannot affect score or explanation;
- conflict/insufficiency behavior;
- score never changes authorization/lifecycle/verification;
- calibration version/fingerprint is reproducible.

### Integration tests

- M8 candidate enters M7 EvidenceSet only after M5 authorization;
- primary/supporting budgets remain 5/3 and total remains 8;
- no graph-to-prompt bypass;
- stored graph text remains DATA under M7 hardening;
- master OFF, `no_memory`, and `external_current` remain unchanged;
- M6 tools remain unaffected unless explicitly extended;
- M7 prompt-injection, grant, resource-type, conflict, and failure-isolation tests remain green;
- zero-LLM/zero-network runtime evidence.

### Required regressions

Every implemented increment must run the focused tests plus relevant M1–M7 regressions. Final M8 must preserve:

- M2 canonical JSONL/rebuild/migration/read-only semantics;
- M3 retrieval order, cursor, FTS, relation, lifecycle, and deleted exclusion;
- M4 project consistency, explicit supersession, visible conflicts, verification, artifact safety, and rebuild;
- M5 authorization and grant freshness/revocation;
- M6.6 resource-type isolation and linked-resource independent authorization;
- M7 master OFF/no-memory, router, EvidenceSet 5+3, hardening, prompt-injection resistance, zero LLM/network, and `test_no_real_hermes_home_writes`.

Final canonical acceptance must use the normal project venv under clean isolated HOME with no deselection, no new skip/xfail, and 0 failures.

---

## 17. Smallest safe increment breakdown

The proposed sequence is six increments. Each is independently reviewable and stops before the next dependency.

### M8.1 — Contract freeze and derived-index foundation

- **Objective:** freeze typed M8 resource/relation/time/calibration contracts and a versioned derived-index boundary without changing runtime retrieval.
- **Scope:** closed vocabularies, stable IDs/hashes, provenance envelope, bounds/config defaults, index-version contract, read-only interfaces, v9 migration design implementation only if separately approved.
- **Likely files:** new `src/graph/`, `src/temporal/`, `src/calibration/`, `src/storage/migrations/migrate_9.py`, shared model/registry files, focused unit tests, runbook, acceptance artifact.
- **Schema:** v9 proposed derived tables; no schema change until approval of this plan and the exact migration review.
- **API:** internal contracts only; no M6 tool changes and no M7 behavior change.
- **Authorization:** define mandatory authorization input and resource type; no traversal yet.
- **Performance:** contract overhead only; no full rebuild benchmark.
- **Non-goals:** entity extraction, traversal, temporal semantics, scoring, injection, Obsidian, vectors.
- **Focused tests:** enum closure, IDs/hashes, provenance, bounds, malformed-input fail closed, zero LLM/network, migration contract if approved.
- **Regressions:** M2 migration/rebuild and M3–M7 contract/security subsets.
- **Acceptance:** exact contracts documented, no canonical mutation, schema decision bound, derived classification proven, clean isolated acceptance.
- **Stop/deviation:** any need to alter canonical JSONL, M5 policy, Hermes core, or M7 budget.
- **Commit boundary:** one contract/foundation implementation commit; separate evidence/state commit only after acceptance.

### M8.2 — Explicit graph projection and deterministic rebuild

- **Objective:** project only explicit existing relations and approved typed entity/mention inputs into the derived graph.
- **Scope:** node/edge materialization, provenance, duplicate semantics, source validation, deterministic rebuild/publish.
- **Likely files:** graph projector/rebuild modules, storage migration/rebuild integration, runbook, focused graph tests.
- **Schema:** v9 derived graph/entity tables only.
- **API:** internal read-only projection/rebuild API; no public M6 extension yet.
- **Authorization:** projection stores scope metadata; no authorization inheritance.
- **Performance:** rebuild and index creation measured; request traversal deferred.
- **Non-goals:** inferred NLP entity linker, LLM extraction, vector search, Obsidian.
- **Acceptance:** delete-derived/replay-canonical produces equivalent fingerprint; malformed/secret/scope-invalid inputs fail closed; conflicts/supersession preserved.
- **Stop/deviation:** any request for opaque entity extraction or semantic write-back.
- **Commit boundary:** graph projection commit, then evidence commit.

### M8.3 — Authorization-first bounded graph reads

- **Objective:** expose bounded direct and depth-2 graph expansion through M5 authorization-first checks.
- **Scope:** seed lookup, per-edge/per-target authorization, resource-type preservation, cycle/bomb limits, sanitized outputs.
- **Likely files:** graph read service, M5 adapter integration if needed, typed result models, focused security tests.
- **Schema:** no additional schema beyond approved v9.
- **API:** internal read-only contract; a new M6 read tool is non-goal unless separately approved.
- **Authorization:** M5 remains sole authority; no post-filter global traversal.
- **Performance:** direct/depth-2 lookup and bounded traversal median/p95.
- **Non-goals:** automatic injection, score-based authorization, unbounded expansion.
- **Acceptance:** all isolation/existence-leak/cycle/bound tests pass; M7 unchanged.
- **Stop/deviation:** any alternate graph ACL, GrantAdmin access, or budget increase.
- **Commit boundary:** graph read/security commit, then evidence commit.

### M8.4 — Temporal projection and bounded as-of/history reads

- **Objective:** compose existing event/M4 temporal fields and explicit supersession into deterministic current/as-of/history contracts.
- **Scope:** UTC normalization, valid/transaction time distinction, current/historical labeling, bounded history, conflict/time precedence.
- **Likely files:** temporal index/service, M3/M4 read composition, runbook, focused temporal tests.
- **Schema:** approved v9 temporal derived table; no new canonical clocks.
- **API:** internal read-only temporal contract; no silent change to existing M6 tools.
- **Authorization:** authorize each historical version/resource independently.
- **Performance:** temporal lookup/filter and bounded history p50/p95.
- **Non-goals:** timestamp-based truth, full bitemporal query language, automatic state mutation.
- **Acceptance:** all temporal edge cases and M2–M7 current-state regressions pass; malformed time fails closed.
- **Stop/deviation:** any request to infer missing valid time or replace M4 active-state semantics.
- **Commit boundary:** temporal implementation commit, then evidence commit.

### M8.5 — Deterministic calibration and retrieval metadata integration

- **Objective:** add explainable bounded candidate scoring after authorization/eligibility without changing truth or access policy.
- **Scope:** factor registry, versioned formula, reason codes, conflict/temporal factors, deterministic ordering metadata.
- **Likely files:** `src/calibration/`, retrieval composition modules, typed envelopes/models, focused calibration tests.
- **Schema:** request-time preferred; persist only approved derived factors/index metadata.
- **API:** internal candidate result metadata; existing M3 ordering must remain stable unless an explicit M8 retrieval contract opts in.
- **Authorization:** score only authorized candidates; hidden evidence never contributes.
- **Performance:** calibration and combined augmented retrieval benchmark.
- **Non-goals:** LLM judge/reranker, embedding, automatic promotion, authorization changes.
- **Acceptance:** decomposition reproducible; hard precedence enforced; unauthorized evidence cannot alter visible result; M3/M7 default behavior remains compatible.
- **Stop/deviation:** opaque score, score-driven access/truth, or external service requirement.
- **Commit boundary:** calibration implementation commit, then evidence commit.

### M8.6 — M7 EvidenceSet integration, hardening, performance, final acceptance

- **Objective:** optionally consume approved M8 candidates through the existing M7 path and close M8 with security/performance/rebuild evidence.
- **Scope:** router capability flag/metadata only where needed, M5→eligibility→EvidenceSet adapter, fixed 5+3+8 budget, M7 hardening, benchmarks, acceptance docs/state binding.
- **Likely files:** narrow M7 integration modules, M8 integration tests/benchmarks, `acceptance-m8.6.md`, `acceptance-m8.md`, runbook/state artifacts according to established convention.
- **Schema:** v9 only if approved and already implemented; no further schema changes.
- **API:** no Hermes core changes; no M6 tool changes unless separately approved.
- **Authorization:** M5 first for every candidate and linked resource.
- **Performance:** complete M8-augmented path p95 remains within <2s MVP target on deterministic fixture.
- **Non-goals:** M9 projection, M10 corpus, embeddings, write-back.
- **Acceptance:** focused, security, benchmark, zero-LLM/network, full M1–M7 regressions, clean isolated HOME, 0 failed, final-HEAD canonical rerun.
- **Stop/deviation:** any evidence-budget expansion or direct prompt bypass.
- **Commit boundary:** integration implementation commit; final acceptance/evidence/state-binding commit; final canonical run on final HEAD.

M8.1 is intentionally not a giant graph+temporal+calibration+retrieval increment.

---

## 18. Acceptance artifact and commit strategy

Planning artifact created now: `plan-m8.md`.

For implementation, use repository-consistent artifacts such as:

- `acceptance-m8.1.md` through `acceptance-m8.6.md` as applicable;
- final `acceptance-m8.md`;
- a runbook for v9 migration/rebuild/rollback if v9 is approved;
- minimal `implementation-plan.json`/`project-state.yaml` updates only after focused and canonical evidence exists, unless repository convention requires a planning marker now.

Each increment must separate:

1. implementation/test commit;
2. evidence/state-binding commit;
3. final canonical evidence bound to the exact final HEAD.

No commit may claim an increment VERIFIED before its acceptance criteria pass. The planning commit must contain only `plan-m8.md`.

---

## 19. Final M8 acceptance criteria

M8 is VERIFIED only when all of the following have executable evidence:

- approved schema decision and, if applicable, v8→v9/fresh/idempotent/rebuild/rollback acceptance;
- canonical JSONL/artifacts unchanged as source-of-record and derived rebuild fingerprint stable;
- explicit graph nodes/edges with provenance, closed relation vocabulary, independent authorization, resource-type isolation, bounded traversal, cycle handling, and no existence leaks;
- deterministic current/as-of/history semantics using explicit time fields, bounded historical output, existing supersession, and visible conflicts;
- deterministic explainable calibration with versioned factors/reason codes; no score authority over access, truth, or verification;
- M5 authorization preserved as sole access authority;
- M6 ten read tools unchanged unless an explicitly approved read-only extension is documented;
- M7 master switch, router, EvidenceSet 5+3+8 budget, hardening, injection boundary, and no-memory behavior preserved;
- no direct graph-neighbor prompt path;
- routine memory-operation LLM calls = 0;
- routine external network calls = 0;
- deterministic performance evidence reports median/p95/sample count for all M8 stages and complete augmented retrieval, with p95 <2s MVP target on the approved fixture;
- focused unit/failure/security/rebuild/benchmark tests pass;
- full M1–M7 regressions pass;
- final canonical suite under clean isolated HOME, normal project venv, no deselection, no new skip/xfail, and 0 failures; `tests/unit/test_m2_ingest.py::test_no_real_hermes_home_writes` remains intact;
- final evidence/state-binding commit is followed by authoritative canonical rerun on final HEAD;
- working tree is clean.

This is implementation verification, not a requirement of this planning-only turn.

---

## 20. M9 and M10 boundaries

### M9 — Obsidian Projection

Deferred entirely: Vault generation, Markdown/YAML projection, curated note editing, review/change queue, projection sync, operational pages, and Obsidian acceptance. M8 may expose stable provenance/index interfaces that M9 can consume, but M8 does not write a Vault or treat Obsidian as storage.

### M10 — Corpus Expansion / large research-library integration

Deferred entirely: 600-PDF ingestion, bulk parsing/chunking, page/section extraction at corpus scale, corpus embeddings/vector DB, batch QA, and operational corpus expansion. M8 does not add vectors or remote services.

---

## 21. Critical design questions — explicit answers

1. **Schema v8?** PARTIAL only; full M8 proposes derived v9.
2. **Why not v8?** No typed entity/mention model, general validity projection, graph-version provenance, or safe calibration decomposition; overloading fields would be ambiguous and unsafe.
3. **Graph relations authority?** Existing explicit relations/approved structured links are canonical inputs; graph rows are derived projections. Derived edges never create facts.
4. **Completely rebuildable?** Yes, from canonical JSONL, approved M4/project operation records, artifact metadata, and explicit source links; not from Obsidian or scores.
5. **Authorization-first?** M5 authorizes seed, edge, and target independently before traversal/output.
6. **Existence leaks?** Fixed bounds, sanitized outcomes, no unauthorized counts/degree/chain/conflict/omitted details, and no global pre-traversal.
7. **Temporal semantics required?** Current, bounded as-of, bounded history, explicit supersession, and bounded change windows where source time exists.
8. **Valid vs transaction time?** Both, narrowly: explicit valid/effective fields plus canonical append/observation history; not unrestricted bitemporal inference.
9. **Interaction with supersession/verified_state?** Reuse M4 explicit chains and stored lifecycle/verification; timestamps do not select winners.
10. **What is calibrated?** Authorized candidate evidence quality/order, not truth or access.
11. **Factors?** Retrieval match, policy priority, verification, provenance, temporal validity, lifecycle/conflict, and bounded requested relation relevance.
12. **Forbidden truth factors?** Recency, repetition, centrality, degree, link count, score, assistant claim, hidden evidence, or similarity alone.
13. **Explanation/audit?** Versioned bounded factor values, reason codes, provenance, temporal/conflict basis, and deterministic fingerprint.
14. **Unauthorized evidence score influence?** NO.
15. **EvidenceSet integration?** M5 authorization → eligibility → calibration/order → M7 EvidenceSet; budget remains 5 primary + 3 supporting + 8 total.
16. **M6 read-tool changes?** NONE by default; any extension requires separate approval and remains READ-only/M5-routed.
17. **Hermes core changes?** NONE.
18. **Routine LLM calls?** NO; 0.
19. **External network calls?** NO; 0.
20. **Deferred?** M9 Obsidian projection and M10 corpus/large research-library integration, including embeddings/vector scope.

---

## 22. Open design questions requiring explicit approval

- **M8-OQ-1:** Approve derived schema v9 versus a narrower v8-preserving subset. Full plan recommendation: approve v9 derived structures.
- **M8-OQ-2:** Approve the closed entity-type vocabulary and whether entity mentions may be created only from explicit structured input (recommended) rather than deterministic local text rules.
- **M8-OQ-3:** Approve the relation vocabulary and which existing M4 links are projected as which edge classes; no semantic synonym expansion by default.
- **M8-OQ-4:** Approve traversal defaults (depth 2, fan-out 20, nodes 40, edges 80) and whether a caller may request lower bounds only.
- **M8-OQ-5:** Approve the narrow temporal contract and both-time model; no invented time and no unrestricted bitemporal query language.
- **M8-OQ-6:** Approve whether calibration remains request-time only (recommended) or whether derived factor rows are persisted in v9.
- **M8-OQ-7:** Approve explicit calibration factors/weights and score range before M8.5; no opaque or LLM-tuned formula.
- **M8-OQ-8:** Approve whether M8.6 changes M7 routing metadata only or exposes a new explicit M6-compatible read tool; recommendation: internal integration first, no M6 tool changes.
- **M8-OQ-9:** Resolve the authoritative-source path discrepancy (`IDEA.md` Markdown reference versus present DOCX) if a different specification is intended.

No implementation should begin while a material question changes schema, authority, authorization, time semantics, score semantics, or the EvidenceSet boundary.

---

## 23. Plan-deviation conditions — STOP and request approval

Stop implementation and report a plan deviation if any of the following occurs:

- Hermes core modification becomes necessary;
- GrantAdmin or any new authority-bearing control plane is needed;
- automatic write-back, fact confirmation, conflict resolution, lifecycle promotion, project-state mutation, or grant mutation is proposed;
- an external network, remote graph/vector/reranker/moderation/temporal service is required;
- a routine LLM call is required for extraction, linking, temporal reasoning, calibration, conflict resolution, classification, or reranking;
- schema change exceeds the approved v9 design or canonical JSONL must change;
- M5 authorization or M6.6 `resource_type` isolation must change;
- M7 EvidenceSet budget or hardening boundary must change;
- graph traversal cannot remain authorization-first and bounded;
- hidden protected resources affect visible scores, counts, conflict indicators, or omission metadata;
- M9/M10 functionality becomes necessary;
- Neo4j, Redis, a message queue, distributed storage, or another external graph system becomes necessary;
- required source material materially conflicts with this plan;
- canonical acceptance cannot run in the normal project venv with clean isolated HOME and the prescribed real-home safety test.

In any such case the correct result is `M8 PLAN DEVIATION — <exact change requiring approval>`, not silent scope expansion.

---

## 24. Planning-only completion boundary

This artifact is the only intended repository change for this turn. M8 implementation is **NOT STARTED**. No product code, tests, migration, schema, M8.1, M9, or M10 work is authorized by creation of this plan.

**Next action:** await explicit approval of this M8 plan and the open design questions above.

**DO NOT BEGIN M8.1.**
