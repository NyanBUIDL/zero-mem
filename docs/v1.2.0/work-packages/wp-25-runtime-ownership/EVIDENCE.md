# WP-25 Evidence

## Identity and authorization

- WP: WP-25 Runtime Ownership
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Canonical workspace: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Authorization: `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; routine WP approval not required; architecture escalation required; release publication not authorized.
- Dependency: WP-24 `VERIFIED`.

## Changed files

- `src/integration/zero_mem_runtime.py`
- `src/integration/hermes_registration.py`
- `tests/unit/test_wp25_runtime_ownership.py`
- WP-25 planning/acceptance documentation.

## Implementation evidence

- Added `RuntimeConfig` with explicit-root safety validation; explicit roots inside the real home are rejected.
- `ZeroMemRuntime.open()` is the composition root that creates `JsonlCaptureStore` from an explicit validated root.
- Runtime instance owns one writer and closes it idempotently; access after close is rejected.
- Disabled runtime creates no writer and reports `ZERO_MEM_DISABLED`.
- Compatibility `configure/get_runtime` retains only master boolean state and never owns a writer.
- `RegistrationAdapter` consumes the runtime-owned writer, invokes capture in the production no-injected-store path, and delegates shutdown to the runtime.
- No SQLite, projection queue, derived-state mutation, dependency, release, tag, push, or publication was added.

## Commands and results

- Workspace invariant: passed. Root `/home/lenovo/Hermes Workspace/zero-mem-v1.1`; GitHub remote `git@github.com:NyanBUIDL/zero-mem.git`; branch `NyanBUIDL-Zero-mem`; HEAD `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`.
- RED test: `.venv/bin/python -m pytest tests/unit/test_wp25_runtime_ownership.py -q` failed during collection because `RuntimeConfig`/`ZeroMemRuntime.open` did not yet exist (expected missing-contract failure).
- Focused WP-25 tests: `.venv/bin/python -m pytest tests/unit/test_wp25_runtime_ownership.py -q` → `5 passed in 0.18s`.
- Runtime/M1/Hermes regression: `.venv/bin/python -m pytest tests/unit/test_m7_1_master_gate.py tests/unit/test_m7_5_hardening.py tests/unit/test_m7_6_end_to_end.py tests/unit/test_m1_capture_boundary.py tests/integration/test_hermes_registration_v0191.py tests/integration/test_hermes_registration_non_interference.py tests/integration/test_m1_failure_isolation.py tests/integration/test_wp02_boundary_integration.py tests/unit/test_wp25_runtime_ownership.py -q` → `226 passed in 0.98s`.
- M1/M7/Hermes regression: `.venv/bin/python -m pytest tests/integration/test_m1_final_acceptance.py tests/integration/test_m1_capture_rate.py tests/integration/test_m1_failure_isolation.py tests/integration/test_m1_non_interference.py tests/unit/test_m1_capture_boundary.py tests/unit/test_m7_1_master_gate.py tests/unit/test_m7_5_hardening.py tests/unit/test_m7_6_end_to_end.py tests/integration/test_hermes_registration_v0191.py tests/integration/test_hermes_registration_non_interference.py tests/integration/test_wp02_boundary_integration.py tests/unit/test_wp25_runtime_ownership.py -q` → `259 passed in 0.99s`.
- Isolated full regression: `HOME=/home/lenovo/.hermes-test-home-5 XDG_CONFIG_HOME=/home/lenovo/.hermes-test-config-5 XDG_DATA_HOME=/home/lenovo/.hermes-test-data-5 XDG_STATE_HOME=/home/lenovo/.hermes-test-state-5 .venv/bin/python -m pytest tests/ --ignore=tests/baseline/test_project_artifacts.py -q` → `3177 passed, 5 skipped in 43.71s`.
- Static checks: `git diff --check` and `.venv/bin/python -m compileall -q src/integration/zero_mem_runtime.py src/integration/hermes_registration.py tests/unit/test_wp25_runtime_ownership.py` → pass.
- Graphify final local-tree read-only analysis after final fixes: `7090 nodes, 20944 edges, 200 communities`; `ZeroMemRuntime` connects to `JsonlCaptureStore`, `CaptureStoreConfig`, `RegistrationAdapter`, and WP-25 tests. Disposable output: `/home/lenovo/graphify-zero-mem-v1.2-wp25-final2`.

## Security and boundary review

- Adapter no longer instantiates `JsonlCaptureStore` or resolves a writer path.
- Canonical JSONL remains the sole event truth; runtime close only releases the existing lock/file handle.
- No secrets or payload values are logged or persisted by the runtime.
- No future WP-26 projection behavior was introduced.

## Independent review

Fresh independent fail-closed review passed: `passed: true`, with empty `security_concerns` and `logic_errors`. Reviewer confirmed absolute-root/path safety, instance writer ownership, master-gate enforcement, durable receipt propagation, lifecycle behavior, canonical/derived boundary preservation, and no WP-26+ scope creep. Non-blocking suggestions were recorded for future hardening only: additional writer-construction-failure tests, invalid injected-store tests, and a redundant local assignment cleanup.

## Final acceptance

`VERIFIED`. No escalation is active. WP-26 is the next dependency-ready package.
