# Zero-Mem v1.3.2 — Closure Handoff

**Status:** `IMPLEMENTATION_COMPLETE` — chờ user phê duyệt release
(`APPROVE-RELEASE-V132.md`). KHÔNG tag/push/publish khi chưa có approval.
**Branch:** `release/v1.3.2-remediation` | **Base:** `07ab93e` (v1.3.1 tip) | **Date:** 2026-08-23
**Scope:** Remediation: eligibility bug + workspace hygiene + state consolidation (V132-FULL-PROMPT).

## Kiến trúc & data flow (không đổi khung)

JSONL canonical (append-only) → ingest/registry → derived SQLite/FTS →
retrieval/eligibility → EvidenceSet. v1.3.2 sửa 2 điểm behavior trong lớp
derived classification/gate (`eligibility.py`, benchmark redaction gate) +
governance tooling (machine state, spec hash) + workspace hygiene. Không đụng
canonical schema, không đổi enum, không thêm runtime dependency.

## Changed paths theo WP

| WP | Paths |
|---|---|
| 01 | `src/integration/m7/eligibility.py` (L178 + import); `tests/unit/test_v132_01_is_verified_alignment.py`; ADR-V132-01 |
| 02 | `benchmarks/v130_real_corpus_pipeline.py` (marker regex + rules); `tests/unit/test_v132_02_marker_abuse.py`; `tests/unit/test_v130_05_redaction_gate.py` (case a đổi format); RELEASE-NOTES-v1.3.2.md |
| 03 | `docs/v1.3.1/evidence/GITHUB-PUBLICATION-RECORD.md` (PENDING) |
| 04 | ngoài repo: `_archive/zm-v130-04-tmp/`; WORKSPACE-POLICY.md inventory (GATE-W4) |
| 05 | `scripts/check_machine_state.py`; `tests/unit/test_v132_05_machine_state.py`; `implementation-plan.json` (header frozen only) |
| 06 | `scripts/check_master_spec_hash.py`; `tests/unit/test_v132_06_master_spec_freeze.py`; ADR-V132-02 |
| 07 | `benchmarks/_legacy/` (14 file git-mv) + README; BENCHMARKS-INVENTORY.md |
| 08 | `tests/v132_skip_report.py`; `scripts/report_skips.py` |
| 09 | WORKSPACE-POLICY.md Legacy exception (GATE-W9); `zero-mem-dev-data/venvs/` tạo |
| gates | AGENTS.md Authority; docs/v1.3.2 scaffold |

## Evidence

Baseline **3448/6** → final suite **3474 passed / 6 skipped**
(`zero-mem-dev-data/evidence/v132/final-suite.log`, skip có lý do đầy đủ).
Regression triple-log đầy đủ cho WP-01 (wp1-red/reverted/green.log).

## Risks / Open questions

1. **WP-01 OPEN QUESTION:** `src/integration/m7/budget.py:51` còn cùng kiểu
   conflates ("verified"/"confirmed") trong verified_rank — ranking-only,
   behavior-neutral hôm nay. Khuyến nghị follow-up WP ở v1.3.3.
2. **WP-02 semantics:** marker exempt thu hẹp mạnh so v1.3.1 — corpus cũ chứa
   marker lỏng giờ bị scan (block nhiều hơn, an toàn hơn). Đã ghi release notes.
3. **v1.3.1 chưa publish:** drift remote vẫn 11→12+ commit khi v1.3.2 merge
   nội bộ. Publish làm riêng sau APPROVE-RELEASE-V131.md.
4. Skip #6 phụ thuộc env fixture — coverage WP-7-v131 mất trên máy không set;
   đã minh bạch hoá qua skip-report.

## Draft release notes

`docs/releases/RELEASE-NOTES-v1.3.2.md`.

## Next integration steps

1. User review CLOSURE + EVIDENCE → soạn `APPROVE-RELEASE-V132.md`.
2. Publish riêng cho v1.3.1 rồi v1.3.2 theo GITHUB-POLICY (tag thứ tự).
3. Follow-up: budget.py:51 alignment; cân nhắc regenerate MASTER-SPEC.md nếu
   .docx thay đổi (hash-check sẽ chặn).
