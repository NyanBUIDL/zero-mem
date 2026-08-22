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
- [x] B5. GATE B: branch `release/v1.3.0` tạo từ `e2c0d7ac…`; commit docs `011c1f3` (stage exact paths, `git diff --check` sạch, working tree sạch sau commit).

## MASTER-SPEC-RECONCILIATION
Xem `docs/v1.3.0/MASTER-SPEC-RECONCILIATION.md`. Verifier tự extract độc lập docx — khớp byte-for-byte.

## VERIFIER-LOG
| Artifact | Verdict | Findings | Xử lý |
|---|---|---|---|
| Pha A authority-chain audit (deleg_54e820b1, 2026-08-22) | **PASS-WITH-NOTES** | N1: D-01/D-02 status cũ → đã cập nhật "user-approved"; N2: L156 paraphrase → đã đánh dấu rõ; N3: V130-02 spec chưa có khi audit → đã viết với đủ ràng buộc D-03 | Cả 3 notes đã xử lý |
| WP V130-01 pre-merge audit (deleg_44b4b317, 2026-08-22) | **DEVIATED** → remediated | MEDIUM: fingerprint chưa bind match_mode → đã bind (`make_fingerprint(..., match_mode=)` + encode theo mode hiện hành + chỉ fallthrough với `cursor_query_mismatch`); LOW: test cross-mode yếu → đã siết (corpus paginate được, same-mode pagination assert) | Re-audit cần trước khi WP V130-02 bắt đầu implement |
| WP V130-01 re-audit sau remediation (deleg_1951a089, 2026-08-22) | **PASS-WITH-NOTES** | Note 1: spec invariant "cursor chéo chế độ bị từ chối" mâu thuẫn với fallthrough qf_and→qf_or → đã soften spec text khớp hành vi; Note 2: quote chống injection là điểm cộng | Đã xử lý note 1. **V130-01 CLOSED — V130-02 được phép bắt đầu** |
| WP V130-02 audit (deleg_9d091714, 2026-08-23) | **PASS-WITH-NOTES** | N1 minor: leak-test chưa chứa NULL event trực tiếp (đủ semantic qua test riêng) → gộp trong V130-05 benchmark case; N2 info: rebuild compare trực tiếp ≡ byte-compare | Đã ghi tracker; **V130-02 CLOSED** |

## Work-package evidence
| WP | Evidence | Verdict |
|---|---|---|
| V130-01 | Focused: 49 passed (`tests/unit/test_v130_01_fts_or_fallback.py` + `test_m3_fts.py` + sidecar integration). Full suite run3: **3388 passed / 5 skipped / 0 failed** ≥ baseline 3378 — `zero-mem-dev-data/evidence/v130-wp01-full-suite-run3.log`. C7: revert fix → 8 failed; restore → xanh. RED trước implement: 5 failed (match_mode AttributeError). Graphify pre: `graphify/v130/phase-a-baseline`; post: `graphify/v130/wp01-post`. Commit `620e76b`. Integration test `test_sidecar_advertises_and_dispatches_the_same_public_reads` đổi probe zero-result sang single nonce `zm_probe_no_such_token_v130` theo GATE-A-REPLY-V130-01.md (probe cũ → test dương or_fallback trong unit test). | **PASS-WITH-NOTES** (re-audit deleg_1951a089) — CLOSED |
| V130-02 | RED: 7 failed/1 passed trước implement. GREEN: 8/8 unit mới. Full suite run2: **3396 passed / 5 skipped / 0 failed** ≥ baseline — `zero-mem-dev-data/evidence/v130-wp02-full-suite-run2.log`. C7: stash migration+ingest+retrieval → 7 failed; restore → 8 passed. R1 rebuild test xanh; R2 3 test NULL-ks policy đủ; R3 fingerprint bind ks qua req.to_dict() từ đầu (Verifier probe thực nghiệm: cursor ks-a bị từ chối ở ks-b). Schema-version bump 36 test files theo precedent a861ff0 (literal 10→11, Verifier xác nhận 0 dòng suspicious). Graphify post: `graphify/v130/wp02-post`. Commit `cdada94`. | **PASS-WITH-NOTES** (deleg_9d091714) — CLOSED. Notes: leak-test có thể gộp thêm NULL event (minor, xử lý trong V130-05 benchmark case); rebuild compare trực tiếp ≡ byte-compare (info) |
| WP V130-03 | RED: 10 failed trước implement. GREEN focused: 122→158 passed. Full suite run3: **3412 passed / 5 skipped / 0 failed** ≥ baseline — `zero-mem-dev-data/evidence/v130-wp03-full-suite-run3.log`. C7 ngược 2 hướng. Phát sinh + xử lý theo user: D-05, D-06, m8_6 snapshot-diff refactor. Commits `20bbe3e` + `ffaf7ba` (tách theo yêu cầu user). Verifier audit: **PASS-WITH-NOTES** (deleg_1dfdc4c5) — F1 Medium (snapshot-diff chưa chứng minh bắt mutation) → đã thêm `test_snapshot_diff_catches_injected_mutation` (poison qua dataclasses.replace, assert diff bắt được); F2 Low (defense-in-depth non-promotable guard trong promotion block + test direct-API misuse); F4 (`is`→`==`). Commit remediation `e656ecf`. | **PASS-WITH-NOTES** (deleg_1dfdc4c5) — CLOSED sau remediation F1/F2/F4 |
| (chưa có) | | |

## Verifier
- Independent verifier verdict: PENDING — link artifact khi có.

## Git protocol
- Commits: chỉ stage exact paths; `git diff --check` sạch; không `git add .`.
- Release invariant: `MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA`.

## Known limitations
- **Runtime requirement mới (V130-02):** migration 11 `down` yêu cầu SQLite ≥ 3.35 (ALTER TABLE DROP COLUMN); up không có yêu cầu này. Tracker (user-approved APPROVE-V130-02): (1) mục này; (2) V130-05 benchmark phải kiểm tra SQLite version trước khi chạy rebuild trên môi trường khác; (3) release notes v1.3.0 phải ghi rõ. Tick cả 3 trước Gate D.
- Master spec `.docx` đã extract và đối chiếu (`MASTER-SPEC-RECONCILIATION.md`) — không còn limitation.
- Baseline P1 (v1.2.4): functional, corpus tổng hợp nhỏ; chưa phải gate release — V130-05 xử lý.
- Graphify: 8 file JSON sinh zero-node (warning #1666 của graphify, không phải code product).
