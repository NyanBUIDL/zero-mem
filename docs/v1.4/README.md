# Zero-Mem v1.4.0 — Corpus Showcase + Agent Independence

**Status:** `PLANNING`
**Branch:** `release/v1.4.0` (tạo tại Gate-0)
**Purpose:** Chuyển Zero-Mem từ "hạ tầng đã chứng minh" sang "sản phẩm có dữ liệu thật": hoàn tất ingest quant_lab làm showcase corpus, chứng minh agent-independence qua MCP client ngoài Hermes, thiết lập retrieval-quality baseline đầu tiên.

## Đọc theo thứ tự
1. ROADMAP.md — lộ trình 6 WP + 6 Gate
2. TECH_STACK.md — công nghệ (nguyên tắc tối thiểu thay đổi)
3. DEVELOPMENT.md — swarm roles (SCOUT/BUILDER/VERIFIER/SCRIBE) + gates
4. CHECKLIST.md — checklist 2 tầng per-WP (gốc + riêng)
5. EVIDENCE.md — bằng chứng (điền dần khi thực thi)

## Work packages
| ID | Nội dung | Status |
|---|---|---|
| V140-00 | Re-baseline & recon (corpus DB state, prompt preconditions) | PLANNED |
| V140-01 | Ingest hoàn tất quant_lab (600 md + 471 pdf) | PLANNED |
| V140-02 | ADR DEF-004 knowledge-space resolution + implement | PLANNED |
| V140-03 | MCP adapter + import tool + POC client ngoài | PLANNED |
| V140-04 | Retrieval-quality benchmark (precision@k trên quant_lab) | PLANNED |
| V140-05 | Closure: EVIDENCE + release notes + publish v1.4.0 | PLANNED |

## Điều kiện vào version
- Baseline: HEAD `d142fd2`+ (v1.3.4 RELEASED_PUBLISHED, suite 3479 passed / 7 skipped / 0 failed)
- Graphify pre-flight PASS (8699n/24509e, snapshot `graphify-zero-mem-v1.3.4`)
- Active prompt: `CORPUS-QUANT-LAB-PROMPT.md` (root workspace) — preconditions cần re-baseline ở V140-00

## Deferred khỏi v1.4 (không được tự ý đưa vào)
- Semantic/vector search → v1.5 (phải đo FTS baseline trước — WP V140-04)
- Rust hot-path → chưa có bottleneck (p95 21ms)
- Enterprise/multi-tenant → sau v1.5
