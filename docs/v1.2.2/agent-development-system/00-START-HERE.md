# 00 — Start here: operating contract for implementation agents

## Purpose

This directory is the execution system for the `release/v1.2.2` line. Its job is to prevent an agent from treating existing helpers, historical `VERIFIED` files, or a passing narrow test as proof that the production path works.

An agent may plan, inspect, test, and update documentation under this system. It may not change product code until the maintainer approves the relevant work package and any architecture decision it requires.

## Required reading order

Before work on any package, read all of the following in order:

1. [`AGENTS.md`](../../../AGENTS.md) — repository-level authority and prohibitions.
2. [`docs/architecture/ARCHITECTURE.md`](../../architecture/ARCHITECTURE.md) — system boundary and data flow.
3. [`docs/v1.2.0/SPEC-AMENDMENT-001-CANONICAL-MEMORY-EVENT-TRUTH.md`](../../v1.2.0/SPEC-AMENDMENT-001-CANONICAL-MEMORY-EVENT-TRUTH.md) and [ADR-009](../../v1.2.0/decisions/ADR-009-CANONICAL_MEMORY_EVENT_TRUTH_AND_DERIVED_STATE_BOUNDARY.md) — canonical/derived semantics.
4. [01-AUTHORITY-AND-INVARIANTS.md](01-AUTHORITY-AND-INVARIANTS.md) — non-negotiable constraints.
5. [02-CODE-AND-TEST-MAP.md](02-CODE-AND-TEST-MAP.md) — exact implementation and test ownership.
6. The selected package in [04-MASTERPLAN.md](04-MASTERPLAN.md), including its prerequisite packages.
7. The corresponding v1.2 work-package technical design, acceptance and evidence files under [`docs/v1.2.0/work-packages`](../../v1.2.0/work-packages).

Before a Git or GitHub mutation, additionally read [`docs/governance/GITHUB-POLICY.md`](../../governance/GITHUB-POLICY.md). A request to edit source does not authorize commit, push, tagging, or publishing.

## One-package rule

At any time, an agent may have exactly one package in `IN_PROGRESS`. It must not begin a dependent package until the predecessor has a committed (or explicitly reviewer-approved) evidence record.

Valid package states are:

```text
PLANNED → APPROVED → IN_PROGRESS → IMPLEMENTED → VERIFIED → RELEASE_QUALIFIED
                              └──────────────→ BLOCKED
```

- `IMPLEMENTED` means code and focused tests exist; it does **not** mean accepted.
- `VERIFIED` requires all package acceptance tests, negative tests, static boundary checks, and recorded evidence.
- `RELEASE_QUALIFIED` is reserved for the final version after the platform/artifact gates pass.
- `BLOCKED` requires a stable reason code, the failed gate, and a maintainer decision; it is never silently bypassed.

## Working sequence

```text
Select package
  → record baseline SHA and scope
  → read required authority/docs/code
  → write/update package plan and tests first
  → implement smallest vertical slice
  → run focused + dependency + negative checks
  → record evidence
  → independent review
  → update package status
```

Use [03-AGENT-DELIVERY-PROTOCOL.md](03-AGENT-DELIVERY-PROTOCOL.md) for the detailed procedure and [07-WORK-PACKAGE-TEMPLATE.md](07-WORK-PACKAGE-TEMPLATE.md) to create the package record.
