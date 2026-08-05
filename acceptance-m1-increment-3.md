# M1 Increment 3 Acceptance Evidence

**Increment:** Capture boundary and deduplication
**Status:** VERIFIED
**Starting commit:** `df44a7d016ec13fb4c0038f493f8609da3ce316d`
**Implementation commit:** `0a18c912477e4324d0a60580a043573f3630f217`
**Product-code test state:** `17ca41e5e9c6f91dfe45fbcbbddcf0205a8e2118`
**Current evidence-review HEAD:** `17ca41e5e9c6f91dfe45fbcbbddcf0205a8e2118`
**Rerun required:** No. Changes after the product-code test state are documentation, state, and acceptance-evidence records only; no executable source, tests, schemas, storage behavior, redaction behavior, or runtime configuration changed.
**Checkpoint:** `checkpoint-m1-increment-3-start` → `df44a7d016ec13fb4c0038f493f8609da3ce316d`

| Criterion | Status | Objective evidence |
|---|---|---|
| Append-only authoritative JSONL source | PASS | Focused tests validate append-only bytes, no rewrite/delete, and restart recovery | `src/storage/jsonl_capture.py`; `tests/unit/test_m1_capture_boundary.py` |
| One complete parseable record per line | PASS | JSONL line count/newline and independent `json.loads` checks pass | `test_valid_append_and_one_record_per_line` |
| Stable CaptureStore interface | PASS | Config, append result, append/contains/inspect/close operations are implemented and exercised | `src/storage/capture_boundary.py`; focused tests |
| Redaction before persistence | PASS | Synthetic secret is redacted before append; missing audit and never-store cases reject | `test_redaction_before_persistence_and_secret_absence` |
| Event-ID deduplication | PASS | Repeated event ID returns explicit duplicate class and no append | `test_event_id_and_hash_duplicates_do_not_rewrite` |
| Sanitized-content-hash deduplication | PASS | Equal sanitized hash returns explicit duplicate and preserves first record | Same focused test |
| Deterministic serialization | PASS | Equivalent key order yields equal sanitized content hashes and stable JSON | `test_deterministic_serialization` |
| Monotonic sequence/restart recovery | PASS | Reopen reconstructs next sequence; values are contiguous and duplicate attempts do not advance | `test_sequence_recovery_and_timestamp_preservation` |
| Source timestamp preservation | PASS | Source timestamp remains distinct from assigned capture sequence | Same focused test; event contract |
| Partial/malformed line handling | PASS | Partial final and malformed historical lines fail closed without deletion | `test_partial_final_line_blocks_append_without_deletion`; malformed-line test |
| Atomic/recoverable append behavior | PASS | Append flushes and fsyncs complete line; unsafe write returns sanitized rejection | `src/storage/jsonl_capture.py`; focused tests |
| Restrictive permissions/path configuration | PASS | Explicit root honored; POSIX permissions assert directory `0700`, file `0600` | `test_restrictive_permissions_and_explicit_path` |
| Source immutability/secret absence | PASS | Sanitized event is used; synthetic secret absent from persisted JSONL | Redaction-before-persistence test and ad-hoc verification |
| Increment 1/2 compatibility and no LLM | PASS | Canonical suite includes contract/redaction tests; storage uses no LLM/network | `.venv/bin/python -m pytest tests/ -q` |
| Future behavior excluded | PASS | No retries, dead letters, Hermes hooks, SQLite, retrieval, MCP, Obsidian, or prompt injection added | Scope boundary and Git diff |

## Commands

Focused Increment 3 tests:

```text
.venv/bin/python -m pytest tests/unit/test_m1_capture_boundary.py -q
10 passed in 0.14s
```

Canonical regression suite:

```text
.venv/bin/python -m pytest tests/ -q
40 passed in 0.05s
```

Fresh verification: focused tests and canonical suite passed. The first temporary ad-hoc verifier attempt failed during script startup because it omitted the project-root `sys.path` setup; it was a verifier-generation error, not product-code failure. The temporary file was cleaned, the corrected verifier passed, and was cleaned successfully.

Corrected focused Increment 3 ad-hoc verification:

```text
focused Increment 3 ad-hoc verification: PASS
exit_code=0
cleaned=True
```

## Semantics

- Sequence scope: one configured JSONL capture stream, reconstructed from valid historical records on startup.
- Duplicate results do not append, rewrite, or delete source records.
- Partial or malformed data is retained and blocks startup; no silent repair occurs.
- Redaction is mandatory before persistence through the required `redaction_audit` and sanitized envelope fields.
- Retries and dead-letter persistence remain excluded from Increment 3.

## Incidents

- Initial focused collection failed as the intended RED phase because the capture implementation did not yet exist.
- The first canonical run exposed a stale baseline state assertion after Increment 2 state advancement; the baseline assertion was updated to the verified Increment 2/Increment 3 state, then the canonical suite passed.
- No no-op patch attempt occurred during Increment 3.
- Fixtures use synthetic values only; no real secrets were used.

No test caches, temporary verification files, or unintended generated artifacts remain after cleanup.

M1 remains in progress; Increment 4 is not implemented.

**M1 INCREMENT 3: VERIFIED**
