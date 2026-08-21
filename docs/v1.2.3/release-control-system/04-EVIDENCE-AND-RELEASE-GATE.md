# 04 — Evidence and release gate

## Exact-SHA invariant

Before tagging, all values must be full, equal Git object IDs:

```text
master SHA = release/v1.2.3 SHA = candidate tag target = artifact source SHA = evidence manifest source SHA
```

If any differs, release is `NO-GO`. The current `v1.2.2` tag remains immutable; fix provenance only through the next additive release.

## Required evidence verifier behavior

`scripts/verify_v122_evidence.py` (or its v1.2.3 successor) must run from a clean checkout of the candidate tag and verify:

- evidence bundle exists in the tag;
- manifest source SHA equals `git rev-parse HEAD`;
- every raw log and asset checksum matches;
- collection log has zero errors;
- exact full suite and platform rows are recorded;
- release note/platform claim matches matrix result.

The verifier itself runs in CI before a tag or release asset can be created.

## Release checklist

- [ ] R-00 through R-05 are marked only by three-proof closure.
- [ ] Direct/sidecar/Hermes E2E suite passes.
- [ ] Linux, Windows and macOS status is exactly reflected in documentation and release notes.
- [ ] Wheel/sdist install in fresh environment and run public smoke path.
- [ ] Artifact checksums match source-bound manifest.
- [ ] Independent reviewer reruns verifier from clean clone and records result.
- [ ] Maintainer separately authorizes commit, push, tag and GitHub Release.

## Post-release reconciliation

Within the release workflow, run a read-only check against GitHub: tag target, release existence, release note version/scope and uploaded asset hashes. Save the output in the *next* additive release evidence record. Never leave a final document claiming `TAG: NOT_PERFORMED` after a tag/release exists.
