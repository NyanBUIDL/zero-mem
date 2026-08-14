# Zero-Mem V1.1.0 Master Plan

**Status:** IN REVIEW

**Control document version:** 3 — canonical-spec alignment

**Released baseline:** annotated tag `v1.0.0` at `79989f34ce3578f275a7b910c8a189896ce9ad57`

**Reconciliation point:** `origin/master` at `78c4bb46b88b8ce9987c6882b24201e08b82a7f0`, verified 2026-08-14

**Canonical product source:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` at the reconciliation point, SHA-256 `85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a`

**Source modification:** NOT AUTHORIZED

## 1. Purpose and Release Problem

V1.1.0 turns the verified v1.0.0 subsystems into a usable local external-memory substrate without rewriting Hermes or sacrificing canonical provenance, authorization, privacy, bounded context, or deterministic operation.

The release must close two classes of gap together:

1. exact-master implementation gaps F-001–F-014: persistence composition, freshness, scale, concurrency, packaging, configuration, public lifecycle, observability, and compatibility; and
2. planning gaps against the canonical product specification: local sidecar/MCP capability contract, complete profile/knowledge-space semantics, Obsidian workspace/projection/reviewed write-back, conflict ownership, composite canonical-store terminology, and 1:1 requirement traceability.

Sources: canonical DOCX §§1–5, 8–13, 16–18; `docs/audit/FINDINGS_RECONCILIATION.md`; `reviews/SPEC_ALIGNMENT_GAP_ANALYSIS.md`.

## 2. Current Implementation Truth

Exact master is one documentation/path-reference commit after v1.0.0. The source blobs behind F-001–F-014 are unchanged.

- Sanitized JSONL is the durable append-only event source used by capture.
- SQLite/WAL/FTS and project/graph/temporal/projection tables are currently derived/rebuildable.
- Capture and ingest are separate; public Hermes capture can register without a store.
- Exact master contains strong access/grant logic, a transport-independent M6 dispatcher, a thin MCP wrapper, ten read-only internal tool names, bounded controlled injection, and a deterministic M9 Obsidian projection.
- The M9 projection is one-way and explicitly has no Candidate Review or canonical write-back.
- No supported packaged local sidecar lifecycle or small versioned public capability facade exists.

Implementation evidence: `docs/baseline/`, `docs/audit/SYSTEM_AUDIT.md`, exact-master source/tests, and historical M5/M6/M7/M9/M10 acceptance records. Historical `VERIFIED` labels prove only their bound behavior; they do not authorize or complete v1.1.0.

## 3. Canonical Invariants

These are release-blocking and may be narrowed only by an approved ADR that cites an explicit canonical allowance:

- Hermes remains orchestration/final action; Zero-Mem is an optional sidecar and agent-agnostic substrate.
- Capture is sidecar-first and Hermes-core change is minimized; core never imports Hermes-specific code.
- Sanitized raw traces are append-first with stable provenance; updates append replacement/supersession/resolution records.
- The canonical trace system follows ADR-003: append-first JSONL/artifacts/approved write-back records plus queryable canonical SQLite metadata/lifecycle; FTS/vector/graph/cache/Obsidian projections are rebuildable.
- Verified state outranks assistant self-report; unresolved conflicts and uncertainty remain visible.
- Authorization precedes influence across lexical, dense, temporal, relational, graph, projection, and context paths.
- Profiles are policies; default reads are authorized global/profile-first and bounded. `isolated` and `source_restricted` do not leak or fall back.
- Cross-profile writes require explicit WRITE authority and review/verification.
- Secrets are redacted or rejected before every persistent boundary, including queue/manifest/write-back.
- Normal capture, indexing, routing, retrieval, dedupe, calibration, projection, and review-state operations make zero LLM calls and no mandatory external network call.
- Evidence/context uses bounded candidates, top-k/token budgets, dedupe, provenance, conflict/insufficiency, and deterministic ordering.
- Obsidian is the one-Vault human workspace and a curated rebuildable projection, never raw canonical storage or the retrieval engine.
- Obsidian edits enter a review queue; only approved authorized candidates append canonical records. Direct raw overwrite and last-writer-wins are forbidden.
- Migration starts from populated v1.0.0 state, is previewable/idempotent/interruptible, and has verified backup and rollback.

Sources: canonical DOCX §§3.3, 5–15, 17–21; Appendix D–E; ADR-001 through ADR-008.

## 4. Target Architecture

```text
Hermes Adapter        Generic Client         Other Local Agent
      |                     |                       |
      +---------- Zero-Mem Agent Interface --------+
                            |
        lifecycle + four canonical read capabilities
                            |
             embedded API / local MCP sidecar
                            |
             explicit identity + authorization
                            |
     +---------------- Zero-Mem Core ----------------+
     | capture/redact | policy | retrieval | conflict |
     +----------------------+-------------------------+
                            |
          composite canonical trace contract
       +--------------------+--------------------+
       | append-first JSONL | canonical SQLite   |
       | artifacts/writeback| metadata/lifecycle |
       +--------------------+--------------------+
                            |
         rebuildable FTS/dense/graph/projections
                            |
          bounded evidence + provenance envelope
                            |
                   Hermes/final agent LLM

