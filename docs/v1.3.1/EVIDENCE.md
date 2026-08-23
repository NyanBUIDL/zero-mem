# Zero-Mem v1.3.1 — EVIDENCE

**Branch:** `release/v1.3.1-remediation` (từ master `8264711`)
**Date:** 2026-08-23 · **Prompt:** V131-FULL-PROMPT.md
**Baseline:** `zero-mem-dev-data/evidence/v131/baseline.log` — 3434 passed, 5 skipped
(baseline kỳ vọng ≈3424/5; suite đã lớn hơn sau v1.3.0 — chấp nhận ≥ baseline)
**Final (G6):** `zero-mem-dev-data/evidence/v131/final-suite.log` — **3448 passed, 6 skipped**
(skip thứ 6 = archive fixture env unset — portability WP-7, đúng semantic skip).

## Môi trường test cách ly

```
TMPDIR=/dev/shm/zm131  HOME=/dev/shm/zm131home  .venv-v124
```
Ghi chú: HOME tạm phải khác TMPDIR và ngoài real-home (`src/storage/runtime_root.py`
chặn storage root resolve được vào Path.home()).

## Per-WP evidence

| WP | Commit | Nội dung | Focused test |
|---|---|---|---|
| WP-1a | `d27465c` | version.py → 1.3.1; metadata test; release notes v1.3.1 | `test_v131_version_integrity.py` 1/1; pip metadata = 1.3.1 |
| WP-1b | `20907cf` | version pins 1.2.4→1.3.1 trong packaging contract + release_common | pkg1/pkg2/pkg6/m9.6 focused 29/29 → full suite xanh |
| WP-2 | `f348bd8` | D-01 phương án A: extra `pdf-advanced`, guard import, ADR-V131-01, sửa claim TECH_STACK/EVIDENCE | `test_v131_pdf_tooling_guard.py` 4/4; `pip install -e .` sạch |
| WP-3 | `5cb9632` | banner SUPERSEDED POST_RELEASE_CLOSURE.md + CLOSURE.md; status → RELEASED_PUBLISHED | grep còn 2 cụm trong phần lịch sử đã-banner (đạt tiêu chí) |
| WP-4 | `3f817b9` | ingest: dedup theo registry-size delta, parse 1 lần, counter đủ cả 2 mode, actually_new thật | `test_v131_ingest_stats.py` 3/3 (idempotency run 2: new=0, dedup=1) |
| WP-5 | `68e36da` | project runner: main() wrap, install_adapter() tường minh, migration qua sqlite_master + ledger rows, --root arg | `test_v131_project_runner_safety.py` 5/5 (import không side-effect; re-run cùng report) |
| WP-6 | `532c59c` | redaction gate: strip «redacted:…» trước scan; secret thật vẫn fail-closed | gate tests 7/7; TimeGPT-1 p12 corpus lines giờ PASS gate (behavior change có chủ đích) |
| WP-7 | `8cd80d1` | archive path qua env `ZERO_MEM_V130_ARCHIVE_FIXTURE`; output tmp_path; bỏ hardcode/dev-data write | suite chạy sạch khi archive absent (skip, không fail) |
| WP-8 | `0adc1b4` | phân tích is_verified enum mismatch — KHÔNG đổi behavior | `docs/v1.3.1/analysis/is-verified-enum-mismatch.md` |

## Skip inventory (final-suite)

- 3× FTS5 unavailable (SQLite build) — môi trường, đã tồn tại từ baseline.
- 2× pypdf not installed — môi trường.
- 1× archive fixture unset — WP-7 portability (trước đây là hardcode pass).

## Ràng buộc cứng

- `_archive/`: không đụng ✓ · JSONL canonical schema: không đổi ✓
- Không tag/push/publish; local-only ✓ · Không runtime dependency mới ✓
- Repeated-failure rule: không kích hoạt (mỗi lỗi xử lý trong ≤2 lần)
