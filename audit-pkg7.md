# PKG-7 Audit Summary — Final Release Audit & Release Candidate Freeze

**Authority:** owner-authorized PKG-7 contract.

**Audit scope:** repository architecture; canonical/derived boundaries; M5/M6.6/M7/M8 authorization controls; M9 path and sensitivity controls; corpus storage/retrieval; persistence/rebuild; backup/restore/upgrade; packaging/lifecycle; dependencies; documentation and metadata; static dead/stale-code review.

## Findings

| ID | Severity | Component | Evidence | Risk | Smallest corrective action | Release-blocking | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PKG7-AUD-001 | HIGH | `src/corpus/blob_store.py` canonical corpus artifacts | `CorpusBlobStore.get()` and the pre-existing-file path in `put()` accepted a digest-shaped filename without recomputing SHA-256 of its bytes. Backup/upgrade validation detects this later, but normal corpus projection can consume a tampered canonical blob before those lifecycle commands run. | Canonical corpus payload integrity is not fail-closed during normal projection/rebuild; corrupted bytes could enter derived text/indexes. | Verify payload SHA-256 equals the requested/content-derived digest at both read and existing-target reuse boundaries; add a permanent regression proving tampered blobs are rejected and cannot project units. | YES | Owner-authorized HIGH fix required. |
| PKG7-AUD-002 | MEDIUM | PKG-2 deterministic wheel packaging | Repeated `pip wheel --no-index --no-deps --no-build-isolation` builds had identical payload bytes but different ZIP timestamps and therefore different wheel SHA-256 values when no reproducible-build timestamp was set. | Release artifact identity cannot be reproduced byte-for-byte. | Set the standard `SOURCE_DATE_EPOCH` in the permanent deterministic-build regression, assert complete wheel digest equality, and document the accepted build input. | YES | Owner-authorized release-portability correction required. |
| PKG7-AUD-003 | MEDIUM | Corpus blob tamper regression coverage | The existing regression for `PKG7-AUD-001` asserted only `get()` rejection. It did not permanently prove the separately required `exists() -> False` and idempotent `put()` refusal boundaries. | A future change could reopen one canonical-consumer boundary while the partial regression remained green. | Extend the existing minimal tamper regression with the two missing assertions; no product change. | YES | Resolved by `fb9578d`. |
| PKG7-AUD-004 | MEDIUM | M6 unwired-dispatcher contract tests | Four M6.1 tests depended on the mutable module-global dispatcher. They expected `CAPABILITY_UNAVAILABLE`, but became `EMPTY` when an earlier test configured M6.2 handlers; the formal security matrix failed four assertions. | Release security evidence was order-dependent and the contract was not deterministically tested. | Inject an explicit fresh `Dispatcher()` in tests that verify the unwired-tool envelope; retain the actual product contract. | YES | Resolved by `e864f53`. |

## Audit conclusion before fixes

- Four release-blocking findings were identified: `PKG7-AUD-001` through `PKG7-AUD-004`.
- No schema migration, version change, dependency addition, feature work, real-corpus mutation, or `package-lock.json` change is warranted.
- The corrective scope is limited to canonical artifact integrity verification,
  reproducible wheel timestamps, and deterministic release-regression coverage.

## Final disposition

- `PKG7-AUD-001` — **RESOLVED** by `d085224`: normal blob reads, idempotent reuse,
  and existence checks now verify the content address; the permanent tamper
  regression is in `tests/unit/test_m10_2_ingestion.py`.
- `PKG7-AUD-002` — **RESOLVED** by the PKG-7 deterministic-wheel regression:
  the accepted offline build environment pins `SOURCE_DATE_EPOCH=315532800` and
  asserts complete wheel digest equality across repeated builds.
- `PKG7-AUD-003` — **RESOLVED** by `fb9578d`: the existing corpus-tamper regression
  now proves fail-closed behavior at all three canonical-consumer boundaries:
  `exists()`, `get()`, and idempotent `put()`.
- `PKG7-AUD-004` — **RESOLVED** by `e864f53`: M6 unwired-envelope tests construct
  their own dispatcher and no longer inherit handler registration from test order.
- Open release blockers: **0**. No LOW or quality-only observations warrant an
  RC exception.
