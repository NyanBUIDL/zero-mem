# v1.4.0 — EVIDENCE

> Điền dần khi thực thi. Mỗi mục phải có: lệnh chạy nguyên bản, exit code, output trích dẫn, commit hash. Self-report không phải evidence.

## Pre-flight (đã hoàn thành trước khi mở version)

| Hạng mục | Kết quả | Evidence |
|---|---|---|
| Graphify pre-flight v1.3.4 | PASS — 8699 nodes / 24509 edges / 259 communities, 0 dangling/duplicate/self-loop; god-nodes ổn định; migrate_12 degree=4 (coupling mỏng đúng thiết kế); `_to_evidence_item` impact-set đóng gọn | `zero-mem-dev-data/graphify/graphify-zero-mem-v1.3.4/` |
| Baseline suite | 3479 passed / 7 skipped / 0 failed (Py 3.13.15, isolated HOME) | `project-state.yaml` v134_final_suite |
| Baseline HEAD | `d142fd2` (AGENTS.md workspace-layout + workflow fix) | git log |

## V140-00 — Re-baseline & recon

Status: `PLANNED` — chưa thực thi.

## V140-01 — Ingest quant_lab

Status: `PLANNED` — chưa thực thi.

## V140-02 — ADR DEF-004

Status: `PLANNED` — chưa thực thi. (Chờ SCOUT soạn đối chiếu A/B → GATE-2 user chọn.)

## V140-03 — MCP adapter + POC

Status: `PLANNED` — chưa thực thi.

## V140-04 — Benchmark baseline

Status: `PLANNED` — chưa thực thi.
Baseline tham chiếu cũ (corpus tổng hợp N=500): recall@8 0.519, p95 2.09ms.

## V140-05 — Closure

Status: `PLANNED` — chưa thực thi.

---

## Gate log

Xem `CHECKLIST.md` mục Gate log — SCRIBE đồng bộ cả hai nơi khi duyệt.
