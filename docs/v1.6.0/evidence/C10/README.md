# Evidence C10

- Scope: Legacy/E2E/benchmark/release gates.
- Implementation commit: `2423878`.
- Executable test: [`tests/integration/test_v160_c10_multi_ks_acceptance.py`](../../../../tests/integration/test_v160_c10_multi_ks_acceptance.py).
- Verdict: PASS trong focused C1–C10 run (`66 passed`).

Local full suite: `3618 passed, 38 skipped, 0 failed`. Remote CI và release là gate riêng.

Remote run đầu tại exact SHA `cc8a5c4` đạt 7/9 cell. Windows 3.11 phát hiện
Python cũ chưa có `Path.is_junction()` và test DEF-036 phụ thuộc timer 2 ms;
Windows 3.13 phát hiện cùng timing test. Follow-up dùng Windows reparse attributes
và explicit worker barrier; local full suite sau fix vẫn `3618/38/0`.

Remote run thứ hai tại exact SHA `78738ae` đạt 7/9 cell: toàn bộ Ubuntu và
Windows xanh, macOS 3.11 xanh. macOS 3.12 phát hiện test đa tiến trình dùng
`fork` từ pytest process đa luồng; macOS 3.13 phát hiện pin test DEF-026 đo
snapshot executor queue phụ thuộc scheduler. DEF-039/DEF-040 chuyển test sang
barrier + eventual-drain contract và portable `spawn`; local focused `5 passed`,
hai test mục tiêu `2 passed` ×10, full suite `3628 passed, 38 skipped, 0 failed`.
Remote macOS requalification còn là gate trước khi đóng hai defect.

Run `33043577737` xác nhận DEF-039 xanh trên macOS 3.13 nhưng DEF-040 vẫn fail
trên macOS 3.12 sau khi đổi sang `spawn`: failure nằm ở hai child đồng thời tạo
lock file trên root trống. Follow-up bootstrap canonical root bằng owner parent
trước contention, đúng runtime-ownership boundary; phần concurrent append và
100-record integrity assertions không đổi. Local test mục tiêu `1 passed` ×10,
focused `5 passed`, full suite `3628 passed, 38 skipped, 0 failed`.

Run cuối [33044025860](https://github.com/NyanBUIDL/zero-mem/actions/runs/33044025860)
tại exact SHA `6433fb2` đạt **9/9 cell**. Ubuntu, Windows và macOS đều PASS trên
Python 3.11, 3.12, 3.13; DEF-039/040 được đóng. DX01 wizard sau đó đạt 9/9 tại
exact SHA `68bdf29` trong run
[33045453992](https://github.com/NyanBUIDL/zero-mem/actions/runs/33045453992).

## Benchmark junction

Command: `python benchmarks/v160_junction_lookup.py --sizes 1000 10000 100000 --repeats 1000`

| Events | Junction rows | Median | p95 | DB bytes |
|---:|---:|---:|---:|---:|
| 1,000 | 2,000 | 10.3 µs | 13.4 µs | 143,360 |
| 10,000 | 20,000 | 10.2 µs | 13.4 µs | 1,294,336 |
| 100,000 | 200,000 | 14.0 µs | 23.3 µs | 13,135,872 |

Mọi size đều dùng `SEARCH zm_event_spaces USING COVERING INDEX
sqlite_autoindex_zm_event_spaces_1 (event_id=? AND knowledge_space_id=?)`.
Số đo gồm Python/SQLite call overhead và là evidence của máy qualification,
không phải SLA đa nền tảng.
