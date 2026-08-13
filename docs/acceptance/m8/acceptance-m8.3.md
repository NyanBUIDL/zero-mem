# Acceptance — M8.3: Authorization-First Bounded Graph Reads

**Status: STRICT VERIFIED**

Milestone: M8.3 (Graph / Temporal / Calibration — increment 3 of 6)
Schema version: **9** (unchanged; no v10 created)
M8 overall: **IN PROGRESS**

---

## 1. Starting state (reconciled)

| Item | Value |
|---|---|
| Expected starting HEAD | `068e55847c48ec2a7ef330ee099f5f47f34e97ad` |
| Implementation tested commit | `eb91d60b4ee94d436d6a33eb8545c1a17a867745` |
| Working tree at start | clean ✅ |
| Branch | `master` |
| Schema at start | v9 |
| M0–M8.2 | VERIFIED |
| M8.1 | STRICT VERIFIED |
| M8.2 | STRICT VERIFIED |
| M8.3 at start | NOT STARTED |

Reconciliation performed with `git rev-parse HEAD`, `git status --short
--branch`, `git diff --check`. No mismatch; no reconciliation stop triggered.

---

## 2. Files changed

### Added — implementation (2 modules, `src/m8/`)

| File | Purpose |
|---|---|
| `src/m8/graph_bounds.py` | Frozen traversal bounds (depth 2, fan-out 20, nodes 40, edges 80); `GraphBoundsError` fails closed on any widening attempt. |
| `src/m8/graph_access.py` | `GraphAccessService` — the authorization-first bounded graph read layer over the deterministic M8.2 projection. |

### Added — tests (4 files, `tests/unit/`)

| File | Tests |
|---|---|
| `tests/unit/test_m8_3_helpers.py` | v9 fixture: M4 resources across two profiles/projects, M5 persistent grants, and a v9 derived graph with an explicit hidden-middle path. |
| `tests/unit/test_m8_3_authorization_first.py` | 28 focused tests: auth-before-traversal, denied-seed info-hiding, hidden middle node, unauthorized-edge degree/count, M6.6 resource_type isolation, bypass resistance, scope isolation, revocation, traversal bounds, determinism, existence-leak safety, read-only proof, zero LLM/network. |
| `tests/unit/test_m8_3_static.py` | 5 static tests: forbidden imports (no write service / grant admin / LLM / network), no hardcoded HOME, M5-only dependency contract, no tool surface. |
| `tests/unit/test_m8_3_smoke.py` | Wiring smoke (authorized seed returns subgraph; denied seed returns no graph info). |

### Modified — objectively required

| File | Change | Why |
|---|---|---|
| `tests/unit/test_m8_1_security.py` | `test_access_import_is_contract_only` now exempts `graph_access.py`. | M8.3 is the sanctioned increment that CONSUMES the M5 `AuthorizedReadService` as its sole authorization authority; the M8.1 "no M5 import" rule still holds for every other M8 module (M8.1 freeze must not import policy surfaces). |
| `tests/baseline/test_project_artifacts.py` | Baseline-gate assertions updated to the real post-M8.3 state (`m8_increment_3_status == "verified"`, `m8_next_incomplete_increment == "M8.4"`). | The gate encoded a stale M8.2-time M8.3=not_started assumption; it is corrected to validate current fact, not a wildcard. |

No other file in the repository was modified. Hermes core: **untouched**. M6
tool surface: **unchanged**. M4/M5/M7: **unchanged**.

---

## 3. Authorization-first flow (mandatory order)

```
GraphReadRequest
      │
      ▼  normalize (resource_type / scope carried verbatim; M6.6 preserved)
      ▼  M5 authorize SEED  (AuthorizedReadService — sole authority)
      │       └─ denied  →  empty result, no graph info, no counts
      ▼  bounded expansion (depth 2, fan-out 20, nodes 40, edges 80)
      │       for each candidate edge:
      ▼  M5 authorize CANDIDATE  using the candidate's OWN scope
      │       (profile_id / project_id taken from the edge row, never the seed's)
      │       └─ denied  →  node AND edge withheld; no degree/count change
      ▼  authorized-candidate-only edge emission
      ▼  deterministic ordering (nodes by type+id; edges by relation+edge_id)
      ▼  GraphReadResult (nodes, edges, provenance, bound_codes, authorized flag)
```

Authorization occurs **before** any graph expansion. A denied node (seed or
candidate) never contributes its existence, node, edge, degree, or count to the
result. No access decision is derived from graph topology (degree, connected
component, shared edge, relation type).

---

## 4. Bounded traversal values (frozen, fail-closed)

