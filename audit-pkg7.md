# PKG-7 Audit Summary — Final Release Audit & Release Candidate Freeze

**Authority:** owner-authorized PKG-7 contract.

**Audit scope:** repository architecture; canonical/derived boundaries; M5/M6.6/M7/M8 authorization controls; M9 path and sensitivity controls; corpus storage/retrieval; persistence/rebuild; backup/restore/upgrade; packaging/lifecycle; dependencies; documentation and metadata; static dead/stale-code review.

## Findings

| ID | Severity | Component | Evidence | Risk | Smallest corrective action | Release-blocking | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PKG7-AUD-001 | HIGH | `src/corpus/blob_store.py` canonical corpus artifacts | `CorpusBlobStore.get()` and the pre-existing-file path in `put()` accepted a digest-shaped filename without recomputing SHA-256 of its bytes. Backup/upgrade validation detects this later, but normal corpus projection can consume a tampered canonical blob before those lifecycle commands run. | Canonical corpus payload integrity is not fail-closed during normal projection/rebuild; corrupted bytes could enter derived text/indexes. | Verify payload SHA-256 equals the requested/content-derived digest at both read and existing-target reuse boundaries; add a permanent regression proving tampered blobs are rejected and cannot project units. | YES | Owner-authorized HIGH fix required. |
| PKG7-AUD-002 | MEDIUM | PKG-2 deterministic wheel packaging | Repeated `pip wheel --no-index --no-deps --no-build-isolation` builds had identical payload bytes but different ZIP timestamps and therefore different wheel SHA-256 values when no reproducible-build timestamp was set. | Release artifact identity cannot be reproduced byte-for-byte. | Set the standard `SOURCE_DATE_EPOCH` in the permanent deterministic-build regression, assert complete wheel digest equality, and document the accepted build input. | YES | Owner-authorized release-portability correction required. |

## Audit conclusion before fixes

- Two release-blocking findings were identified: `PKG7-AUD-001` and `PKG7-AUD-002`.
- No schema migration, version change, dependency addition, feature work, real-corpus mutation, or `package-lock.json` change is warranted.
- The corrective scope is limited to canonical artifact integrity verification and its regression coverage.
