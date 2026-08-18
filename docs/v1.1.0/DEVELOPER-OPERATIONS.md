# Zero-Mem v1.1 Developer and Operations Notes

- Canonical memory is append-only JSONL; SQLite, graphs, and workspace notes are derived.
- Use `zero_mem.PublicClient` for generic integrations and `LocalSidecar` only through its bounded local contract.
- Use doctor/status for content-free readiness and capability diagnostics.
- FTS5 is required for FTS-backed retrieval; unavailable FTS5 is an explicit capability failure.
- Native Windows and network-filesystem guarantees are outside v1.1.0.
- Before upgrades, verify a backup; after recovery, rerun doctor and rebuild derived projections when required.
