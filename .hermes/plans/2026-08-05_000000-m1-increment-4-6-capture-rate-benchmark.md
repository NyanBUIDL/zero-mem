# M1 Increment 4.6 — Capture-Rate Benchmark and Final M1 Acceptance Plan

**Status:** READY FOR APPROVAL

## Objective

Implement and verify the controlled capture-rate benchmark for the operationally supported Hermes hooks, then perform final M1 acceptance. This increment is verification-focused and uses the verified Increment 4.1–4.5 adapters through the real project `JsonlCaptureStore`.

## Scope

In scope:

- temporary HERMES_HOME and capture root;
- synthetic project_id/profile_id and synthetic payloads/secrets;
- controlled benchmark harness driving the verified bridge over supported hooks;
- capture-rate measurement against the exact formula;
- duplicate-event accounting without extra record creation;
- envelope validation, sequence monotonicity, identifier preservation checks;
- separate reporting for deferred/conditional events (excluded from denominator);
- final M1 acceptance assertions across all required properties.

Explicit exclusions:

- conditional LLM/API hooks, subagent hooks, on_session_reset;
- retry loops, backoff, dead-letter persistence;
- SQLite, retrieval, MCP, Obsidian, prompt/context injection;
- modifications to installed Hermes source or real Hermes state;
- any M2 work.

## Capture-rate formula

successfully_accounted_logical_events / expected_supported_logical_events * 100

A logical event is successfully accounted for when:

- one valid sanitized record is appended; or
- an accepted duplicate result is returned and the original stored record is confirmed to exist.

Each expected logical event counts at most once. Accepted threshold: capture_rate >= 99.0%.

## Harness design

1. Create `TemporaryDirectory(prefix="hermes-verify-")` for `HERMES_HOME` and capture storage.
2. Set explicit synthetic `project_id`/`profile_id`.
3. Use the real `JsonlCaptureStore` (temporary root) as the store.
4. Register the verified `RegistrationAdapter` (enabled) against a fake context.
5. Drive each supported hook with a unique synthetic logical event.
6. Optionally replay duplicate payloads for a subset and confirm accepted-duplicate accounting.
7. Drive conditional/deferred hooks through the mapper to confirm they are reported separately and excluded from the denominator.
8. Collect: expected supported events, appended unique events, accepted duplicates, rejected events, failed captures, unsupported/deferred events, ordering failures, correlation failures, envelope-validation failures, secret-scan failures, final capture rate.
9. Scan synthetic secrets across JSONL, results, diagnostics, metrics, logs, exceptions, and temporary files.
10. Confirm no path under the real `/home/brian-nguyen/.hermes` was written.
11. Remove all temporary artifacts.

## Acceptance criteria

| Criterion | Objective evidence |
|---|---|
| Capture rate >= 99% | Harness report |
| Every captured record passes validate_envelope | Per-record validation in harness |
| JSONL records independently parseable | Reparse JSONL lines |
| Deterministic serialization | Stable canonical JSON per record |
| Event/correlation identifiers preserved | Field assertions |
| Committed sequence valid and monotonic | Sequence assertions |
| Duplicate attempts no extra records | Store dedup assertions |
| Duplicate attempts no incorrect sequence advance | Sequence equality across duplicates |
| Observer non-interference | Reuse Increment 4.5 equivalence checks |
| Failure isolation | Injected failures reported, not propagated |
| No original synthetic secret anywhere | Secret scan |
| Conditional/deferred excluded from denominator | Separate counts |

## Files

Create:

```text
src/integration/capture_benchmark.py
tests/integration/test_m1_capture_rate.py
tests/integration/test_m1_final_acceptance.py
acceptance-m1-increment-4-6.md        # after verification only
acceptance-m1-final.md                # after verification only
runbooks/m1-increment-4-6-capture-rate.md
```

Modify after verification only:

```text
implementation-plan.json
project-state.yaml
```

Do not modify installed Hermes or verified Increment 1–4.5 modules unless a test-proven compatibility correction is separately reported and approved.

## Tests and commands

Focused:

```bash
.venv/bin/python -m pytest tests/integration/test_m1_capture_rate.py tests/integration/test_m1_final_acceptance.py -q
```

Canonical:

```bash
.venv/bin/python -m pytest tests/ -q
```

## Rollback

Create a checkpoint before implementation. Revert only the 4.6 commit, preserve JSONL records, and rerun Increment 1–4.5 focused/canonical suites. Never modify or delete real Hermes state or installed source.

Do not implement Increment 4.6 until separately approved.

**Increment 4.6 plan: READY FOR APPROVAL**

# End of file
