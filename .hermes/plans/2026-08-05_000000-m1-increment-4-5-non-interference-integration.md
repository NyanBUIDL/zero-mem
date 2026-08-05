# M1 Increment 4.5 — Non-Interference Integration Plan

**Status:** READY FOR APPROVAL

## Objective

Exercise the project-local registration bridge against isolated Hermes-like runtime fixtures and prove that enabled observation does not mutate Hermes inputs, outputs, control flow, session/task state, or exit behavior. This increment is verification-focused and follows the verified 4.4 registration adapter.

## Scope

In scope:

- isolated temporary `HERMES_HOME` runtime harness;
- temporary capture root;
- synthetic session/tool/Kanban callbacks;
- enabled versus disabled execution comparison;
- input, nested payload, result, exception, and return-value comparisons;
- registration/callback/adapter/storage failure isolation;
- installed Hermes source status/hash inspection;
- sanitized diagnostics and secret scans;
- non-interference acceptance evidence and runbook.

Explicit exclusions:

- new hook classes or conditional-hook registration;
- capture-rate benchmark (Increment 4.6);
- retries, backoff, dead letters;
- SQLite, retrieval, MCP, Obsidian, prompt/context injection;
- modifications to installed Hermes source or real Hermes state.

## Harness design

Create a controlled harness that:

1. Creates `TemporaryDirectory(prefix="hermes-verify-")` for `HERMES_HOME` and capture storage.
2. Sets explicit synthetic `project_id` and `profile_id`.
3. Instantiates the project-local `RegistrationAdapter` with an injected fake store.
4. Runs the same synthetic callback sequence with bridge disabled and enabled.
5. Compares callback positional/keyword payloads before and after.
6. Compares tool arguments, tool results, Kanban transition data, session IDs, and neutral callback return values.
7. Injects mapping, redaction, envelope, store, registration, and shutdown failures.
8. Confirms failures do not propagate or alter observable control flow.
9. Scans JSONL, diagnostics, exceptions, logs, reports, and temporary artifacts for synthetic secret corpus values.
10. Confirms no path under the real `/home/brian-nguyen/.hermes` was written.
11. Captures installed Hermes source status and commit before/after; any pre-existing modification is reported, never overwritten.
12. Removes all temporary artifacts.

## Acceptance criteria

| Criterion | Objective evidence |
|---|---|
| Enabled/disabled behavior equivalent | Same synthetic action and callback observations except expected sanitized capture side effects |
| Callback arguments immutable | Deep before/after equality for positional, keyword, and nested values |
| Tool/result/session/Kanban non-interference | Explicit before/after assertions |
| Neutral return values | Callback returns the verified neutral value in both paths |
| Failure isolation | Injected failures produce fixed diagnostics and no propagated exceptions |
| Secret absence | Corpus scan finds no secrets in output, diagnostics, logs, exceptions, or temp files |
| Temporary-home isolation | Runtime writes confined to temporary roots; real home unchanged |
| Installed-source protection | Hermes source status/commit unchanged by tests |
| Registration compatibility | 4.4 focused integration tests pass under isolated harness |
| Scope protection | No conditional/deferred hooks, retries, dead letters, retrieval, or injection added |

## Files

Create:

```text
src/integration/non_interference.py
tests/integration/test_m1_non_interference.py
tests/integration/test_m1_failure_isolation.py
acceptance-m1-increment-4-5.md  # after verification only
runbooks/m1-increment-4-5-non-interference.md
```

Modify after verification only:

```text
implementation-plan.json
project-state.yaml
```

Do not modify installed Hermes or verified Increment 1–4.4 modules unless a test-proven compatibility correction is separately reported and approved.

## Tests and commands

Focused:

```bash
.venv/bin/python -m pytest tests/integration/test_m1_non_interference.py tests/integration/test_m1_failure_isolation.py -q
```

Canonical:

```bash
.venv/bin/python -m pytest tests/ -q
```

A temporary verifier is allowed only for a runtime observation not expressible in tests; use `tempfile`, `hermes-verify-`, synthetic values only, no destructive commands, and clean it afterward.

## Rollback

Create a checkpoint before implementation. Disable the bridge, revert only the 4.5 commit, preserve JSONL records, and rerun Increment 1–4.4 focused/canonical suites. Never modify or delete real Hermes state or installed source.

Do not implement Increment 4.5 until separately approved.

**Increment 4.5 plan: READY FOR APPROVAL**

# End of file
    