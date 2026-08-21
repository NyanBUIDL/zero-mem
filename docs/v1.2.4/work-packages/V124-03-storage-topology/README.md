# V124-03 — Single storage topology and truthful freshness

Status: IMPLEMENTED_VERIFIED
Owner: Lead Delivery Agent
Baseline SHA: ebcc2d54eef8b1ce5e7f40bceaebf8e78f75bfe3
Depends on: V124-02 (IMPLEMENTED_VERIFIED @ ebcc2d5)

## Authority and problem

- Master plan V124-03: one runtime composition owns canonical writer, projection
  coordinator, derived DB, authorized read service. No config that captures to A but
  reads/injects from B. Health must publish at least: capture_enabled,
  last_canonical_sequence, last_projected_sequence, lag, projection_status,
  read_store_identity, injection_enabled. `sync()` returns CURRENT only when the derived
  watermark catches the canonical watermark.
- ADR-009: JSONL canonical; SQLite derived/rebuildable. Capture success independent of
  projection success. Projection failure keeps capture receipt and yields STALE/UNAVAILABLE.
- Problem: `RuntimeHealth` does not yet publish the full freshness contract; `sync()` does
  not exist on the runtime (only `flush_projection`). Capture/read/injection/health must
  report the same storage identity.

## In scope

- Production: `src/integration/zero_mem_runtime.py` (RuntimeHealth fields; health(); sync()).
- Test: `tests/unit/test_v124_storage_topology.py`.

## Out of scope

- V124-04 HITL (separate package).
- V124-05 cross-platform packaging (separate package).
- Changing canonical/derived boundary, auth, or adding LLM/network.

## Contract

| Input/state | Output/status | Side effects |
|---|---|---|
| capture ok, projection ok, watermarks equal | health.projection_status=DERIVED_CURRENT, lag=0, sync()=CURRENT | none |
| capture ok, projection lagging | health.lag>0, projection_status=DERIVED_PENDING, sync()=STALE | none (capture receipt kept) |
| capture ok, projection unavailable | health.projection_status=DERIVED_UNAVAILABLE, sync()=UNAVAILABLE | none (capture receipt kept) |
| capture/read/injection | all report same read_store_identity (derived path) | none |
| restart | resumed from watermark, no duplicate writer/projection | none |

Backward compatibility: RuntimeHealth gains optional fields; existing positional callers
(health tests) updated. No public contract removed.

## Security and compatibility

- Capture success never downgraded by projection failure.
- Health reads a snapshot; no side effect to "green" itself.
- read_store_identity is the runtime-owned derived path; no raw secret/private path leak.
- No new dependency / LLM / network.

## Acceptance commands

```text
python -m pytest tests/unit/test_v124_storage_topology.py -q
python -m pytest tests/unit/test_wp25_runtime_ownership.py tests/unit/test_v124_runtime_modes.py -q
python -m py_compile src/integration/zero_mem_runtime.py
git diff --check
```

## Required evidence

- Tested full SHA: <filled after tests pass>
- Environment: Linux x86_64, Python 3.11.16
- Results: <pass/fail counts>
- Known limitations: Windows/macOS + Python 3.12/3.13 matrices not executable locally.
- Reviewer: independent Verification Agent pass
