# Zero-Mem System Audit — Observed Truth

Audit target: `NyanBUIDL/zero-mem`, tag `v1.0.0`, commit `79989f34ce3578f275a7b910c8a189896ce9ad57`.

Audit mode: read-only. No source, configuration, tests, schemas, migrations, dependencies, CI files, or git state were changed. The repository was inspected from a temporary shallow clone; only this report was created in the user workspace.

Evidence labels used throughout: **Confirmed issue** means directly demonstrated by code or a reproducible run; **Likely issue** means the code path makes the risk probable but production impact needs measurement; **Architectural concern** means the design is valid in isolation but conflicts with the stated reusable-memory objective; **Optimization opportunity** means correctness is not presently disproven; **Unknown** means the repository does not provide enough evidence.

## 1. Executive Summary

Zero-Mem has a thoughtful local-first data model: sanitized append-only JSONL is intended as canonical state, SQLite/WAL/FTS5 and several projections are derived, access policy is explicit, and most Hermes adapters are separated from persistence and retrieval. The repository also contains unusually strong deterministic tests, rebuild paths, bounded EvidenceSet selection, backup/restore scaffolding, and a documented fail-open observer goal.

The system is not yet suitable as a drop-in, agent-agnostic V1 external memory layer. The main reason is not SQLite query speed; it is the integration contract and lifecycle wiring. The release CLI configures an owned descriptor but does not install or activate a host plugin. The public `HermesBoundary` registers capture hooks without supplying a capture store, so the boundary can report hooks as registered while the callback performs no persistence. Even when a lower-level store is supplied, capture appends JSONL only; the derived SQLite/FTS layer is updated by a separate explicit ingest/rebuild path.

The persistence design also has important long-run limits. JSONL loading materializes the complete history and full records into process memory. Ingestion reads and splits the complete file, then re-reads it through a second iterator. The canonical append path performs an `fsync` per event and uses only a process-local lock, so several agent processes sharing one installation can race on sequence numbers, duplicate detection, and canonical writes.

Measured evidence from this audit:

- Empty setup command: about 169 ms; doctor command: about 202 ms on Windows, CPython 3.14, SQLite 3.50.4.
- Existing M3 benchmark: 200-record synthetic corpus, FTS p95 about 0.79 ms; structured p95 below 0.52 ms.
- New synthetic scaling probe: JSONL capture-load peak grew from 6.42 MiB at 1,000 records to 64.20 MiB at 10,000 records; ingest grew from 0.408 s to 19.355 s; FTS p95 grew from 1.648 ms to 22.198 ms.
- Full suite on the available host: `3068 passed, 59 failed, 11 errors, 5 skipped` in 74.05 s. This run is not a clean product baseline because the host is Windows/CPython 3.14 while the repository requires CPython `>=3.11,<3.14`; the packaging tests also assume Unix virtual-environment paths. The failures are nevertheless direct evidence of Windows/runtime compatibility gaps.

Overall conclusion: Zero-Mem has a credible core and strong security-minded boundaries, but V1 readiness requires a small, real public lifecycle API, a functioning persistence composition, process-safe canonical writes, a supported Windows/runtime story or an explicit Linux-only scope, and benchmarks at the intended memory volumes.

## 2. Architecture Overview

The repository is larger than a minimal memory sidecar: 248 Python files, approximately 66,678 Python lines including tests and tooling, 100 test Python files, and 89 Markdown files. The implementation is organized into these layers:

| Layer | Main implementation | Responsibility | State owned |
|---|---|---|---|
| Release package | `zero_mem/*` | CLI, paths, setup, doctor, backup, upgrade, Hermes descriptor/boundary | User-local runtime/configuration |
| Capture | `src/integration/*`, `src/capture/*`, `src/redaction/*` | Hook mapping, sanitization, validation, event envelope | Canonical event input |
| Canonical storage | `src/storage/jsonl_capture.py` | Append-only JSONL and in-process indexes | Raw sanitized event stream |
| Derived storage | `src/storage/sqlite_store.py`, `src/storage/ingest.py`, `src/storage/migrations/*` | Metadata, lifecycle, provenance, relations, scopes, FTS5 | Rebuildable SQLite projection |
| Retrieval/policy | `src/retrieval/*`, `src/access/*` | Read-only queries, FTS, pagination, grants, scope enforcement | No canonical state |
| Context selection | `src/integration/m7/*`, `src/m8/*` | Routing, authorized EvidenceSet construction, hardening, bounded injection | No durable state |
| Corpus | `src/corpus/*` | Source registry, blobs, extraction, normalization, dedup, versioning, corpus FTS/graph | Canonical corpus registry/blob store plus derived corpus tables |
| Projection | `src/project_memory/*`, `src/projection/*` | Project-memory and Obsidian-style derived views | Rebuildable projections |
| Integration | `src/integration/hermes_*`, `zero_mem.hermes_integration` | Hermes plugin-context adapters | Host-owned lifecycle |

The intended direction is `Zero-Mem core + small stable adapter`, but the repository does not yet expose a dedicated `api/` or `core/` public facade. The release package exports only `__version__` from `zero_mem/__init__.py`; operational memory APIs remain under internal-looking `src.*` modules.

## 3. Data Flow

The documented flow is:

```text
Hermes/plugin context
    -> hook adapter
    -> payload mapping
    -> redaction and validation
    -> canonical JSONL append
    -> explicit SQLite ingest/rebuild
    -> M3/M5 read-only query and authorization
    -> M7 route and bounded EvidenceSet
    -> optional pre_llm_call context envelope
    -> agent
```

The important actual split is:

```text
RegistrationAdapter
    -> map_hook_payload
    -> adapt_mapped_event
    -> store.append(envelope)       [only if caller supplied store]
    -> JSONL

separate operator/runtime call
    -> ingest_file(store, jsonl_path)
    -> SQLite metadata/lifecycle/provenance/relations/FTS
```

`adapt_mapped_event()` ends at `store.append()` and does not update SQLite. `ingest_file()` is a separate explicit operation. `HermesBoundary.register()` creates `RegistrationAdapter` without a store, so its capture surface is not connected to the canonical writer. Retrieval then reads a potentially absent or stale derived database.

The retrieval/injection flow is better separated: M7 routes first, M5 authorizes before corpus influence, M7.3 builds a bounded EvidenceSet, M7.5 validates and sanitizes it, and the adapter returns a data-only envelope. That separation is a strength, but it does not compensate for the missing capture-to-storage composition.

## 4. Performance Assessment

### Startup

The empty `setup` and `doctor --json` commands were measured at approximately 169 ms and 202 ms respectively on this Windows host. Setup creates directories, configuration, an empty JSONL file, and the SQLite schema. The current setup cost is acceptable for a local CLI, but these measurements do not include a populated capture-store startup.

`JsonlCaptureStore.__init__()` calls `_load()`, which reads the complete JSONL file, parses every line, validates every envelope, and stores each complete record in `_by_id` and `_by_hash`. Therefore capture-store startup is O(total canonical records) in time and O(total record content) in memory. It is not constant-time with respect to memory history.

### Ingestion/write path

The live capture append path validates, checks two in-memory maps, serializes, appends, flushes, and calls `os.fsync()` for every record. The derived ingest path reads the entire JSONL file, splits it in memory, then iterates through a second full read and performs a SQLite transaction/commit per line. This is durable and deterministic but not a low-overhead burst-write path.

### Retrieval

The existing M3 benchmark is fast at small scale: 200 records, SQLite 3.50.4, FTS enabled, structured p95 below 0.52 ms and FTS p95 about 0.79 ms. The synthetic audit probe showed FTS p95 of 1.65 ms at 1,000 records, 11.80 ms at 5,000, and 22.20 ms at 10,000 records. These results are indicative only; they are not a production SLA and were measured on one machine with simple matching text.

