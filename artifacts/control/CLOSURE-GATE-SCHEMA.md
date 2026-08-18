# Closure Gate Schema

A frozen gate set must bind to canonical requirements, WP contract, security invariants, compatibility, and phase/WP objective before implementation.

Required gates:

1. source/planning/canonical identity unchanged;
2. every task has complete authorized mutable scope;
3. production caller and downstream consumer are resolved;
4. implementation and integration are exercised at real entry points;
5. focused, integration, negative/security, compatibility/migration, and benchmark checks required by the WP pass;
6. canonical storage/Product Memory/read-write boundaries hold;
7. later WPs remain untouched;
8. full regression has zero unexpected failures;
9. evidence, handoff, Development Memory, state, and hashes are source-bound;
10. `git diff --check` passes and remote publication remains denied.

Closure may classify blockers only as `SELF_RECONCILABLE`, `IMPLEMENTATION_REPAIRABLE`, or `TRUE_EXTERNAL_BLOCKER`. One remediation cycle is allowed.
