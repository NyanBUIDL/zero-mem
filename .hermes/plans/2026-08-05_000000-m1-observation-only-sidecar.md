# M1 Observation-Only Capture Sidecar Implementation Plan

> **For Hermes:** Execute only after explicit approval of this M1 plan and resolution of the blockers/decisions below. Use strict TDD and re-read master-spec §§10, 14.2, 17.1–17.2, and 18 before each increment.

**Goal:** Capture relevant Hermes events through verified integration seams, normalize and redact them before persistence, attach deterministic provenance, and persist observation-only traces without retrieval, prompt injection, LLM summarization, or later-milestone behavior.

**Architecture:** Add a project-local sidecar adapter behind a narrow event boundary. Prefer Hermes' existing lifecycle/plugin hook seam for events that Hermes actually emits; do not assume hooks for file operations, skill usage, or task transitions until verified. The sidecar writes only to the approved M1 canonical capture boundary, with raw JSONL append semantics and metadata persistence isolated behind an interface so M2 can complete the durable SQLite/artifact implementation without redesigning the M1 event contract.

**Tech Stack:** Python 3.11+, stdlib JSON/UUID/time/pathlib/hashlib, existing Hermes hook/plugin integration where available, project-local pytest. No new network service, embedding, vector index, retrieval engine, Obsidian sync, or LLM dependency.

---

## A. Exact M1 objective

Implement the smallest observation-only capture slice required by the master specification:

```text
Hermes event
  -> event adapter
  -> secret/PII detector
  -> redact or reject
  -> schema validation
  -> content hash + duplicate check
  -> append raw trace
  -> deterministic metadata extraction
  -> retry/dead-letter handling
```

M1 must record session metadata, messages, tool call/result observations, file read/write events when a verified source exists, skill usage when a verified source exists, task transitions when a verified source exists, timestamps, provenance, profile/project context, sensitivity, and verification metadata. It must not retrieve memory or inject anything into Hermes prompts.

## B. Requirements covered

From master specification §§10, 14.2, 17.1–17.2, and 18:

- Observation-only capture; no automatic prompt injection.
- Event adapter for session/message/tool/file/skill/task/verification events.
- Redaction or rejection at the capture boundary before persistence.
- Schema validation.
- Content hash and duplicate detection without deleting source data.
- Append raw trace in JSONL and pass canonical metadata through the approved storage boundary.
- Deterministic metadata extraction; no LLM memory operation.
- Retry or dead-letter record for capture failures.
- Provenance fields: trace/event ID, source, timestamp, session, profile, project, status, verification, sensitivity, retention, content reference/hash, and relevant parent/relation IDs.
- Acceptance: at least 99% capture in the test harness; correct order/timestamps; secret corpus absent from raw/index; redaction audit without original value; no prompt injection.

M1 uses the M0 contracts in `config/schemas/m0-contracts.yaml` and `config/policies/m0-security-retention.yaml`; it does not change those architecture decisions.

## C. Explicit non-goals

- No retrieval API, FTS search, vector search, graph traversal, evidence routing, calibration, or context injection.
- No LLM calls for capture, classification, summarization, deduplication, or indexing.
- No Obsidian projection or synchronization.
- No full corpus/PDF ingestion.
- No profile retrieval policy or cross-profile write workflow beyond preserving supplied metadata and enforcing the M0 secret boundary.
- No deep Hermes-core redesign.
- No silent conversion of assistant claims into verified states.
- No replacement of Hermes' existing session database; M1 must use an adapter boundary.

## D. Available Hermes integration points inspected

The installed local Hermes is `/home/brian-nguyen/.hermes/hermes-agent`, version `0.19.1`, git commit `82c6acae`, Python 3.11.15. The project’s own working tree is separate and currently contains no Hermes source dependency.

Verified seams:

