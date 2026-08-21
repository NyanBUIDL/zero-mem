# R-02 — Canonical Sidecar Discovery

**Status:** OPEN
**Baseline SHA:** `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
**Finding closed:** Sidecar capability discovery and dispatch are not yet proven as the one canonical semantic path.
**Allowed paths:** `zero_mem/sidecar.py`, `src/integration/sidecar.py`, focused R-02 tests, v1.2.3 evidence/work-package documentation.
**Public boundary tested:** Advertised capability list plus sidecar request boundary.
**Platform scope:** Linux first; transport-neutral behavior.

## Contract decision

Advertise exact callable read names and normalize direct/sidecar results to `capability,status,reason_code,items,provenance,freshness`. Preserve shared authorization and do not advertise a legacy replacement.

## Negative cases

READY, EMPTY, DENIED, STALE, TIMEOUT, UNAVAILABLE, malformed request, oversize payload, deadline and closed lifecycle.

## Evidence

Pending R-00 and R-01 dependency gates.
