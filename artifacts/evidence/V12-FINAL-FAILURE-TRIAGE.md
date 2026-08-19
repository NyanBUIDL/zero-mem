# Zero-Mem v1.2.0 Final Failure Triage

## Baseline

- RC checkpoint: `bd2728ff9c5f1012bb9366c24508c95f67425121`
- Original release-gate result: `3240 passed, 19 failed, 5 skipped`; exit `1`
- Original raw log: `/dev/shm/zero-mem-v12-final-gate.log`
- Reproduction after controlled HOME creation: `3241 passed, 18 failed, 5 skipped`; one additional environment failure was not reproduced.

## Failure inventory

| # | Test | Fingerprint / classification |
|---:|---|---|
| 1 | `tests/unit/test_m7_1_master_gate.py::TestSingleAuthority::test_config_is_canonical_source` | stale process-global runtime overrode explicit config; PRODUCT_REGRESSION |
| 2 | `tests/unit/test_m7_1_master_gate.py::TestAdapterEnabledDistinction::test_master_off_adapter_on_unavailable` | same runtime-state root cause; PRODUCT_REGRESSION |
| 3 | `tests/unit/test_m7_1_master_gate.py::TestAdapterEnabledDistinction::test_master_off_adapter_off_unavailable` | same runtime-state root cause; PRODUCT_REGRESSION |
| 4 | `tests/unit/test_m7_1_master_gate.py::TestM6ReadGate::test_all_ten_tools_return_disabled` | same runtime-state root cause; PRODUCT_REGRESSION |
| 5 | `tests/unit/test_m7_1_master_gate.py::TestM6ReadGate::test_off_does_not_open_db` | same runtime-state root cause; PRODUCT_REGRESSION |
| 6 | `tests/unit/test_m7_1_master_gate.py::TestM6ReadGate::test_handler_registration_respects_off` | same runtime-state root cause; PRODUCT_REGRESSION |
| 7 | `tests/unit/test_m7_1_master_gate.py::TestPersistence::test_off_then_on_old_memory_readable` | same runtime-state root cause; PRODUCT_REGRESSION |
| 8 | `tests/unit/test_m7_1_master_gate.py::TestPersistence::test_on_then_off_subsequent_disabled` | same runtime-state root cause; PRODUCT_REGRESSION |
| 9 | `tests/unit/test_m7_1_master_gate.py::TestFailureIsolation::test_off_with_missing_db_safe` | same runtime-state root cause; PRODUCT_REGRESSION |
| 10 | `tests/unit/test_m7_1_master_gate.py::TestRuntimeAudit::test_no_independent_automatic_runtime_path` | audit searched approved bounded storage loops; STALE_TEST_EXPECTATION |
| 11 | `tests/unit/test_m7_2_memory_router.py::TestM7_1Regression::test_master_off_all_ten_m6_tools_disabled` | same runtime-state root cause; PRODUCT_REGRESSION |
| 12 | `tests/unit/test_m7_6_end_to_end.py::TestRealHermesIntegration::test_current_m8_m10_fields_survive_real_hook_path` | injected test double lacked `close`; PRODUCT_REGRESSION |
| 13 | `tests/unit/test_m9_6_hardening.py::test_unconfigured_returns_unavailable_and_creates_nothing` | configured HOME directory did not exist; TEST_ENVIRONMENT_REGRESSION |
| 14 | `tests/unit/test_pkg4_hermes_integration.py::test_boundary_registers_hook_tool_and_injection_surfaces` | stale global disabled state blocked enabled boundary; PRODUCT_REGRESSION |
| 15 | `tests/unit/test_pkg4_hermes_integration.py::test_boundary_adapts_successful_read_tool_registration` | same boundary state root cause; PRODUCT_REGRESSION |
| 16 | `tests/unit/test_pkg4_hermes_integration.py::test_registration_failure_isolated` | same boundary state root cause; PRODUCT_REGRESSION |
| 17 | `tests/unit/test_wp25_runtime_ownership.py::test_production_adapter_observes_without_injected_store` | stale disabled runtime prevented owned writer; PRODUCT_REGRESSION |
| 18 | `tests/unit/test_wp25_runtime_ownership.py::test_registration_adapter_uses_runtime_owned_injected_test_store` | stale disabled runtime prevented injected writer; PRODUCT_REGRESSION |
| 19 | `tests/unit/test_wp31_hermes.py::test_wp31_read_adapter_uses_bounded_sidecar_and_restarts` | stale disabled runtime prevented sidecar startup; PRODUCT_REGRESSION |

