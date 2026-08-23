# v1.3.2 — ARCH-MEASURE-PRE (Pha A: Đo kiến trúc trước triển khai)

**Vai trò:** Measurer độc lập, fail-closed, READ-ONLY. Không mutate repo.
**Repo:** `zero-mem-v123-engineering` @ `release/v1.3.1-remediation` (HEAD `07ab93e`, worktree sạch).
**Ngày:** 2026-08-23.
**Căn cứ được cấp:** AGENTS.md (repo root), audit/2026-08-23-project-overview-audit.md,
`git diff master..HEAD --stat` (27 files, +929/−103), và các file nguồn chỉ định trong nhiệm vụ.
**Graphify:** code-only read-only, output ngoài repo tại
`zero-mem-dev-data/graphify/v132/pre/graphify-out/graph.json`
(8610 nodes, 24348 edges, 241 communities; AST extraction 373/373 files).
Hạn chế đã công bố: graph code-only, KHÔNG có semantic của docs/papers; edge
`[EXTRACTED]` là source-derived, `[INFERRED]` là giả thuyết; node bậc cao có thể bị
thổi phồng bởi test imports.

---

## A-ARC1 — Impact-set dự kiến theo finding

Phương pháp: với mỗi finding, lấy tập node thuộc file đích, BFS ngược (reverse
`calls`/`imports`) depth ≤ 2 trên graph, rồi đối chiếu trực tiếp với nguồn/tests.
Ước lượng node/edge là **candidate impact-set**, không phải chứng cứ đầy đủ (graph
code-only).

### P1-1 → WP V132-01: `is_verified` alignment (eligibility.py ~L178)

Corroborated (nguồn thật):
- `src/integration/m7/eligibility.py` L177–178:
  `verification = (_attr(item, "verification_status", "verification") or "").lower()`;
  `is_verified = verification in ("verified", "confirmed")`.
- `src/capture/event_types.py` L42–47: `VerificationStatus` = none /
  direct_tool_output / user_confirmation / deterministic_verification / approval.
  Không giá trị nào khớp `"verified"`/`"confirmed"` → mọi event verify qua enum chuẩn
  hiện bị `is_verified=False`. `"confirmed"` thực chất thuộc LifecycleStatus (nhánh
  `lifecycle == "confirmed"` ở dòng kế bên) → conflates 2 taxonomy.

Graphify impact-set:
| Vùng | Node/Edge (ước lượng) | Ghi chú |
|---|---|---|
| File sửa: eligibility.py | 15 nodes | 1 dòng logic + constant set |
| Reverse-reach d≤2 từ eligibility.py | ~153 nodes / ~153 edges, 23 files | gồm m7 budget/context/evidence_builder/injection_adapter, benchmarks run_m10_e2e/run_memory_benchmark/scale_memory_benchmark/v130_benchmark_runner/wp06_context, tests m7_3/m7_4/m7_5/m7_6/m8_6/m9_1/m10_5/m10_6 |
| Nếu chạm enum event_types.py | ~169 nodes / 169 edges, 75 files | **Không nằm trong phạm vi** — ROADMAP cấm đổi enum VerificationStatus |

Tách biệt canonical/derived: **tốt**. Fix chỉ đổi hàm thuần deterministic (classification),
không đổi JSONL canonical, không đổi schema SQLite (derived), không đổi enum. Vùng sửa
nằm hoàn toàn ở lớp integration/eligibility — derived classification, rebuildable.
Rủi ro lan: chủ yếu qua test expectations, không qua persisted state.

### P1-2 → WP V132-03: Publish v1.3.1 (11 commit chưa publish)

Không phải thay đổi mã. Graphify: **không cần** (governance/git-only). Impact-set là
remote refs + tag; rủi ro đo bằng git state, không phải graph.

### P1-3 → WP V132-02: Redaction marker-abuse hardening

Corroborated: `benchmarks/v130_real_corpus_pipeline.py` L27–47:
`_REDACTED_MARKER_RE = re.compile(r"«redacted:[^»]*»")`; `scan_line_secret()` strip
marker trước secret-scan. Khoảng trống marker-like do attacker kiểm soát là đúng như
audit mô tả (audit P1-3/G7).

Graphify impact-set:
| Vùng | Node/Edge |
|---|---|
| File sửa: v130_real_corpus_pipeline.py | 7 nodes |
| Reverse-reach d≤2 | ~19 nodes / ~19 edges, chỉ 2 files: chính nó + `tests/unit/test_v130_05_redaction_gate.py` |

