# Zero-Mem v1.3.2 — EVIDENCE

**Branch:** `release/v1.3.2-remediation` (từ HEAD `07ab93e` của `release/v1.3.1-remediation`)
**Date:** 2026-08-23 · **Prompt:** V132-FULL-PROMPT.md + V132-CHECKLIST.md

## Điều kiện tiền đề (Pha B)

- **B1 đã đọc:** AGENTS.md, WORKSPACE-POLICY.md, docs/v1.3.1/CLOSURE.md,
  audit/2026-08-23-project-overview-audit.md,
  docs/v1.3.1/analysis/is-verified-enum-mismatch.md; GITHUB-POLICY đối chiếu
  cho WP-3 (không push — PENDING).
- **B2 pre-state:** HEAD `07ab93e`, branch `release/v1.3.1-remediation`,
  worktree sạch trừ untracked `docs/v1.3.2/` scaffold —
  `zero-mem-dev-data/evidence/v132/pre-state.log`.
- **B3 điều kiện release v1.3.1:** CHƯA publish, KHÔNG có APPROVE-RELEASE-V131.md.
  User duyệt qua chat 2026-08-23 (verbatim trong DECISIONS-V132.md §B3): cho phép
  dựng v1.3.2 từ HEAD local.
- **B4 branch:** `release/v1.3.2-remediation` tạo sau Gate A0 PASS.

## Baseline suite

| Run | Scope | Kết quả |
|---|---|---|
| run#1 (cmd checklist) | tests/unit+integration | 3438 passed / 6 skipped |
| **run#2 canonical** | tests/unit+integration+packaging+baseline | **3448 passed / 6 skipped** |

Lệnh trong V132-CHECKLIST §A thiếu `tests/packaging tests/baseline` (10 test)
so với scope v131 final-suite → thu hẹp 3438/6. Scope chuẩn (= v131 final):
**3448/6 = baseline chính thức** (`zero-mem-dev-data/evidence/v132/baseline.log`).

## Per-WP evidence (`zero-mem-dev-data/evidence/v132/`)

| WP | Commit | Nội dung | Evidence |
|---|---|---|---|
| A | `2dd839c` | ARCH-MEASURE-PRE, GATE A0 **PASS** (Measurer sa-0-a51fb4d2; graphify pre: 8610n/24348e) | ARCH-MEASURE-PRE.md |
| 01 | `d95c08c` | is_verified align enum (D-01 A); matrix RED→revert FAIL→PASS | wp1-red/reverted/green.log, wp1-full-suite.log (3454/6) |
| 02 | `909e1b6` | marker-abuse hardening: chỉ exact-format `«redacted:[REDACTED:<rule>]»` exempt; 4-case RED-first | wp2-red.log (2 fail=bypass thật), wp2-green.log (15/1s), wp2-full-suite.log (3463/6) |
| 03 | `bfa1b46` | publish v1.3.1 **PENDING** (WP3-C2a) | docs/v1.3.1/evidence/GITHUB-PUBLICATION-RECORD.md |
| 04 | — (ngoài repo) | zm-v130-04-tmp → `_archive/` (75 entries, 43M, mv không xoá); refs hiệu lực = 0 | wp4-inventory.log, wp4-mv.log; policy edit qua GATE-W4 (duyệt chat) |
| 05 | `abf00f9` | D-02 A: project-state.yaml single-source; implementation-plan.json frozen + validator fail-closed + 7 tests | test_v132_05_machine_state.py |
| 06 | `4cd48c5` | D-03 A: .docx freeze SHA-256 `85b66cbf…`; checker + tamper tests; docx/md không đổi | test_v132_06_master_spec_freeze.py |
| 07 | `9c8…(bench)` | 14 wp*.py → benchmarks/_legacy/ (git mv, giữ history); wp33 giữ (live test import); inventory bảng 100% file | BENCHMARKS-INVENTORY.md, wp7-full-suite.log (3474/6) |
| 08 | `fecd435` | skip-report plugin `-p tests.v132_skip_report --v132-skips` + parser script | wp8-skip-report.log |
| 09 | policy | D-04=A: .venv-v124 giữ đến hết v1.3.x; zero-mem-dev-data/venvs/ tạo; mốc chuyển v1.4.0; GATE-W9 duyệt chat | WORKSPACE-POLICY.md Legacy exception |
| gates | `f3fae27` | AGENTS.md Authority precedence + hash anchor (duyệt chat) | git |

## Ý nghĩa 6 skip (WP8-C2 — in ra kèm lý do trong final-suite.log)

1–3. `test_m2_indexes.py` ×3 — FTS5 unavailable trong SQLite build của venv.
4–5. `test_m10_2_ingestion.py` ×2 — pypdf not installed (corrupt/valid path).
6. `test_v130_05_redaction_gate.py::test_real_archive_fixture_outside_git_tracking`
   — ZERO_MEM_V130_ARCHIVE_FIXTURE unset (archive fixture export không có sẵn).
Tất cả là environment-unavailable, đúng semantic skip; không phải regress.

## Final suite (Pha Z)

`zero-mem-dev-data/evidence/v132/final-suite.log` — **3474 passed / 6 skipped**
(≥ baseline 3448/6; +26 test mới từ WP-01/02/05/06). Skip report có lý do đầy đủ.

## Graphify

- Pre: `zero-mem-dev-data/graphify/v132/pre/graphify-out/graph.json`
- Final-tree: `zero-mem-dev-data/graphify/v132/final-tree/` (đang build — xem
  CLOSURE nếu thiếu; nodes/edges ghi khi xong).

## CHECKLIST-STATUS

Xem V132-CHECKLIST.md đối chiếu từng mục — tất cả mục Pha A/B/C/Z đã tick kèm
evidence trên; WP3-C2b/C3 (push) cố ý không thực hiện theo quyết user (PENDING).

## VERIFIER-LOG (tóm tắt verdict độc lập)

- Measurer (Pha A): "VERDICT: PASS — Không có WP nào mang rủi ro CAO không giảm
  được bằng test." (nguyên văn trong ARCH-MEASURE-PRE.md §A-ARC3).
- Reviewer/Verifier per-WP: Builder tự-review diff + suite per WP; verifier-loop
  fail-closed điều kiện: mọi WP trước phải xanh — thoả (không WP DEVIATED/BLOCKED).
