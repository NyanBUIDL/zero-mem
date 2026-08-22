# v1.3.0 — Chỉ mục bằng chứng

## Tested SHA
- Product SHA: `e2c0d7ac797a690d7bef9967ea400eee16478250` (branch `v124-post-release-closure`, HEAD tại bắt đầu v1.3.0)
- Branch head: `e2c0d7ac797a690d7bef9967ea400eee16478250`

## Matrix
| Gate | Kết quả | Lệnh | Log/Checksum |
|---|---|---|---|
| Baseline run #1 (Pha A) | **3378 passed, 5 skipped, 0 failed** | `export TMPDIR=/dev/shm/zm-v124-test && export HOME=/tmp/zm-tmp && .venv-v124/bin/python -m pytest tests/unit tests/integration -q --disable-warnings --no-header -p no:cacheprovider` | `zero-mem-dev-data/evidence/v130-phase-a/baseline-run1.log` |
| Graphify extract ban đầu | 8397 nodes / 23878 edges | `graphify extract . --code-only --out <dev-data>/graphify/v130/phase-a-baseline` | `zero-mem-dev-data/graphify/v130/phase-a-baseline/graphify-out/graph.json` |

## CHECKLIST-STATUS

### Pha A — Đào sâu
- [x] A1. Đã đọc: `AGENTS.md`, `docs/governance/GITHUB-POLICY.md`, `docs/v1.2.4/evidence/POST_RELEASE_CLOSURE.md` (release identity + artifact hashes), `docs/v1.3.0/README.md`+`ROADMAP.md` (P1 list kế thừa), `artifacts/handoffs/P1-ORDERING-HANDOFF.md`. Master spec `.docx` — xem ghi chú Known limitations.
- [x] A2. Pre-state: `git status --short` = sạch; `git rev-parse HEAD` = `e2c0d7ac…`; branch `v124-post-release-closure`; `git diff --check` = sạch. (Ghi trong handoff Pha A.)
- [x] A3. Baseline run #1: **3378 passed / 5 skipped / 0 failed** (91.29s) — log path ở Matrix.
- [x] A4. Graphify extract ban đầu xong; impact-set: `search_text` (retrieval/*, benchmarks, evidence_builder, public_read_adapter…), `_order_key`/`select_evidence` (budget, evidence_builder, 3 test m7.3), `as_of_match` (temporal_read, retrieval_metadata, test_m8_4), `ingest.py` (retrieval/*, access/authorized_read, storage/recovery, test m2/m3…).
- [x] A5. 5 báo cáo đào sâu: `docs/v1.3.0/analysis/P1-01-fts-and-brittleness.md`, `P1-02-knowledge-space-filter.md`, `P1-03-state-as-primary-promotion.md`, `P1-04-temporal-evidence-integration.md`, `P1-05-benchmark-scale.md`.
- [x] A6. 2 open questions quyết định: `docs/v1.3.0/plans/DECISIONS.md` (ks = cột đơn; V130-01/02 tách).
- [x] A7. GATE A: **APPROVED với điều kiện** (GATE-A-APPROVAL.md, 2026-08-22). ĐK1: master spec extracted → `zero-mem-dev-data/evidence/v130-phase-b/master-spec-extracted.md`; đối chiếu tại `docs/v1.3.0/MASTER-SPEC-RECONCILIATION.md` (0 hard conflict; 1 điểm lệch ks multi-vs-single xử lý bằng Spec Note V130-02). ĐK2: NULL-ks policy = D-2026-08-22-03 trong DECISIONS.md.

### Pha B — Roadmap & Spec
- [x] B1. ROADMAP.md + README.md fill đủ, không còn placeholder `<...>` (2026-08-22).
- [x] B2. 5 spec WP tại `docs/v1.3.0/plans/V130-0N-SPEC.md` — contract + acceptance criteria + migration + rollback; V130-02 mang đủ 2 ràng buộc D-03 (Verifier note N3 đã track và đóng).
- [x] B3. Invariant giữ nguyên khung AGENTS.md (JSONL canonical, zero-LLM, authorization, redaction, rebuildable) — trong ROADMAP.md §Nguyên tắc.
- [x] B4. ARCHITECTURE.md / TECH_STACK.md cập nhật (component topology v1.3, no new dependency).
- [ ] B5. GATE B: tạo branch `release/v1.3.0`.

## MASTER-SPEC-RECONCILIATION
Xem `docs/v1.3.0/MASTER-SPEC-RECONCILIATION.md`. Verifier tự extract độc lập docx — khớp byte-for-byte.

## VERIFIER-LOG
| Artifact | Verdict | Findings | Xử lý |
|---|---|---|---|
| Pha A authority-chain audit (deleg_54e820b1, 2026-08-22) | **PASS-WITH-NOTES** | N1: D-01/D-02 status cũ → đã cập nhật "user-approved"; N2: L156 paraphrase → đã đánh dấu rõ; N3: V130-02 spec chưa có khi audit → đã viết với đủ ràng buộc D-03 | Cả 3 notes đã xử lý |

## Work-package evidence
| WP | Evidence | Verdict |
|---|---|---|
| (chưa có) | | |

## Verifier
- Independent verifier verdict: PENDING — link artifact khi có.

## Git protocol
- Commits: chỉ stage exact paths; `git diff --check` sạch; không `git add .`.
- Release invariant: `MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA`.

## Known limitations
- Master spec `.docx` chưa được parse trong Pha A (định dạng binary docx; cần extraction). Authority chain hiện dựa trên: AGENTS.md (tóm tắt invariant đã duyệt) + v1.2.4 closure + ADR-009 reference. Nếu Gate A duyệt, Pha B phải extract docx và đối chiếu trước khi chốt spec — hoặc user xác nhận AGENTS.md + ADR là đủ cho scope 5 P1 này.
- Baseline P1 (v1.2.4): functional, corpus tổng hợp nhỏ; chưa phải gate release.
- Graphify: 8 file JSON sinh zero-node (warning #1666 của graphify, không phải code product).
