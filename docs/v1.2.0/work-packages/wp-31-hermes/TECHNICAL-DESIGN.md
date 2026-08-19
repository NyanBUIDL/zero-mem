# WP-31 Technical Design

## Components

Python 3.11, existing `ZeroMemRuntime`, `RegistrationAdapter` observer hooks, `HermesReadAdapter` read tools, M6 dispatcher, and WP-30 bounded sidecar. No new dependency or Hermes-core import.

## Lifecycle

```text
explicit BridgeConfig
→ master gate
→ ZeroMemRuntime.open (single writer owner)
→ read-only M6/sidecar startup
→ register approved hooks/tools
→ callbacks/calls
→ bounded shutdown
→ fresh restart without duplicate registration/ownership
```

Disabled master gate performs no DB open, capture, or read query. Adapter-local disabled state remains narrower than the master switch.

## Failure/isolation

Observer callbacks deep-copy payloads, map/capture through runtime-owned client, swallow and record sanitized callback failures. Read adapter returns bounded sanitized capability/downstream statuses. Startup failure is registration diagnostic, not Hermes process failure. Shutdown is idempotent and records failure without raising into Hermes.

## Ownership/security

`ZeroMemRuntime` owns canonical writer lifecycle. Hermes adapters never infer or create competing writers. Identity is explicit from BridgeConfig/environment policy already validated by configuration. Read calls remain behind WP-29 authorization and WP-30 transport; no context injection is automatically applied.

## Bounds/compatibility

Hook list and read tool allowlist are fixed existing registries. Registration is idempotent. No retry loop, SQL, JSONL, ranking, LLM, or network code in adapters. Preserve existing plugin-context APIs and v1.1 behavior.

## Exit evidence

Tests must prove master-disabled no-op, writer ownership, registration, payload immutability, capture/read failure isolation, shutdown/restart, and controlled context behavior.
