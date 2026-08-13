# M1 Acceptance Criteria — Approved Scope

**Milestone:** M1 — Observation-only capture sidecar
**Status:** Approved for implementation; not implemented or verified
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
**Plan:** `.hermes/plans/2026-08-05_000000-m1-observation-only-sidecar.md`
**Decision records:** ADR-M1-001 through ADR-M1-007 in `ARCHITECTURE.md`

## Supported event classes

The >=99% harness threshold applies only to directly verified Hermes hook classes:

- session lifecycle
- `pre_tool_call`
- `post_tool_call`
- LLM/API lifecycle where explicitly used for observation
- subagent lifecycle
- verified task/Kanban lifecycle

File operations, skill usage, and generic task transitions are deferred coverage. M1 must not claim them captured or modify Hermes core to add hooks for them.

## Criteria

| ID | Exact requirement | Scope | Planned objective evidence |
|---|---|---|---|
| M1-1 | Capture at least 99% of events in the declared supported-hook harness; failures have retry/dead-letter evidence | Supported classes only; three total attempts; 50 ms and 200 ms backoff; 500 ms per-event deadline; no automatic replay | Criterion-specific harness report and persisted event/dead-letter counts from `tests/integration/test_m1_capture.py` |
| M1-2 | Accepted JSONL records preserve correct order and timestamps | Monotonic capture sequence; preserve supplied source timestamp; generate valid adapter timestamp | Focused ordering/timestamp test and sanitized JSONL inspection |
| M1-3 | Secret fixtures are absent before M2 index layer exists | Scan raw JSONL, dead-letter JSONL, redaction audits, logs, exceptions, temporary verification artifacts, and test snapshots; SQLite/index scan deferred to M2 | Security scan test over all M1 outputs; no secret values in output or diagnostics |
| M1-4 | Redaction audit exists without original secret | Audit includes event/trace ID, rule/field metadata, and timestamp; excludes original secret and pre-redaction payload | Focused redaction-audit test and audit JSONL inspection |
| M1-5 | Observer non-interference / “no prompt injection” | Bridge does not modify prompts, messages, tool args, context, or actions; capture failures do not change Hermes control flow; no LLM calls | Fake-hook integration test with prompt/context snapshots, tool-result identity, failure injection, and LLM-call counter |

## Explicit exclusions

M1 acceptance does not include SQLite metadata/index scanning, retrieval, profile isolation, MCP, controlled injection, graph traversal, Obsidian projection, or corpus ingestion. SQLite/index secret scanning is an M2 acceptance requirement.

## Required output boundaries

- Raw source of record: versioned append-only JSONL.
- Stable storage interface: `append(event)`, `contains(event_id)`, `write_dead_letter(event, error)`.
- Dead-letter path: `data/dead-letter/YYYY-MM-DD.jsonl`.
- Project identity: `HERMES_PROJECT_ID`, then explicit project-local bridge configuration, then null/`unassigned`.
- Profile identity: explicit value or null; never inferred from cwd, repository, session text, prompt, or unrelated Hermes state.
- Integration: independently enabled/disabled project-local observer bridge; no installed Hermes source changes and no real `~/.hermes` writes in tests.

## Verification commands after implementation

```bash
.venv/bin/python -m pytest tests/unit/test_m1_envelope.py -q
.venv/bin/python -m pytest tests/unit/test_m1_redaction.py -q
.venv/bin/python -m pytest tests/unit/test_m1_retry.py -q
.venv/bin/python -m pytest tests/integration/test_m1_capture.py -q
.venv/bin/python -m pytest tests/ -q
```

M1 is not complete until all five criteria pass with criterion-specific evidence and the final repository state is recorded.

**M1 PLAN APPROVED AND RECORDED**
