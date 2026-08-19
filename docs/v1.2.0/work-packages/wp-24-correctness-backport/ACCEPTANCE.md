# WP-24 Acceptance

**Status:** `VERIFIED`
**Acceptance contract frozen before implementation.**

## Functional acceptance

- [x] A durable canonical JSONL append returns a receipt with event identity, sequence, canonical durability, duplicate class, and reason code.
- [x] `ZeroMemClient.capture()` returns `CAPTURED` only for a durable canonical receipt.
- [x] Duplicate event/content behavior is explicit and does not append a second canonical record.
- [x] Existing successful M1 capture behavior and event ordering remain intact.
- [x] Recovery reads the actual `zm_*` derived schema and reports a valid ready/stale state without querying `memories`.

## Negative and failure-path acceptance

- [x] Writer exception, returned non-durable receipt, permission failure, and simulated append failure never return `CAPTURED`.
- [x] Canonical partial final line/malformed record is diagnosed without mutation.
- [x] Missing derived database is typed as derived missing.
- [x] Corrupt/unreadable/incompatible derived schema is typed as unavailable/corrupt/incompatible and fails closed.
- [x] Derived lag is typed stale using actual watermark/checkpoint evidence.
- [x] Recovery never changes canonical JSONL or derived SQLite bytes.

## Security acceptance

- [x] Error/reason/evidence output contains no raw payload or secret.
- [x] Recovery uses fixed/parameterized SQL and read-only access.
- [x] Tests use isolated temporary roots and do not modify real Hermes home.
- [x] No absolute developer paths, credentials, or temporary runtime databases enter committed artifacts.

## Regression requirements

- [x] Focused WP-24 tests pass.
- [x] Existing public API, M1 capture, M2 ingestion/rebuild, and WP-14 recovery tests pass.
- [x] Canonical project test suite passes with only pre-existing, documented environment limitations.
- [x] `git diff --check` passes and scope/path audit finds no future-WP implementation.

## Recovery/restart requirements

- [x] Reopening the canonical writer preserves sequence and duplicate semantics.
- [x] A restart after canonical append but before derived availability preserves canonical truth and reports derived pending/stale rather than loss.

## Performance/artifact requirements

- [x] No new unbounded work or retry loop.
- [x] Existing package build/evidence path is exercised if available; wheel/sdist/hash results are recorded as baseline evidence only.
- [x] No tag, push, release publication, or release-version bump.

## Exit gate

WP-24 may transition `VERIFYING → VERIFIED` only when every applicable checkbox above has executable evidence in `EVIDENCE.md`, the actual tested state is recorded, and self-review finds no architecture, canonical-storage, security, compatibility, or scope violation.

## Verification checklist

- [x] Acceptance objectives defined
- [x] Functional, negative, security, regression, and recovery tests defined
- [x] Artifact/reproducibility boundary defined
- [x] Required tests executed
- [x] Evidence recorded
- [x] Exit gate reviewed
