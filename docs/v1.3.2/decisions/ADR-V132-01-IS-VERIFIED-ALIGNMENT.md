# ADR-V132-01 — is_verified enum alignment (D-01 Option A)

**Date:** 2026-08-23 · **Status:** ACCEPTED · **WP:** V132-01 (audit P1-1)

## Context

`src/integration/m7/eligibility.py:178` classified verification with
`verification in ("verified", "confirmed")`, but no `VerificationStatus`
member (src/capture/event_types.py: none / direct_tool_output /
user_confirmation / deterministic_verification / approval) matches either
value. `"confirmed"` belongs to `LifecycleStatus`. Result: `is_verified`
was always False for memory events verified through the canonical enum;
they fell to supporting even when verified. Analysis:
docs/v1.3.1/analysis/is-verified-enum-mismatch.md.

## Decision (D-01 Option A)

Align eligibility with the real enum:

```python
_VERIFIED_STATUSES = frozenset(
    v.value for v in VerificationStatus if v.value != "none"
)
is_verified = verification in _VERIFIED_STATUSES
```

The adjacent lifecycle check `lifecycle == "confirmed"` (line 183) is kept
unchanged — it is correct in its own taxonomy.

## Rationale

- Restores verified discrimination on the retrieval-quality path without
  opening any new promotion path (closed set derived from the enum).
- No enum change, no schema change, no canonical JSONL change.
- Option B (freeze always-False) permanently loses verified discrimination
  and codifies the bug; rejected.

## Consequences

- Events with any non-none VerificationStatus + active lifecycle now classify
  primary (when not otherwise excluded). Covered by contract matrix tests:
  tests/unit/test_v132_01_is_verified_alignment.py (RED→revert FAIL→green
  PASS triple-log in zero-mem-dev-data/evidence/v132/wp1-*.log).
- Full suite: 3454 passed / 6 skipped (≥ baseline 3448/6; +6 new tests).

## Repo-wide sweep (WP1-C6 — OPEN QUESTION finding)

Other sites using "verified"/"confirmed" as verification values, NOT changed
(out of scope, recorded as open questions for the maintainer):

| Site | Value used | Assessment |
|---|---|---|
| src/integration/m7/budget.py:51 `verified_rank` | `("verified","confirmed")` | Same enum mismatch, ranking-only (no role promotion). Every item ties at rank 1 → ordering falls through to lifecycle/timestamp. Behavior-neutral today, but the same conflation. **Recommend follow-up alignment in a future WP.** |
| src/access/admin.py:209, src/access/resolver.py:162 | `status != "verified"` on WRITE-grant verification refs | Different pipeline: VerificationView records (zm_verifications) use "verified" as their status vocabulary (tests/unit/test_m5_grants.py, tests/unit/test_m9_3_provenance_links_conflict.py produce `verification_status="verified"`). Separate taxonomy from event VerificationStatus; consistent within its own pipeline. No change. |

No other src/ site consumes "verified"/"confirmed" as event-verification
values.
