# M1 Maintenance — Deterministic redaction-audit observed_at

**Status:** PLAN (narrowly-scoped M1 maintenance, separate from M2)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`; `AGENTS.md`; `project-state.yaml`.
**Trigger:** M2.7 final acceptance requires a complete normal canonical-suite run without deselecting
`tests/unit/test_hermes_payload_fixtures.py::test_mapping_is_deterministic`. That test is the
documented pre-existing M1 timing flake (intermittent failure when two `map_hook_payload` calls
straddle a wall-clock second boundary, because `RedactionAudit.observed_at` is set from
`datetime.now()` per call).

## Scope

This is a SEPARATE maintenance task. It is NOT part of M2 product implementation and does not touch
any M2.1–M2.6 code. It fixes only the deterministic-time source of the M1 flake in
`src/redaction/redactor.py`.

## Root cause

`src/redaction/redactor.py::_utc(value)` returns `datetime.now(timezone.utc)...` when `value is None`.
`redact_payload` calls `_utc(observed_at)` with `observed_at=None` by default, so
`RedactionAudit.observed_at` is wall-clock per call. `map_hook_payload` is otherwise a pure function
of `(hook, payload)`, so `test_mapping_is_deterministic` fails intermittently when the two calls
land in different clock seconds.

## Fix (smallest deterministic-time change)

In `src/redaction/redactor.py`:
- Define a module-level `DEFAULT_OBSERVED_AT = "1970-01-01T00:00:00.000Z"`.
- `_utc(value)` returns `value` if provided, else `DEFAULT_OBSERVED_AT` (deterministic sentinel).

Real capture (`src/capture/adapter.py`, `src/integration/capture_adapter.py`) always passes an
explicit `observed_at` derived from the payload / `utc_now()`, so real redaction timestamps are
unchanged. Only the no-arg default — exercised by the deterministic-mapping unit test — becomes
stable. This makes `map_hook_payload` a true pure function of its inputs, satisfying the test
without weakening or removing it.

## Verification

1. Focused M1 flake test (must be deterministic and green):
   `.venv/bin/python -m pytest tests/unit/test_hermes_payload_fixtures.py::test_mapping_is_deterministic -q`
   Run in a tight loop (>=20 iterations) to confirm no intermittent failure.
2. Full canonical suite (no deselect):
   `.venv/bin/python -m pytest tests/ -q`
   Must pass with the M1 flake gone.

## Out of scope

No M2 behavior changes. No M3 behavior. No schema change. No test weakening/removal.
