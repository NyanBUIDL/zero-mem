# WP-30 Implementation Plan

**STATUS: VERIFIED**

## Baseline

- Workspace: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- WP-28 and WP-29 are VERIFIED.
- Existing sidecar boundary: `src/integration/m6/mcp_wrapper.py`, `dispatcher.py`, `contracts.py`, `errors.py`, `tools.py`, and `src/integration/hermes_read_adapter.py`.

## Gap analysis

The repository already has a thin MCP wrapper and Hermes read adapter. WP-30 must verify and minimally harden bounded transport behavior: byte limits, queue/concurrency limits, deadline propagation, identity preservation, sanitized serialization, overload status, and restart/shutdown. No separate authorization or retrieval implementation is permitted.

## Increments

1. Inspect current M6 contracts/dispatcher and adapter lifecycle; record direct-to-sidecar mapping.
2. Add red/green tests for request/response byte bounds, invalid envelope, identity propagation, queue full, concurrency, deadline, downstream failure, and restart.
3. Implement the smallest bounded transport coordinator using standard-library primitives and existing dispatcher.
4. Run parity/security/failure tests, full regression, static checks, Graphify final, and independent review.

## Expected files

- `src/integration/m6/mcp_wrapper.py`, `contracts.py`, `dispatcher.py`, `errors.py`, or `src/integration/hermes_read_adapter.py` only if required.
- `tests/unit/test_wp30_sidecar.py` and integration parity tests.
- WP-30 evidence/state/docs.

## Compatibility/security

No new dependency, schema, canonical write path, auth path, or network endpoint. Existing M6 tool envelopes and Hermes registration remain compatible. Rollback is WP-30-only source/test/doc reversal.

## Open questions

Exact byte and concurrency defaults must follow existing M6 configuration if present; otherwise use explicit validated configuration rather than arbitrary hidden constants. No blocking architecture question identified.

## Plan validation

Validated against WP-28/WP-29 contracts, current M6 wrapper/dispatcher/adapter implementation, roadmap WP-30 sidecar gate, and existing M6/Hermes tests.
