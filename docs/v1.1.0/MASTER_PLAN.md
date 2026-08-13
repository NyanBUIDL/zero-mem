# Zero-Mem V1.1.0 Master Plan

**Status:** IN REVIEW

Control document version: 2

Released baseline: Zero-Mem v1.0.0, annotated tag at `79989f34ce3578f275a7b910c8a189896ce9ad57`

Exact reconciliation point: `origin/master` at `78c4bb46b88b8ce9987c6882b24201e08b82a7f0` (verified 2026-08-14)

Source modification: **NOT AUTHORIZED**

## Current State

V1.0.0 is a local-first Python memory/evidence system with sanitized canonical JSONL, rebuildable SQLite/WAL/FTS5 projections, authorization, project memory, corpus ingestion, bounded context projection, backup/restore, and optional Hermes adapters. Its dependency footprint is small and its deterministic/security test coverage is substantial.

Current master is one documentation-organization commit ahead of the v1.0.0 tag. That delta moves repository documents and updates their path references in manifests, comments/docstrings, one verification script, and tests. It does not change the source blobs that support F-001 through F-014, so no finding is closed by the master delta. The resolved PKG-7 findings remain closed and are not part of the v1.1.0 backlog.

The system is not yet a drop-in external memory layer. The audited release boundary can register Hermes capture hooks without a persistence store; canonical capture and derived indexing have no public consistency lifecycle; JSONL startup/replay scales with all history; shared JSONL writes are process-unsafe; corpus fallback retrieval can materialize all candidates; public operational APIs remain under `src.*`; Windows packaging is not functional; sync/async and multi-agent contracts are incomplete.

## Target State

V1.1.0 is a controlled hardening release, not a rewrite. It must provide:

- a versioned agent-agnostic public lifecycle API;
- a Hermes adapter built only on that API and demonstrably connected to persistence;
- an explicit canonical-to-derived consistency and freshness contract;
- bounded normal startup and incremental ingest behavior;
- an enforced single-writer policy or verified process-safe write protocol;
- bounded, authorization-safe retrieval suitable for context construction;
- explicit synchronous and asynchronous integration guidance;
- honest, tested OS/Python/package compatibility;
- measurable diagnostics, migration safety, and release gates.

## V1.1.0 Objectives

| Objective | Evidence source | Success signal |
|---|---|---|
| Make capture operational end-to-end | F-001, F-002 | Registered capture writes canonical state and becomes retrievable under the documented consistency mode |
| Bound history-dependent hot paths | F-003, F-008, F-010 | Normal incremental operations do not reread or materialize all history/candidates |
| Establish safe ownership and concurrency | F-004, F-006 | Writer and runtime configuration ownership are explicit and tested |
| Publish a stable agent API | F-011 | Generic Python integration imports only the public API |
| Improve context quality/cost discipline | F-008, F-009 | Context-facing retrieval is bounded, deterministic, and current-state aware |
| Make installation/upgrade credible | F-005, F-007, F-012 | Supported environments pass fresh install, upgrade, doctor, and uninstall tests |
| Improve failure isolation visibility | F-013, F-014 | Fail-open behavior has persistent content-safe health/lag diagnostics |

## Non-Goals

V1.1.0 will not add distributed memory, a cloud service, Kubernetes, Kafka, Redis, an external vector database, distributed consensus, a UI, autonomous self-modification, multi-machine synchronization, or a V2 rewrite. Semantic/vector retrieval remains optional and cannot become a mandatory dependency. Shared multi-agent service mode is not required unless WP-12 verification proves a minimal local coordinator is necessary.

## Current Architecture

```text
Hermes PluginContext / custom host
  -> src.integration.hermes_registration / hermes_read_adapter / m7.injection_adapter
  -> payload mapping + redaction + envelope validation
  -> JsonlCaptureStore (only when caller injects a store)
  -> canonical events-v1.jsonl

explicit, separate ingest/rebuild
  -> src.storage.ingest
  -> SQLite metadata/lifecycle/provenance/relations/FTS
  -> src.access + src.retrieval
  -> M7/M8 evidence selection and context envelope
  -> host agent
```

