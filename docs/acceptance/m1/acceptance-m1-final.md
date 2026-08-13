# Final M1 Acceptance Evidence

**Milestone:** M1 — Observation-only capture sidecar
**Status:** VERIFIED
**M1 plan approval commit:** `0194113675afe8e433bd1bcede1607e672fc0bcd`
**Increment 4.6 starting commit:** `7fee198f4319398c9c837e915063e07690580456`
**Final M1 commit:** PENDING_EVIDENCE_COMMIT

## Increments

- Increment 1: event contract frozen — VERIFIED
- Increment 2: deterministic redaction — VERIFIED
- Increment 3: capture boundary + deduplication — VERIFIED
- Increment 4.1: project-local opt-in bridge config — VERIFIED
- Increment 4.2: pure payload mapping — VERIFIED
- Increment 4.3: redaction + CaptureStore adapter — VERIFIED
- Increment 4.4: verified hook registration — VERIFIED
- Increment 4.5: non-interference integration — VERIFIED
- Increment 4.6: capture-rate benchmark + final M1 acceptance — VERIFIED

## Required M1 properties (all verified by tests)

1. observation-only sidecar — no memory retrieval, no prompt injection, no LLM
   summaries, no graph/Obsidian/large-corpus
2. versioned event contract (schema_version=1, validate_envelope)
3. deterministic redaction (sha256 content hash, redaction_audit)
4. never_store enforcement (sensitivity=secret / retention=never_store rejected)
5. append-only JSONL (JsonlCaptureStore)
6. deduplication (event_id + content_hash, accepted-duplicate semantics)
7. sequence recovery (monotonic committed sequence)
8. project-local opt-in bridge (disabled by default, explicit project/profile)
9. verified hook registration (only 8 supported hooks registered)
10. observer non-interference (enabled vs disabled equivalent outputs)
11. failure isolation (bridge swallows observation-side exceptions)
12. capture rate >= 99% (measured 100.0%)
13. no raw-secret leakage (secret scan across JSONL/results/metrics/diagnostics)
14. no LLM use for routine memory operations (deterministic/local only)
15. no real Hermes-home writes (temporary homes only)
16. no installed Hermes source modification
17. conditional and deferred hooks remain explicitly unsupported
18. retry, dead-letter, SQLite, retrieval, Obsidian, MCP, and context injection
    remain unimplemented (out of M1 scope)

## Test results

- Canonical suite: 166 passed
- Increment 4.6 focused: 20 passed
- Last canonical before M1 final: 146 passed (Increments 1–4.5)

## Environment

- Active provider/model: nous / tencent/hy3:free
- Hermes Agent version: 0.19.1
- Installed Hermes upstream commit: 25c7827e (baseline exception: only
  package-lock.json modified, untouched by this project)

## Next milestone

M2 — SQLite metadata, state, relations, and indexes (NOT started).