Corpus retrieval has a separate scale risk. Metadata-only retrieval, FTS-unavailable fallback, and malformed/empty lexical fallback materialize all corpus units. Even with FTS, all matching rows are fetched before authorization/filtering and Python scoring/sorting. This is safe from unauthorized result return in the tested path, but it is not bounded candidate processing at large corpus sizes.

### CPU, RAM, disk, and I/O

- CPU: repeated JSON decoding, validation, hashing, full-prefix hashing, Python scoring, and global sorting grow with history/candidate volume.
- RAM: complete canonical records are retained by `JsonlCaptureStore`; `ingest_file()` creates complete byte and split-line representations; corpus fallback retains all candidate rows and hit objects.
- Disk: each captured event causes a canonical append and `fsync`; derived ingestion creates metadata, lifecycle, provenance, relation, FTS, checkpoint, and log writes. SQLite WAL adds normal write amplification.
- I/O: full-file rereads occur on ingestion and rebuild paths; backup and upgrade intentionally scan/copy all canonical sources, which is safe but O(total data).

## 5. Scalability Assessment

The current design is acceptable for a single-user, single-process, small-to-medium local store where periodic explicit rebuild/ingest is acceptable. It is not yet demonstrated at 100,000 or 1,000,000 memory records.

The main growth characteristics are:

- capture startup: O(N) parsing plus O(N) retained record state;
- incremental ingest: O(file size) read/parse on every invocation, even when a checkpoint skips old rows, plus per-line transactions;
- rebuild/upgrade: O(all canonical memory and corpus state), with graph and projection work layered on top;
- ordinary FTS retrieval: index-assisted candidate discovery but chronological output and bounded result materialization;
- corpus metadata-only/fallback retrieval: O(N) candidate materialization, Python authorization/filtering/scoring, and sorting;
- multi-scope authorized reads: one query per effective scope, followed by Python deduplication and global sorting.

At 10x current usage, the main risks are increased startup and ingest latency, higher memory pressure, and a growing lag between canonical capture and derived retrieval. At 100x, the full-file and full-candidate paths become the dominant design constraints. Multiple agents add process-safety and configuration-collision risks before raw query throughput becomes the limiting factor.

## 6. Long-Running Stability

The canonical/derived separation is directionally good for recovery: derived SQLite, FTS, graph, temporal, and project projections can be rebuilt from canonical sources. The PKG-6 upgrade path stages a full derived rebuild before activation, and the repository documents a 601-PDF rollout with 26,144 normalized units and 32,377 graph edges.

However, long-running cost is not stable with total history:

- every new `JsonlCaptureStore` instance scans all historical JSONL and retains full records;
- every explicit ingest reads the complete file and repeats parsing work;
- prefix verification and replay cost grows with the consumed prefix;
- full upgrades rebuild all derived state rather than applying a bounded incremental delta;
- corpus fallback retrieval can scan every unit;
- canonical JSONL has no built-in compaction or segment rotation in the capture store itself.

The repository state explicitly says a post-M10 full audit had not started and packaging had not started; this audit therefore treats the measured large-corpus result as workload evidence, not proof of one-year stability.

## 7. Token & Cost Efficiency

The design avoids mandatory embeddings, LLM calls, network calls, and paid APIs. That is a strong cost property. M7 applies a `NO_MEMORY` default, freshness requests avoid stale-memory injection, EvidenceSet selection caps primary/supporting evidence, and the serialized context is bounded.

The tradeoff is that local work can become expensive before token savings are realized:

- per-event `fsync` and per-line derived commits add local latency to capture/replay;
- ordinary FTS search is deterministic but not relevance-ranked by verification, recency, or confidence;
- a global FTS/corpus candidate set may be materialized before authorization/filtering;
- no semantic retrieval is enabled by default, so lexical misses can lead to either no useful context or repeated agent attempts;
- stale derived state can cause retrieval misses unless the host explicitly runs ingest/rebuild.

No token-savings percentage is claimed because the repository does not measure baseline prompt size, injected tokens, avoided model calls, or end-to-end agent cost.

## 8. Hermes Integration

The Hermes boundary is adapter-oriented in code: it uses a plugin-context-like `register_hook`/`register_tool` surface, does not import the Hermes package in the release layer, and documents explicit project/profile identity. The adapter classifies Hermes dependencies as mostly **B. Adapter-level dependency**, with **C. Internal implementation dependency** risk around the assumed hook names and callback signatures. There is no hard import coupling to Hermes internals.

The integration workflow is nevertheless incomplete as a user experience:

- `zero-mem integrate hermes` writes a Zero-Mem-owned descriptor; it does not register a plugin, install a host entry point, edit Hermes configuration, or launch a sidecar.
- An external host must find and instantiate `HermesBoundary`, supply a compatible plugin context, choose `capture_root` and `store_path`, and manage lifecycle.
- The public boundary registers capture hooks without a capture store, so the default composed capture path is observational but non-persistent.
- The adapter supports only a declared subset of hooks. File operations, skill usage, generic task transitions, and several LLM/API/subagent hooks are explicitly deferred or conditional.
- The integration descriptor is rejected when `package_version` differs from the current package version, so an otherwise compatible package upgrade invalidates the stored integration descriptor.

Hermes therefore remains operational when Zero-Mem fails in the tested fail-open hook path, but the integration is not yet “install and forget”; it requires host code and operational knowledge.

## 9. General Agent Compatibility

### Current contract

There is no single public generic contract equivalent to:

```text
initialize
session_start
observe_message
observe_tool_call
session_end
retrieve_memory
shutdown
```

Instead, a generic agent must compose internal types from `src.capture`, `src.storage`, `src.retrieval`, `src.access`, and `src.integration.m7`. The release package exposes CLI lifecycle commands, not a stable memory library facade.

### Runtime classes

- Custom synchronous Python agent: possible with moderate adaptation, but it must import internal modules, construct valid envelopes, own the capture store, and schedule ingestion/rebuild.
- CLI agent: possible as a subprocess workflow, but there is no stable daemon/service protocol and no documented one-command observe/retrieve protocol.
- OpenAI-style tool agent: possible through the M6 tool schemas if the host supplies a compatible context; host-specific registration and store wiring remain required.
- LangGraph/CrewAI/AutoGen-like runtimes: no native adapter; lifecycle and async bridging must be written by the adopter.
- Local/server-side agents: embedded local storage is possible; shared service mode is not provided by the current code.

The core is conceptually reusable, but the integration surface is not yet small or stable enough for an external developer who does not know Zero-Mem internals.

## 10. Installation & Packaging

The packaging model is intentionally offline and low-dependency. The wheel has no mandatory third-party dependencies; `pypdf` is optional. Installation requires an existing CPython `>=3.11,<3.14`, a locally obtained bundle containing the wheel, and a virtual-environment-capable interpreter. Setup then creates user-local data/config/state/cache roots.

The fresh-machine steps are currently:

1. Obtain/build the offline bundle.
2. Run the platform-appropriate installer with an existing supported Python.
3. Ensure the CLI shim is on `PATH`.
4. Run `zero-mem setup`.
5. Run `zero-mem doctor`.
6. For Hermes, run `zero-mem integrate hermes --project-id ... --profile-id ...` and separately arrange for a host plugin to instantiate/register `HermesBoundary`.
7. Arrange explicit capture-store and derived-ingest/rebuild lifecycle calls.

The package is simple on Linux/macOS when the Unix assumptions hold, but the installer implementation hardcodes `venv/bin/python` and `venv/bin/zero-mem`; Windows venvs use `Scripts/python.exe` and `Scripts/zero-mem.exe`. The repository also contains shell installers. The package metadata correctly excludes Python 3.14, but `doctor` turns an otherwise importable runtime into `NOT_READY` on 3.14.

