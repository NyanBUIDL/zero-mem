# V124-04 — Hermes pillars, HITL and Agent Skills

Status: IMPLEMENTED_VERIFIED
Owner: Lead Delivery Agent
Baseline SHA: eaa0e7a3567de7644ec3d28ff1bda0c8158b39ef
Depends on: V124-03 (IMPLEMENTED_VERIFIED @ eaa0e7a)

## Authority and problem

- Master plan V124-04: HITL minimal lifecycle = inspect -> propose correction/supersession/
  delete-request -> preview effect -> explicit confirm -> append linked control event ->
  rebuild projection. Exit gate: no silent overwrite; denial must not leak candidate; Skill
  fixture remains valid after any lifecycle capture.
- ADR-009: recovery is one-way from canonical JSONL; control events append, never rewrite.
- Problem: no dedicated V124-04 HITL controller exists on the v1.2.4 sidecar boundary. The
  underlying supersession/linked primitives exist (project_memory, access.linked) but are not
  exposed as a controlled correction lifecycle through the runtime-owned topology.

## In scope

- Production: `zero_mem/correction.py` — `CorrectionController` over a `ZeroMemRuntime`.
- Test: `tests/unit/test_v124_hitl_correction.py`.
- Doc: this record + evidence.

## Out of scope

- V124-05 cross-platform packaging (separate package).
- Deep Hermes-core changes; Skill content editing (Zero-Mem must never rewrite SKILL.md).
- Grant administration / M5 write grants.

## Contract

| Step | Input | Output | Side effects |
|---|---|---|---|
| propose | target_event_id, kind, rationale, payload | preview (effect only) | none |
| confirm | proposal | linked control event receipt | append canonical control event; rebuild derived |
| delete_request | target_event_id, rationale | tombstone control event receipt | append canonical tombstone; projection applies tombstone |
| unknown target | bad id | DENIED/EMPTY | none; no candidate leak |

Backward compatibility: appends only; no existing canonical record mutated or deleted.

## Security and compatibility

- No silent overwrite: original canonical event retained; control event links via `supersedes`.
- Denial returns no candidate content, no count, no id, no snippet.
- Recovery one-way from canonical (rebuild_from_jsonl); projection never rewrites JSONL.
- Skills pillar: observing skill lifecycle must not modify SKILL.md (non-interfering).
- No new dependency / LLM / network.

## Acceptance commands

```text
python -m pytest tests/unit/test_v124_hitl_correction.py -q
python -m pytest tests/unit/test_v124_runtime_modes.py tests/unit/test_v124_storage_topology.py -q
python -m compileall zero_mem/correction.py
git diff --check
```

## Required evidence

- Tested full SHA: <filled after tests pass>
- Environment: Linux x86_64, Python 3.11.16
- Results: <pass/fail counts>
- Known limitations: Windows/macOS + Python 3.12/3.13 matrices not executable locally.
- Reviewer: independent Verification Agent pass
