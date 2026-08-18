# WP-14 Recovery Runbook

1. Preserve canonical JSONL and stop writes when diagnosis reports `CANONICAL_MALFORMED`.
2. Run read-only `zero_mem.recovery.diagnose`; never repair canonical history in place.
3. If derived state is missing, unavailable, or stale, rebuild the disposable derived store from canonical JSONL using the existing replay/rebuild path.
4. Verify backup manifests and checksums before restore or migration.
5. For interrupted upgrades, use the staged rollback path in `zero_mem.upgrade`; do not delete rollback evidence.
6. Retry only typed failures classified as pre-commit/retryable; ambiguous commit state is recovery-required.

The canonical stream is authoritative. Repair and rollback require explicit operator authority and must preserve forensic evidence.