Uninstall is directionally safe: the default path removes owned runtime components and preserves user data. Upgrade stages derived state and keeps canonical sources. The integration descriptor’s exact package-version binding weakens upgrade continuity.

## 11. OS & Runtime Compatibility

| Environment | Assessment |
|---|---|
| Linux | Best-supported path. XDG and Unix venv assumptions align. Still needs host plugin wiring and explicit ingest lifecycle. |
| macOS | Likely workable for the Unix installer and SQLite path; no native macOS CI evidence was found. |
| Windows | Core Python paths can run, but the release installer/verification uses Unix `bin` paths and shell scripts are not native. The full test run exposed this directly. |
| WSL | Likely workable as Linux; Windows-side host integration and filesystem semantics remain operator concerns. |
| Docker/container | Embedded core is possible with explicit absolute roots and a supported Python; no Dockerfile, service protocol, or container lifecycle contract was found. |
| CPython 3.11–3.13 | Declared supported range. Clean canonical results are recorded in project state, but this audit could not run pytest under those interpreters because pytest is not installed there and no dependency installation was authorized. |
| CPython 3.14 | Explicitly unsupported; `doctor` reports FAIL. |
| PyPy/alternate Python | Unsupported by `doctor`, which requires CPython. |

Portability is therefore conditional rather than broad. The code uses `Path` in many places, but platform portability is limited by packaging, permission assumptions, XDG defaults, and the lack of cross-platform integration tests.

## 12. Dependency Audit

| Classification | Dependencies |
|---|---|
| Core required | CPython 3.11–3.13; stdlib `sqlite3` with SQLite >=3.35 and FTS5 capability; setuptools at build time |
| Integration-specific | Hermes is not a wheel dependency; a host plugin context with the expected registration methods is required |
| Optional | `pypdf` for PDF extraction |
| Development/testing | pytest and local test tooling; not declared as runtime dependencies |
| Native/large footprint | No mandatory native third-party dependency; SQLite capabilities are supplied by the Python build |

The small dependency footprint is a strength. The primary dependency risks are implicit platform tooling (venv layout, shell, symlink support), the narrow Python version gate, and dependence on SQLite FTS5 being compiled in. The code does not appear to duplicate substantial standard-library functionality with unnecessary third-party packages.

## 13. Sync / Async Compatibility

No async API or async file/database adapter was found. Capture, JSONL append, `fsync`, SQLite operations, FTS queries, corpus extraction, and rebuilds are synchronous. Hermes callback signatures are synchronous.

This is acceptable for a synchronous agent or for work moved to a worker thread/process by the host. It is risky for async agent runtimes because a pre-LLM hook can perform blocking filesystem/database work on the event loop. The code does not provide `async` methods, an executor policy, backpressure, a queue, or a documented non-blocking capture mode.

The M7 no-memory route is cheap and pure. Memory-needed routes can open SQLite and execute Python-side selection synchronously. The parent agent will not crash on many adapter exceptions because callbacks catch broad exceptions, but the event loop can still be delayed before a failure is caught.

## 14. Multi-Agent Capability

The repository has useful logical profile/project scopes and explicit grants, but physical multi-agent safety is incomplete.

- `JsonlCaptureStore` uses `threading.RLock`, which coordinates threads sharing one object, not multiple processes with separate store instances.
- Each process maintains its own `_next_sequence`, `_by_id`, and `_by_hash` snapshot. Concurrent processes can assign duplicate sequence numbers, miss each other’s dedupe state, and append without a cross-process lock.
- The module-level `ZeroMemRuntime` can be reconfigured by multiple adapter constructors in one process.
- The M5 access model can isolate profiles logically, but it does not solve canonical-write races or configuration collision.
- SQLite has a busy timeout, WAL, and read-only connections, but the canonical JSONL write boundary remains separate and process-unsafe.

Classification: **multi-agent capable with significant limitations**, not properly multi-agent capable. One Zero-Mem installation per process/agent is safer than several agents sharing one canonical capture file.

## 15. Storage Architecture

The canonical/derived distinction is explicit and mostly respected:

- canonical memory: append-only JSONL;
- derived event metadata/lifecycle/provenance/relations/scopes/FTS: SQLite;
- canonical corpus: source registry and content-addressed blobs;
- derived corpus units/relations/graph/temporal/project views: SQLite/projection stores;
- backups contain canonical sources and configuration descriptors; upgrades rebuild disposable derived state.

The major issue is not the declared model but the absence of an atomic or continuously composed write pipeline. The canonical JSONL append and SQLite projection are separate operations. A process crash or missing scheduler can leave the system with data that exists canonically but is invisible to retrieval. This is recoverable through replay/rebuild, but the runtime contract does not make freshness or lag explicit.

The design also lacks capture-store rotation/compaction in the basic JSONL implementation. File segmentation by session/day is described in architecture documentation, but `CaptureStoreConfig` defaults to one `events-v1.jsonl` stream and `JsonlCaptureStore` itself has no rotation policy.

## 16. Retrieval & Context Efficiency

M7 context projection is one of the stronger areas. The router has a safe `NO_MEMORY` default, freshness requests avoid injecting stale memory, authorization is performed before EvidenceSet eligibility, evidence is sanitized, and primary/supporting totals are bounded.

The lower-level memory search path is weaker as a relevance system. FTS candidates are ordered by `(created_at ASC, event_id ASC)` rather than relevance, verification, confidence, or recency. A limit can therefore return old matching records before newer/current records. The repository deliberately avoids ranking in M3, but the result is a chronological search primitive rather than a strong context selector.

Corpus retrieval computes deterministic lexical scores and can optionally fuse a local semantic adapter, but it fetches all FTS matches first and performs authorization/filtering/scoring/sorting in Python. Metadata-only and FTS fallback paths read all units. This keeps authorization influence controlled, but context-selection CPU and RAM are proportional to candidate volume rather than final evidence size.

## 17. Configuration Architecture

Configuration is spread across environment variables, XDG defaults, `config.json`, Hermes integration JSON, `BridgeConfig`, CLI arguments, and runtime globals. This is understandable for a staged project, but an adopter must know which layer controls which behavior.

Important properties:

- `ZERO_MEM_DATA_ROOT` can override the data root; XDG variables control config/state/cache roots.
- The persisted config stores absolute paths and requires them to equal the paths recomputed from the current environment.
- Hermes identity is explicit in the release descriptor, while lower-level bridge config can also read `HERMES_PROJECT_ID` and `HERMES_PROFILE_ID`.
- `ZERO_MEM_ENABLED` is documented as the master switch, but the module-level runtime can be reassigned by adapter construction.
- There is no single configuration object passed through the full capture→ingest→retrieval lifecycle.

Moving a data directory requires preserving the correct environment/config relationship or using backup/restore. Moving a configured Hermes installation across package versions requires revalidating or rewriting the descriptor.

## 18. Failure Isolation & Recovery

The fail-open observer behavior is a strength: registration callbacks catch exceptions and do not propagate them into Hermes; injection catches failures and returns no context; read adapters return sanitized capability/downstream errors. SQLite and derived-state upgrades are staged and rebuildable. Backup/restore verifies canonical payloads and attempts rollback.

The main failure-isolation limitation is silent degradation:

- a missing capture store can result in registered hooks that do not append anything;
- callback failures are recorded in in-memory diagnostics only;
- a canonical append can succeed while derived ingest never runs;
- doctor checks existence/readability, not freshness, ingestion lag, or event loss;
- malformed historical JSONL causes capture-store initialization to reject the whole store rather than exposing a degraded/readable prefix.

For a parent agent, this generally means “agent continues but memory may be absent or stale.” That is safer than crashing the agent, but not safe enough for an operator who assumes memory capture is active.

