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
