# v1.3.2 — Module map (modular blocks, dễ sửa từng khối)

> Ghi lại TỪNG mô-đun bị đụng trong v1.3.2 để user phát triển/tweak sau này không phải
> dò lại. Mỗi block: vai trò, file, WP nào đụng, biên an toàn.

## Block E1 — Eligibility classifier
- **File:** `src/integration/m7/eligibility.py` (dòng 178 vùng role classification)
- **Vai trò:** xếp primary/supporting cho memory events khi dựng EvidenceSet (pure, deterministic, zero-LLM).
- **WP đụng:** V132-01.
- **Biên:** KHÔNG đổi lifecycle checks (dòng 183+), NON_CURRENT/SUBORDINATE/NON_PROMOTABLE logic; chỉ tập giá trị verification hợp lệ.
- **Sửa sau này:** muốn thêm verification value → sửa enum `src/capture/event_types.py` TRƯỚC rồi mới align đây; luôn kèm test RED-first.

## Block R1 — Redaction gate (benchmark pipeline)
- **File:** `benchmarks/v130_real_corpus_pipeline.py`
- **Vai trò:** fail-closed secret scan trước khi corpus thật vào benchmark fixtures.
- **WP đụng:** V132-02.
- **Biên:** chỉ chạm điều kiện already-redacted; KHÔNG đổi logic scan chính, KHÔNG nới lối đi.
- **Sửa sau này:** mọi thay đổi pattern marker phải đi qua bộ 4 case test (chuẩn/secret-lẫn/biến-thể/thuần).

## Block GV1 — Governance state
- **Files:** `project-state.yaml` (machine state duy nhất), `implementation-plan.json` (historical record nếu D-02=A)
- **WP đụng:** V132-05.
- **Biên:** không xoá dữ liệu lịch sử; validator script là nơi duy nhất kiểm tra tính nhất quán.

## Block SP1 — Master spec anchor
- **Files:** master .docx (authority), `docs/MASTER-SPEC.md` (projection), `scripts/check_master_spec_hash.py` + ADR-V132-02
- **WP đụng:** V132-06.
- **Biên:** docx freeze-by-hash; md regenerate khi hash đổi; script fail-closed.

## Block BM1 — Benchmarks tree
- **Dir:** `benchmarks/`; legacy → `benchmarks/_legacy/`
- **WP đụng:** V132-07.
- **Biên:** file evidence-bound (`v130_*`, `m10_*`, wp* còn referenced) bất động.

## Block TS1 — Test suite observability
- **File:** skip-summary hook (stdlib pytest plugin nhỏ)
- **WP đụng:** V132-08.
- **Biên:** chỉ báo cáo, không thay đổi kết quả test.

## Block WS1 — Workspace policy files
- **Files:** `WORKSPACE-POLICY.md` (inventory + venv exception), `_archive/zm-v130-04-tmp/`, `zero-mem-dev-data/venvs/`
- **WP đụng:** V132-04, V132-09.
- **Biên:** mọi edit policy cần user gate; mv vào archive được phép, xóa không.

## Block PUB1 — Release publication (v1.3.1)
- **Files:** tag/push/master merge theo `docs/governance/GITHUB-POLICY.md`; record tại `docs/v1.3.1/evidence/GITHUB-PUBLICATION-RECORD.md`
- **WP đụng:** V132-03.
- **Biên:** chỉ chạy khi APPROVE-RELEASE-V131.md hợp lệ; không trường hợp push một phần.