## 19. Observability & Debuggability

The project has content-safe metrics structures, sanitized diagnostic codes, `doctor --json`, backup verification, and benchmark JSON outputs. That is a good foundation.

Missing operational signals include:

- capture events accepted/rejected/duplicated by profile/project over time;
- canonical-to-derived lag and last ingested sequence;
- ingest checkpoint age and source identity;
- concurrent writer/lock contention;
- retrieval latency and result counts by route;
- EvidenceSet truncation and empty/insufficient reasons;
- SQLite WAL size/health and rebuild duration;
- explicit warning when a Hermes hook is registered without a persistence store;
- persistent or exportable logs for fail-open callback errors.

The result is that a user can often prove that files exist, but cannot easily prove that the running agent is capturing, indexing, and retrieving the expected records.

## 20. Findings

### F-001

Category: INTEGRATION / DATA

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Hermes boundary composition

File: `zero_mem/hermes_integration.py`

Class/Function: `HermesBoundary.register`

Lines: 308–351, especially 326–330

Current behavior: When `capture_root` is supplied, `HermesBoundary.register()` constructs `RegistrationAdapter(BridgeConfig(...))` without passing a `store`. `RegistrationAdapter` accepts `store=None` and only calls `adapt_mapped_event(..., store=self.store)` when a store is present.

Why this is a problem: The public composed Hermes boundary can report capture hooks as registered while the callback only maps/redacts/validates and then drops the event. The CLI integration command does not create or inject a capture store either.

Impact on:

- performance: low direct cost, but wasted hook work and false confidence;
- compatibility: host must know an internal store-injection requirement not represented by the public boundary;
- Hermes integration: capture surface is not functionally connected to persistence;
- other agents: generic adopters face the same silent no-op risk;
- scalability: no records reach the intended pipeline, so scale can look healthy while memory is empty;
- maintenance: the public composition and lower-level adapter contract can drift independently.

Evidence: `src/integration/hermes_registration.py:27–30` makes the store optional; `src/integration/hermes_registration.py:86–87` persists only when it is non-null; `zero_mem/hermes_integration.py:328–330` omits it.

Expected behavior / desired architectural property: A registered capture boundary must either own a configured canonical writer or refuse registration with an explicit `CAPTURE_NOT_CONFIGURED` diagnostic. Registration success should imply that an event has a persistence path.

Recommended direction:

- short-term: make the boundary construct a configured writer from an explicit path, or fail closed for capture registration when no writer is provided;
- long-term: expose one stable lifecycle object that owns capture, derived synchronization policy, diagnostics, and shutdown.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Now

### F-002

Category: DATA / ARCH / PERF

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Capture-to-derived synchronization

File: `src/integration/capture_adapter.py`, `src/storage/ingest.py`

Class/Function: `adapt_mapped_event`, `ingest_file`

Lines: `src/integration/capture_adapter.py:102–124`; `src/storage/ingest.py:525–615`

Current behavior: Capture calls `store.append(envelope)` and returns. SQLite metadata, lifecycle, provenance, relations, scopes, FTS, and checkpoints are updated only by a separate explicit `ingest_file()` call.

Why this is a problem: The architecture diagram implies an end-to-end append plus derived update, but the implementation does not define whether ingestion is synchronous, queued, scheduled, or host-owned. Canonical data can be newer than retrieval data indefinitely.

Impact on:

- performance: synchronous coupling is avoided, but the cost is shifted to unbounded lag or later full replay;
- compatibility: every adopting agent must invent its own ingest scheduler or rebuild policy;
- Hermes integration: the hook path does not guarantee searchable memory;
- other agents: no portable lifecycle contract states when a write becomes retrievable;
- scalability: repeated replay grows with the complete JSONL history;
- maintenance: two state machines must be kept consistent without a shared transaction boundary.

Evidence: capture ends at `store.append()`; `ingest_file()` is a separate API that reads a JSONL path and writes the derived store. No call from the Hermes boundary connects the two.

Expected behavior / desired architectural property: The public write operation should define a clear consistency mode: synchronous derived projection, bounded asynchronous queue with observable lag, or explicitly canonical-only with a documented retrieval freshness contract.

Recommended direction:

- short-term: document and expose an explicit `sync()`/`rebuild()` lifecycle call and report stale-derived status;
- long-term: add a lightweight owned projection worker or transactional batch coordinator, keeping JSONL canonical and making lag measurable.

Estimated complexity: High

Breaking-change risk: High

Priority: Before V1

### F-003

Category: PERF / SCALE / DATA

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Canonical capture startup and JSONL ingestion

File: `src/storage/jsonl_capture.py`, `src/storage/ingest.py`

Class/Function: `JsonlCaptureStore._load`, `ingest_file`, `_iter_jsonl_lines`

Lines: `jsonl_capture.py:28–49`; `ingest.py:537–566`

Current behavior: Capture startup reads the entire file with `read_bytes()`, splits all lines, validates every record, and stores full records in two dictionaries. Ingestion reads the entire file and splits it, then `_iter_jsonl_lines()` reads and splits the file again.

Why this is a problem: Startup and replay cost grow with all historical memory, even when only new records are needed. Full sanitized content is retained in memory for dedupe/inspection, and ingestion creates multiple large in-memory representations.

Impact on:

- performance: measured load and ingest time grow sharply with N;
- compatibility: small agents work, but long-running adopters can hit memory or latency limits without changing code;
- Hermes integration: reinitializing a capture adapter becomes increasingly expensive;
- other agents: embedded use in an event loop or short-lived process is unattractive at scale;
- scalability: 100k/1M records are not supported by demonstrated bounded memory behavior;
- maintenance: future compaction/rotation must preserve sequence, dedupe, and checkpoint semantics.

Evidence: synthetic probe results were 1,000 records: 52.25 ms load / 6.42 MiB peak; 5,000: 274.10 ms / 32.08 MiB; 10,000: 1,237.77 ms / 64.20 MiB. Ingest was 0.408 s, 2.982 s, and 19.355 s respectively.

Expected behavior / desired architectural property: Startup should be O(1) or bounded by a compact index; incremental ingest should stream from a checkpoint without rereading/materializing the full source.

Recommended direction:

- short-term: stream line-by-line, avoid the duplicate full read, and measure/limit retained payload state;
- long-term: segment canonical streams and maintain a compact durable event-id/hash/offset index that can be rebuilt independently.

Estimated complexity: High

Breaking-change risk: High

Priority: Before V1

### F-004

Category: RELIABILITY / DATA / SCALE

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Canonical JSONL write safety

File: `src/storage/jsonl_capture.py`

Class/Function: `JsonlCaptureStore.append`

Lines: 22–25, 55–86

Current behavior: The writer uses a `threading.RLock` and per-process `_by_id`, `_by_hash`, and `_next_sequence` state. It appends with `open("ab")`, flushes, and fsyncs, but does not use a cross-process lock or a durable shared sequence allocator.

Why this is a problem: Separate agent processes can make decisions from stale maps, assign the same sequence number, miss duplicate content, and interleave writes. WAL protects SQLite independently; it does not make the canonical JSONL protocol process-safe.

Impact on:

- performance: retries and rebuilds may be needed after races;
- compatibility: a shared installation is unsafe unless users serialize writers themselves;
- Hermes integration: multiple Hermes workers/processes are not covered by the lock;
- other agents: multi-process runtimes cannot rely on the default store;
- scalability: concurrency scales poorly and can corrupt logical sequencing;
- maintenance: recovery must distinguish valid duplicate/raced records from corruption.

Evidence: the only lock is `threading.RLock`; sequence and dedupe state are ordinary in-memory fields; no `fcntl`, Windows locking, lock file, or interprocess protocol exists in the file.