1. `hermes_cli.lifecycle.invoke_hook()` calls built-in observability and then `hermes_cli.plugins.invoke_hook()`.
2. `VALID_HOOKS` includes `pre_tool_call`, `post_tool_call`, `pre_llm_call`, `post_llm_call`, `pre_api_request`, `post_api_request`, `api_request_error`, `on_session_start`, `on_session_end`, `on_session_finalize`, `on_session_reset`, `subagent_start`, `subagent_stop`, and Kanban task lifecycle hooks.
3. `model_tools.py` emits `pre_tool_call` and `post_tool_call`; post-tool kwargs include tool name/args/result/status/error/duration/task/session/turn/request IDs and middleware trace.
4. `agent/conversation_loop.py` emits `on_session_start` with session/model/platform; session state is persisted by Hermes' SQLite `SessionDB` and `AIAgent.session_id` is exposed through `HERMES_SESSION_ID`.
5. `hermes_cli.lifecycle` also exposes session end/finalize/reset calls.
6. `agent.shell_hooks` provides an external subprocess hook wire protocol, but it is user-configured, allowlist/consent-gated, observer-oriented, and not a suitable canonical capture implementation by itself.
7. Hermes' existing monitoring emitter is content-free and explicitly does not persist prompts, messages, tool args/results, or session history; it cannot be reused as the M1 trace store.
8. `tools/file_tools.py` uses `agent.redact.redact_sensitive_text`, but repository search did not verify a generic file-read/file-write lifecycle hook suitable for complete capture.
9. Skill usage is tracked by `tools.skill_usage.bump_use()` in skill loading paths, but no generic trace hook was verified.
10. Task events exist in task/Kanban-specific paths, but a generic task-transition event contract for all Hermes tasks was not verified.

### Integration consequence

M1 can directly consume existing lifecycle/tool/session hooks. File operations, skill usage, and generic task events require either a verified additional Hermes seam or an explicitly approved sidecar-neutral adapter API at the call sites. Do not claim complete capture coverage for those categories until the source emits them or the project receives explicit integration authorization.

## E. Proposed event envelope

The event adapter accepts a mapping and produces a trace envelope without changing raw content semantics:

```json
{
  "event_id": "uuid",
  "trace_id": "uuid",
  "event_type": "tool_observation",
  "source": "hermes.lifecycle.post_tool_call",
  "created_at": "RFC3339 UTC",
  "observed_at": "RFC3339 UTC",
  "sequence": 1,
  "session_id": "...",
  "profile_id": "...",
  "project_id": "...",
  "task_id": "...",
  "turn_id": "...",
  "parent_event_ids": [],
  "status": "observed",
  "verification": "direct_tool_output",
  "confidence": "high",
  "sensitivity": "private",
  "retention": "persistent",
  "content": {"...": "redacted before this object is persisted"},
  "content_ref": null,
  "content_hash": "sha256:...",
  "redaction": {"applied": true, "fields": ["..."], "audit_only": true},
  "relations": [],
  "schema_version": 1
}
```

Exact field naming must be finalized against the M0 `provenance_required` contract before implementation. `created_at`/`observed_at` must be generated by the adapter, not trusted from unvalidated event content. Missing optional profile/project/task fields remain null/empty according to schema; the adapter must not infer them from unrelated state.

## F. Proposed module boundaries

