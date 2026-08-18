# Traceability Index — V1.1 Current Governance Chain

This is a derived control-plane index. It does not replace the canonical specification, planning authority, source, tests, closure evidence, or Product Memory.

## Authority and current evidence

| Chain element | Current authoritative path/evidence |
|---|---|
| Canonical requirement | `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` SHA-256 `85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a` |
| Planning authority | ref `2f1763f1335326b83bf90f263cada5c3715f21eb`; `docs/v1.1.0/MASTER_PLAN.md`; exact WP contracts and ADRs restored from that ref |
| Machine WP authority | `artifacts/tasks/task-manifest.json` |
| Phase sequencing | `artifacts/control/PHASE-OVERLAY.yaml` |
| WP verification | `artifacts/evidence/WP-00-CLOSURE.md` through `WP-22-CLOSURE.md` |
| Phase verification | `artifacts/evidence/PHASE-A-CLOSURE.md` through `PHASE-G-CLOSURE.md` |
| Runner state | `artifacts/control/runner-state.yaml` |
| Final release readiness | `artifacts/evidence/PHASE-G-CLOSURE.md`, final remediation evidence |
| Durable checkpoint | current local Git lineage from `0162d8f6c9c65fd65ebc9ec0d88b113df7a42b56` through final remediation commit |

## WP coverage

All exact IDs WP-00 through WP-22 are covered by the task manifest, WP closure evidence, WP tracker, phase overlay, and current durable verification projection. No current required reference is dangling.

## Phase coverage

All phases A through G are covered by the phase overlay, phase closure evidence, phase tracker, runner terminal state, and final release-readiness evidence. No next incomplete phase or WP remains.

## Historical boundary

Historical artifacts may retain NOT_STARTED, IN_PROGRESS, BLOCKED, or READY_FOR_REVIEW claims when accurate at the time. They are preserved as historical/superseded evidence and do not override the current projection above.
