# Code Traceability v1.2.4

Mọi task phải chỉ ra contract, code owner, tests và evidence. Không chấp nhận mô tả “đã nối” nếu không có executable path.

## Runtime and capture map

| Contract | Production code | Test/evidence anchor |
|---|---|---|
| Public message observation | [`zero_mem/api.py`](../../zero_mem/api.py), [`zero_mem/local.py`](../../zero_mem/local.py) | [`tests/unit/test_v124_message_contract.py`](../../tests/unit/test_v124_message_contract.py) |
| Hermes hook registry | [`src/integration/bridge_config.py`](../../src/integration/bridge_config.py) | [`tests/unit/test_hermes_bridge_config.py`](../../tests/unit/test_hermes_bridge_config.py) |
| Semantic mapping/event ID | [`src/integration/payload_mapping.py`](../../src/integration/payload_mapping.py) | [`tests/unit/test_hermes_payload_fixtures.py`](../../tests/unit/test_hermes_payload_fixtures.py) |
| Non-interfering registration | [`src/integration/hermes_registration.py`](../../src/integration/hermes_registration.py) | [`tests/integration/test_m1_non_interference.py`](../../tests/integration/test_m1_non_interference.py) |
| Capture benchmark | [`src/integration/capture_benchmark.py`](../../src/integration/capture_benchmark.py) | [`tests/integration/test_m1_capture_rate.py`](../../tests/integration/test_m1_capture_rate.py) |
| Runtime ownership | [`src/integration/zero_mem_runtime.py`](../../src/integration/zero_mem_runtime.py) | runtime ownership/integration tests |
| Hermes composition/injection | [`zero_mem/hermes_integration.py`](../../zero_mem/hermes_integration.py), [`src/integration/m7/injection_adapter.py`](../../src/integration/m7/injection_adapter.py) | Hermes composition + injection gate tests |

## Storage and read map

| Contract | Production code | Required proof |
|---|---|---|
| Canonical append | [`src/storage/jsonl_capture.py`](../../src/storage/jsonl_capture.py) | durability, duplicate, secret, concurrency tests |
| Platform-safe filesystem | [`src/storage/platform.py`](../../src/storage/platform.py) | Windows/POSIX identity, lock, promotion, cleanup |
| Projection/watermark | [`src/storage/projection.py`](../../src/storage/projection.py), [`src/storage/ingest.py`](../../src/storage/ingest.py) | lag, retry, restart, rebuild tests |
| Derived SQLite/FTS5 | [`src/storage/sqlite_store.py`](../../src/storage/sqlite_store.py) | migration, FTS5 fallback, corruption tests |
| Authorization | [`src/access/authorized_read.py`](../../src/access/authorized_read.py), [`src/access/policy.py`](../../src/access/policy.py) | deny-before-read and non-leakage tests |
| Public read mapping | [`src/integration/public_read_adapter.py`](../../src/integration/public_read_adapter.py) | direct/sidecar parity tests |
| Local sidecar | [`src/integration/sidecar.py`](../../src/integration/sidecar.py) | bounds, timeout, overload and typed status tests |
| Recovery | [`src/storage/recovery.py`](../../src/storage/recovery.py), [`zero_mem/recovery.py`](../../zero_mem/recovery.py) | canonical immutability and atomic rebuild tests |

## Finding-to-package ledger

| Audit finding | Package | Acceptance signal |
|---|---|---|
| Message bị map thành session event | V124-01 | semantic user/assistant tests pass |
| Event ID mặc định bị trùng | V124-01 | distinct occurrence + retry-idempotency tests |
| Observation vẫn có injection | V124-02 | observe-mode negative registration test |
| Capture/read khác store | V124-03 | one-topology E2E + identity health field |
| Health/sync báo xanh giả | V124-03 | watermark/lag truth-table tests |
| Thiếu lifecycle quản lý memory | V124-04 | HITL proposal/confirm/supersession tests |
| Host có thể đoán khi `EMPTY` | V124-04 | host policy fixture handles evidence statuses |
| Windows/macOS assumptions | V124-05 | cross-platform matrix green |

## Change rule

Nếu thêm hoặc đổi public field, event type, status hoặc mode, Agent phải cập nhật đồng thời:

1. schema/contract;
2. producer mapping;
3. consumer/adapter;
4. migration/backward behavior;
5. positive + negative tests;
6. tài liệu trong thư mục này;
7. evidence record gắn exact commit SHA.
