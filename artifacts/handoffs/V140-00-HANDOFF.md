# V140-00 HANDOFF — Re-baseline & Recon

- **WP:** V140-00 (v1.4.0 WP đầu tiên) — CHỈ đọc + docs, không đụng `src/`, không ghi corpus DB
- **Ngày:** 2026-08-24 · **Repo:** zero-mem-v123-engineering @ `789db91` (master = GitHub)
- **Authorization:** PROMPT-V140-00.md (user paste) — local only, KHÔNG push
- **Phases:** SCOUT (subagent read-only) → BUILDER → VERIFIER (subagent độc lập) → SCRIBE

## Observed

### DB state (`zero-mem-dev-data/corpus-quant-lab/`)
| Thành phần | Giá trị |
|---|---|
| corpus-derived.sqlite | 123,006,976 B; zm_corpus_sources=1070, zm_corpus_units=9863, zm_corpus_fts=9863 |
| corpus_sources.jsonl | 1070 dòng (khớp sources); normalization m10.3 |
| blobs/ | 1070 blob, ~876 MB |

### Phân loại nguồn (tất cả ks=`quant-theory`, project=`quant-lab-corpus`, profile=`quant-lab-profile`)
| kind | sources | units | extract_status | blob_ref |
|---|---|---|---|---|
| primary-pdf | 471 (= 471 PDF trong `papers/`) | 9 863 | OK 471/471 | đủ, sample sha256 khớp |
| derived-md | 470 | **0** | n/a | NULL (đúng thiết kế md) |
| orphan-md | 129 | **0** | n/a | NULL |
| Tổng | 1070 | 9863 | | |

### Đối chiếu mục tiêu 600 md + 471 pdf
- PDF: **471/471** — khớp, không gap.
- MD trên disk: **600 file .md**, nhưng 599 là article-md (đã register đủ 599/599,
  external_ref khớp 1:1). File thứ 600:
  `papers/2002-10-22 - cond-mat_0210475 - Statistical theory of the continuous double auction.md`
  — nằm TRONG `papers/`, text garbage (mirror OCR hỏng của bài cond-mat_0210475,
  bài này đã có primary-pdf + derived-md riêng đúng đường). Không đăng ký nó là
  hành vi đúng của run trước.

## Changed

1. `CORPUS-QUANT-LAB-PROMPT.md` (workspace root):
   - Preconditions v1.3.0/`14e52ff`/release-gate → v1.3.4/`789db91` + baseline suite
     3479/7/0 + venv `v133-test-venv`.
   - Thêm section "Current state" (Scout report, đã verifier PASS).
   - QL-1 scope điều chỉnh: 599 md-sources đã register → phần việc còn lại là
     **extraction → zm_corpus_units cho 599 nguồn md** (KHÔNG re-register).
   - Bước 0 gate mới.
2. `project-state.yaml`: overlay V140 (`v140_status: IN_PROGRESS`,
   `v140_00_status: CLOSED_PENDING_GATE0`, `v140_00_handoff`).
3. `docs/v1.4/CHECKLIST.md`: tick đầy đủ mục V140-00 kèm evidence pointers.
4. File này (`artifacts/handoffs/V140-00-HANDOFF.md`).

Không thay đổi gì trong `src/`, không ghi corpus DB (toàn bộ SELECT / mode=ro).

## Gap analysis → phạm vi thật của V140-01

| Hạng mục | Trạng thái | Việc còn lại ở V140-01 |
|---|---|---|
| Register 600 md + 471 pdf | ✅ xong (599+471=1070; 1 md-garbage loại đúng) | chỉ xác nhận idempotency khi chạy lại |
| PDF extraction (primary-pdf) | ✅ 471/471 OK, 9 863 units, FTS index đầy đủ | verbatim spot-check ≥10 units vs PDF gốc |
| MD extraction (derived-md + orphan-md) | ❌ **0 units cho 599 sources** | extract units cho 599 md-sources ← **gap chính** |
| FTS smoke | ✅ Kelly criterion 8 / limit order book 620 / rough volatility 381 hits | re-run sau khi nạp md units |
| Idempotency registry | ✅ 0 dup (external_ref, kind) | log bằng chứng chạy lần 2 |

## Verified

- content_hash sweep **1070/1070** sources khớp disk qua
  `src/corpus/identity.py::compute_content_identity` (sha256 domain-wrapped).
- Blob integrity sample 50/50 (Scout) + ≥20 (Verifier): sha256(blob)==blob_ref,
  bytes == PDF gốc.
- Units tồn tại duy nhất cho primary-pdf; derived/orphan-md 0 units (gap khai báo).
- Verifier độc lập (subagent tách session, tự chạy lại lệnh): **OVERALL: PASS**
  (8/8 mục PASS). Verdict nguyên văn lưu tại
  `zero-mem-dev-data/evidence/v140-00/verifier-report-v140-00.md`
  (nguồn: delegation `deleg_4e5a1e02`, subagent-summary-0-20260824_101400_656199.txt).
  Caveat duy nhất (đã xử lý sau verify): bullet Stop-rules cũ "Release v1.3.0 chưa
  được duyệt" trong prompt line 94 → đã sửa thành gate master/suite v1.3.4.
  Verifier re-run hash sweep dùng v133-test-venv python: 1070/1070 match,
  blob sample 25/25 ok — trùng khớp Scout/BUILDER độc lập.

## Risk

- Md thứ 600 trong `papers/` (garbage mirror) hiện KHÔNG có trong registry. Nếu sau
  này muốn audit-full-disk, cần quy ước xử lý tường minh (skip-list entry), tránh
  bị coi là "thiếu 1 source" im lặng.
- `zm_meta`, `zm_migrations`… đều 0 rows trong DB corpus này — DB corpus dùng subset
  bảng riêng (zm_corpus_*), không phải full event store; điều này nhất quán với
  thiết kế nhưng cần nhớ khi viết tooling V140-01 (đừng giả định migrations table).
- Extraction md chưa có nên chưa biết thống kê skip/quality của 599 file md
  (có thể gặp md rác tương tự file papers/).

## Next (trình GATE-0)

Đề xuất phạm vi V140-01 chờ maintainer duyệt:
1. Extraction pipeline md → units cho 599 sources (dùng extract path hiện có,
   zero-LLM), batch theo source, dry-run counts trước.
2. Skip-list tường minh per-file (nếu có file md nhiễu như mirror cond-mat_0210475).
3. Idempotency re-run: 0 source mới, 0 unit mới lần 2.
4. Verbatim spot-check ≥10 (pdf units vs PDF gốc; md units vs .md gốc).
5. FTS smoke lại 3 truy vấn chuẩn.

**DỪNG tại đây theo PROMPT-V140-00 — không tự chuyển sang V140-01.**

## Authorization

Local-only theo prompt user. Chưa commit — trình GATE-0 duyệt đồng thời phạm vi
V140-01 và quyết định commit docs/state của WP này.