- `src/capture/event_types.py` — typed event categories and normalized input contract.
- `src/capture/adapter.py` — Hermes hook kwargs to normalized envelope; deterministic IDs/timestamps/relations.
- `src/capture/validation.py` — required-field/type/enum validation; no persistence.
- `src/redaction/redactor.py` — boundary redaction/rejection using approved local deterministic rules; emits sanitized audit metadata only.
- `src/storage/capture_boundary.py` — narrow append interface (`append(trace)`, `append_dead_letter(record)`); no retrieval.
- `src/storage/jsonl_capture.py` — append-only JSONL implementation for M1 observation capture, subject to approval of the M1/M2 sequencing decision.
- `src/capture/dedup.py` — exact content hash duplicate detection; never deletes source records.
- `src/capture/retry.py` — bounded retry and sanitized dead-letter records.
- `src/integration/hermes_hooks.py` — optional registration/bridge for verified Hermes lifecycle hooks. This must not import or mutate Hermes core internals unless explicitly approved.
- `tests/unit/` — envelope, validation, redaction, hash, retry, ordering tests.
- `tests/integration/` — real temporary-directory capture boundary and a real Hermes hook payload fixture; no live user secrets or network.
- `runbooks/m1-capture.md` — operational diagnostics, dead-letter replay, backup/restore handoff, and rollback.

The exact file list is provisional until the blockers/decisions below are resolved.

## G. Files to create or modify

Likely create:

- `src/capture/event_types.py`
- `src/capture/adapter.py`
- `src/capture/validation.py`
- `src/capture/dedup.py`
- `src/capture/retry.py`
- `src/redaction/redactor.py`
- `src/storage/capture_boundary.py`
- `src/storage/jsonl_capture.py` (only if approved as the M1 temporary canonical capture implementation)
- `src/integration/hermes_hooks.py` (only if hook integration is approved)
- `tests/unit/test_m1_envelope.py`
- `tests/unit/test_m1_redaction.py`
- `tests/unit/test_m1_retry.py`
- `tests/integration/test_m1_capture.py`
- `runbooks/m1-capture.md`

Likely modify only after implementation approval:

- `project-state.yaml`
- `implementation-plan.json`
- `pyproject.toml` if a dependency is approved
- `AGENTS.md` only if M1 introduces a durable rule not already covered

Do not modify the installed Hermes repository during M1 unless the user explicitly authorizes an upstream integration change. The initial integration should be a project-local adapter or separately configured plugin boundary.

## H. Dependency changes

Preferred: no new runtime dependency. Use Python 3.11 standard library plus existing local deterministic redaction logic ported only as needed under the project’s own tests.

Test dependency: project-local `.venv` already has pytest. There is no project `pyproject.toml`, `requirements*.txt`, `uv.lock`, or declared development dependency file in the Zero-Mem repository. Do not install system-wide packages.

Potential unresolved dependencies:

- A YAML parser is not needed if M1 consumes already-loaded policy data or uses JSON-compatible contracts; adding PyYAML requires approval.
- A Hermes SDK/package dependency is not available in the project and must not be assumed.
- SQLite is available through Python stdlib, but canonical schema ownership is assigned to M2 in the current roadmap.

## I. Migration and compatibility considerations

- Preserve the M0 envelope names and provenance semantics; do not silently rename required fields.
- M1 must not alter Hermes’ `~/.hermes/state.db`, session transcripts, profiles, hooks, config, or installed files without explicit integration approval.
- The adapter must tolerate missing optional metadata and unknown future event fields while rejecting malformed required fields.
- JSONL records must be append-only; retries must be idempotent by `event_id`/content hash.
- If M1 writes a local JSONL capture file before M2, it must be explicitly labeled as the approved capture boundary and provide a migration path into M2 SQLite metadata. If this is not approved, M1 should stop at a tested storage interface and remain blocked on M2.
- No existing Hermes hook may return a blocking/injection response due to the capture observer; registration must be observer-only and fail-open for agent execution while recording capture failure.

## J. Security and redaction flow

1. Receive event kwargs at the adapter boundary.
2. Copy/normalize into an isolated structure; never mutate Hermes’ live objects.
3. Detect and redact/reject secrets before hashing or writing.
4. Do not hash or log the unredacted payload; hashes are computed over the sanitized canonical representation.
5. Validate that the sanitized record contains no known secret corpus values.
6. Emit a redaction audit record containing event/trace ID, rule labels, field paths, and timestamp—but never the original secret.
7. Apply sensitivity and retention policy from M0; `secret` and `never_store` content is not persisted.
8. Persist only sanitized envelope/content through the capture boundary.
9. Treat adapter/storage exceptions as capture failures, not as Hermes actions.