| Bound | Value | Behaviour on attempt to widen |
|---|---|---|
| `max_depth` | 2 | `GraphBoundsError` at construction |
| `max_fan_out` | 20 | `GraphBoundsError` at construction |
| `max_nodes` | 40 | `GraphBoundsError` at construction |
| `max_edges` | 80 | `GraphBoundsError` at construction |

Defaults come from `plan-m8.md` §7 "Bounds and cycles"; they are module-level
constants and not negotiable by the caller. A request may only *tighten* an
already-safe bound (e.g. depth 0/1, fewer nodes/edges); any value above the
ceiling raises `GraphBoundsError` and the read fails closed rather than
returning an unbounded result.

Cycles, self-loops, and dense graphs terminate: visited-node and visited-edge
sets prevent re-expansion and re-emission; only authorized edges are emitted,
including a second edge to an already-visited node (no death-by-merge dropping a
legitimate authorized edge).

---

## 5. Determinism

- Results are ordered, not set-like: nodes sorted by
  `(resource_type, resource_id)`, edges sorted by `(relation_type, edge_id)`.
- Deterministic across **different edge insertion order** (proven by building
  two independent v9 DBs seeded in different order and asserting identical
  node and edge sequences).
- No Python `hash()` / set-iteration in identity; no wall-clock in the result.
- Edge reads use a fixed `ORDER BY relation_type, edge_id`.

---

## 6. Hidden middle node / path protection

The fixture builds an explicit hidden path:

```
ART-A (PR1/P1, authorized)
   -[source_of]-> ART-A2 (PR1/P1, authorized)
   -[decision_for]-> DEC-B (PR2/P2, NOT authorized for PR1)
                       -[requirement_for]-> REQ-C (PR1/P1, authorized)
```

M8.3 must **not** reveal DEC-B, nor that ART-A and REQ-C are "connected" through
DEC-B, nor surface REQ-C via that path. Verified:

- DEC-B never appears as a node.
- No edge to/from DEC-B appears (the `e_ab` / `e_bc` edges are withheld).
- REQ-C is absent from the ART-A seed result (its only path is through DEC-B).

This is the core anti-leak guarantee: graph traversal does not discover a hidden
node and then authorize it; authorization gates every step.

---

## 7. Unauthorized node/edge exclusion

- A denied candidate contributes **neither** its node **nor** its connecting
  edge to the result.
- Therefore degree/count of an authorized node is computed only over authorized
  edges — an unauthorized edge cannot inflate or distort it.
- Authorization uses the candidate's own scope: a P1 seed cannot "pull in" a P2
  resource by checking it under the seed's P1 scope; the candidate is checked
  under its actual project (P2), where PR1 has no decision grant.

---

## 8. Scope and resource_type preservation

| Dimension | Preserved | Evidence |
|---|---|---|
| `profile_id` (same-profile vs cross-profile) | ✅ | `TestScopeIsolation` |
| `project_id` (same-project vs cross-project) | ✅ | `TestScopeIsolation` |
| `knowledge_space_id` | ✅ | request scope propagated to M5 `AccessRequest` |
| `resource_type` (M6.6) | ✅ | `TestM66ResourceTypeIsolation` |

**M6.6 permanent invariant preserved:** when PR1 holds only an
`artifact`-scoped grant on P1, a graph read starting at an authorized artifact
does **not** pull in decision/requirement neighbours — every candidate is
authorized under its own resource_type, and the artifact-only grant denies the
non-artifact types. The explicit `resource_type` is never dropped.

---

## 9. Revocation behavior

Removing a grant from canonical `zm_access_grants` immediately removes access:
a fresh service reading the changed grant state denies the previously-authorized
seed. No cached authorization survives revocation.

---

## 10. Cycle / self-loop / dense-graph behavior

- **Cycle** (`A↔B` among authorized nodes): terminates, no node duplicated, no
  count explosion.
- **Self-loop** (`A→A`): the node appears once; at most one edge emitted.
- **Dense fan-out** (30 authorized artifacts from one seed): fan-out cap (20)
  and total-node cap (40) enforced; result stays bounded with a `bound_*`
  code recorded.

---

## 11. Provenance visibility behavior

Provenance is populated only from the **authorized** seed row and only with
fields present in the underlying M4/M5 source (`profile_id`, `project_id`,
`trace_id`, `source_event_id`, `origin_jsonl`, `created_at`). Unauthorized
rows never contribute to `provenance`. Hidden rows contribute nothing. The
result carries `bound_codes` indicating which ceiling was hit (if any), so the
caller sees that the result was truncated by policy, never an existence leak.

---

## 12. Read-only behavior

