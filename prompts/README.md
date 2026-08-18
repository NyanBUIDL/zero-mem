# Prompt Registry

The active execution classes are exactly:

- `MASTER RUNNER` — `MASTER-AUTONOMOUS-RUNNER.md`
- `PHASE` — `phases/WP-00.md` and later WP packets
- `TASK` — task-local packets generated from the manifest
- `CLOSURE` — `closure/CLOSURE-GATE.md`
- `REMEDIATION` — `remediation/SINGLE-REMEDIATION.md`

No recursive or duplicate reconciliation/closure classes are active. Superseded prompts belong under `archive/superseded/` and are non-authoritative.

## Durable v1.1 sequencing authority

- Canonical roadmap: `docs/v1.1.0/MASTER_PLAN.md` at planning ref `2f1763f1335326b83bf90f263cada5c3715f21eb`
- Durable phase overlay: `../artifacts/control/PHASE-OVERLAY.yaml`
- Runner: `MASTER-AUTONOMOUS-RUNNER.md`
- Current durable phase: `A` (`IN_PROGRESS`)
- Next incomplete WP: `WP-02`
- Phase F/G: defined in the overlay, not started

The runner must resolve current durable WP evidence and WP dependencies before consulting the phase overlay. A phase is never complete by label or by partial WP completion. This registry does not authorize runtime implementation, Product Memory writes, or remote publication.

Historical or temporary phase labels are not current evidence.
