# v1.4.0 — Lộ trình

## Mục tiêu version
1. **Showcase corpus:** quant_lab (600 .md + 471 PDF, ~1.1GB) nạp đầy đủ vào knowledge space `quant-theory` với provenance PDF-origin.
2. **Agent independence:** MCP server interface cho phép client ngoài Hermes truy vấn knowledge base — bằng chứng sản phẩm đầu tiên.
3. **Quality baseline:** precision@k đo chính thức trên corpus thật — metric hướng sản phẩm đầu tiên.

## Phạm vi
- **Trong phạm vi:** 6 WP dưới đây; thay đổi `src/` chỉ ở WP V140-02 (theo ADR được duyệt) và V140-03 (MCP wrapper tái dùng M6); còn lại tooling/data/docs.
- **Ngoài phạm vi:** semantic/vector search (v1.5), Rust hot-path (chưa có bottleneck), enterprise/multi-tenant (sau v1.5), DEF-005 enrichment wiring (backlog), sửa product code ngoài scope từng WP (stop rule).

## Nguyên tắc / invariant không được phá
- JSONL canonical append-only; SQLite/FTS derived rebuildable (ADR-009).
- Zero-LLM memory ops — extraction thuần deterministic.
- Authorization-first mọi read path; redaction gate fail-closed không nới lỏng.
- PDF blob gốc là nguồn sự thật; text extract là DERIVED, provenance trỏ về blob + page.
- Không copy corpus vào repo; fixtures/data ngoài git track.
- Swarm roles: Builder không tự VERIFIED; Verifier luôn session độc lập; Gate chặn bằng evidence vật lý.

## Work-packages (dependency order)

| ID | Tên | Depends on | Trạng thái | Gate |
|---|---|---|---|---|
| V140-00 | Re-baseline & recon: kiểm tra `corpus-derived.sqlite`, đếm source/unit hiện có vs mục tiêu 600+471, re-baseline prompt preconditions sang v1.3.4 | — | PLANNED | GATE-0 (user duyệt gap-analysis → chốt phạm vi WP-1) |
| V140-01 | Ingest hoàn tất quant_lab: QL-1 (.md → quant-theory) + QL-2 (PDF primary-pdf, orphan-md labeling) | V140-00 | PLANNED | GATE-1 (user duyệt ingest metrics) |
| V140-02 | ADR DEF-004: knowledge-space resolution — 2 phương án đối chiếu (A: migration v13 column / B: resolution layer), user chọn, rồi implement | V140-00 | PLANNED | GATE-2 (user chọn phương án) + GATE-2b (duyệt kết quả) |
| V140-03 | MCP adapter + import tool: expose M6 handlers qua MCP server; POC client ngoài Hermes query OK | V140-02 | PLANNED | GATE-3 (user duyệt POC độc lập) |
| V140-04 | Retrieval-quality benchmark: QA held-out set từ quant_lab, precision@k, ≥2 runs tái lập | V140-01 | PLANNED | GATE-4 (user duyệt baseline metric) |
| V140-05 | Closure: EVIDENCE.md tổng hợp, RELEASE-NOTES-v1.4.0.md, full suite cuối, publish | tất cả | PLANNED | GATE-FINAL (user duyệt release) |

## Swarm execution model (chi tiết trong DEVELOPMENT.md)

| Role | Vai trò | Session |
|---|---|---|
| SCOUT | Dò đường trước — chỉ đọc, báo cáo trạng thái/rủi ro | Subagent độc lập |
| BUILDER | Thực thi theo scope chốt | Session chính |
| VERIFIER | Kiểm chứng độc lập output Builder | Subagent độc lập |
| SCRIBE | Ghi nhật ký + viết handoff từ evidence thô | Session chính |

Bắt buộc: SCOUT trước mỗi Builder; Verifier tách session cho mọi claim PASS; Gate chặn bằng file/log/test output.

## Stop rules (áp dụng mọi WP)
- Cùng lỗi lặp ≥3 lần không rõ root cause → DỪNG hỏi.
- Bug product code cản trở pipeline → DỪNG, đăng ký defect registry.
- Cần dependency mới ngoài TECH_STACK → DỪNG xin approval.
- Disk/perf bất thường → DỪNG kiểm tra.
- Mọi Gate chưa duyệt → không sang WP kế tiếp.

## Open questions (chờ quyết tại gate tương ứng)
- GATE-2: phương án A hay B cho DEF-004? (SCOUT sẽ soạn đối chiếu)
- V140-04: quy mô QA set tối thiểu? (đề xuất ≥30 câu held-out, chốt tại GATE-0)
