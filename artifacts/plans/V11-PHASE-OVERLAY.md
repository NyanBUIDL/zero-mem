# V1.1 Durable WP-to-Phase Overlay

## Status

**Governance/planning only. Runtime implementation is not authorized by this artifact.**

## Authority model

```text
Canonical specification
  -> WP-00..WP-22 ownership and dependency DAG
    -> Phase A..G execution sequencing overlay
```

WPs remain the ownership and requirements layer. Phases only sequence execution. The overlay does not rewrite the planning ref, historical planning documents, WP ownership, WP dependencies, or canonical requirements.

## Source refs

- Canonical DOCX: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
- Canonical SHA-256: `85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a`
- Planning ref: `2f1763f1335326b83bf90f263cada5c3715f21eb`
- Roadmap: `docs/v1.1.0/MASTER_PLAN.md` and `docs/v1.1.0/work-packages/WP-00..WP-22`
- Machine DAG: `artifacts/tasks/task-manifest.json`

## Derived mapping

| Phase | WPs | Purpose | Current state |
|---|---|---|---|
| A | WP-00, WP-01, WP-02 | baseline, architecture, core/adapter boundaries | IN_PROGRESS |
| B | WP-13, WP-04, WP-03, WP-08 | configuration, canonical storage, scale, public API | NOT_STARTED |
| C | WP-05, WP-20, WP-06, WP-09, WP-11, WP-12 | retrieval, scope, context, compatibility, async, process ownership | NOT_STARTED |
| D | WP-14, WP-15 | reliability/recovery/conflict and diagnostics | NOT_STARTED |
| E | WP-21, WP-07, WP-22 | local sidecar/MCP, Hermes consumer, Obsidian workspace | NOT_STARTED |
| F | WP-17, WP-10, WP-18 | migration, packaging, documentation/DX | NOT_STARTED |
| G | WP-16, WP-19 | final validation and release readiness | NOT_STARTED |

The sequence is topologically valid because every dependency of a WP is in the same or an earlier phase. Phase F/G are defined but not started by this operation.

## Phase closure rule

A phase is not verified by its name or by partial WP completion. Every mapped WP must be VERIFIED, its implementation and production integration obligations must be proven where applicable, required tests and full regression must pass, governance must remain consistent, and a local durable Git checkpoint must exist.

## Current reconstruction point

- `WP-00 = VERIFIED` from durable closure evidence.
- `WP-01 = VERIFIED` from durable closure evidence.
- `WP-02 = NOT_STARTED`.
- Therefore `Phase A = IN_PROGRESS`, not VERIFIED.
- `CURRENT_DURABLE_PHASE = A`.
- `NEXT_INCOMPLETE_WP = WP-02`.
- `NEXT_LEGAL_EXECUTION = Phase A / WP-02 scope materialization`; this overlay does not authorize runtime implementation.

## Deferred boundaries

No Product Memory change, runtime implementation, Phase F/G task packet, future-phase implementation, new dependency, remote publication, or historical planning rewrite is part of this governance operation.
