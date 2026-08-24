# EVIDENCE — v1.4.1 (DEF-012 + remediation DEF-013…016)

Mọi lệnh chạy với: `HOME=/tmp/zm-test-home`, `-p no:cacheprovider`.

## RED-first (trước fix, trên tree v1.4.1-WIP)

```
$ .venv-v124/bin/python -m pytest tests/unit/test_v141_r2_remediation.py -q
FAILED .../TestDef013GrantCliReverted::test_grant_subcommand_absent
FAILED .../TestDef014CorpusConnLifecycle::test_service_close_closes_corpus_conn
FAILED .../TestDef014CorpusConnLifecycle::test_facade_close_releases_corpus_conn
FAILED .../TestDef015DoctorHonesty::test_stale_path_fails_not_passes
4 failed, 5 passed in 0.12s
```

## GREEN (sau fix)

```
$ pytest tests/unit/test_v141_r2_remediation.py -q   → 9 passed in 0.27s
$ pytest tests/unit/test_v141_def012_wiring.py tests/unit/test_v141_r2_remediation.py -q
  → 19 passed in 0.12s
```

## Focused regression

```
$ pytest tests/unit/test_m5_authorized_read.py tests/unit/test_m6_memory_tools.py \
      tests/unit/test_v122_public_reads.py -q            → 90 passed in 0.82s
$ pytest tests/unit/test_v140_02_ks_resolution.py \
      tests/unit/test_v134_def003_crash_durability.py -q  → 11 passed in 0.66s
```

## Full suite ×2 liên tiếp trên tree cuối (số chính thức)

```
run1: 3521 passed, 6 skipped in 87.43s (/tmp/zm_full_v141b_run1.txt)
run2: 3521 passed, 6 skipped in 89.30s (/tmp/zm_full_v141b_run2.txt)
run3 (post-commit): 3521 passed, 6 skipped in 88.63s (/tmp/zm_full_final.txt)
```

Sự cố môi trường ghi nhận riêng (KHÔNG phải product evidence): một lần chạy giữa
run2 và run3 báo `46 failed … OSError(122, 'Disk quota exceeded')` + pytest
INTERNALERROR — nguyên nhân xác định: `/tmp` là tmpfs bị đầy bởi rác pytest tích tụ
(`/tmp/pytest-of-lenovo` = 3.1G). Sau khi dọn thư mục pytest-tmp, chạy lại trên cùng
commit → sạch `3521/6/0`. Phân loại: disk-I/environment, không phải regression.
Bài học vận hành: dọn định kỳ `/tmp/pytest-of-lenovo` trên máy này trước full-suite.

Giải trình chênh lệch số giữa các lần đo trong lịch sử v1.4.1:

| Số | Tree | Giải thích |
|---|---|---|
| 3515 passed / 6 skipped | sau `c3e721e`, trước remediation | chưa có 9 test remediation, còn 3 test superseded |
| 3521 passed / 6 skipped | tree cuối | 3515 + 9 − 3 = 3521 ✓ |
| (đo độc lập lần đầu) 3514 / 7 | cùng cây nhưng venv Py 3.13 | skip khác 1 do môi trường; không phải failure |

## Packaging pins (bump 1.4.1 từ commit c3e721e, verify lại trên tree cuối)

- `zero_mem/version.py` = `__version__ = "1.4.1"` ✓
- `release_helpers/release_common.py:127` manifest guard `"1.4.1"` ✓
- pkg1/pkg2/pkg6 test pins = `1.4.1` ✓ (đi qua full suite ở trên)
- `src/integration/m6/mcp_server.py` import version thay hardcode ✓

## Graphify (disposable, read-only)

Snapshot: `zero-mem-dev-data/graphify/v141-r1-scout/` — 8876 nodes / 24905 edges,
code-only. Corroboration cho DEF-013: `commands_config_grant.py` KHÔNG có directed path
tới `m6/handlers.py`; chuỗi production `_open_facade → _resolve_grants → resolve_read_grants`.
