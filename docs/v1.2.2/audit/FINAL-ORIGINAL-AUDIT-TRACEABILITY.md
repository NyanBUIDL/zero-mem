# Zero-Mem v1.2.2 — Final Original-Audit Traceability

## Identity and authority

- Original audit: `artifacts/audits/V11-FINAL-MAINTAINER-AUDIT.md`
- Original findings: `artifacts/audits/V11-FINAL-MAINTAINER-FINDINGS.yaml`
- Expanded inventory: `/home/lenovo/Hermes Workspace/ZERO-MEM-v1.2.1-AUDIT-FINDING-MATRIX.md`
- Pre-release candidate HEAD: `ad6e38eaa7ac7a764aa54bd5fee8dfcd59a5a6a6`; final release evidence must bind the post-qualification release commit.
- Current worktree: intentionally dirty
- Scope: Linux qualification only; Windows/macOS explicitly deferred to v1.2.3
- Canonical authority: AGENTS.md, architecture document, Spec Amendment 001, ADR-009, v1.2.2 master plan and maintainer platform decision.

## Finding traceability matrix

| ID | Severity | Original requirement | Current proof/implementation | Current status | Deferred? | Residual risk |
|---|---|---|---|---|---|---|
| A-01 | Blocker | Public reads must be implemented, authorized, typed and bounded. | `zero_mem/api.py` → injected `PublicReadService` → `AuthorizedReadService`; current public-read tests pass. | CLOSED_VERIFIED | No | Compatibility unavailable result remains when no service is injected. |
| A-02 | Blocker | WP-33 benchmark must collect and remain deterministic. | Benchmark module exists; collection succeeds; WP-33 tests pass. | CLOSED_VERIFIED | No | No Windows/macOS execution. |
| A-03 | High | Projection coordinator must have runtime ownership, restart and failure semantics. | Runtime owns writer, derived store and bounded coordinator; current projection/runtime tests pass. | CLOSED_VERIFIED | No | Historical handoffs/evidence are stale. |
| A-04 | High | Legacy sidecar requires explicit deprecation and canonical parity. | Deprecation warning exists; `LocalSidecar` delegates canonical read capabilities through bounded `ZeroMemSidecar` and preserves canonical statuses. | CLOSED_VERIFIED | No | Legacy observe/sync/health/capabilities remain compatibility-only. |
| A-05 | High | Hermes lifecycle must be composed and tested. | Project-local Hermes boundary covers enable/disable, capture, projection, reads, restart, idempotence and shutdown. | CLOSED_VERIFIED | No | Real external host execution remains fixture-bound. |
| A-06 | High | Platform-sensitive storage needs one owner and safe identity/path/lock/promotion semantics. | Platform owner, identity fencing, locking, short-write and recovery paths pass Linux tests. | DEFERRED_WITH_EXPLICIT_AUTHORITY | Yes | Windows/macOS ABI, reparse and filesystem behavior unqualified. |
| A-07 | Medium | Evidence must bind exact source, commands, logs, hashes and collection state. | Current verifier-backed bundle `artifacts/evidence/v1.2.2/ba9cd2d…/` matches HEAD, tree fingerprint, raw logs and assets; verifier PASS. | CLOSED_VERIFIED | No | Reviewer result must be persisted in the final bundle. |
| A-08 | Medium | Windows/macOS must not be claimed qualified without executable matrix evidence. | Documentation and maintainer decision correctly state Linux-only and defer both platforms. | DEFERRED_WITH_EXPLICIT_AUTHORITY | Yes | No real Windows/macOS evidence. |

**Inventory:** 8 findings. **Final counts:** CLOSED_VERIFIED 5; CLOSED_BY_DESIGN_CHANGE 0; DEFERRED_WITH_AUTHORITY 2; STILL_OPEN 0; NOT_APPLICABLE_WITH_PROOF 0.

## Core invariants