Expected behavior / desired architectural property: The canonical write boundary must either be explicitly single-process or provide cross-process serialization and durable idempotency semantics.

Recommended direction:

- short-term: declare the current store single-process and reject/shared-mode assumptions in doctor/integration diagnostics;
- long-term: use a small lock/append coordinator or SQLite-backed durable write index while retaining JSONL as canonical payload storage.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Before V1

### F-005

Category: PORTABILITY / DEP / COMPAT

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Release installer and runtime policy

File: `packaging/install.py`, `pyproject.toml`, `zero_mem/commands_doctor.py`

Class/Function: `_runtime_python`, `_verify_runtime`, `collect`

Lines: `install.py:48–72, 123–133`; `pyproject.toml:10`; `commands_doctor.py:91–95`

Current behavior: The package requires CPython `>=3.11,<3.14`. The installer assumes `venv/bin/python` and `venv/bin/zero-mem`; Windows uses `Scripts/python.exe` and `Scripts/zero-mem.exe`. Doctor rejects Python 3.14 even when imports and SQLite are otherwise available.

Why this is a problem: The repository’s stated portability target cannot include Windows through the supplied installer, and newer Python environments fail readiness by design. The full host run exposed installer setup errors and doctor failures.

Impact on:

- performance: no direct effect;
- compatibility: fresh Windows installation is not supported by the supplied path;
- Hermes integration: Windows adopters cannot reach the documented integration flow reliably;
- other agents: container/CI environments with Python 3.14 fail readiness;
- scalability: no direct effect;
- maintenance: platform-specific release logic and test baselines are missing.

Evidence: full suite on Windows/CPython 3.14 produced 11 packaging errors and doctor failures; test setup attempted a non-existent `.../venv/bin/python`.

Expected behavior / desired architectural property: Either support Windows and the chosen Python versions end-to-end or state a narrow Linux/macOS + CPython policy and keep the compatibility matrix honest.

Recommended direction:

- short-term: make installer executable discovery platform-aware and publish explicit supported OS/runtime combinations;
- long-term: add cross-platform packaging/test workflows, including Windows venv, shim, permissions, and path semantics.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Before V1

### F-006

Category: CONFIG / INTEGRATION / SCALE

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Process-global master switch

File: `src/integration/zero_mem_runtime.py`, `src/integration/hermes_read_adapter.py`, `src/integration/hermes_registration.py`

Class/Function: `configure`, adapter constructors

Lines: `zero_mem_runtime.py:76–96`; `hermes_read_adapter.py:88–96`; `hermes_registration.py:27–37`

Current behavior: `configure()` overwrites the module-global `_default_runtime` every time it is called. Multiple adapters call it during construction with their local `zero_mem_enabled` value.

Why this is a problem: The code describes one resolved process-wide value configured once at startup, but construction order can replace it. Different agents/profiles in one process can therefore observe different effective master-switch behavior. M7 injection reads `get_runtime()` dynamically, making the effect especially sensitive to later reconfiguration.

Impact on:

- performance: low direct cost;
- compatibility: embedding multiple Zero-Mem clients in one host is unsafe;
- Hermes integration: plugin registration order can change global behavior;
- other agents: one adapter can affect another adapter in the same process;
- scalability: multi-agent in-process use is not isolated;
- maintenance: configuration ownership is unclear and hard to reason about.

Evidence: `configure()` assigns a new runtime unconditionally; both Hermes read and capture adapters call it from `__init__`.

Expected behavior / desired architectural property: Resolve configuration once at host/runtime initialization and pass an immutable runtime object to each adapter, or explicitly scope it per client.

Recommended direction:

- short-term: guard/reject conflicting reconfiguration and expose the effective owner in diagnostics;
- long-term: remove mutable module-global policy from the integration contract and inject immutable runtime/configuration state.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Before V1

### F-007

Category: COMPAT / INTEGRATION / CONFIG

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Hermes integration descriptor compatibility

File: `zero_mem/hermes_integration.py`

Class/Function: `IntegrationConfig.from_dict`

Lines: 59–81, especially 69–72

Current behavior: A descriptor is accepted only if `package_version == __version__` and `boundary == BOUNDARY_ID`. A package-version mismatch is returned as “incompatible integration configuration.”

Why this is a problem: A package upgrade that preserves the data schema and boundary contract invalidates the integration descriptor and requires manual reconfiguration. This is stricter than the derived-state upgrade model and makes “upgrade is safe” conditional on re-running integration setup.

Impact on:

- performance: no direct effect;
- compatibility: upgrades can disable an otherwise compatible adapter;
- Hermes integration: host registration may fail after a package-only upgrade;
- other agents: each adapter descriptor needs a migration/compatibility policy;
- scalability: no direct effect;
- maintenance: package version is being used as an interface/schema version.

Evidence: exact equality checks on `schema_version`, `package_version`, and `boundary`; no descriptor migration table exists.

Expected behavior / desired architectural property: Bind compatibility to a stable boundary/schema version and record package version for diagnostics, not as the sole acceptance gate.

Recommended direction:

- short-term: distinguish package-version drift from boundary incompatibility and provide a safe revalidation path;
- long-term: version the adapter contract independently and define descriptor migration/compatibility ranges.

Estimated complexity: Low

Breaking-change risk: Low

Priority: Before V1

### F-008

Category: PERF / SCALE / INTEGRATION

Severity: P1 — High

Confidence: Confirmed issue, high confidence

Location: Corpus retrieval candidate discovery

File: `src/corpus/retrieval.py`

Class/Function: `retrieve_corpus`

Lines: 341–373, 379–402

Current behavior: Metadata-only and FTS-unavailable paths select all corpus units. With FTS, the query fetches all matching rows before `_authorize_and_filter`; Python then authorizes, scores, optionally fuses semantic results, sorts, and truncates.

Why this is a problem: Final EvidenceSet bounds are small, but pre-bound candidate work is proportional to all matching/available units. At large corpus sizes, latency and RAM can be dominated by unauthorized or ultimately discarded candidates.

Impact on:

- performance: O(N) fallback and O(number of FTS matches) materialization;
- compatibility: large corpora require FTS and careful query shapes;
- Hermes integration: pre-LLM retrieval can block the host;
- other agents: a generic agent cannot assume bounded retrieval cost from the final limit;
- scalability: 100k/1M corpus units are a clear risk;
- maintenance: authorization-before-ranking semantics must be preserved while pushing predicates down.

Evidence: `_read_all_units()` returns all rows; FTS uses `.fetchall()` before authorization; Python performs the subsequent filter/score/sort.

Expected behavior / desired architectural property: Candidate discovery and authorization should be pushed into indexed SQL where possible, with bounded fetches and explicit fallback warnings.

Recommended direction:

- short-term: add performance measurements and refuse/diagnose unbounded fallback for large stores;
- long-term: maintain authorization-aware indexed predicates or per-scope candidate queries, then rank only a bounded authorized set.

Estimated complexity: High

Breaking-change risk: Medium

Priority: Before V1

### F-009

Category: RETRIEVAL / PERF / COST

Severity: P2 — Medium

Confidence: Confirmed architectural concern, high confidence

Location: Memory FTS result ordering

File: `src/retrieval/search.py`

Class/Function: `search_text`

Lines: 113–150, especially 120–133

Current behavior: FTS results are ordered by `created_at ASC, event_id ASC`. The code deliberately does not use bm25, verification, confidence, or recency ranking.

Why this is a problem: A bounded result set can return old matching records before newer or more relevant records. The M7 specialized EvidenceSet path improves selection for supported routes, but the lower-level memory search API remains a chronological scan primitive.

Impact on:

- performance: indexed lookup remains fast at small scale;
- compatibility: callers must implement their own relevance/current-state policy;
- Hermes integration: generic memory tools can surface stale context first;
- other agents: context quality depends on internal knowledge of M3 limitations;
- scalability: bounded limits can hide relevant records behind old matches;
- maintenance: multiple ranking semantics may diverge across routes.

Evidence: the SQL `ORDER BY` is chronological and the module documentation explicitly excludes ranking signals.

Expected behavior / desired architectural property: The public retrieval contract should state whether it returns chronological evidence or relevance-ranked context, and context-facing calls should have a bounded freshness/relevance policy.

Recommended direction:

- short-term: expose ordering mode and document stale-state behavior;
- long-term: keep deterministic ranking modular, combining lexical match with verification/currentness/conflict state only after authorization.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Before V1

### F-010

Category: PERF / COST

Severity: P2 — Medium

Confidence: Confirmed optimization opportunity, high confidence

Location: Capture and derived-write durability path

File: `src/storage/jsonl_capture.py`, `src/storage/ingest.py`

Class/Function: `JsonlCaptureStore.append`, `_commit_outcome`

Lines: `jsonl_capture.py:76–80`; `ingest.py:627–656`

Current behavior: Every capture append flushes and fsyncs the JSONL file. Every ingested line runs a transaction that can insert multiple derived rows, write an ingest log/checkpoint, and commit.

Why this is a problem: This maximizes per-event durability but makes burst capture and replay expensive. It is particularly costly when the agent produces many tool/LLM lifecycle events and the host expects low synchronous overhead.

Impact on:

- performance: high write amplification and syscall/commit frequency;
- compatibility: async hosts need an explicit offload policy;
- Hermes integration: hook latency can increase under disk contention;
- other agents: local SSD/HDD/container overlay behavior will vary widely;
- scalability: bulk replay cost grows more than a batched write path;
- maintenance: durability guarantees are not expressed as a configurable consistency mode.

Evidence: direct `os.fsync()` in append and per-line `BEGIN`/`COMMIT` in ingestion.

Expected behavior / desired architectural property: Make durability/batching semantics explicit and measurable while preserving a safe default.

Recommended direction:

- short-term: batch derived ingestion and benchmark synchronous capture overhead separately from durability mode;
- long-term: provide bounded queue/batch policies with clear loss/recovery semantics.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Before V1

### F-011

Category: ARCH / INTEGRATION / COMPAT

Severity: P2 — Medium

Confidence: Confirmed architectural concern, high confidence

Location: Public API surface

File: `zero_mem/__init__.py`, `pyproject.toml`, internal `src/*` modules

Class/Function: package exports and entry points

Lines: `zero_mem/__init__.py:1–5`; `pyproject.toml:18–30`

Current behavior: The public package exports only `__version__` and one CLI entry point. Capture, storage, retrieval, authorization, and injection interfaces are exposed through internal `src.*` modules rather than a documented stable facade.

Why this is a problem: A developer adding memory to a generic agent must know internal module topology, envelope fields, storage construction, and lifecycle ordering. This is tight coupling to Zero-Mem internals even where Hermes coupling is avoided.

Impact on:

- performance: adopters may create inefficient ad hoc compositions;
- compatibility: internal module moves become breaking changes;
- Hermes integration: host code must understand multiple adapter classes;
- other agents: no small sync/async-neutral contract exists;
- scalability: lifecycle ownership is duplicated by each integration;
- maintenance: support burden increases as integrations fork their own wiring.

Evidence: `zero_mem.__all__` contains only `__version__`; packaging includes `src*`, but no stable `api` package or lifecycle facade is declared.

Expected behavior / desired architectural property: External agents should depend on a small versioned API, not directly on `src` implementation modules.

Recommended direction:

- short-term: publish a minimal generic facade and mark internal modules private;
- long-term: version the lifecycle contract separately from storage, retrieval implementation, and host adapters.

Estimated complexity: High

Breaking-change risk: High

Priority: Before V1

### F-012

Category: CONFIG / PORTABILITY / INTEGRATION

Severity: P2 — Medium

Confidence: Confirmed architectural concern, high confidence

Location: Path defaults and capture-root safety

File: `zero_mem/paths.py`, `src/integration/bridge_config.py`

Class/Function: `data_root`, `_xdg_path`, `_safe_root`

Lines: `paths.py:26–50`; `bridge_config.py:100–104`

Current behavior: Runtime defaults use XDG variables or `Path.home()/'.local/...` even on Windows. `BridgeConfig._safe_root()` rejects any capture root inside the real home directory. The release setup’s default data root is itself under the user home on common systems.

Why this is a problem: The default storage model and the capture-root safety rule are difficult to compose. A user can complete `zero-mem setup` but cannot simply point the Hermes capture boundary at the default home-local canonical root without violating the bridge safety rule. Windows also receives Unix-style default directories unless explicitly configured.

Impact on:

- performance: no direct effect;
- compatibility: users need non-obvious explicit paths and environment setup;
- Hermes integration: setup success does not imply a valid capture root;
- other agents: path policy differs between release layer and integration layer;
- scalability: no direct effect;
- maintenance: multiple path authorities must remain aligned.

Evidence: release defaults are home-local; bridge config rejects roots under `Path.home()`; no CLI option connects the two policies.

Expected behavior / desired architectural property: The product should have one explicit data-root contract and a documented policy for whether capture data may live there.

Recommended direction:

- short-term: surface path conflicts in `doctor` and require an explicit, validated capture root;
- long-term: centralize path policy and support native platform defaults or an explicitly Unix-only product scope.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Before V1

### F-013

Category: OBS / RELIABILITY

Severity: P2 — Medium

Confidence: Confirmed issue, high confidence

Location: Failure reporting and health checks

File: `src/integration/hermes_registration.py`, `src/integration/m7/injection_adapter.py`, `zero_mem/commands_doctor.py`

Class/Function: callback wrappers, `_on_pre_llm_call`, `collect`

Lines: `hermes_registration.py:53–70`; `injection_adapter.py:115–125`; `commands_doctor.py:124–142`

Current behavior: Broad exceptions are converted to in-memory diagnostic codes or `None`. Doctor checks Python, paths, file readability, SQLite schema, FTS capability, and optional integration presence, but does not check capture freshness, ingestion lag, event counts, or last successful write.

Why this is a problem: Fail-open protects the agent process, but an operator cannot distinguish “memory intentionally empty,” “capture store missing,” “derived index stale,” and “callbacks failing” from a durable operational signal.

Impact on:

- performance: no direct cost;
- compatibility: host integrations cannot reliably monitor readiness;
- Hermes integration: registered-but-failing hooks can remain invisible;
- other agents: debugging requires reading internals or reproducing locally;
- scalability: backlog/lag growth is not surfaced;
- maintenance: failures are hard to correlate with lifecycle events.

Evidence: broad `except Exception` paths and a doctor result based on existence/readability rather than freshness/lag.

Expected behavior / desired architectural property: Lightweight structured diagnostics should expose health, counts, lag, and failure classes without exposing payloads or secrets.

Recommended direction:

- short-term: add content-free counters and last-success/last-failure diagnostics to the public health report;
- long-term: define an observable lifecycle with bounded logs/metrics suitable for local agents.

Estimated complexity: Medium

Breaking-change risk: Low

Priority: Before V1

### F-014

Category: PERF / RELIABILITY / SYNC-ASYNC

Severity: P2 — Medium

Confidence: Likely issue, medium-high confidence

Location: Context injection read path

File: `src/integration/m7/injection_adapter.py`

Class/Function: `_make_service`, `process`

Lines: 176–195, 224–238

Current behavior: Each memory-needed `pre_llm_call` creates a new read-only SQLite connection and `AuthorizedReadService`. The service is not given an explicit lifecycle/close boundary by the adapter; cleanup relies on object lifetime after the request.

