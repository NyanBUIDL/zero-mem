# WP-31 Instructions

## Objective

Integrate Zero-Mem with Hermes through explicit runtime bootstrap, approved capture/read hooks, bounded lifecycle, controlled context/capability exposure, and failure isolation without modifying Hermes core.

## Dependencies

WP-25 Runtime Ownership, WP-29 Authorization, and WP-30 Sidecar are VERIFIED.

## Scope

Validate and minimally harden `RegistrationAdapter`, `HermesReadAdapter`, runtime bootstrap, hook registration, read capability registration, startup/shutdown/restart, capture failure isolation, and controlled context boundary.

## Out of scope

Hermes core edits, new transport/auth/retrieval/ranking implementation, context assembly (WP-32), profile/Obsidian projection (WP-34), or publication.

## Invariants

Use the real `ZeroMemRuntime`; one canonical writer owner; observe-only hooks do not mutate payloads; callback failures do not kill Hermes but remain observable; read tools route through WP-29 and WP-30; disabled master gate is a safe no-op; startup/shutdown/restart are bounded and deterministic.

## Escalation

Escalate if Hermes core modification, a new trust boundary, competing writer, uncontrolled context injection, or inability to isolate failure is required.

## Completion

Bootstrap/hooks/read capabilities/lifecycle/restart/failure-isolation/context-control evidence passes; independent review passes; state becomes `VERIFIED`.
