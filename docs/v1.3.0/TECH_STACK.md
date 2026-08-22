# v1.3.0 — Technology Stack

> Tạo từ `docs/VERSION-TEMPLATE.md` (mục TECH_STACK). Điền trước khi code.

## Approved stack
| Layer | Technology | Usage | Constraint |
|---|---|---|---|
| Runtime | Python 3.11–3.13 | Core, adapters, CLI | Standard library first |
| Canonical storage | JSONL append-only | Durable sanitized events | Never silently rewrite |
| Derived storage | SQLite | Projection, relations, grants, checkpoints | Rebuildable |
| Lexical search | SQLite FTS5 | Local deterministic retrieval | Typed fallback nếu unavailable |
| Concurrency | Bounded in-process coordinator/locks | Projection/storage ownership | No unbounded worker/queue |
| Filesystem safety | `src/storage.platform` | Lock, identity, safe read, promote, cleanup | POSIX/Windows hidden behind abstraction |
| Hermes integration | Python plugin hooks/tools | Observation + authorized reads | No deep Hermes-core fork |
| Packaging | setuptools, wheel, sdist | Offline-capable install artifact | Build from exact candidate SHA |
| Tests | pytest + CI OS matrix | Unit/integration/security/E2E | Raw evidence retained |

## Deliberately not used (trạng thái từ v1.2.4; cập nhật khi có quyết định)
| Technology | Decision | Reason |
|---|---|---|
| External vector database | Deferred | FTS5 covers contract correction; avoids service/cost |
| Embedding model | Deferred | Memory ops zero-LLM/local by default |
| REST/gRPC server | Deferred | In-process/local sidecar sufficient |
| Kafka/Redis event bus | Rejected | Canonical JSONL + bounded coordinator simpler/cheaper |

## Performance/cost budgets
- Zero LLM calls cho capture/classify/redact/project/retrieve/health.
- Capture append synchronous qua durability receipt; projection decoupled.
- Benchmark phải ghi corpus size, repeats, platform, Python version, seed.
- Mục tiêu v1.3: token-savings ratio và Recall@K có baseline production (từ P1 scale harness).
