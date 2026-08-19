# WP-29 Implementation Plan

**STATUS: VERIFIED**

## Baseline

- Workspace: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- WP-24..WP-28 are `VERIFIED` in project state.
- Existing authorization boundary: `src/access/contracts.py`, `policy.py`, `grants.py`, `resolver.py`, and `authorized_read.py`.
- Existing evidence: M5/M8 security and authorized-read tests cover deny-before-query, read-only behavior, grants, and scope checks.

## Gap analysis

The repository already contains a substantial authorization-first facade. WP-29 must verify the entire current read surface rather than replace it: all public read methods need pre-query gating, candidate sets must be scope-restricted, and negative tests must cover leakage through counts, pagination, identifiers, errors, and metadata. Any real gap gets a minimal fix in the owning access module.

## Increments

1. Inventory every `AuthorizedReadService` read method and its low-level call path.
2. Add/extend StoreSpy and seeded-derived-store tests proving DENY performs zero candidate discovery and that unauthorized rows never influence result shape.
3. Test profile/project/space/global/isolated scopes, READ vs WRITE, revoked/deleted grants, cursor binding, deterministic ordering, and sanitized denials.
4. Fix only verified authorization-order or scope-isolation defects.
5. Run focused security suites, public API regression, isolated full suite, static checks, and independent review.

## Expected files

- `src/access/authorized_read.py`, `contracts.py`, `grants.py`, `resolver.py` only if required.
- Focused WP-29 tests under `tests/unit/` and `tests/integration/`.
- WP-29 documentation/evidence/state files.

## Interfaces/contracts

`AccessRequest → effective scope/grants → authorized candidate predicate → low-level read → defensive boundary validation → deterministic response`. Denials return typed `AuthorizedResult` with fixed reason codes and no protected existence information.

## Migration/security impact

No new schema or dependency is planned. Existing derived grant tables remain derived from canonical events. Authorization is read-only. Identity is explicit and no raw credential is stored.

## Rollback

Revert WP-29-only source/tests/docs changes; do not delete or rewrite canonical events or derived grant state.

## Test strategy

TDD with low-level StoreSpy first, then seeded real SQLite read-only stores. Cover all read method families, leakage-negative invariants, cursor/count/order isolation, and grant lifecycle. Run WP-24..WP-29 focused and isolated full regression.

## Open questions

None blocking. Knowledge-space row predicates must use existing schema semantics; if a required scope column is absent, fail closed rather than invent a projection.

## Plan validation

Validated against Master Plan WP-29 hard gate, Unified Specification security invariants, current `src/access` implementation, M5/M8 tests, and verified WP-28 public contracts. No architecture conflict identified.