Security tests must cover bearer tokens, API-key assignments, OAuth secrets, private-key blocks, passwords, credential URL userinfo, nested tool results, and secrets split across supported fields. Exact redaction pattern coverage must be based on the M0 policy, not an invented secret corpus.

## K. Failure and retry behavior

- Validation failure: reject persistence and append a sanitized dead-letter record with error category, event ID if available, and no raw payload.
- Redaction failure or uncertain detector failure: fail closed for secret-classified content; never persist raw content.
- Storage I/O failure: bounded retry with deterministic backoff; after exhaustion append a dead-letter record to a separate local failure path, also sanitized.
- Duplicate event: return an idempotent duplicate outcome; never create a second source record and never delete the first.
- Ordering: assign a monotonic process/storage sequence for accepted records; retain source timestamps separately.
- Hook/adapter exceptions: observer path must not block or alter Hermes execution; emit local diagnostics without leaking content.
- Dead-letter replay is not part of automatic M1 processing; document a manual, audited replay command for a later increment.

The exact retry count, backoff, dead-letter location, durability guarantee, and crash-consistency behavior are unresolved until the M1/M2 storage-boundary decision is approved.

## L. M1 acceptance criteria

The exact M1 criteria from `implementation-plan.json` are:

1. **“>=99% harness capture”** — capture at least 99% of events in the specified test harness; failures have retry or dead-letter records.
2. **“correct order/timestamps”** — accepted events preserve deterministic sequence/order and valid timestamps.
3. **“secret corpus absent from raw/index”** — no secret test corpus value appears in persisted raw capture or any M1 index/output.
4. **“redaction audit without original secret”** — redaction audit identifies the redaction event/rule/field without retaining the original value.
5. **“no prompt injection”** — observation-only capture does not retrieve memory, mutate prompt/context, summarize with an LLM, or inject content into Hermes prompts.

M1 acceptance does not include SQLite rebuildability, retrieval, profile isolation, MCP, controlled injection, graph, Obsidian, or corpus expansion; those belong to later milestones.

## M. Automated tests for each criterion

- **M1-1 capture rate:** deterministic harness generates a fixed number of valid events, injects controlled storage failures, verifies accepted + retried/dead-letter outcomes account for all events, and asserts accepted ratio >= 0.99. This is a criterion-specific integration test, not a generic suite count.
- **M1-2 ordering/timestamps:** submit events with controlled source timestamps and concurrent/serial arrival; assert monotonic capture sequence, preserved source timestamp, adapter-generated RFC3339 timestamp, and parent/event linkage.
- **M1-3 secret absence:** persist a fixture containing every M0 `never_store` class; recursively inspect JSONL/dead-letter/index outputs for exact and normalized secret values; assert none occur.
- **M1-4 redaction audit:** capture a redacted event; assert audit has trace/event ID, rule labels, and field paths, and assert original secret and raw pre-redaction payload are absent.
- **M1-5 no injection:** use a fake Hermes hook consumer and fake prompt/context object; assert capture registration is observer-only, returns no context/block/transform response, makes zero LLM calls, and never writes to prompt messages.

Run focused tests individually first (RED/GREEN), then the canonical repository suite.

## N. Canonical test commands

Current repository command:

```bash
.venv/bin/python -m pytest tests/ -q
```

Planned focused commands after each increment:

```bash
.venv/bin/python -m pytest tests/unit/test_m1_envelope.py -q
.venv/bin/python -m pytest tests/unit/test_m1_redaction.py -q
.venv/bin/python -m pytest tests/unit/test_m1_retry.py -q
.venv/bin/python -m pytest tests/integration/test_m1_capture.py -q
.venv/bin/python -m pytest tests/ -q
```