Why this is a problem: Repeated pre-LLM calls pay connection open/schema validation cost and can create connection churn. On non-reference-counted runtimes or exceptional paths, resource release timing is less predictable. All work is synchronous.

Impact on:

- performance: repeated connection setup on the agent hot path;
- compatibility: async runtimes can block while opening/querying SQLite;
- Hermes integration: high-turn sessions pay the cost before generation;
- other agents: no reusable read-session or executor contract;
- scalability: connection churn grows with hook frequency;
- maintenance: ownership of read-store closure is implicit.

Evidence: `_make_service()` calls `open_readonly()` on every request and returns a service without a context manager or explicit close in the adapter.

Expected behavior / desired architectural property: Reuse a safe read-only session per lifecycle or expose explicit request-scoped ownership and close semantics.

Recommended direction:

- short-term: measure connection-open cost and make ownership/close explicit;
- long-term: provide sync and async-safe read-session abstractions with bounded concurrency.

Estimated complexity: Medium

Breaking-change risk: Medium

Priority: Before V1

## 21. Performance Complexity Table

| Operation | Current complexity | Main bottleneck | Scale risk |
|---|---:|---|---|
| Empty setup | O(schema) | Directory creation and SQLite migrations | Low |
| Capture-store startup | O(N) time, O(total record content) RAM | Full JSONL read/parse and two full-record maps | High |
| Insert to canonical JSONL | O(1) logical work plus fsync | Serialization, per-event durability, process-local dedupe | High under burst/concurrency |
| Dedup at live capture | O(1) after startup | In-memory maps; stale across processes | High for shared process mode |
| Incremental ingest | O(file bytes) read/parse; per-line DB commit | Full read/split plus transaction per line | High |
| FTS memory search | Index-assisted candidate lookup, then O(limit) result shaping | Chronological ordering and SQLite join/filter | Medium; quality risk grows with history |
| Authorized multi-scope read | O(scopes × rows fetched) plus Python merge/sort | One query per scope and materialized union | High with many grants/scopes |
| Corpus lexical retrieval | O(matches) with FTS, O(N) fallback; Python sort | Fetch-before-auth and in-memory scoring | High |
| Corpus metadata-only retrieval | O(N) | Full `zm_corpus_units` materialization | High |
| Canonical replay/rebuild | O(N) plus all derived projection work | Full parse, per-event projection, graph/temporal rebuild | High |
| Upgrade | O(all canonical memory + optional corpus) | Full staged derived rebuild and doctor | Medium/High |
| Backup verify | O(total backup bytes/files) | Full path walk, checksums, canonical validation | Medium |

N means total historical canonical records; corpus M means total corpus units/files.

## 22. System-Wide Bottlenecks

1. **Integration composition:** The release boundary does not connect registered capture hooks to a persistence store, and no CLI command activates a host plugin.
2. **Canonical-to-derived freshness:** JSONL capture and SQLite projection are separate lifecycle operations with no public consistency contract.
3. **History-dependent persistence:** full-file load/replay and full-record in-memory maps make startup and ingest scale with all historical memory.
4. **Shared-write safety:** process-local locking is insufficient for multiple agents/processes sharing one installation.
5. **Context candidate processing:** corpus fallback and FTS candidate materialization can scale with all matching/available units before final bounded selection.

At 10x usage, these bottlenecks produce longer ingest/rebuild windows and increasing retrieval staleness. At 100x, memory footprint and full-scan behavior become operational constraints. Across multiple machines, the current embedded-file architecture is not the right mode without a new service/write-coordinator boundary.

## 23. Compatibility Matrix

| Environment | Current status | Main issue | Required work |
|---|---|---|---|
| Hermes | Possible with adapter code; not drop-in | Descriptor-only CLI; missing capture-store wiring; hook coverage limited | Stable host plugin entry point and owned lifecycle composition |
| Generic Python agent | Possible with moderate adaptation | Must import internal `src.*` APIs and manage ingest | Public generic lifecycle/retrieval facade |
| Async Python agent | Limited | Synchronous file/SQLite/fsync in hook path; no async API | Explicit worker/executor or async-safe facade and backpressure |
| Linux | Best-supported | Still requires explicit integration and ingest scheduling | End-to-end install/integration test |
| macOS | Likely supported | No native CI evidence; Unix assumptions only | Native packaging/test coverage |
| Windows | Not supported by supplied installer | Hardcoded `bin` paths; shell scripts; permission/venv differences | Platform-aware installer/shim and Windows CI |
| WSL | Possible as Linux | Host/Windows boundary and filesystem semantics | Documented WSL mode and tests |
| Docker | Embedded-only possible | No image/service protocol; explicit roots required | Container contract, or document embedded-only scope |
| Multi-agent | Limited/unsafe for shared JSONL | No interprocess lock; global runtime/config collisions | Single-writer coordinator or explicit per-agent stores |

## 24. Scores

### Performance readiness: 5/10

Small-store query latency is strong and no mandatory model calls are required. Full-file startup/ingest, per-event durability, and unbounded corpus candidate materialization prevent a higher score without 100k/1M evidence.

### Hermes compatibility: 4/10

The adapter separation and fail-open behavior are good, but the actual release workflow does not activate a host plugin, and the public boundary can register capture hooks with no store.

### General agent compatibility: 4/10

Core logic is mostly host-independent, but the public contract is internal-module-oriented and there is no generic lifecycle facade or async story.

### Installability: 5/10

The offline, no-root Linux path is clear and low-dependency. Windows installation is not supported by the implementation, and Hermes still requires custom host wiring.

### Long-run scalability: 4/10

Rebuildability and canonical separation are strong, but startup, replay, fallback retrieval, and shared writes grow with total history/corpus.

### Maintainability: 5/10

Tests, contracts, migrations, and documentation are substantial strengths. The large staged surface, duplicated configuration/lifecycle concepts, internal `src` dependency, and version-bound integration descriptor increase change cost.

## 25. Recommended Target Direction

The target should remain lightweight and local:

```text
zero_mem/
  core/                 # typed memory events, policy-neutral lifecycle, errors
  storage/
    canonical/          # segmented JSONL/blob writer and durable offsets
    indexes/             # SQLite/FTS projections and rebuilds
  retrieval/             # authorized, bounded query primitives
  context/               # route, rank, budget, projection
  adapters/
    generic/             # stable sync/async-neutral host contract
    hermes/              # Hermes-specific hook/tool mapping only
  api/                   # versioned public lifecycle facade
  cli/
```

The key properties are more important than the exact directories:

- one public client object with explicit `initialize`, `observe`, `retrieve`, `sync`, `health`, and `shutdown` operations;
- canonical writes either explicitly single-writer or protected by a small cross-process coordinator;
- incremental stream/segment indexes so startup does not parse all history;
- a visible canonical-to-derived lag/consistency state;
- authorization pushed into candidate discovery where possible;
- bounded, context-facing ranking separate from raw chronological search;
- host adapters that never own core storage logic;
- independent API/boundary versioning from package release version;
- platform-aware paths/installers or a clearly limited OS support policy.

This does not require Kubernetes, Kafka, Redis, a vector database, or cloud infrastructure. A single local writer, SQLite projection, segmented canonical files, and a small worker/executor are sufficient for the intended V1 scale.

## 26. Recommended Roadmap

### Phase 0 — Must resolve before V1

1. Repair the public Hermes composition so registered capture has a real persistence path or explicitly fails registration.
2. Define and implement the canonical-to-derived consistency contract: synchronous, queued, or explicit canonical-only; include `sync`, lag, and recovery semantics.
3. Decide and document shared-installation policy; either enforce single-process/single-writer or add cross-process serialization.
4. Publish a small generic public API and mark `src.*` implementation modules non-contractual.
5. Resolve OS/runtime scope: make the installer cross-platform or explicitly limit V1 and remove misleading portability claims.