canonical state -> projection generator -> Obsidian managed workspace
Obsidian edit -> candidate/review/conflict -> approved canonical append
```

### 4.1 Agent interface

WP-08 owns the transport-neutral contract in `INTERFACE_CONTRACT.md`. The mandatory V1.1.0 external capabilities are:

- `zero_mem.search`
- `zero_mem.get_trace`
- `zero_mem.get_task_state`
- `zero_mem.get_decisions`

WP-21 owns MCP/local binding, version negotiation, deadlines, size/concurrency limits, endpoint security, lifecycle, and transport conformance. MCP is the baseline local binding because exact master already contains a thin MCP wrapper and the canonical roadmap names MCP+Hermes at the MVP integration stage. Local HTTP/Unix socket may be added only as the same contract, never as a divergent API.

Canonical `zero_mem.expand`, `zero_mem.propose_memory`, and `zero_mem.project_to_obsidian` are explicitly “Sau MVP” and therefore `DEFERRED`; their names remain reserved and return a typed unavailable state until separately authorized.

### 4.2 Hermes boundary

WP-07 owns only Hermes hook/event mapping, explicit identity, plugin activation, client lifecycle, descriptor migration, timeout/fallback, and fail-open host behavior. It consumes WP-08/WP-21 and may not define storage, authorization, ranking, or tool semantics. Capture registration must have a valid writer path or be unavailable. Read denial fails closed; service failure/timeout prevents unsafe injection and does not crash Hermes.

### 4.3 Profiles and knowledge spaces

WP-20 owns `PROFILE_KNOWLEDGE_SPACE_CONTRACT.md`. Authorization resolves the maximum set before the mode applies. The five modes are `profile_first`, `explicit_union`, `isolated`, `global`, and `source_restricted`. Behavior identity and knowledge scope are separate. Exact-master physical multi-process/profile ownership remains WP-12 and cannot redefine retrieval semantics.

### 4.4 Obsidian workspace and write-back

WP-22 owns `OBSIDIAN_WORKSPACE_CONTRACT.md`: required pages, note/provenance schema, managed-root ownership, projection trigger/version/idempotency/stale/delete behavior, Candidate Review, write-back lifecycle, and projection/edit conflicts. WP-14 remains the canonical conflict/recovery authority; WP-04 owns append-first persistence.

## 5. Responsibility Ownership

| Responsibility | Sole owner | Consumers/support |
|---|---|---|
| Architecture/import/state boundaries | WP-01/WP-02 | all WPs |
| Composite canonical storage/freshness/retention/delete | WP-04 | WP-03, WP-14, WP-15, WP-17, WP-22 |
| Retrieval algorithms/ranking/fusion | WP-05 | WP-06, WP-08, WP-20 |
| Profile/knowledge-space modes and write-scope policy | WP-20 | WP-05, WP-08, WP-12, WP-21, WP-22 |
| Context/evidence budget | WP-06 | WP-07, WP-08, WP-21 |
| Transport-neutral public capability/lifecycle contract | WP-08 | WP-07, WP-11, WP-18, WP-21 |
| MCP/local sidecar transport | WP-21 | WP-07, WP-10, WP-15, WP-18 |
| Hermes adapter/hooks | WP-07 | WP-10, WP-17, WP-18 |
| Canonical conflict/failure/recovery | WP-14 | WP-05, WP-08, WP-15, WP-22 |
| Obsidian projection/review/write-back | WP-22 | WP-04, WP-14, WP-17, WP-18 |
| Physical multi-runtime/process ownership | WP-12 | WP-04, WP-11, WP-15, WP-20 |
| Configuration | WP-13 | all runtime/integration WPs |
| Tests/benchmarks | WP-16 | all WPs |
| Migration/rollback | WP-17 | WP-10, WP-16, WP-19 |
| Final go/no-go | WP-19 | all WPs; final despite numeric ID |

No WP may redefine a contract owned by another WP. It references the owner and supplies only its adapter/validation contribution.

## 6. Work-Package Quality Contract

Every WP inherits these mandatory fields even when a local heading uses different words:

- objective/why, scope/out of scope, canonical requirements/sources, dependencies;
- architecture constraints, expected future implementation components, forbidden components;
- implementation tasks, testable acceptance criteria, negative and regression tests;
- migration/compatibility, security/privacy, performance/benchmarks, observability;
- rollback, exit gate, traceability, and explicit planning-vs-implementation authorization.

Acceptance uses Given/When/Then where it clarifies behavior. “Works,” “supports,” or “is compatible” without an observable result is not an acceptance criterion. All source/test scopes are proposals until the maintainer explicitly authorizes one WP and exact paths.

## 7. Dependency Graph and Implementation Order

```text
WP-00 Baseline + canonical parity audit
  -> WP-01 Architecture
    -> WP-02 Core boundaries
      -> WP-13 Configuration
        -> WP-04 Canonical storage/freshness
          -> WP-03 Performance
          -> WP-05 Retrieval
            -> WP-20 Profiles/knowledge spaces
              -> WP-06 Context efficiency
          -> WP-08 Agent interface
            -> WP-09 Compatibility
            -> WP-11 Sync/async
              -> WP-12 Multi-agent/process
          WP-04 + WP-08 + WP-12 -> WP-14 Reliability/conflict/recovery
            -> WP-15 Observability
              -> WP-21 Local sidecar/MCP
          WP-06 + WP-08 + WP-15 + WP-20 + WP-21 -> WP-07 Hermes adapter
          WP-04 + WP-14 + WP-20 -> WP-22 Obsidian workspace/write-back
          WP-07 + WP-09 + WP-14 + WP-20 + WP-21 + WP-22 -> WP-17 Migration
          WP-07 + WP-09 + WP-17 + WP-21 + WP-22 -> WP-10 Packaging
  all implementation WPs -> WP-16 Testing/benchmarks
  public/install/operations/profile/Obsidian WPs -> WP-18 Documentation/DX
  WP-16 + WP-17 + WP-18 + every mandatory WP -> WP-19 Release readiness
