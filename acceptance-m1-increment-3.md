# M1 Increment 3 Acceptance Evidence

**Increment:** Capture boundary and deduplication
**Status:** VERIFIED
**Starting commit:** `df44a7d016ec13fb4c0038f493f8609da3ce316d`
**Checkpoint:** `checkpoint-m1-increment-3-start` → `df44a7d016ec13fb4c0038f493f8609da3ce316d`

| Criterion | Status | Objective evidence |
|---|---|---|
| Append-only authoritative JSONL source | PASS | 10 focused tests validate one deterministic newline-terminated JSON object per record, append-only bytes, and reopen recovery |
| Stable CaptureStore interface | PASS | `CaptureStoreConfig`, `AppendResult`, `CaptureStore`, `append`, `contains_event_id`, `contains_content_hash`, `inspect_record`, and `close` are implemented and tested |
| Redaction before persistence | PASS | Test redacts a synthetic secret before append; raw stream contains no original secret; missing audit/secret policy is rejected |
| Event-ID deduplication | PASS | Repeated event ID returns `duplicate` with `duplicate_class=event_id`; source bytes remain unchanged |
| Sanitized-content-hash deduplication | PASS | Equal sanitized hash returns `duplicate` with unchanged source bytes |
| Deterministic serialization | PASS | Equivalent key order produces equal content hashes; JSON lines parse independently |
| Monotonic sequence and restart recovery | PASS | Reopen test reconstructs next sequence; records are contiguous `[0, 1]`; source timestamps remain separate |
| Partial/malformed line handling | PASS | Partial final line and malformed historical line fail closed without deletion |
| Restrictive permissions/path configuration | PASS | Explicit root is honored; POSIX tests assert directory `0700` and file `0600` |
| Immutability and secret absence | PASS | Sanitized source event is used; synthetic secret is absent from persisted JSONL |
| Future behavior excluded | PASS | Store exposes no retry/search/injection methods; no Hermes hooks, retries, dead letters, SQLite, retrieval, MCP, Obsidian, or prompt injection added |

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
