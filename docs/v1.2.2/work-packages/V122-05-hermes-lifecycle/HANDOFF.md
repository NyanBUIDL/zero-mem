# V122-05 Hermes Lifecycle Handoff

**Status:** `VERIFIED_LINUX_SCOPED`
**Current tree fingerprint:** `ba9cd2d8719bcb00e8562b4a7baf07dfb69cceb0616c134c519d7ec99f5a3bdc`

## Observed and changed

The existing project-local `HermesBoundary` remains the integration boundary. It composes capture registration, bounded Hermes read adapter/sidecar, and controlled injection without modifying Hermes core. Runtime composition now includes projection and strict read-service opening behind Zero-Mem-owned adapters.

Relevant owners: `zero_mem/hermes_integration.py`, `src/integration/hermes_registration.py`, `src/integration/hermes_read_adapter.py`, `src/integration/hermes_plugin.py`, `src/integration/m7/injection_adapter.py`, and `src/integration/zero_mem_runtime.py`.

Lifecycle contract: explicit project/profile identity, storage root supplied by caller, master enable gate, idempotent registration, disabled side-effect-free state, restart without duplicate registration, deterministic shutdown, capture/projection/read boundary, and controlled injection only.

## Verification

- Hermes lifecycle and disabled/restart tests pass.
- Focused combined V122 run: `82 passed`.
- Runtime smoke confirms capture → projection current before shutdown.
- No Hermes core or external installed source was modified.

## Risk / next

Fresh exact-tree review must verify actual host callback/tool compatibility and lifecycle ownership. Any required modification to external Hermes core is a hard stop; adapter-local defects are in scope for automatic remediation.
