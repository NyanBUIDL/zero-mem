# M1 Increment 4.3 — Redaction and CaptureStore Adapter

**Status:** READY FOR APPROVAL

## Objective

Connect the verified Increment 4.2 sanitized mapping result to the verified Increment 1 envelope contract and Increment 3 JSONL CaptureStore through a narrow, deterministic adapter. The adapter must accept only sanitized mapper output, enforce redaction-before-persistence, and isolate mapping, validation, redaction, and storage failures. It must not register or invoke real Hermes hooks.

## Exact processing boundary

```text
Increment 4.2 MappingResult(status=mapped, sanitized payload)
  -> verify mapped/sanitized result shape
  -> invoke/verify Increment 2 redaction boundary
  -> construct Increment 1 envelope
  -> validate envelope
  -> append through Increment 3 CaptureStore
  -> return append or duplicate result
```

Rejected, conditional, deferred, or malformed mapping results never reach persistence.

## Scope

### In scope

- `src/integration/capture_adapter.py`.
- Sanitized `MappingResult` input validation.
- Increment 2 redaction invocation on copied mapper output.
- Increment 1 envelope construction and validation.
- Increment 3 `CaptureStore.append` integration through dependency injection.
- Explicit append/duplicate result handling.
- Fixed sanitized diagnostics for mapping, redaction, validation, and storage failures.
- Source-payload immutability.
- Unit tests with fake/spied CaptureStore only.
- Acceptance evidence and runbook updates after verification.

### Explicit exclusions

- Real Hermes hook registration or callback execution.
- Runtime Hermes integration and temporary HERMES_HOME harness.
- Retry loops, deadlines, backoff, or dead-letter persistence.
- Capture-rate benchmark.
- SQLite, retrieval, MCP, Obsidian, prompt/context injection, or later increments.

## Security and ordering rules

1. Copy the mapper payload.
2. Validate only safe structural containers; reject unsupported objects without `str()`/`repr()`.
3. Invoke the verified Increment 2 redaction boundary.
4. Construct the Increment 1 envelope from sanitized data only.
5. Validate the envelope and recompute/check sanitized hash.
6. Call only the injected CaptureStore append operation.
7. Return a sanitized adapter result.

No raw mapper input may be passed to hashing, diagnostics, validation output, or storage. No temporary raw representation may be persisted.

## Duplicate semantics

- `appended` returns the verified store append result.
- `duplicate` returns the duplicate class and existing sequence/content hash metadata without exposing content.
- The adapter does not retry or reinterpret duplicates.
- Source records are never rewritten or deleted.

## Failure handling

| Failure | Adapter result | Persistence | Hermes/runtime effect |
|---|---|---|---|
| mapping status not mapped | fixed `mapping_not_persistable` | none | no real hook effect |
| unsafe mapped payload | fixed `unsafe_payload` | none | no propagation |
| redaction rejection | fixed `redaction_rejected` | none | no propagation |
| envelope validation failure | fixed `envelope_invalid` | none | no propagation |
| CaptureStore append failure | fixed `capture_failed` | no unverified result | no propagation |
| conditional/deferred status | fixed status preserved | none | remains unsupported |

Diagnostics may contain only hook/event class, fixed category/code, and safe IDs explicitly supplied by the mapper. They must not contain raw payloads, secret values, arbitrary exception strings, or object representations.

## Files

Create:

```text
src/integration/capture_adapter.py
tests/unit/test_hermes_capture_adapter.py
acceptance-m1-increment-4-3.md  # after verification only
```

Modify after verification only:

```text
implementation-plan.json
project-state.yaml
```

Do not modify installed Hermes, real Hermes state, Increment 1–3 modules, bridge configuration, or payload mapper unless a test-proven compatibility issue is reported before change.

## Acceptance criteria and tests

| Criterion | Objective evidence | Test |
|---|---|---|
| Only mapped sanitized input accepted | Non-mapped/conditional/deferred results never call store | `test_non_mapped_result_rejected` |
| Increment 2 redaction invoked | Spy confirms redaction before envelope/store | `test_redaction_precedes_envelope_and_append` |
| Increment 1 envelope valid | Returned envelope passes `validate_envelope` | `test_constructed_envelope_valid` |
| Increment 3 append used | Fake store receives only sanitized envelope | `test_store_append_receives_sanitized_envelope` |
| Duplicate semantics preserved | Duplicate class/result returned unchanged and sanitized | `test_duplicate_result_is_preserved` |
| Failures sanitized | Mapping/redaction/validation/store failures use fixed codes only | `test_failure_diagnostics_are_sanitized` |
| Source immutable | Mapper result/payload remains unchanged | `test_adapter_does_not_mutate_input` |
| No retries/dead letters | Store fake interaction proves one append attempt and no dead-letter call | `test_no_retry_or_dead_letter_behavior` |
| No real hooks/persistence side effects | Dependency injection and static/import tests | `test_adapter_has_no_hook_registration` |
| Regression compatibility | Increment 1–3 suites remain passing | canonical suite |

## Commands

Focused:

```bash
.venv/bin/python -m pytest tests/unit/test_hermes_capture_adapter.py -q
```

Canonical:

```bash
.venv/bin/python -m pytest tests/ -q
```

## Rollback

Create a checkpoint before implementation. Revert only the 4.3 adapter commit if any redaction ordering, envelope, duplicate, or failure isolation criterion fails. Do not alter raw JSONL records or Hermes installation. Re-run Increment 1–3 and 4.1–4.2 focused/canonical tests after rollback.

Do not implement Increment 4.3 until separately approved.

**Increment 4.3 plan: READY FOR APPROVAL**
``` in code 񟿿
