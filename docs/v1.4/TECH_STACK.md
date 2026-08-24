# v1.4.0 — Technology Stack

> Nguyên tắc: **tối thiểu thay đổi so với v1.3.4**. Hai điểm thêm mới có kiểm soát (MCP surface + benchmark harness), không dependency runtime mới.

## Approved stack

| Layer | Technology | Usage v1.4 | Constraint |
|---|---|---|---|
| Runtime | Python 3.11–3.13 | Core, adapters, tooling, MCP wrapper | Stdlib first |
| Canonical storage | JSONL append-only | Durable events + corpus sources registry | Never silently rewrite |
| Derived storage | SQLite (+ FTS5) | zm_corpus_units/sources, zm_meta, migrations v1..v12; +v13 CHỈ nếu GATE-2 chọn phương án A | Rebuildable từ canonical |
| Corpus pipeline | `src/corpus/` (registry, blob_store, extract, adapters) | Ingest quant_lab quy mô lớn lần đầu | PDF blob = truth, text = derived |
| PDF extraction | pymupdf (`pdf-advanced` optional-extra, AGPL dual-license per ADR-V131-01); pypdf (`pdf`, BSD) fallback | 471 PDFs | Tooling-only, không phải runtime dep |
| MCP surface | `src/integration/m6/` handlers → MCP server wrapper (mới, WP V140-03) | Cho phép client ngoài Hermes | Tái dùng M6, không fork core |
| Import tooling | `scripts/*.py` stdlib-only | corpus ingest/extract/project scripts | Deterministic, batched, logged |
| Benchmark | stdlib harness (mới, WP V140-04) | precision@k trên QA held-out set | ≥2 runs trùng kết quả; ghi corpus size/platform/seed |
| Tests | pytest | Full suite baseline 3479/7/0 | Isolated HOME; crash-durability pattern tái dụng được |
| Governance state | project-state.yaml single source | V140 overlay theo tiến độ | Validator fail-closed |

## Chi phí dự kiến per-WP

- V140-00: 0 LOC product; docs + DB inspection.
- V140-01: 0 LOC `src/` (thuần tooling/data); storage derived +~1–2GB; runtime batched ingest.
- V140-02: nếu phương án A — migration v13 additive (~40 LOC + tests); nếu B — resolution layer (~100–150 LOC pure functions). Chốt sau Gate-2.
- V140-03: MCP wrapper vài trăm LOC (tooling layer, tái dùng M6 dispatcher); import CLI nhỏ.
- V140-04: benchmark harness stdlib ~200 LOC + QA set data (ngoài repo).
- V140-05: docs only.

## Deliberately not used

| Technology | Decision | Reason |
|---|---|---|
| Vector DB / embedding model | Deferred → v1.5 | Phải đo FTS baseline trước (V140-04 cung cấp số liệu đó) |
| REST/gRPC server | Deferred | MCP thay thế vai trò cross-agent interface |
| Kafka/Redis event bus | Rejected (từ v1.2.4) | Canonical JSONL + bounded coordinator đơn giản/hơn |
| LLM trong memory ops | Rejected vĩnh viễn | Zero-LLM invariant là giá trị cốt lõi sản phẩm |
| Rust hot-path | Not needed | p95 21ms chưa phải bottleneck |

## Environment notes

- Test venv chuẩn: `zero-mem-dev-data/venvs/v133-test-venv` (uv + Python 3.13.15 + pytest/pyyaml/editable install) — dùng lại cho v1.4, đổi tên/khôi phục theo nhu cầu.
- System Python 3.14 NGOÀI `requires-python >=3.11,<3.14` — không bao giờ chạy suite bằng system python.
- pymupdf chỉ trong venv dev-data, không cài hệ thống.
