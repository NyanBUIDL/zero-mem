# Zero-Mem v1.3.4 Release Notes (V134 — durability proof + hygiene)

**Date:** 2026-08-23 · **Scope:** DEF-003 + DEF-008 (see `docs/defects/DEFECT-REGISTRY.md`)

## Fixes

### DEF-003 — crash/power-loss durability proof (closes AUD-003 gap)
AUD-003 recorded: "no crash/power-loss proof; race is separately reproduced."
This release adds the missing executable evidence — no production code changed;
the existing fail-closed machinery is now *proven* under hard-kill conditions:

`tests/unit/test_v134_def003_crash_durability.py`
1. **SIGKILL mid-ingest:** a subprocess ingesting 4000 events is SIGKILLed
   partway through. Proven: canonical JSONL byte-identical after the kill →
   resume ingest completes with `stopped=False` → logical digest of the resumed
   DB equals a clean single-pass ingest of the same file (wall-clock
   `updated_at` columns normalized, matching the established m8 test pattern).
2. **Torn canonical tail:** a JSONL whose last line is truncated mid-bytes
   (power loss during append) never projects the incomplete line; repairing the
   file and re-ingesting converges to the same state.

5/5 consecutive runs stable. Stdlib only, no new dependencies.

### DEF-008 — dead code in `make_relation_fingerprint`
`src/retrieval/cursor.py:99-100` duplicated the `canonical = json.dumps(...)`
/ `return hashlib.sha256(...)` pair after the first return (unreachable).
Found by an external model review; verified on tree before registering.
Removed; focused regression (`test_m3_pagination`, `test_m3_query`): 80 passed.

## Registered but deferred

### DEF-009 — registry O(n) update + fp_request field naming
(a) `CorpusSourceRegistry._update_record` re-reads the whole JSONL per update —
O(n)/update, only material above ~10k records; fixing it properly means adding
a second derived index over canonical data, which requires an ADR.
(b) `authorized_read.py:343` assigns `profile_id=project_filter` in the cursor
fingerprint request — behavior-neutral (scope truth lives in `eff_text`) but
audit-confusing. Both planned for v1.4.x alongside the knowledge-space work
(DEF-004).

**Final suite evidence:** `3479 passed, 7 skipped, 0 failed`
(Python 3.13.15, isolated HOME, full canonical run).
