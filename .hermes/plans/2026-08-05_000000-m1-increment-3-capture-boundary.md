# M1 Increment 3 — Capture Boundary and Deduplication Plan

> Implement only after approval. Use strict TDD. This increment follows the verified Increment 1 event contract and Increment 2 redaction boundary.

**Goal:** Add the project-owned append-only JSONL capture boundary that persists only redacted, validated envelopes, provides atomic append/contains/dead-letter interface shape, deduplicates by event ID and sanitized-content hash without deleting source records, and preserves deterministic ordering and crash-safe recovery.

## Scope

### In scope

- `append(event)`, `contains(event_id)`, and the approved capture-store interface.
- Versioned append-only JSONL raw trace stream as authoritative raw source.
- Redaction-before-persistence enforcement using Increment 2 output.
- Deterministic envelope serialization.
- Atomic line append and newline framing.
- Event-ID and sanitized-content-hash duplicate detection.
- Duplicate-result semantics without deleting or overwriting source records.
- Monotonic sequence/order guarantees within one store instance and documented process scope.
- Configurable capture path under the project data directory.
- Safe file permissions and parent-directory creation.
- Partial-write/truncated-last-line detection and recovery semantics.
- Contract-compatible `contains` behavior and sanitized failure results.

### Explicit exclusions

- Retry behavior and timing/deadlines.
- Dead-letter persistence and replay.
- Hermes hook registration or runtime integration.
- Capture-rate harness.
- SQLite, metadata/indexes, FTS, retrieval, graph, MCP, Obsidian, or prompt/context injection.
- Storage migration beyond a documented future M2 reader boundary.

## Authoritative raw stream

- Default path: project-configured capture root with a versioned filename such as `traces/events-v1.jsonl`.
- JSONL is the authoritative raw trace stream, not a temporary cache.
- Each accepted line is one deterministic serialized Increment 1 envelope after Increment 2 redaction.
- No separate competing SQLite or index store is created.
- Path configuration must be explicit; never infer from cwd, repository name, prompt, or session text.
- The implementation must expose a path constructor/configuration object so later M2 can place metadata above the same stream.

## Proposed interface

Create `src/storage/capture_boundary.py`:

```python
@dataclass(frozen=True)
class AppendResult:
    status: Literal["appended", "duplicate"]
    event_id: str
    sequence: int
    content_hash: str

class CaptureStore(Protocol):
    def append(self, event: Mapping[str, Any]) -> AppendResult: ...
    def contains(self, event_id: str) -> bool: ...
    def contains_content_hash(self, content_hash: str) -> bool: ...
```

Create `src/storage/jsonl_capture.py` with the concrete implementation. Exact names may be simplified during RED/GREEN, but the three approved operations and result semantics are binding.

`append` must reject an event that lacks Increment 1 required fields, has a stale/mismatched content hash, or has no evidence that redaction completed. It must not accept raw pre-redaction payloads. The store may verify `sanitized_content_hash` by recomputing it from the sanitized content before writing.

## Redaction-before-persistence boundary

Processing order:

```text
incoming payload
  -> Increment 2 redact_payload
  -> Increment 1 normalize/validate envelope
  -> recompute/check sanitized content hash
  -> deterministic serialize_envelope
  -> duplicate lookup
  -> atomic append
```

`append` should accept only a normalized sanitized envelope or a clearly named sanitized-envelope constructor output. It must not invoke arbitrary redaction heuristics itself, but must require the redaction audit/sanitized fields and reject a secret sensitivity/never-store retention envelope. No unredacted data may enter a file-open/write call.

## Deduplication

- First matching `event_id` returns `AppendResult(status="duplicate", ...)` and does not append a second line.
- A different event ID with an identical `sanitized_content_hash` returns duplicate according to the selected policy; default conservative behavior is duplicate/no append while preserving the first source line. The result must identify the duplicate status without exposing content.
- Deduplication indexes are in-memory/rebuilt by scanning the raw JSONL; no separate canonical index is introduced in this increment.
- Malformed or truncated lines are never used as valid deduplication entries.
- Source records are never deleted or silently rewritten.

## Ordering and sequence

- The store assigns a monotonic non-negative `sequence` for accepted records within the configured JSONL stream.
- Existing valid lines are scanned at initialization to recover the next sequence.
- Concurrent appends in one process are serialized by a lock.
- Cross-process locking must use a sibling lock file or platform-safe advisory lock; if unavailable, fail closed rather than interleave lines.
- Source event timestamps remain untouched; storage sequence is separate deterministic order evidence.

## Atomic append and crash handling

- Serialize one complete JSON object with deterministic key ordering, UTF-8, and exactly one trailing newline.
- Hold the store lock across duplicate check, sequence assignment, write, flush, and `fsync`.
- Use append mode; never rewrite the raw stream during normal append.
- On startup, detect a final line without a newline or invalid JSON. Do not silently delete it. Mark the stream as requiring repair and reject new appends until an explicit repair operation is approved; repair is out of scope for this increment.
- A complete final line remains valid after process crash. Partial writes remain visible for audit and are not promoted into the dedup set.
- File and directory creation must use restrictive permissions where supported (`0700` directory, `0600` file); do not weaken existing permissions.

