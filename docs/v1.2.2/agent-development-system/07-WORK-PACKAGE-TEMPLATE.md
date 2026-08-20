# 07 — Work-package record template

Create one directory per package at `docs/v1.2.2/work-packages/V122-XX-<slug>/`. Do not edit status from `PLANNED` directly to `VERIFIED`.

```markdown
# V122-XX — <name>

**Status:** PLANNED
**Owner:**
**Baseline SHA:**
**Audit IDs closed:**
**Prerequisites:**
**Allowed source paths:**
**Forbidden source paths:**

## Authority read

- [ ] AGENTS.md
- [ ] Master spec section(s):
- [ ] Spec Amendment / ADR:
- [ ] Existing WP technical design / acceptance:
- [ ] Code and test map:

## Problem and non-goals

State the observable production failure, not only the helper that is absent.

## Contract

Input, output, typed statuses, identity/authorization point, freshness behavior,
resource ownership, platform behavior and backward compatibility.

## Design and implementation boundary

List exact files/symbols to add/change. Explain why each owner is the correct
single authority and how JSONL canonical truth remains protected.

## Acceptance criteria

- [ ] Functional success path:
- [ ] Negative/security path:
- [ ] Failure/timeout/restart path:
- [ ] Concurrency/path-safety path:
- [ ] Platform matrix row(s):
- [ ] Direct/sidecar/Hermes parity, if public:

## Test commands and results

| Command | OS/Python | SHA | Result | Raw log checksum |
|---|---|---|---|---|

## Evidence and review

- Changed files:
- Evidence manifest:
- Independent reviewer:
- Findings and disposition:
- Rollback:

## Status transition

Document exactly why every criterion is satisfied. If blocked, record the failed
gate, reproduction, risk and maintainer decision; do not use a silent workaround.
```

## Review checklist

Before accepting a package, reviewers must answer yes to each question:

1. Does the code follow the authority order and preserve all invariants?
2. Is there exactly one production owner for the changed behavior?
3. Do direct API, sidecar and Hermes share semantics rather than duplicate logic?
4. Do denied/stale/unavailable paths expose no unauthorized data or false success?
5. Is every asynchronous/process/platform primitive bounded and cleaned up?
6. Does current-SHA evidence prove the behavior on each declared platform?
7. Can the change be rolled back without corrupting canonical JSONL?
