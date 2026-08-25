# EVIDENCE — Zero-Mem v1.5.1 Finish (candidate tree, chưa commit)

Môi trường: Python 3.13.15 (`zero-mem-dev-data/venvs/v133-test-venv`), pytest 9.1.1, Linux, isolated HOME `/tmp/zm-test-home`. Baseline: tag `v1.5.0` @ 10ad8da. Tất cả lệnh chạy với workdir = repo root.

## B1 — Recon dispatcher/admission (Phase 4)

Graphify read-only trên cây hiện tại (bản sao phân tích trong dev-data, không đụng repo):

```
$ graphify update <copy> --no-cluster
[graphify watch] Rebuilt (no clustering): 14988 nodes, 33790 edges
```
Snapshot: `zero-mem-dev-data/graphify/v151-finish-b1/graphify-out/` (log: `evidence/v151f-graphify-extract.log`).

Ownership grep:
```
$ grep -rnE 'deadline|timeout|max_concurrency|ThreadPoolExecutor|Queue|Future' \
    src/integration/m7/ src/corpus/ zero_mem/sidecar.py src/integration/sidecar.py zero_mem/api.py
→ owners: src/integration/sidecar.py (sync sidecar), zero_mem/api.py (AsyncClient), zero_mem/sidecar.py (config)
```
Full output: `evidence/v151f-b1-grep.txt`.

## B2 — DEF-026 (async deferred cancellation) — CLOSED no-defect

Probe RED-phase (100 request timeout khi worker block):
```
$ python evidence/v151f-b1-async-probe.py          # zero-mem-dev-data/evidence/
statuses: {'timeout': 98, 'ok': 2, 'queue_full': 0}
executor_work_queue_len_after_100_timeouts: 98
worker_threads: 1
```

Probe quyết định (cancel có propagate xuống concurrent.Future CHƯA start?):
```
$ python evidence/v151f-b1-execution-probe5.py     # real PublicClient + blocking writer
timeouts: 20
queue_size_while_worker_blocked: 20
queue_size_after_drain: 0
total_appended_events: 1   ← expected 21 nếu abandoned work chạy; =1 ⇒ cancel-before-start THẬT
```

CPython semantics control:
```
$ python evidence/v151f-b1-cancel-probe3.py
queue while blocked: 10
asyncio futures cancelled: True
executed after release: []
```

Sync sidecar control (sequence-100 timeout):
```
$ python evidence/v151f-b1-saturation-probe.py
statuses: {'DEADLINE_EXCEEDED': 100}
admitted_after_drain: 0
pending_futures_after_drain: 0
threads_during_test_max_observed_at_end: 3
close_complete: True
```

Kết luận: không có defect hành vi. Registry entry DEF-026 CLOSED no-defect; pin tests:
```
$ HOME=/tmp/zm-test-home <venv>/bin/python -m pytest -q -p no:cacheprovider \
    tests/unit/test_v151_phase4_async_cancellation.py
2 passed in 2.01s
```

## B3 — Performance evidence

### SQL trace (limit=1 → LIMIT 2; zero unbounded page query)

Sau fix DEF-027 (`evidence/v151f-b3-sql-trace2-after-fix.out`, fixture 300 events):
```
FTS path:      zm_meta SELECTs: 1 | without numeric LIMIT: 0 | last SELECT LIMIT: ['2']
Structured:    zm_meta SELECTs: 2 | without numeric LIMIT: 0 | LIMIT values: [['2'], ['2']]
Pagination walk (limit=5): pages: 60 | sum items: 300
```
Page-1 query giờ mang keyset clause `(created_at, event_id) > (?, ?)` (trước fix: v151f-b3-minrepro6.out cho thấy page-1 KHÔNG có).

### tracemalloc peak tại 1k/10k/100k rows zm_meta

`evidence/v151f-b3-tracemalloc.out` (số đo thật, không trần bịa):
```
rows=1000:   single-page peak=21590B  full-walk pages=200  items=1000   walk-cumulative-peak=73358B
rows=10000:  single-page peak=20574B  full-walk pages=2000 items=10000  walk-cumulative-peak=72110B
rows=100000: single-page peak=20574B  full-walk pages=6289*items=31443* walk-cumulative-peak=72110B
(*script timeout 7 phút dừng walk 100k giữa chừng — per-page memory flat đã đủ chứng minh;
 completeness full-walk chứng minh riêng ở repro 300 rows.)
```
Single-page peak FLAT theo N ⇒ bounded-query remediation đúng.

