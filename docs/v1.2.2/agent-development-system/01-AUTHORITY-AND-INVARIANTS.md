# 01 — Authority, invariants, and stop conditions

## Authority order

When documents disagree, use this order and report the conflict rather than inventing a reconciliation:

```text
1. Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx
2. Approved v1.2+ Spec Amendment 001 and ADR-009
3. AGENTS.md and approved repository governance
4. This v1.2.2 master plan and its approved package records
5. Existing source code and executable tests
6. Historical acceptance/evidence files
```

Tests prove behavior only; they do not override the specification. Historical `VERIFIED` text is evidence to re-check, not a waiver for a current release gate.

## Immutable architectural invariants

| ID | Rule | Enforcement point |
|---|---|---|
| INV-01 | JSONL is the single canonical append-only event/traces truth. | [`src/storage/jsonl_capture.py`](../../../src/storage/jsonl_capture.py), [`zero_mem/core.py`](../../../zero_mem/core.py) |
| INV-02 | SQLite, FTS, graph/indexes and Obsidian are derived and rebuildable. | [`src/storage/ingest.py`](../../../src/storage/ingest.py), [`src/storage/projection.py`](../../../src/storage/projection.py) |
| INV-03 | `CAPTURED` is returned only after a durable canonical append receipt. | [`AppendReceipt`](../../../zero_mem/core.py#L23), [`ZeroMemClient.capture`](../../../zero_mem/core.py#L57) |
| INV-04 | Derived failure never rewrites or erases canonical history. | [`zero_mem/recovery.py`](../../../zero_mem/recovery.py), recovery tests |
| INV-05 | Authorization occurs before candidate discovery or metadata disclosure. | [`AuthorizedReadService`](../../../src/access/authorized_read.py#L187), [`tests/unit/test_wp29_authorization.py`](../../../tests/unit/test_wp29_authorization.py) |
| INV-06 | Hermes is the orchestrator/final-action layer; Zero-Mem observes and serves bounded evidence. | [`docs/architecture/ARCHITECTURE.md`](../../architecture/ARCHITECTURE.md) |
| INV-07 | Raw secrets are redacted/rejected before persistence and never leak in diagnostics/evidence. | capture/redaction tests and `src/integration` |
| INV-08 | One runtime owns one canonical writer for a storage root; no competing global writer. | [`ZeroMemRuntime`](../../../src/integration/zero_mem_runtime.py#L71) |
| INV-09 | A platform is supported only after its executable qualification matrix passes. | [06-TEST-EVIDENCE-AND-RELEASE.md](06-TEST-EVIDENCE-AND-RELEASE.md) |

## Interface conventions

- Public methods use stable, typed request/response envelopes. They never expose a SQLite connection, filesystem path, raw exception, grant internals, or secret.
- `READY`, `EMPTY`, `STALE`, `POLICY_DENIED`, `UNAVAILABLE`, `OVERLOADED`, `DEADLINE_EXCEEDED`, and `INVALID_REQUEST` are semantically distinct. Do not flatten them into a boolean success flag.
- Every returned memory item needs event identity and provenance sufficient to locate its canonical source without leaking unauthorized fields.
- `CAPABILITY_NOT_IMPLEMENTED` is permitted only for explicitly deferred APIs. It must not be advertised as an available production capability.
- A deprecated API has a stable warning, a documented replacement, a migration test, and a removal version. It cannot be the only public route to a claimed capability.

## Mandatory stop/escalation conditions

Stop and request maintainer direction when any condition holds:

1. A change requires canonical event schema, migration, retention, authorization semantics, or public API compatibility decision not approved in this plan.
2. A platform cannot provide an equivalent safe lock/path primitive and a weaker fallback would be needed.
3. A test can only pass by weakening a security/property assertion or deleting a negative test.
4. The real Hermes host contract differs from the fixture contract.
5. A prior evidence file and current executable result conflict.
6. A release asset cannot be linked to the exact source SHA, build command, and checksum.
