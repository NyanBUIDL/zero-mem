# V122-04 Canonical Sidecar Handoff

**Status:** `VERIFIED_LINUX_SCOPED`
**Current tree fingerprint:** `ba9cd2d8719bcb00e8562b4a7baf07dfb69cceb0616c134c519d7ec99f5a3bdc`

The bounded `src.integration.sidecar.ZeroMemSidecar` remains the canonical transport. `zero_mem.sidecar.LocalSidecar` is now a deprecated compatibility adapter that delegates canonical read capabilities (`search`, `get_trace`, `get_task_state`, `get_decisions`) through the same bounded transport and the injected `PublicClient` read service. Legacy observe/sync/health/capabilities remain compatibility-only.

## Verification

- Canonical-read status parity tests cover READY, EMPTY, DENIED, STALE, TIMEOUT and UNAVAILABLE.
- Identity mismatch and request-size bounds remain enforced.
- Canonical transport owns queue, deadline, executor and response bounds; LocalSidecar does not duplicate authorization, SQL, retrieval or freshness.

## Review state

This handoff is `VERIFIED_LINUX_SCOPED`; the prior fingerprint and evidence are historical and superseded by the current candidate bundle.
