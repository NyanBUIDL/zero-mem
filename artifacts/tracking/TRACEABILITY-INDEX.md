# Traceability Index — Durable Phase Overlay

| Authority | Derived artifact/field | Verification role |
|---|---|---|
| Canonical DOCX SHA-256 | `artifacts/control/PHASE-OVERLAY.yaml:canonical_hash` | identity anchor |
| Planning ref `2f1763f...` | overlay, plan, WP tracker | WP ownership/DAG source |
| `docs/v1.1.0/MASTER_PLAN.md` §5 | WP responsibilities and phase rationale | ownership preservation |
| `docs/v1.1.0/MASTER_PLAN.md` §7 | phase ordering and dependency checks | topological validity |
| `artifacts/tasks/task-manifest.json` | `dependencies`, `WP_to_phase` | machine-readable DAG authority |
| `artifacts/evidence/WP-00-CLOSURE.md` | WP-00 VERIFIED | current durable evidence |
| `artifacts/evidence/WP-01-CLOSURE.md` | WP-01 VERIFIED | current durable evidence |
| `artifacts/evidence/WP-02-CLOSURE.md` | WP-02 VERIFIED | current durable evidence |
| `artifacts/handoffs/WP-02-HANDOFF.md` | WP-02 boundary handoff | next-phase context |
| `artifacts/control/runner-state.yaml` | current phase/WP selection | runner compatibility |
| `artifacts/control/PHASE-OVERLAY.yaml` | phases, mapping, closure model | canonical derived sequencing overlay |

## Boundary

This is a derived control-plane index. It does not replace the canonical specification, planning ref, WP contracts, source, tests, or Product Memory.