## Root-cause map

### ROOT_CAUSE_A — adapter-local configuration was overridden by stale process-global state

- Affected: 1–9, 11, 17–19; also contributed to 14–16.
- Symptom: explicit `BridgeConfig(zero_mem_enabled=...)` was ignored after an earlier adapter configured the compatibility runtime.
- Cause: adapters retained/reused the module-level runtime object instead of owning a composition-local gate while still honoring an explicitly changed global gate.
- Minimum correction: use an instance-scoped `ZeroMemRuntime` for adapter composition; detect a replacement process-global runtime for explicit shutdown/disable propagation. Boundary lifecycle tracks only its own disabled runtime so it cannot re-enable an external disabled runtime.
- Risk: lifecycle interactions between adapter-local and process-global state; covered by WP-25/WP-31 tests and focused regression.

### ROOT_CAUSE_B — injection cleanup assumed a richer test double than the interface requires

- Affected: 12.
- Symptom: valid injected EvidenceSet was converted to `downstream_error` because `object()` has no `close()`.
- Cause: unconditional cleanup call.
- Minimum correction: call `close()` only when callable; real services still close normally.

### ROOT_CAUSE_C — M7.1 audit test included bounded storage implementation loops

- Affected: 10.
- Symptom: broad grep found `while True` in JSONL/coordination/recovery storage code.
- Cause: test expectation predated WP-27 bounded storage coordination/recovery implementation and conflated storage retry loops with independent automatic runtime paths.
- Classification: STALE_TEST_EXPECTATION. The test now scopes its audit to `src/integration`, the component boundary owned by M7.1. WP-27 storage loops remain subject to their own bounded/failure tests.
- Authority: WP-27 acceptance/technical design and M7.1 audit intent (no independent integration runtime path).

### ROOT_CAUSE_D — release gate HOME fixture was absent

- Affected: 13 only.
- Symptom: `Path.home().iterdir()` raised `FileNotFoundError`.
- Cause: the release-gate shell setup selected an isolated HOME path without creating it.
- Classification: TEST_ENVIRONMENT_REGRESSION, not product behavior. Re-run with `mkdir -p` passed the test; no product or test edit required.

## Correction record

Changed product paths:

- `src/integration/hermes_registration.py`
- `src/integration/hermes_read_adapter.py`
- `src/integration/m7/injection_adapter.py`
- `zero_mem/hermes_integration.py`

Changed test path:

- `tests/unit/test_m7_1_master_gate.py`

The test change narrows an over-broad implementation audit; it does not weaken an executable product contract. No feature, dependency, schema, canonical storage, or architecture expansion was introduced.

## Focused verification

Command used with isolated HOME/XDG roots and `/dev/shm` basetemp:

```text
.venv/bin/python -m pytest \
  tests/unit/test_m7_1_master_gate.py \
  tests/unit/test_m7_2_memory_router.py \
  tests/unit/test_m7_6_end_to_end.py \
  tests/unit/test_m9_6_hardening.py \
  tests/unit/test_pkg4_hermes_integration.py \
  tests/unit/test_wp25_runtime_ownership.py \
  tests/unit/test_wp31_hermes.py \
  --basetemp=/dev/shm/zero-mem-v12-focus-pytest -q
```

Result: **257 passed, 0 failed**.

The original 19 failures are therefore explained by four bounded clusters: three product-regression clusters, one stale test expectation, and one test-environment setup failure. No failure was accepted as an unexplained baseline exclusion.

## Requalification result

- Final focused affected suite after all corrections: `257 passed, 0 failed`.
- Final exact release suite: `3259 passed, 5 skipped, 0 failed`, exit `0`, duration `52.73s`.
- Replacement independent review: `passed: true`; blocking findings, security concerns, logic errors, and release risks all empty.
- `FINAL_V1_2_REQUALIFICATION: PASS`.
