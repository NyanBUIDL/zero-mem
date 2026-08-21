# 05 — Minimal work-package template

```markdown
# R-XX — <name>

**Status:** OPEN | IN_PROGRESS | PARTIAL | VERIFIED_<platform> | DEFERRED_WITH_AUTHORITY
**Baseline SHA:**
**Finding closed:**
**Allowed paths:**
**Public boundary tested:**
**Platform scope:**

## Observable problem

Describe what a caller cannot safely do today.

## Contract decision

Input/output/statuses, authorization point, freshness behavior, owner lifecycle,
compatibility and rollback. Link an approved decision if a new public name/schema is required.

## Three proofs

| Proof | Test/evidence | Exact result |
|---|---|---|
| Wiring | | |
| Public behavior | | |
| Provenance | | |

## Negative cases

Denied scope, stale/missing derived state, timeout/overload, restart and platform-specific unsafe path behavior.

## Evidence

Commands, OS/Python, raw-log SHA, source SHA, reviewer and remaining risks.
```

## Why this is not over-engineering

This template is required only when a change crosses a public API, storage lifecycle, authorization, transport, host integration, platform or release boundary. A normal bug fix inside one private module needs ordinary tests and code review, not a new package record.

The system has one purpose: prevent a release from being marked complete when it only proves helpers or mocks. It does not prescribe algorithms, impose new services, or require paperwork for routine internal refactors.
