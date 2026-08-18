# Zero-Mem v1.1 Local Interface Contract

Contract version: `1.1`.

Capabilities are `observe`, `sync`, `health`, and `capabilities`. Requests require a non-empty caller identity and are bounded by configured payload and deadline limits. The embedded-local dispatcher creates no public network listener. Disabled or unavailable persistence returns typed unavailable results or deterministic sidecar errors; it never reports ready.

The canonical API remains transport-neutral. Hermes and generic clients use the same dispatcher semantics. Endpoint paths, tokens, memory payloads, source paths, and hidden scope identifiers are not emitted in status or errors.
