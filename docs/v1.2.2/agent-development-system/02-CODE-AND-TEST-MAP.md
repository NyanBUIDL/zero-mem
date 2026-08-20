# 02 — Code and test map

This map is the required navigation layer. An agent must modify the named owner or add an explicitly approved adapter; it must not copy behavior into a second implementation.

| Concern | Current owner | Required tests/evidence | v1.2.2 action |
|---|---|---|---|
| Public API contracts | [`zero_mem/api.py`](../../../zero_mem/api.py#L50) (`PublicClient`), [`zero_mem/api.py`](../../../zero_mem/api.py#L135) (`AsyncClient`) | [`tests/unit/test_wp28_public_api.py`](../../../tests/unit/test_wp28_public_api.py) | Replace unavailable read stubs through an injected, storage-neutral read-service protocol. |
| Capture receipt | [`zero_mem/core.py`](../../../zero_mem/core.py#L23) and [`zero_mem/core.py`](../../../zero_mem/core.py#L57) | `tests/unit/test_wp24_correctness_backport.py` | Preserve durable receipt semantics; never use projection success as capture success. |
| Runtime ownership | [`src/integration/zero_mem_runtime.py`](../../../src/integration/zero_mem_runtime.py#L71) | `tests/unit/test_wp25_runtime_ownership.py` | Compose writer, projection lifecycle and health in one owned runtime. |
| Canonical-to-derived projection | [`src/storage/projection.py`](../../../src/storage/projection.py#L56), [`src/storage/ingest.py`](../../../src/storage/ingest.py#L525) | `tests/unit/test_wp26_projection.py` | Wire `ProjectionCoordinator` into runtime; expose canonical/projected sequences. |
| Recovery | [`zero_mem/recovery.py`](../../../zero_mem/recovery.py#L242) and `src/storage/recovery.py` | `tests/unit/test_wp27_recovery.py` | Keep diagnosis/rebuild one-way and add platform contract coverage. |
| Authorization-first reads | [`src/access/authorized_read.py`](../../../src/access/authorized_read.py#L187) | [`tests/unit/test_wp29_authorization.py`](../../../tests/unit/test_wp29_authorization.py) | Add public adapters only; do not recreate authorization/query logic. |
| Bounded sidecar | [`src/integration/sidecar.py`](../../../src/integration/sidecar.py#L70) | `tests/unit/test_wp30_sidecar.py` | Make this the canonical public transport contract; keep legacy shim only for compatibility. |
| Legacy public sidecar | [`zero_mem/sidecar.py`](../../../zero_mem/sidecar.py) | `tests/unit/test_wp21_sidecar.py` | Map/deprecate safely; public exports must not misstate capabilities. |
| Hermes capture | [`src/integration/hermes_registration.py`](../../../src/integration/hermes_registration.py#L26) and [`src/integration/hermes_plugin.py`](../../../src/integration/hermes_plugin.py#L10) | [`tests/integration/test_hermes_registration_v0191.py`](../../../tests/integration/test_hermes_registration_v0191.py) | Host factory must compose the approved lifecycle, not just a test-only hook wrapper. |
| Hermes reads/injection | [`src/integration/hermes_read_adapter.py`](../../../src/integration/hermes_read_adapter.py#L83), [`zero_mem/hermes_integration.py`](../../../zero_mem/hermes_integration.py#L311) | [`tests/unit/test_wp31_hermes.py`](../../../tests/unit/test_wp31_hermes.py) | Prove capture, read, restart, disable and shutdown end-to-end. |
| Platform safety | [`src/storage/coordination.py`](../../../src/storage/coordination.py), [`src/storage/runtime_root.py`](../../../src/storage/runtime_root.py) | process/path tests; new OS matrix | Isolate POSIX details behind a platform contract and add Windows/macOS backends. |
| Retrieval benchmark | [`benchmarks/wp33_lexical_benchmark.py`](../../../benchmarks/wp33_lexical_benchmark.py) | [`tests/unit/test_wp33_retrieval.py`](../../../tests/unit/test_wp33_retrieval.py) | Keep benchmark deterministic and portable; benchmark code may not secretly reimplement retrieval. |

## Audit ledger at v1.2.2 baseline

| Audit ID | Baseline result | Package that closes it |
|---|---|---|
| A-01 | Four public read methods return `CAPABILITY_NOT_IMPLEMENTED`. | V122-03 |
| A-02 | WP-33 import was restored in v1.2.1. | V122-01 verifies it on every supported OS. |
| A-03 | `ProjectionCoordinator` exists but lacks proven runtime composition. | V122-02 |
| A-04 | Legacy `LocalSidecar` is deprecated but not canonical parity. | V122-04 |
| A-05 | `create_plugin` composes capture only; complete host lifecycle is unproven. | V122-05 |
| A-06 | Core locking/path code is POSIX/Linux-specific. | V122-01 |
| A-07 | v1.2.1 assets have SHA-256 evidence; reproducibility must be automated. | V122-06 |
| A-08 | Windows/macOS matrix is absent; Windows focused tests currently fail rather than qualify/skip deliberately. | V122-01 and V122-06 |

No package may mark an ID closed merely because a helper exists, a legacy test expects unavailability, or a historical report says `VERIFIED`.