## Configuration

Use explicit constructor configuration, for example:

```python
CaptureStoreConfig(root=Path("data/traces"), stream_name="events-v1.jsonl")
```

No environment-variable expansion is required unless explicitly passed by a caller. Do not infer project identity or storage path from Hermes state. Do not write under real `~/.hermes` during tests.

## Tests mapped to acceptance criteria

### C3-1 Append-only authoritative stream

- Append two valid sanitized envelopes.
- Assert two deterministic JSONL lines, one newline per line, and no SQLite/index files.
- Assert a second store instance recovers sequence from the stream.

### C3-2 Redaction-before-persistence

- Build a payload with synthetic secret, redact it through Increment 2, normalize it, append it.
- Assert raw file contains sanitized marker and never the synthetic secret.
- Attempt to append an envelope marked `secret`/`never_store` or missing redaction evidence; assert rejection and no file write.

### C3-3 Event-ID deduplication

- Append the same event twice.
- Assert first result is `appended`, second is `duplicate`, and line count remains one.

### C3-4 Sanitized-content-hash deduplication

- Append two event IDs with equal sanitized content hash.
- Assert duplicate result and preserved first source line.

### C3-5 Ordering/sequence

- Append ordered events and reopen the store.
- Assert sequences are contiguous and monotonic, while source timestamps remain as supplied.
- Use concurrent threads to assert no duplicate sequence or interleaved JSON lines.

### C3-6 Atomic/crash handling

- Simulate a final partial line and assert new appends fail closed without deleting it.
- Verify complete lines remain readable and dedup-able after reopen.
- Verify restrictive permissions on newly created path where supported.

### C3-7 Deterministic serialization

- Append equivalent mappings with different key insertion order.
- Assert serialized line/content hash is deterministic.

### C3-8 Compatibility/regression

- Increment 1 contract tests remain passing.
- Increment 2 redaction tests remain passing.
- No Hermes integration, retry, dead-letter, or future component is imported or invoked.

## Acceptance criteria

| Criterion | Objective evidence |
|---|---|
| Append-only source of record | Focused tests show versioned JSONL lines, no rewrites/deletes, and reopen recovery |
| Stable interface | Tests exercise `append`, `contains`, and dead-letter interface boundary placeholder without implementing dead-letter persistence |
| Mandatory redaction boundary | Secret fixture is redacted before append; raw stream has no original secret; unsafe envelope is rejected |
| Event-ID deduplication | Duplicate result with unchanged line count |
| Content-hash deduplication | Duplicate result for equal sanitized hash with source preserved |
| Ordering/sequence | Monotonic contiguous sequences across reopen and serialized concurrent appends |
| Atomic/crash behavior | Partial final line is detected and blocks append without silent deletion |
| Deterministic serialization | Equivalent sanitized structures yield stable lines/hashes |
| File safety | Newly created directories/files use restrictive permissions where supported |
| Regression/exclusions | Increment 1 + Increment 2 tests pass; no Hermes hooks, retries, dead letters, retrieval, SQLite, MCP, Obsidian, or injection |

## Commands

Focused Increment 3 tests:

```bash
.venv/bin/python -m pytest tests/unit/test_m1_capture_boundary.py -q
```

Canonical regression suite:

```bash
.venv/bin/python -m pytest tests/ -q
```

No generic ad-hoc check should replace these tests. A temporary criterion-specific check is allowed only if a crash/permission observation cannot be expressed reliably as a test; it must use `tempfile`, the `hermes-verify-` prefix, contain only synthetic values, and be removed afterward.

## Rollback strategy

- Create a Git checkpoint before implementation.
- Keep the store project-local and opt-in; never write real Hermes state.
- If atomicity, deduplication, or redaction boundary fails, revert only the Increment 3 commit and retain prior raw source data.
- Never rewrite/delete the authoritative JSONL stream during rollback.
- Remove only empty test directories and generated caches; preserve any intentional test fixture evidence.
- Verify Increment 1 and Increment 2 focused/canonical suites after rollback or contract correction.

## Implementation files

Create:

- `src/storage/__init__.py`
- `src/storage/capture_boundary.py`
- `src/storage/jsonl_capture.py`
- `tests/unit/test_m1_capture_boundary.py`
- `acceptance-m1-increment-3.md` after verification

Modify only after tests pass:

- `implementation-plan.json`
- `project-state.yaml`

Do not modify Increment 1 contract code, Increment 2 redactor code, Hermes installation, M0 policies, or architecture decisions unless a test-proven compatibility correction is required.

## Explicit exclusions for this increment

Retries, 500 ms deadlines, dead-letter persistence/replay, Hermes hooks, capture-rate harness, SQLite metadata/indexes, retrieval, MCP, Obsidian, prompt/context injection, and future M1 increments remain unimplemented.

**Increment 3 plan: READY FOR APPROVAL**
Do not implement Increment 3 until approved.