| Invariant | Current proof | Status |
|---|---|---|
| INV-01 JSONL is sole canonical append-only truth | capture/recovery/source inspection and tests | PASS Linux |
| INV-02 SQLite/FTS/graphs/projections are derived/rebuildable | projection/rebuild/recovery tests | PASS Linux |
| INV-03 CAPTURED follows durable canonical append | append receipt and capture tests | PASS |
| INV-04 Derived failure cannot rewrite canonical history | recovery and failure-isolation tests | PASS |
| INV-05 Authorization precedes discovery/disclosure | fixed public adapter tests now authorize before freshness | PASS for remediated path; fresh evidence required |
| INV-06 Hermes owns orchestration/final action | architecture and integration boundary tests | PASS for supported project-local contract |
| INV-07 Secrets are rejected/redacted | redaction and capture tests | PASS Linux |
| INV-08 One runtime owns one canonical writer | runtime ownership/restart tests | PASS Linux |
| INV-09 Platform claims require executable qualification | Linux evidence and explicit platform decision | Linux PASS; Windows/macOS deferred |

## Remediations performed

1. Distribution version corrected from stale `1.2.1` to `1.2.2`.
2. Packaging bundle generation now derives its version from wheel metadata.
3. Packaging manifest validation now accepts the v1.2.2 contract.
4. Packaging tests and clean wheel/sdist smoke were updated and exercised.
5. Public-read request validation now rejects malformed list, boolean and scope values.
6. Public reads now authorize before freshness/wait-provider observation.

These changes were implemented with focused failing tests first. The focused public-read regression is `4 passed`. A fresh full Linux run after these changes is:

```text
3288 passed, 5 skipped, 0 failed
```

## Skip audit

Five visible skips remain:

- Two optional PDF tests because `pypdf` is not installed.
- Three FTS5 tests because their capability checks report FTS5 unavailable. A separate SQLite probe reports FTS5 enabled; this discrepancy is not silently treated as qualification.

## Independent reviews

### `V122-FINAL-EXACT-TREE-AUDIT-001`

Failed on evidence freshness, contradictory package records and stale packaging evidence. No security or product logic issue was reported in that review.

### `V122-FRESH-EXACT-TREE-REPLACEMENT-REVIEW-004-20260821`

Failed closed with blockers:

- **BR-01:** stale V122-current evidence and nonexistent claimed review-003.
- **BR-02:** packaging version split-brain in the pre-remediation tree.
- **BR-03:** fresh full-suite failure in the pre-remediation execution.
- **BR-04:** public adapter accessed freshness before authorization.
- **BR-05:** malformed public values were silently coerced.
- **BR-06:** A-04 legacy-sidecar parity incomplete.
- **BR-07:** contradictory v1.2.2 package records.

BR-04 and BR-05 were remediated. A-04 parity was remediated through canonical delegation. The current full suite is 3292 passed, 5 skipped, 0 failed.

### `V122-FINAL-CLOSURE-REVIEW-007-20260821`

This terminal closure review confirmed the reconciled package statuses, current manifest reviewer binding, exact tree/evidence identity, A-04 delegation, public-read ordering, package versions, Linux full-suite record, and explicit Windows/macOS deferrals. It returned PASS with no blocking, security or logic findings.

## Evidence state

The old `V122-current/` and `final-audit-096050…/` bundles are explicitly invalidated. The authoritative current bundle is:

`artifacts/evidence/v1.2.2/ba9cd2d8719bcb00e8562b4a7baf07dfb69cceb0616c134c519d7ec99f5a3bdc/`

The pre-release verifier passed against the candidate source SHA and its raw-log/artifact hashes. Final release evidence is source-bound separately to the final release commit; the isolated Linux full suite reports 3292 passed, 5 skipped, 0 failed.

## Final verdict

```text
ZERO_MEM_VERSION: 1.2.2
TRACEABILITY_COMPLETE: true
CORE_INVARIANTS: PASS_LINUX_SCOPE
EVIDENCE_REPRODUCIBLE: true
FINAL_REPLACEMENT_REVIEW_ID: V122-FINAL-CLOSURE-REVIEW-007-20260821
FINAL_REPLACEMENT_REVIEW: PASS
WINDOWS: DEFERRED_TO_v1.2.3
MACOS: DEFERRED_TO_v1.2.3
REMOTE_MUTATION: NO
TAG: NOT_PERFORMED
RELEASE: NOT_PERFORMED
PYPI: NOT_PERFORMED
AUDIT_VERDICT: PASS_LINUX_SCOPE_READY_FOR_RELEASE_AUTHORIZATION
NEXT_ACTION: RELEASE_AUTHORIZATION
```

Linux-scoped v1.2.2 is verified and ready for separate release authorization. Windows/macOS qualification remains deferred. No release publication is authorized or performed by this audit.