State ownership:

| State | Owner | Canonical? |
|---|---|---|
| Sanitized event JSONL | `src.storage.jsonl_capture` | Yes |
| Corpus registry/blobs | `src.corpus.registry`, `blob_store` | Yes |
| SQLite metadata/FTS/graph/temporal/project views | `src.storage`, `src.corpus`, `src.m8`, `src.project_memory` | No, rebuildable |
| Hermes descriptor | `zero_mem.hermes_integration` | Configuration |
| Runtime master switch | `src.integration.zero_mem_runtime` | Process-local mutable state |

## Target Architecture

```text
Hermes Adapter       Generic Python Adapter       Future Adapter
       \                    |                         /
        +---------------- Stable Zero-Mem API ----------------+
                              |
                    lifecycle + health + sync
                              |
                         Zero-Mem Core
                    /                       \
      canonical writer + projector       authorized retrieval
                    \                       /
                  SQLite/FTS derived state
                              |
                   bounded context evidence
```

The core must not import Hermes-specific modules. Hermes owns only hook/tool mapping and host registration. The public API owns configuration resolution, writer/read-session lifecycle, consistency mode, diagnostics, and shutdown.

## Reconciliation Gate

WP-00 is now **Baseline Reconciliation and Delta Audit**. Before any implementation WP can be design-approved or implementation-authorized, a maintainer must verify that WP-00 binds this plan to the exact current master, reconciles every F-001–F-014 disposition, preserves PKG-7 closures, validates governance authority, and passes the documentation quality checks. A later change to `origin/master` requires a new delta check before publication or implementation authorization.

## Planning Repository Structure

```text
AGENTS.md
docs/
├── README.md
├── baseline/
│   ├── V1.0.0_BASELINE.md
│   ├── ARCHITECTURE_MAP.md
│   ├── CURRENT_DATA_FLOW.md
│   └── KNOWN_LIMITATIONS.md
├── audit/
│   ├── SYSTEM_AUDIT.md
│   ├── MASTER_RECONCILIATION.md
│   ├── FINDINGS_INDEX.md
│   └── FINDINGS_RECONCILIATION.md
└── v1.1.0/
    ├── STATUS.md
    ├── MASTER_PLAN.md
    ├── TRACEABILITY.md
    ├── decisions/ADR-001..ADR-005
    ├── work-packages/WP-00..WP-19
    ├── benchmarks/README.md
    └── reviews/README.md
```

## Dependency Graph

```text
WP-00 Baseline Reconciliation and Delta Audit
  -> WP-01 Architecture
      -> WP-02 Core Boundaries
          -> WP-13 Configuration
              -> WP-04 Storage
                  -> WP-03 Performance
                  -> WP-05 Retrieval -> WP-06 Context Efficiency
                  -> WP-08 Agent API
                      -> WP-09 Compatibility
                      -> WP-11 Sync/Async -> WP-12 Multi-Agent
                          -> WP-14 Reliability/Recovery -> WP-15 Observability
                  WP-06 + WP-08 + WP-15 -> WP-07 Hermes Integration
                  WP-07 + WP-09 + WP-14 -> WP-17 Migration
                  WP-07 + WP-09 + WP-17 -> WP-10 Packaging
  all implementation WPs + WP-10 + WP-17 -> WP-16 Testing/Benchmarks
  public/API/install/operations WPs -> WP-18 Documentation/DX
  WP-16 + WP-18 -> WP-19 Release Readiness
```

No implementation work package may be marked VERIFIED before its required WP-16 gates and applicable WP-17 migration checks pass.

## Work Package Order