The graph read opens the same read-only connection the M5 facade wraps
(`mode=ro` + `query_only`). An operational proof: running the same read three
times over a populated store leaves row counts in `zm_graph_edges`,
`zm_access_grants`, and `zm_project_artifacts` unchanged, and no open
transaction remains (`in_transaction is False`). No mutation of canonical,
derived, grant, or state data occurs.

---

## 13. Zero LLM / zero network

| Check | Result |
|---|---|
| LLM calls | **0** |
| External network calls | **0** |
| Banned imports (openai, anthropic, transformers, torch, requests, httpx, aiohttp, urllib, socket, grpc, boto3, faiss, chromadb, qdrant, pinecone, weaviate, neo4j, networkx, …) | none — AST-verified in `test_m8_3_static.py` |
| Network literals (`http://`, `https://`, `urlopen`, `.connect(`) | none |
| `subprocess` / `eval` / `exec` / `__import__` | none |
| Embeddings / vectors / cosine / kNN | none |
| Hardcoded HOME (`/home/`, `/Users/`, `expanduser`, `Path.home()`, `.hermes`) | none |

No Hermes core modification. No M6 tool registration. The service is internal
request-time infrastructure only; it does **not** add a new Hermes/M6 read tool
(verified statically — no `register_tool` / `mcp_tool` / `tool_name` symbol).

---

## 14. Preservation of prior milestones

| Milestone | Status |
|---|---|
| M2 canonical/rebuild | ✅ unchanged |
| M4 relations/conflicts/supersession | ✅ unchanged, semantics preserved |
| M5 scope/grants/authorization | ✅ unchanged; `AuthorizedReadService` remains sole authority and is *used*, not bypassed |
| M6.6 resource_type isolation | ✅ preserved; no M6 tool added or modified |
| M7 EvidenceSet / routing / injection | ✅ untouched |
| M8.1 contracts/schema/rebuild/security | ✅ preserved (M8.1 no-M5-import rule scoped to exempt the sanctioned M8.3 consumer) |
| M8.2 projection/rebuild | ✅ unchanged; M8.3 reads the v9 derived graph but alters nothing |

Schema remains **v9** (no `migrate_10.py`). No M8.4+ work begun.

---

## 15. Non-scope confirmation

Not implemented, and statically asserted absent: as-of and history queries /
latest-wins / temporal precedence (M8.4), calibration scoring and ranking
(M8.5), EvidenceSet integration and automatic injection (M8.6), Obsidian
projection (M9), corpus expansion (M10). No `migrate_10.py` exists.

---

## 16. Test evidence

All runs used the normal repository interpreter `.venv/bin/python3` under an
isolated `HOME` (`HOME="$(mktemp -d)"`). No symlink, wrapper, alternate
interpreter, `execute_code` subprocess, or scanner modification was used for
any authoritative run.

### Focused M8.3

```
.venv/bin/python3 -m pytest \
  tests/unit/test_m8_3_authorization_first.py \
  tests/unit/test_m8_3_static.py -q
33 passed in 0.18s
```

**0 failed** ✅

### Pre-binding canonical (under isolated HOME)

```
.venv/bin/python3 -m pytest tests/ -q
2156 passed, 3 skipped in 15.69s
```

**0 failed, no deselection, no new skip/xfail.** ✅
The 3 skips are the unchanged historical M2 FTS5 skips.

### Final-head canonical

Run on the exact evidence/state-binding commit (see §17) under a fresh isolated
HOME; recorded in the closure report.

---

## 17. Commits

| Role | Commit |
|---|---|
| Implementation / tested | `eb91d60b4ee94d436d6a33eb8545c1a17a867745` |
| Evidence / state binding | recorded in the closure report |

---

## 18. Acceptance criteria

- [x] starting HEAD reconciled
- [x] only M8.3 implemented
- [x] schema remains v9
- [x] authorization occurs before traversal
- [x] denied seed exposes no graph info
- [x] denied neighbour never appears
- [x] hidden middle node does not reveal path
- [x] unauthorized edges do not affect degree/count
- [x] candidate authorized under its own scope
- [x] M6.6 resource_type isolation preserved
- [x] profile / project / knowledge-space isolation
- [x] revocation respected immediately
- [x] traversal bounds enforced (depth/fan-out/nodes/edges)
- [x] widening fails closed
- [x] deterministic ordering
- [x] cycle / self-loop / dense-graph bounded
- [x] provenance only from authorized rows
- [x] read-only (no mutation)
- [x] M5 remains sole authorization authority
- [x] no graph-derived auth
- [x] zero LLM
- [x] zero network
- [x] no Hermes core changes
- [x] no M6 tool changes
- [x] M7 unchanged
- [x] no M8.4+
- [x] no M9/M10
- [x] focused tests 0 failed
- [x] pre-binding canonical 0 failed
- [x] implementation commit created
