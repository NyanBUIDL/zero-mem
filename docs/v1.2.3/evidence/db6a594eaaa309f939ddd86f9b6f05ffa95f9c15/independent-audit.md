# R-00 Independent Audit

**Verdict:** PASS
**Reviewed HEAD:** `32575eb5999401bb1a8fb55399c57cd5a7493ac7`
**Artifact source:** `db6a594eaaa309f939ddd86f9b6f05ffa95f9c15`
**Reviewer mode:** fresh read-only exact-tree review

## Confirmed

- Artifact source is an exact ancestor of reviewed HEAD.
- Reviewed working tree was clean.
- HEAD delta from artifact source contained only allowlisted `docs/v1.2.3/evidence/**` additions.
- No current HEAD SHA was self-embedded as `EVIDENCE_COMMIT_SHA`.
- Focused R-00 tests passed: `4 passed, 0 failed` in isolated `/dev/shm` environment.
- v1.2.3 verifier passed with the current HEAD derived independently.
- `sha256sum -c hashes/SHA256SUMS.txt` passed for all three entries.
- Full-suite raw log records `3296 passed, 5 skipped, 0 failed`.
- Corrected focused raw log records `4 passed, 0 failed`; the earlier quota-failure log was not accepted as evidence.
- Windows and macOS remain explicitly `NOT_RUN`, not inferred PASS.

## Commands independently rerun

- `TMPDIR=/dev/shm/zero-mem-v123-r00-review ... pytest -q tests/unit/test_v123_evidence_verifier.py`
- `PYTHONPATH=. ... python scripts/verify_v123_evidence.py .../manifest.json`
- `sha256sum -c hashes/SHA256SUMS.txt` from the evidence directory
- `git merge-base --is-ancestor ARTIFACT_SOURCE_SHA HEAD`
- `git status --short --branch`
- `git diff --name-only ARTIFACT_SOURCE_SHA..HEAD`

## Remaining scope

R-00 does not qualify Windows/macOS or packaging. Those are R-04/R-05 responsibilities.