- [WP-00 Baseline Reconciliation and Delta Audit](work-packages/WP-00-BASELINE.md)
- [WP-01 Architecture](work-packages/WP-01-ARCHITECTURE.md)
- [WP-02 Core boundaries](work-packages/WP-02-CORE_BOUNDARIES.md)
- [WP-13 Configuration](work-packages/WP-13-CONFIGURATION.md)
- [WP-04 Storage](work-packages/WP-04-STORAGE.md)
- [WP-03 Performance](work-packages/WP-03-PERFORMANCE.md), [WP-05 Retrieval](work-packages/WP-05-RETRIEVAL.md), [WP-08 Agent API](work-packages/WP-08-AGENT_AGNOSTIC_API.md)
- [WP-06 Context efficiency](work-packages/WP-06-CONTEXT_EFFICIENCY.md), [WP-09 Compatibility](work-packages/WP-09-COMPATIBILITY.md), [WP-11 Sync/async](work-packages/WP-11-SYNC_ASYNC.md)
- [WP-12 Multi-agent](work-packages/WP-12-MULTI_AGENT.md), [WP-14 Reliability/recovery](work-packages/WP-14-RELIABILITY_RECOVERY.md), [WP-15 Observability](work-packages/WP-15-OBSERVABILITY.md)
- [WP-07 Hermes integration](work-packages/WP-07-HERMES_INTEGRATION.md), [WP-17 Migration](work-packages/WP-17-MIGRATION_V1_0_TO_V1_1.md), [WP-10 Packaging](work-packages/WP-10-INSTALLATION_PACKAGING.md)
- [WP-16 Testing/benchmarks](work-packages/WP-16-TESTING_BENCHMARKS.md), [WP-18 Documentation/DX](work-packages/WP-18-DOCUMENTATION_DX.md)
- [WP-19 Release readiness](work-packages/WP-19-RELEASE_READINESS.md)

## Priority and Critical Path

Critical path: WP-00 → WP-01 → WP-02 → WP-13 → WP-04 → WP-08 → WP-11 → WP-12 → WP-14 → WP-15 → WP-07 → WP-17 → WP-10 → WP-16/WP-18 → WP-19. WP-05 → WP-06 and WP-09 are merge prerequisites on this path. WP-03 may run after the WP-04 design; WP-05 and WP-08 design may run in parallel after their shared predecessors. WP-16 harness work and WP-18 drafts may start early but cannot satisfy final gates before their declared dependencies.

P1 release blockers: WP-02, WP-04, WP-07, WP-08, WP-09, WP-10, WP-12 policy decision, WP-13, WP-14, WP-16, WP-17, WP-19.

Parallelizable after WP-13 and WP-04 design approval: WP-03, WP-05, and API design in WP-08. After WP-08: WP-09 and WP-11 can proceed while WP-05/WP-06 finish. Documentation can be drafted against approved contracts, while final WP-18 verification waits for WP-10, WP-15, and WP-17. WP-16 harness/fixture work can start early, but release qualification waits for every declared dependency.

## V1.1.0 Exit Criteria

- All P1 work packages are VERIFIED; no open P0 finding exists.
- Hermes capture, read tools, and optional context injection pass an installed-package end-to-end test using the public API.
- A clean generic Python agent initializes, observes, syncs, retrieves, checks health, and shuts down using only documented public imports.
- Normal incremental ingest does not reread the full canonical JSONL; normal retrieval does not read canonical JSONL.
- Shared-writer behavior is either process-safe and tested or explicitly rejected with a deterministic diagnostic.
- 1k and 10k benchmarks pass defined budgets; 100k and 1M are measured or explicitly dispositioned as `Needs verification` with no unsupported scale claim.
- Supported OS/Python matrix passes fresh install, upgrade, backup/restore, doctor, and uninstall checks.
- Existing V1.0.0 canonical memory survives V1.1.0 upgrade and derived state rebuilds equivalently.
- Documentation, migration guide, benchmark record, release checklist, and audit traceability are complete.
