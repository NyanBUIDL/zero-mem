# ADR-006: Local Sidecar Interface and Transport Binding

**Status:** PROPOSED

## Canonical Source

- `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §§4.2, 13.1–13.3, 16.1, 18 stage 6.
- Exact-master `docs/architecture/ARCHITECTURE.md` §8.
- Exact-master `src/integration/m6/mcp_wrapper.py` and historical M6.1/M6.6 acceptance evidence.

## Context

The canonical specification requires a sidecar retrieval interface through MCP or another local transport and defines four minimum MVP capabilities. Exact master already has a transport-independent dispatcher and a thin MCP wrapper, but no supported local service lifecycle or public canonical tool names. Existing WP-08 text rejected mandatory MCP/local HTTP, which contradicts the product requirement.

## Decision

V1.1.0 will expose one transport-neutral capability contract and at least one supported local-only service binding. The baseline binding is the existing MCP-compatible local process/stdio path because it is already present and historically accepted; local HTTP and Unix-domain sockets remain optional bindings and may not define different semantics.

The mandatory external names are `zero_mem.search`, `zero_mem.get_trace`, `zero_mem.get_task_state`, and `zero_mem.get_decisions`. Existing M6 read operations remain implementation primitives or compatibility aliases behind the same dispatcher. Transport code owns serialization, framing, deadlines, connection lifecycle, and local exposure only; it cannot own authorization, ranking, storage, or Hermes policy.

## Security Boundary

Local does not mean trusted. Every request carries explicit caller identity and requested scope, is authenticated where the selected transport permits, and is authorized by the core before evidence can influence ranking or output. The service binds only to an explicitly configured local endpoint, refuses remote/wildcard exposure by default, enforces request/response size limits and deadlines, and returns sanitized typed errors.

## Consequences

- WP-08 owns capability types and semantics.
- WP-21 owns MCP/local transport, lifecycle, deadlines, and conformance.
- WP-07 consumes the interface as a Hermes client and must not duplicate it.
- WP-13 owns configuration; WP-15 owns content-safe health; WP-16 owns conformance/security/performance tests.

## Rejected Alternatives

- Embedded Python API as the only supported integration path.
- A Hermes-specific protocol as the core contract.
- Independent contracts per transport.
- Trusting callers solely because the endpoint is local.