Tách biệt canonical/derived: **rất tốt** — surface cực nhỏ, benchmark-side gate, không
chạm src/ runtime, không chạm canonical store. Hardening thêm regex/escape sẽ không
làm thay đổi behavior của đường dẫn fail-closed hiện có (secret thật vẫn block).

### P2-4 / P2-5 → WP V132-04, V132-09: workspace tmp cleanup + venv strategy

Workspace/policy only, không đụng `src/`. **Không cần Graphify.**

### P2-6 → WP V132-05: Machine-state consolidation (implementation-plan.json ↔ project-state.yaml)

Không đụng `src/`. Consolidation là tooling/docs-only (policy đã chọn project-state.yaml
làm single source). Graphify: **không cần** cho runtime impact; lưu ý graph cho thấy cả
hai file đều ngoài cây import (`src/` không phụ thuộc). Rủi ro duy nhất là quy trình
(gate/verifier đọc nhầm nguồn), không phải kiến trúc mã.

### P2-7 → WP V132-06: Master spec freeze + hash check

Corroborated: authority là .docx (AGENTS.md), projection `docs/MASTER-SPEC.md` tồn tại;
`scripts/convert_master_spec_to_md.py` sẵn có trong tree — điểm neo tự nhiên cho
`scripts/check_master_spec_hash.py`. Tooling/docs-only, không đụng `src/`.
Graphify: **không cần** (không có runtime dependency nào trên spec file trong graph).

### P3-8 → WP V132-07: Benchmarks inventory + legacy archive (`benchmarks/wp*.py`)

Graphify (corroborated): 15 file `wp*.py` (wp02…wp33), ~58 nodes, ~125 outgoing edges.
Reverse-reach cho thấy wp04/wp06/wp12 vẫn được import/reach từ vùng benchmark và một
số test path — nghĩa là **không phải tất cả dead**: wp06_context nằm trong reverse-set
của eligibility (P1-1); wp04_storage/wp12_multi_agent nằm trong reverse-set của
event_types. → Archive phải đi kèm inventory ghi rõ cái nào còn evidence-bound, và
phải chạy suite sau khi mv để bắt breakage import.

### P3-9 → WP V132-08: Skip-count transparency

Corroborated: `tests/unit/test_v130_05_redaction_gate.py` L93 `pytest.skip("archive
source not available (ZERO_MEM_V130_ARCHIVE_FIXTURE unset)")`; audit ghi 6 skips.
Hook pytest thuần test-infra, không đụng `src/`. Graphify: **không cần**.

---

## A-ARC2 — Dự phán rủi ro thiết kế theo WP (≥2 rủi ro/WP, kèm test phát hiện)

