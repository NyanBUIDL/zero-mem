# V124-03 Evidence — Single storage topology and truthful freshness

## Tested environment

- OS: Linux x86_64 (Ubuntu 7.0.0-30-generic)
- Python: 3.11.16
- pytest: 9.1.1
- Baseline SHA: `ebcc2d54eef8b1ce5e7f40bceaebf8e78f75bfe3`
- Tested SHA: post-commit SHA (working tree identical to committed candidate)

## Commands (sanitized)

```text
python -m pytest tests/unit/test_v124_storage_topology.py -v
python -m pytest tests/unit/test_v124_runtime_modes.py tests/unit/test_v124_storage_topology.py tests/unit/test_wp25_runtime_ownership.py tests/unit/test_v124_message_contract.py tests/integration/test_v123_hermes_host_composition.py -q
python -m compileall -q src/integration/zero_mem_runtime.py
git diff --check -- src/integration/zero_mem_runtime.py
```

## Results

- `tests/unit/test_v124_storage_topology.py`: **7 passed**
  - health publishes full freshness contract (capture_enabled, last_canonical_sequence,
    last_projected_sequence, lag, projection_status, read_store_identity, injection_enabled)
  - canonical sequence tracked independent of projection
  - sync() returns CURRENT only when derived watermark catches canonical watermark
  - capture receipt survives projection failure (canonical recorded regardless)
  - health reports UNAVAILABLE truthfully when projection missing (off mode)
  - single topology shutdown/restart resumes from watermark (no duplicate writer/identity)
  - capture/read/injection share one storage identity
- Regression (V124-02 + wp25 + v124-01 + v123 host composition): **63 passed**
- `compileall`: exit 0
- `git diff --check`: exit 0

## Independent review (Verification Agent equivalence)

- Diff reviewed from baseline SHA. No stub, no dead path, no duplicated composition, no false-success.
- Single topology preserved: `ZeroMemRuntime` still owns one writer + one derived store + one
  projection worker; no second canonical/derived path introduced.
- `sync()` never claims CURRENT unless `derived_sequence >= canonical_sequence` after flush.
- Capture success independent of projection (ADR-009): canonical sequence recorded before projection.
- No new dependency / LLM / network. Standard-library only.

## Verdict: PASS

## Known limitations / blockers

- Windows / macOS / Python 3.12 / 3.13 matrices NOT executed locally (not installed). Mode/projection
  logic is stdlib-only and platform-neutral; must be run by CI before RELEASE_QUALIFIED.