Do not call the M1 acceptance suite complete from the baseline three tests. Add criterion-specific tests first and record exact outputs in `project-state.yaml` only after they pass.

## O. Runtime verification commands

No live Hermes production run should be used before the adapter boundary and secret fixtures are validated. Once the integration boundary is approved, use a temporary isolated Hermes home/profile and a temporary project capture directory:

```bash
HERMES_HOME="$(mktemp -d)" \
  .venv/bin/python -m <approved_m1_harness> --fixture tests/fixtures/m1-events.json --out "$HERMES_HOME/capture"
```

Then inspect only sanitized outputs:

```bash
.venv/bin/python -m <approved_m1_inspector> --capture "$HERMES_HOME/capture" --assert-no-secrets
```

The exact module/CLI names are intentionally unresolved because no M1 implementation exists yet. Do not invent or run these commands until the modules are created and the storage decision is approved.

For Hermes integration discovery, the verified local commands were:

```bash
hermes --version
hermes hooks --help
hermes status
hermes memory --help
```

These established the installed Hermes version and available hook/memory surfaces; they did not modify Hermes.

## P. Risks and rollback strategy

Risks:

- Incomplete Hermes event coverage if file/skill/task hooks do not exist.
- Secret leakage through nested or provider-specific tool payloads.
- Blocking or prompt mutation if the observer is registered on a transform/gate hook.
- Duplicate/lost records under concurrent writes or crashes.
- M1 JSONL boundary diverging from M2 SQLite ownership.
- Accidental modification of the user’s real `~/.hermes` state.
- Capturing sensitive raw content in test logs or dead-letter diagnostics.

Rollback:

- Keep M1 integration opt-in and disabled by default until acceptance passes.
- Remove only project-local adapter/config registration; never delete canonical raw traces or Hermes state.
- Preserve append-only capture files and dead-letter evidence for diagnosis.
- Revert the M1 commit/checkpoint if observer registration changes runtime behavior.
- Verify Hermes still starts and the project baseline suite passes after disabling the adapter.
- Do not use destructive cleanup on user Hermes data; use a temporary `HERMES_HOME` for runtime tests.

## Q. Smallest independently testable increments

### Increment 1 — Freeze the M1 event contract

**Test first:** contract tests for envelope fields, event-type mapping, timestamps, IDs, optional metadata, and unknown-field tolerance.

**Implementation:** `src/capture/event_types.py`, `src/capture/adapter.py`, `src/capture/validation.py`.

**Exit evidence:** focused contract tests pass; no Hermes integration or persistence yet.

### Increment 2 — Redaction boundary

**Test first:** secret fixture tests for every M0 never-store category, nested values, audit-without-secret, and rejection behavior.

**Implementation:** `src/redaction/redactor.py` plus narrowly scoped M0-policy fixture loading.

**Exit evidence:** redaction tests prove secrets are removed before hashing/persistence.

### Increment 3 — Append capture boundary and deduplication

**Decision required first:** approve temporary M1 JSONL capture or defer durable persistence to M2.

**Test first:** append ordering, atomic line writes, duplicate idempotency, sanitized dead-letter, and crash/failure behavior in a temporary directory.

**Implementation:** `src/storage/capture_boundary.py`, `src/storage/jsonl_capture.py`, `src/capture/dedup.py`, `src/capture/retry.py`.

**Exit evidence:** storage-boundary tests pass without retrieval or SQLite redesign.

### Increment 4 — Verified Hermes hook adapter

**Test first:** fake hook payloads for session start/end, pre/post tool, and available task/subagent events; assert observer-only behavior and full provenance.

**Implementation:** `src/integration/hermes_hooks.py` using the approved plugin/lifecycle seam, without modifying installed Hermes.

**Exit evidence:** integration tests prove events reach the adapter and no hook response changes Hermes behavior.

### Increment 5 — Coverage harness and M1 acceptance suite

