# Master Autonomous Execution Policy

## Authority

The current maintainer instruction authorizes local v1.1 implementation and local Git checkpoints. Canonical product intent comes from `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`; approved planning and ADRs come from planning ref `2f1763f1335326b83bf90f263cada5c3715f21eb`; direct source/tests define implementation truth.

## Lifecycle

`V1.1_RESTART_BOOTSTRAP → WP_READY → WP_IN_PROGRESS → WP_CLOSURE_REVIEW → WP_REMEDIATION (at most once) → WP_VERIFIED → LOCAL_CHECKPOINT → NEXT_DEPENDENCY_READY`.

No later WP starts before its dependency set is verified and checkpointed. The surviving roadmap is WP-00..WP-22, not Phase A-G.

## Execution rail

Select all tasks; validate dependencies and complete mutable scope; resolve production call graph; authorize exact paths; hash baseline; implement; integrate at the real caller; run focused/integration/security/negative/benchmark checks; audit forbidden paths and canonical/Product Memory boundaries; run `git diff --check`; produce evidence/handoff; close once; remediate once if needed; rerun full regression; commit locally.

## Stop policy

Self-reconcile stale projections and missing approved path bindings. Repair ordinary implementation failures. Stop only for canonical contradiction, forbidden future-phase work, Product Memory violation, unapproved architecture/dependency, destructive Git operation, remote publication, or irreconcilable equal-authority conflict.

## Git

Local branch/stage/commit are allowed. Push, PR, remote tag/release, destructive reset/clean/force/rebase are denied.