```

The graph is intended to be acyclic. Interface-first design permits WP-05, WP-08, and parts of WP-20 design to overlap only after shared architecture/storage/config contracts are stable. WP-16 harness and WP-18 drafts may start early but cannot satisfy final gates before dependencies verify.

Critical path:

`WP-00 → WP-01 → WP-02 → WP-13 → WP-04 → WP-08 → WP-11 → WP-12 → WP-14 → WP-15 → WP-21 → WP-07 → WP-17 → WP-10 → WP-16/WP-18 → WP-19`

WP-05→WP-20→WP-06 and WP-22, WP-09, and WP-03 are merge prerequisites where shown.

## 8. Migration and Backward Compatibility

WP-17 owns a staged path from populated v1.0.0:

1. read-only discovery of JSONL, SQLite/schema/checkpoints, corpus/artifacts, configuration/paths, grants/profiles, Hermes descriptor/hooks, API/internal-import consumers, M9 projection manifest/human edits, and any candidate/write-back state;
2. validate permissions, disk, source hashes, versions, endpoint/Vault paths, and backup readiness;
3. create and verify backup before mutation;
4. migrate typed configuration, API/adapter/transport versions, profile modes, and composite canonical metadata without rewriting raw traces;
5. rebuild disposable indexes/projections from canonical records and compare logical identities/watermarks;
6. preserve human edits as candidates/conflicts, never overwrite them;
7. verify Hermes and generic clients, local sidecar, profile modes, Obsidian views/write-back, doctor/status, and exact-wheel behavior;
8. activate atomically; support interruption resume and rollback readable by the prior supported version.

Compatible behavior: raw v1.0.0 records/artifacts remain readable, internal consumers receive the documented deprecation window, existing M6 tool names map/alias or fail with migration guidance, and package uninstall never implies data deletion. Breaking changes require contract/schema versioning and release notes.

## 9. Security and Privacy Gates

- Redact/reject secrets before JSONL, SQLite, artifact, queue, manifest, log, status, transport, or Vault persistence.
- Local service callers authenticate/identify and authorize; local endpoint location alone grants nothing.
- Authorization precedes candidate influence, expansion, scoring, counts, conflicts, and projection.
- Isolated/source-restricted and cross-profile negative tests include content, identifiers, counts, scores, neighbors/links, caches, conflicts, and timing/error-class leakage.
- Paths and symlinks are resolved safely for data roots, artifacts, sources, migration, and Obsidian managed roots.
- Write boundaries require explicit authorization, review, freshness/concurrency checks, and append-first audit records.
- Default diagnostics are content-free, secret-free, bounded-cardinality, and local.

## 10. Performance and Evidence-Budget Gates

WP-03/WP-16 measure startup, capture/write, canonical metadata update, derived sync, retrieval, local transport, async/queue, profile unions/fallback, context/token, index rebuild, projection, write-back, migration, memory, disk, WAL, and resource lifecycle.

- 1k and 10k results require release budgets; 100k and 1M are measured or explicitly `Needs verification` with no scale claim.
- Candidate discovery, union/fallback, graph/neighbor expansion, context, queues, and projection batches are bounded.
- Canonical defaults start at 5 primary, at most 3 supporting, and 3,000–6,000 evidence tokens; changes require benchmark-backed review.
- Memory-operation LLM calls remain 0.
- Canonical acceptance targets include supported capture ≥99%, provenance 100%, task continuation ≥90%, and local retrieval p95 against an approved machine-specific budget (initial canonical proposal <2 seconds).
- Every performance claim records corpus, hardware/runtime, warm-up, repetitions, median/p95/variance, memory/disk, and raw evidence.

## 11. Validation Strategy

WP-16 consumes every WP acceptance gate and must include:

- exact-wheel unit, integration, lifecycle, compatibility, migration, fault, security, and benchmark suites;
- F-001–F-014 regressions;
- four-capability direct/API/MCP/Hermes/generic conformance;
- all profile modes with positive, negative, union-order, leakage, privilege, cache, pagination, timeout, and concurrent-identity cases;
- canonical lifecycle/conflict/retention/delete/replay/rebuild cases;
- Obsidian required views, provenance, ownership/path safety, idempotency/stale/delete, review/write-back outcomes, no-loop, rebuild, and real-vault integrity;
- redaction/privacy tests at every persistent/exposure boundary;
- sync/async/deadline/backpressure/resource cleanup;
- migration/rollback for populated, empty, stale/missing derived state, malformed tail, non-default paths, legacy descriptors/tool names, profiles/grants, and M9 human edits.

The traceability-completeness gate fails when any mandatory row is `MISSING`, `PARTIAL`, or `CONFLICT`. `DEFERRED` is valid only when the canonical specification explicitly permits post-MVP delivery.

## 12. V1.1.0 Release Exit Criteria

WP-19 records NO-GO unless all of the following are true at the exact candidate artifact:

- canonical invariants and ADR-001 through ADR-008 are satisfied;
- `SPEC_TRACEABILITY.md` covers every mandatory canonical requirement with passing evidence and no unresolved requirement conflict;
- no unresolved BLOCKER/P0/P1 defect or unexplained performance regression remains;
- all mandatory WPs, including WP-20, WP-21, and WP-22, are VERIFIED;
- composite canonical trace/replay and deletion of derived state followed by full rebuild are verified;
- profile isolation/source restriction and authorized profile-first/union/global behavior are verified;
- four API/MCP capabilities and generic-agent/Hermes parity are verified;
- Hermes capture/read/injection failure/timeout/fallback and optionality are verified without hidden core coupling;
- Obsidian required pages, projection, provenance, idempotency, reviewed write-back, every conflict/outcome, rebuild, and no-loop behavior are verified;
- redaction, privacy, local API, path, write, and diagnostic boundaries pass;
- v1.0.0 migration, interruption, rollback, backward compatibility, install/uninstall, and data preservation pass;
- performance/resource/context-token gates pass with reproducible evidence;
- release documentation/examples match the exact artifact and contain no private imports, broken links, or unapproved uncertainty.

## 13. Planning Governance

WP-00 remains the only active work package and is review-ready, not maintainer-verified. WP-01 through WP-22 are NOT STARTED and none is implementation-authorized. Planning approval, ADR approval, a commit, or a merged documentation PR does not authorize source modification.

Before any implementation, the maintainer must verify WP-00, select one WP, name its objective, exact implementation write scope, required tests/benchmarks, and branch/PR workflow, and update `STATUS.md`/the WP accordingly. Git branch/stage/commit/push/PR/tag/release mutations remain separately approval-gated.