### Phase 1 — V1 hardening

- Stream JSONL ingestion and eliminate duplicate full-file materialization.
- Add capture segmentation/rotation and compact durable offsets/dedupe indexes.
- Make master-switch/runtime ownership immutable and non-conflicting.
- Version Hermes boundary descriptors independently from package version.
- Add health counters, lag, last-success timestamps, and persistent content-safe diagnostics.
- Add a sync/async integration guide and failure behavior matrix.

### Phase 2 — Multi-agent readiness

- Support one isolated data root/profile per agent by default.
- If shared mode is desired, add a local single-writer service/coordinator with explicit scope and lock diagnostics.
- Test multi-process writes, crash recovery, sequence uniqueness, and profile isolation.

### Phase 3 — Performance optimization

- Benchmark 1k/10k/100k/1M memory records and corpus units.
- Batch durable writes only after measuring loss/durability tradeoffs.
- Push authorization/filter predicates into indexed candidate discovery.
- Measure context token savings against a no-memory baseline.

### Phase 4 — Ecosystem adapters

- Hermes adapter first, built on the generic contract.
- Then CLI, async Python, and selected framework adapters only when real adopters justify them.
- Keep each adapter thin and independently versioned.

## 27. Final Assessment

```text
ZERO-MEM SYSTEM ASSESSMENT

Architecture:
NEEDS WORK

Performance:
NEEDS WORK

Long-term scalability:
NEEDS WORK

Hermes integration:
NEEDS WORK

General agent compatibility:
NEEDS WORK

Installation portability:
NEEDS WORK

Dependency footprint:
GOOD

Token/cost efficiency:
ACCEPTABLE

Multi-agent readiness:
HIGH RISK

V1 architecture readiness:
NOT READY
```

### Top 5 strengths

1. Clear canonical-vs-derived intent with rebuildable SQLite/FTS/projection state.
2. No mandatory LLM, network, paid API, or heavyweight runtime dependency.
3. Strong authorization, redaction, fail-closed retrieval boundaries, and bounded EvidenceSet design.
4. Deterministic migrations, backups, staged upgrade, and extensive acceptance tests.
5. Hermes adapters avoid direct Hermes package imports and aim for fail-open observer behavior.

### Top 5 weaknesses

1. Public Hermes boundary can register capture without a persistence store.
2. Canonical capture and derived retrieval are disconnected lifecycle operations.
3. JSONL startup/replay and corpus fallback retrieval are history/candidate proportional.
4. Canonical JSONL writes are not safe for multiple processes.
5. No small stable generic API; packaging is Unix-oriented and Hermes activation remains host-code work.

### Top 5 issues to address before V1

1. Fix capture wiring and define write-to-retrieval consistency.
2. Establish a public agent-agnostic lifecycle API.
3. Make canonical storage single-writer-safe or explicitly enforce isolation.
4. Remove full-file startup/replay scaling hazards.
5. Resolve Windows/Python support policy and integration descriptor upgrade compatibility.

### Top 5 improvements after V1

1. Indexed, authorization-aware bounded candidate retrieval.
2. Async worker/batch durability modes with measurable backpressure.
3. Multi-agent shared-local mode, if real demand exists.
4. Context ranking improvements for freshness, verification, confidence, and conflict state.
5. Additional native adapters and container/service packaging based on measured demand.

### Fresh-machine integration experience

#### Hermes Agent

1. Install: obtain the offline bundle, use supported CPython 3.11–3.13, install the managed runtime, and run `zero-mem setup`.
2. Configure: set explicit project/profile IDs with `zero-mem integrate hermes`; choose/bridge explicit data and capture paths.
3. Code required: provide a Hermes plugin entry point/context, instantiate/register `HermesBoundary`, and fix the capture-store/derived-ingest lifecycle. The CLI alone does not do this.
4. Assumptions: expected `register_hook`/`register_tool` methods, declared hook names/signatures, explicit profile/project identity, readable derived SQLite, and an active `ZERO_MEM_ENABLED` policy.
5. Coupling: moderate adapter-level coupling to Hermes lifecycle hooks; high coupling to Zero-Mem internal composition because the stable host contract is not packaged as a generic facade.
6. Removal: relatively straightforward at the runtime/data boundary; remove host registration and the Zero-Mem descriptor/runtime. Default uninstall preserves data.
7. Upgrade safety: derived-state upgrade is staged, but the exact package-version check can invalidate the Hermes descriptor and require reconfiguration.
8. Failure behavior: the agent generally continues because callbacks fail open; memory can silently stop capturing or remain stale.
9. Runtime overhead: small-route memory injection is synchronous and can open a read-only SQLite connection per memory-needed hook; capture can fsync per event.
10. V1 acceptability: not acceptable as a zero-internals drop-in; acceptable only for an owner willing to write/maintain the adapter composition.

#### Generic Python agent

1. Install the same runtime and run setup.
2. Configure explicit roots and profile/project identity.
3. Write code against internal `src.*` modules to build valid envelopes, create a canonical writer, run ingest/sync, and call authorized retrieval/context APIs.
4. Assumptions include Zero-Mem envelope schema, storage paths, lifecycle ordering, and synchronous behavior.
5. Coupling to Zero-Mem internals is high until a public facade exists.
6. Removal is possible but requires deleting custom lifecycle calls and handling any injected context/tool registration.
7. Upgrade is safe for canonical data in principle, but internal APIs and integration descriptors are not yet a stable compatibility boundary.
8. The agent can continue if calls are isolated and failures are caught, but it must implement that isolation.
9. Overhead depends on the adopter’s composition; the repository does not provide a standard measurement.
10. V1 acceptability: not acceptable for an unaware developer; moderate after a documented public API is added.

#### Async Python agent

1. Install/configuration is the same.
2. The adopter must add a worker/executor boundary because file, fsync, SQLite, and rebuild operations are synchronous.
3. Code must define cancellation, queueing, backpressure, and shutdown behavior.
4. Assumptions about synchronous hooks and blocking local I/O are not safe on the event loop.
5. Coupling is high because no async-neutral interface exists.
6. Removal is manageable if integration is isolated behind one worker.
7. Upgrade/data safety is the same as generic Python, with additional in-flight queue concerns.
8. The agent can continue after failures, but blocking work can still delay it before fail-open handling.
9. Runtime overhead is unbounded by a product contract under load.
10. V1 acceptability: not acceptable without adopter-written async isolation.

#### Multi-agent environment

1. Each agent can install its own runtime/data root, which is the safer current mode.
2. A shared JSONL/SQLite installation is not safe by default because canonical writes use only process-local locking and runtime configuration is process-global.
3. Shared mode requires a single-writer/coordinator, namespace policy, and explicit profile/agent ownership.
4. Assumptions about one process, one store snapshot, and one master switch must be removed or enforced.
5. Coupling/operational complexity is high for shared mode.
6. Removal of one agent is straightforward only when data roots are isolated; shared stores require ownership-aware cleanup.
7. Upgrades need coordination across writers and readers; current staged rebuild does not solve concurrent canonical writes.
8. Individual agents may continue if memory is isolated, but shared-store failures can cause stale or conflicting memory.
9. Runtime overhead includes lock contention, repeated connections, and per-agent replay unless a coordinator exists.
10. V1 acceptability: single-agent embedded mode is plausible; shared multi-agent mode is not ready.

Final answer to the core question: Zero-Mem is a promising low-dependency local memory core with strong deterministic/security foundations, but the current repository is not yet a lightweight, portable, drop-in external memory subsystem for unaware agent developers. The missing stable lifecycle API, incomplete Hermes persistence composition, history-dependent JSONL behavior, and process/portability limits must be resolved before V1 can credibly claim reusable agent-memory status.
