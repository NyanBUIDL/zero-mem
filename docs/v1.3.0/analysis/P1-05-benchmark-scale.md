# P1-05 — Benchmark chỉ functional baseline nhỏ (cần N=5.000+)

**Status:** PENDING USER REVIEW (Gate A)
**Date:** 2026-08-22
**Scope:** V130-05. Depends on V130-01..04.

## 1. Hiện trạng code chính xác

- `benchmarks/run_memory_benchmark.py` — functional benchmark hiện tại: corpus tổng hợp nhỏ (vài chục events), đo hit/no-hit per case; `docs/README.md:63` ghi nhận kết quả Option B (recall@8 0.625) từ corpus này.
- `benchmarks/scale_memory_benchmark.py` — đã có khung scale nhưng chưa phải benchmark production-grade cho các fix v1.3.0.
- Không có pipeline real-corpus: dev-data `_archive/` chứa JSONL thật nhưng chưa từng qua export + redaction gate có test riêng.
- Baseline P1 được ghi trong `docs/v1.3.0/EVIDENCE.md`: "functional, corpus tổng hợp nhỏ; chưa phải gate release".

## 2. Root cause

Không có harness đo được precision/recall trên corpus đủ lớn và đủ đa dạng để phân biệt các fix retrieval (OR-fallback, ks filter, state promotion, temporal annotation) với noise; cũng không có số token-savings tin cậy trên dữ liệu thực → mọi claim chất lượng v1.3.0 sẽ là self-report nếu không build V130-05 đúng.

## 3. Phương án thiết kế

### Option A — Hybrid corpus (khuyến nghị, theo prompt)
Hai lớp đo, hai nguồn:
1. **Synthetic deterministic** (seed cố định): generator sinh N=5.000+ memory events có cấu trúc điều khiển được — mỗi fix có bộ case nhắm trực tiếp:
   - OR-fallback: multi-term queries với term hiếm (đo recall gain) + term phổ biến (precision guard — AND-hit không bị fallback).
   - ks filter: events rải trên K knowledge spaces; query sai ks phải 0 hit (leak test).
   - state promotion: PROJECT queries với active state vs decisions cùng timestamp.
   - temporal: as_of trước/sau supersession.
2. **Real corpus**: export từ `zero-mem-dev-data/_archive/` JSONL → REDACTION GATE (test riêng: quét secret pattern, sensitivity, provenance) → fixtures CHỈ nằm dưới `zero-mem-dev-data/`, không vào git/release. Đo token-savings (estimated_tokens của EvidenceSet vs naive full-context) + stale-visible rate.
Determinism bắt buộc: chạy generator 2 lần → byte-giống nhau (hash so sánh).

### Option B — Chỉ scale synthetic lên N=5.000, bỏ real corpus
- Nhược: không có bằng chứng token-savings trên dữ liệu thật — mục tiêu version ("retrieval quality & temporal correctness trên quy mô thực") không đạt; prompt yêu cầu rõ real-corpus pipeline.

| Tiêu chí | A | B |
|---|---|---|
| Độ tin cậy claim | cao (synthetic + real) | trung bình |
| Chi phí build | redaction gate + pipeline | thấp hơn |
| Rủi ro leak | kiểm soát bằng gate test riêng | không áp dụng |

## 4. Khuyến nghị

**Option A**, đúng WP table trong prompt: synthetic đo precision/recall per-fix; real đo token-savings; fixtures ngoài release artifacts.

## 5. Schema / migration impact

Không schema product. Generator + fixtures là tooling: đặt trong `benchmarks/` (generator, vào git) còn corpus data dưới `/home/lenovo/Hermes Workspace/zero-mem-dev-data/benchmarks/v130/` (ngoài repo, xác nhận `.gitignore`/git status sạch).

## 6. Rủi ro

- Real corpus có thể chứa secret chưa redact → gate phải fail-closed, test riêng với known-bad fixture; export KHÔNG đụng `_archive/` gốc (read-only stream).
- Determinism: mọi timestamp trong synthetic phải derive từ seed, không dùng clock thật.
- Thời gian chạy: N=5.000 ingest + query phải hoàn tất trong thời gian hợp lý; đo và ghi runtime thô, không tối ưu sớm.
- Isolation: benchmark chạy với TMPDIR/HOME tạm như checklist §A.

## 7. Test plan dự thảo

1. Generator determinism: 2 lần chạy → sha256 giống nhau (D1).
2. Redaction gate: known-secret fixture bị chặn; clean corpus pass; gate test nằm trong tests/ và chạy CI-local.
3. Per-fix metric case có expected outcome rõ ràng (hit/không-hit, ks leak = 0).
4. Token-savings đo trên real corpus: EvidenceSet tokens vs full-history tokens, ghi số thraw + ratio.
5. Before/after: chạy benchmark trên commit trước fix (baseline) và sau từng WP; lưu log raw vào evidence dir.
6. Fixtures không nằm trong `git status --porcelain` của repo (D2).

## 8. Gate criteria

G5 (benchmark/packaging gate theo ROADMAP): determinism + isolation + stale_safe kiểm chứng được; số liệu thô không tô hồng trong EVIDENCE.md.

## 9. Rollback plan

Benchmark là additive tooling; rollback = xóa file WP, không ảnh hưởng runtime product.

## 10. Migration plan

Không cần.
