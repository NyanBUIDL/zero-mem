# Technology Stack v1.2.4

## Approved stack

| Layer | Technology | Usage | Constraint |
|---|---|---|---|
| Runtime | Python 3.11–3.13 | Core, adapters, CLI | Standard library first |
| Canonical storage | JSONL append-only | Durable sanitized events | Never silently rewrite |
| Derived storage | SQLite | Projection, relations, grants, checkpoints | Rebuildable |
| Lexical search | SQLite FTS5 | Local deterministic retrieval | Typed fallback if unavailable |
| Serialization | JSON | Events and local envelopes | Bounded depth/items/bytes |
| Concurrency | Bounded in-process coordinator/locks | Projection and storage ownership | No unbounded worker/queue |
| Filesystem safety | `src.storage.platform` | Lock, identity, safe read, promote, cleanup | POSIX/Windows behavior hidden behind abstraction |
| Hermes integration | Python plugin hooks/tools | Observation and authorized reads | No deep Hermes-core fork |
| Packaging | setuptools, wheel, sdist | Offline-capable install artifact | Build from exact candidate SHA |
| Tests | pytest + CI OS matrix | Unit/integration/security/E2E | Raw evidence retained |

## Deliberately not used in v1.2.4

| Technology | Decision | Reason |
|---|---|---|
| External vector database | Deferred | FTS5 covers contract correction; avoids new service/cost |
| Embedding model | Deferred | Memory operations must remain zero-LLM/local by default |
| REST/gRPC server | Deferred | In-process/local sidecar is sufficient |
| Kafka/Redis event bus | Rejected for this release | Canonical JSONL + bounded coordinator is simpler and cheaper |
| Cloud synchronization | Out of scope | Local-first privacy boundary |
| Custom sandbox executor | Not Zero-Mem-owned | Hermes owns tool/sandbox execution; Zero-Mem observes evidence |

## Hermes and Agent Skills compatibility

- Register only verified host hooks and preserve host callback return/exception semantics.
- Multiple observers on the same hook must compose without overwriting each other.
- `SKILL.md` remains Hermes-owned. Zero-Mem may record sanitized `skill_name`, lifecycle action, task/session/turn and provenance, but may not rewrite skill instructions.
- Preserve Agent Skills progressive-disclosure layout and YAML frontmatter when fixtures are copied/validated.
- SOUL and Cron definitions are references/provenance only; Zero-Mem does not become their scheduler or authority.

## Performance/cost budgets

- Zero LLM calls for capture, classify, redact, project, retrieve and health.
- Capture append remains synchronous only through durability receipt; projection is decoupled.
- Content/history duplication must be bounded.
- No new always-on network process.
- Benchmarks must report corpus size, repeats, platform, Python version and reproducibility seed.
