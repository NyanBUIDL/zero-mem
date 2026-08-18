# Zero-Mem v1.1.0 Compatibility Matrix

The machine-readable source is `artifacts/control/COMPATIBILITY-MATRIX.yaml`.

## Policy

- Python: `>=3.11,<3.14`.
- FTS5 is required for FTS-backed retrieval; unavailable FTS5 is a typed unavailable capability, not silently equivalent full support.
- Linux x86_64 is verified only for the executor environment recorded in the matrix.
- Linux arm64, macOS arm64, WSL2, and Docker on Linux are supported-if-qualified, not verified here.
- macOS x86_64 is best-effort-unverified.
- Native Windows is not supported for v1.1.0.
- WSL2 uses Linux-side authoritative state; Docker requires an explicitly mounted durable volume.

## Current qualification

Linux x86_64 / Python 3.11.16 / SQLite 3.53.1 / FTS5 enabled passed the available local qualification checks. No unavailable platform result is fabricated.