| WP | Rủi ro thiết kế | Xác suất | Test sẽ bắt |
|---|---|---|---|
| V132-01 (P1-1) | R1: Chọn mapping enum sai chiều (ví dụ map `user_confirmation`→verified quá rộng) làm tăng sai số retrieval, promotion sai thành primary | Trung | Unit eligibility matrix: mỗi giá trị VerificationStatus × lifecycle × memory_type → expected primary/supporting (mở rộng test_m7_3*); regression test_m10_5 retrieval ranking |
| V132-01 | R2: Thay đổi `is_verified` làm trôi kết quả benchmark hiện có (run_m10_e2e, v130_benchmark_runner dùng cùng hàm) mà không ai nhận ra drift số liệu | Trung | Benchmark golden-snapshot test: chạy eligibility trên fixture corpus, so snapshot trước/sau fix (diff phải giải thích được từng dòng) |
| V132-02 (P1-3) | R1: Regex hardening mới vô tình block/redact nội dung hợp lệ chứa chuỗi giống marker (false-positive) → mất dữ liệu corpus vào gate | Trung | Property/edge-case test: corpus line chứa `«redacted:fake»` lồng nhau, marker-like text trong code samples; assert pass-through đúng chiều |
| V132-02 | R2: Hardening làm yếu chiều fail-closed (secret thật đi qua khi bọc trong marker-like wrapper) | Thấp (nếu giữ test case block) | `test_v130_05_redaction_gate.py`: thêm case secret-thật-bên-trong-marker-like → PHẢI vẫn block; đây là test an toàn bắt buộc |
| V132-03 (P1-2) | R1: Publish nhầm nhánh/commit sai (tag v1.3.1 trên HEAD không phải 11-commit tip) | Thấp | CI check: script verify tag↔HEAD↔changelog trước push (gate thủ công GATE-PUB) |
| V132-03 | R2: Drift remote phát sinh thêm trong lúc chờ approval (master tiến xa) → merge conflict khi publish | Trung | Pre-publish gate: `git fetch && git rev-list master..HEAD` re-count 11 commits + fast-forward-only assertion |
| V132-04 (P2-4) | R1: Xóa/nhầm thư mục tmp còn chứa evidence chưa sao lưu (m8_4_* có thể chứa artifact sống) | Trung | Inventory diff test/script: liệt kê file trước xóa, đối chiếu WORKSPACE-POLICY inventory + checksum evidence trước khi rm |
| V132-04 | R2: Policy edit lệch thực tế (inventory ghi nhưng filesystem khác) → onboarding agent lần sau lại lệch | Thấp | Workspace audit script idempotent: assert mọi dir trong policy tồn tại và ngược lại |
| V132-05 (P2-6) | R1: Consolidation làm mất trạng thái per-increment (m4_*, m5_*…) mà project-state.yaml không có trường tương đương → mất lịch sử verified | Trung | Round-trip test tooling: mọi key trong implementation-plan.json phải ánh xạ được vào schema mới hoặc archive record; snapshot diff |
| V132-05 | R2: Hai nguồn tạm thời cùng sống dở dang → gate/verifier đọc nhầm nguồn stale | Trung | Contract test: script single-source check fail-closed khi phát hiện cả hai file vừa ghi mới trong cùng window |
| V132-06 (P2-7) | R1: Hash-freeze sai bản (freeze MD projection thay vì .docx authority, hoặc hash docx thay đổi vì metadata) → false alarm hoặc false pass | Trung | Test chính hash-checker: tamper 1 byte → phải fail; re-hash cùng file → phải pass ổn định |
| V132-06 | R2: Conversion docx→md drift âm thầm (projection lỗi thời nhưng hash-check chỉ soi 1 phía) | Cao→giảm được | CI step: convert lại + so hash projection; lệch ⇒ fail (biến rủi ro CAO thành test-gated) |
| V132-07 (P3-8) | R1: Archive wp*.py làm vỡ import còn sống (wp04/wp06/wp12 nằm trong reverse-reach graph) | Trung | Full pytest suite sau mv (3448 passed baseline); grep import `benchmarks.wp` trong tests/benchmarks |
| V132-07 | R2: Mất khả năng tái lập evidence cũ (script evidence-bound không chạy lại được khi cần audit) | Thấp | Smoke-test archive: `_legacy/` scripts importable/hoặc ghi rõ DEAD trong inventory; inventory review gate |
| V132-08 (P3-9) | R1: Hook đếm skip sai ngữ cảnh (đếm cả skip có lý do hợp lệ vs mất coverage) → noise, team bắt đầu ignore | Thấp | Unit test cho chính hook: fixture session có N skip có lý do → report phân loại đúng |
| V132-08 | R2: Hook fail build trên môi trường thiếu fixture (ZERO_MEM_V130_ARCHIVE_FIXTURE unset ở máy khác) → CI đỏ giả | Trung | Hook phải warn-not-fail mặc định; test hai mode env set/unset |
| V132-09 (P2-5) | R1: Chuyển venv phá evidence path hardcode trong docs/scripts cũ → verify scripts lỗi khi replay | Thấp | Replay smoke: chạy verify_v123_evidence.py-style script trong env mới (dry-run) |
| V132-09 | R2: Policy edit mâu thuẫn exception hiện tại (.venv-v124) → trạng thái nửa vời không audit được | Thấp | Policy consistency check: ADR ghi rõ grandfather clause + ngày hết hạn |

## A-ARC3 — GATE A0 verdict

**VERDICT: PASS — Không có WP nào mang rủi ro CAO không giảm được bằng test.**

- Không WP nào chạm canonical JSONL store, schema migration, hay enum VerificationStatus
  (ngoài phạm vi đã khóa ở ROADMAP). Bề mặt `src/` thật sự chỉ 2 điểm: eligibility.py:178
  và redaction-gate semantics — cả hai đều có test bắt được rủi ro cao nhất của chúng.
- Hai rủi ro khởi điểm mức CAO (V132-06/R2 conversion-drift; V132-07/R1 archive vỡ import)
  đều giảm về TRUNG/THẤP bởi test cụ thể đã nêu (CI convert+hash compare; full-suite
  post-move). Sau giảm, rủi ro dư lớn nhất là TRUNG (V132-01/R1 mapping enum — bắt bằng
  eligibility matrix test; V132-03/R2 drift — bắt bằng pre-publish gate).
- Điều kiện đi kèm verdict: WP-1 PHẢI có eligibility matrix test trước khi fix;
  WP-2 PHẢI giữ nguyên case fail-closed block; WP-7 PHẢI chạy full suite sau archive.

---
*Measurer độc lập, read-only. Graph output là derived/disposable, không phải authority.*