**Test first:** fixed harness with >=99% capture denominator, ordering/timestamp checks, secret absence scan, redaction audit scan, and no-injection assertions.

**Implementation:** `tests/integration/test_m1_capture.py`, fixtures, and sanitized reporting helper.

**Exit evidence:** all five M1 criteria pass with exact command outputs and no temporary artifacts.

### Increment 6 — Operational evidence and checkpoint

Update `runbooks/m1-capture.md`, `project-state.yaml`, `implementation-plan.json`, and M1 acceptance evidence only after the complete acceptance suite passes. Create a Git checkpoint before any destructive or integration-enabling change and a final M1 commit only after review.

## Binding decisions recorded

The following decisions are approved and binding for M1:

- **ADR-M1-001 storage:** versioned append-only JSONL is the authoritative raw trace stream, not disposable temporary storage. M2 adds SQLite metadata/lifecycle/relationships/indexes above JSONL. The project-owned interface is `append(event)`, `contains(event_id)`, and `write_dead_letter(event, error)`; no competing canonical store.
- **ADR-M1-002 coverage:** integrate only directly verified Hermes lifecycle/plugin hooks. File operations, skill usage, and generic task transitions are deferred coverage. The >=99% threshold applies only to declared supported classes.
- **ADR-M1-003 integration:** use an independently enabled/disabled project-local observer bridge. Do not use shell hooks as primary architecture, modify installed Hermes, or write to real `~/.hermes`. Capture failures are fail-open for Hermes control flow.
- **ADR-M1-004 redaction:** use a project-owned deterministic layer derived from M0 policy/contracts. Copy, normalize, redact/reject, hash sanitized content, validate, then persist. Secrets are forbidden in raw/dead-letter JSONL, audits, logs, exceptions, temporary files, and snapshots.
- **ADR-M1-005 retry/dead-letter:** three total attempts, 50 ms then 200 ms backoff, 500 ms per-event deadline, no automatic replay, and `data/dead-letter/YYYY-MM-DD.jsonl` with sanitized event/trace IDs, failure class, timestamp, attempt count, and diagnostic. If both stores fail, emit sanitized local diagnostic without raising.
- **ADR-M1-006 identity:** `project_id` resolves from `HERMES_PROJECT_ID`, then project-local bridge config, then null/`unassigned`; `profile_id` follows explicit value or null. No cwd/repository/session/prompt inference.
- **ADR-M1-007 acceptance scope:** secret scans cover raw, dead-letter, redaction audit, logs, exceptions, temporary artifacts, and snapshots; SQLite/index scanning is deferred to M2. “No prompt injection” means observer non-interference, not a classifier.

## Updated M1 acceptance criteria

1. **>=99% supported-harness capture:** at least 99% of events from the declared verified hook classes are captured; failures have retry/dead-letter evidence. Unsupported file-operation, skill-usage, and generic task classes are explicitly deferred.
2. **Correct order/timestamps:** accepted JSONL records have monotonic capture sequence, preserved source timestamp where supplied, and adapter-generated valid timestamp.
3. **Secret absence before M2 indexes:** secret fixtures are absent from raw JSONL, dead-letter JSONL, redaction audits, logs, exceptions, temporary verification artifacts, and test snapshots. SQLite/index scanning is a M2 criterion.
4. **Redaction audit without original secret:** audits retain event/trace identity, rule/field metadata, and timestamp but never original secret values or pre-redaction payloads.
5. **Observer non-interference:** the independently enabled bridge does not modify prompts, messages, tool arguments, model context, or Hermes actions; capture failures cannot change Hermes results/control flow and no LLM is called.

## Current state

M0 is fully verified at commit `9fc4e7a95e89d504e6401e3d382565c8aaf89a54`. M1 is approved for implementation planning with the binding decisions above. No M1 production code has been implemented.

**M1 PLAN APPROVED AND RECORDED**