### Registry benchmark (DEF-023) — script ngoài repo

`evidence/v151f-b3-registry-bench.py` → `v151f-b3-registry-bench.out`:
```
N=100:  total=0.0184s (0.184 ms/source) | bytes old-model=742350    vs new=72990   (x10)
N=500:  total=0.0574s (0.115 ms/source) | bytes old-model=18411750  vs new=365390  (x50)
N=1000: total=0.1196s (0.12  ms/source) | bytes old-model=73573500  vs new=730890  (x101)
N=5000: total=0.5548s (0.111 ms/source) | bytes old-model=1837867500 vs new=3658890 (x502)
per-source ms FLAT khi N ×50 ⇒ O(1) amortized xác nhận.
```
(old-model = deterministic cost model của happy path cũ: append + full rewrite mỗi lần đăng ký.)

## B3.5 — DEF-027 phát hiện + fix (keyset pagination data loss)

RED (trước fix):
```
$ HOME=/tmp/zm-test-home <venv>/bin/python -m pytest -q -p no:cacheprovider \
    tests/unit/test_v151_finish_def027_keyset.py
FAILED ...::test_full_walk_returns_every_event
FAILED ...::test_page2_starts_after_page1_boundary
2 failed in 0.13s
```
Standalone repro: `evidence/v151f-b3-def027-repro.out` — `pages: 2, unique events retrieved: 6 of 300`.

Root cause: `query_events` decode cursor nhưng không truyền `keyset` cho `_select_m3` (authorized_read.py call-site). Fix nhỏ nhất: thêm `keyset=keyset` vào đúng 1 call site.

GREEN (sau fix):
```
tests/unit/test_v151_finish_def027_keyset.py — 2 passed in 0.14s
Repro: pages: 60 | unique events retrieved: 300 of 300 | GREEN: full walk complete
```

Regression auth/retrieval/pagination:
```
test_m3_pagination test_m3_query test_m5_authorized_read test_m5_cross_profile
test_m8_3_authorization_first test_v151_wp01_fts_ks_auth test_v151_wp02_limit_and_fts_ceiling
test_v150_wp2_per_row_ks test_v130_02_ks_filter
→ 201 passed in 1.92s
```

Registry entry DEF-027: OPEN → FIXED với evidence verbatim (đóng kèm commit sau Gate).

## B4 — Full suite ×2 (isolated HOME)

```
$ rm -rf /tmp/pytest-of-lenovo
$ HOME=/tmp/zm-test-home <venv>/bin/python -m pytest -q -p no:cacheprovider
Run 1: 3555 passed, 12 skipped, 0 failed in 85.83s   (evidence/v151f-b4-suite-run1.out)
Run 2: 3555 passed, 12 skipped, 0 failed in 85.95s   (evidence/v151f-b4-suite-run2.out)
```
Baseline v1.5.0: 3535/12/0 → candidate +20 test mới, **0 failure** (không NEW_REGRESSION).

## B7 — Version bump

```
zero_mem/version.py: __version__ = "1.5.1"        (import check: version: 1.5.1)
release_helpers/release_common.py:127: "1.5.1"
pkg pins: test_pkg1_packaging.py:30, test_pkg2_packaging.py:159/172/177/179/207,
          test_pkg6_upgrade_lifecycle.py:148
$ pytest tests/unit/test_pkg{1,2}_packaging.py tests/unit/test_pkg6_upgrade_lifecycle.py \
         tests/unit/test_v131_version_integrity.py
28 passed in 28.01s
$ python scripts/check_machine_state.py
machine state OK: project-state.yaml is the single source; ...
Doctor honesty (DEF-019): test_v141_r2_remediation.py — 9 passed
SPDX license: pyproject.toml license = "MIT"
```

## B5 — Independent review

Xem mục review trong handoff (`artifacts/handoffs/V151-HANDOFF.md`) — kết quả agent review độc lập fail-closed được ghi nguyên văn tại đó.
