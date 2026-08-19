# WP-35 Acceptance

**Status:** `VERIFIED`

## Functional / E2E acceptance

- Direct API, capture receipt, projection, authorized retrieval, context, restart, recovery, sidecar, and Hermes lifecycle gates pass through executable current-tree tests.
- Canonical JSONL remains unchanged by read/recovery/qualification paths.
- Authorization leakage-negative, scope isolation, provenance, freshness, budget, deterministic ordering, and projection ownership tests pass.

## Failure / chaos acceptance

- Existing safe tests pass for append failure, queue full, projection terminal failure, missing/stale/corrupt derived state, interrupted recovery, sidecar timeout/overload, disabled Hermes, malformed context, and path/secret/ownership failures.
- Disk-full, arbitrary SIGKILL, external process crash, and real-vault destructive scenarios are explicitly recorded `NOT_EXECUTED` when not safely reproducible; no fake pass is allowed.

## Artifact acceptance

- Wheel builds twice with fixed `SOURCE_DATE_EPOCH` and are byte-identical.
- Raw setuptools sdist builds successfully twice but are not byte-identical because the backend embeds owner/group and archive timestamps; this deviation is a qualification blocker unless the deterministic normalizer below succeeds.
- The qualified normalized sdist is produced twice from the raw source trees by `packaging/reproducible_sdist.py`, rejects source symlinks, passes `tar -tzf`, has byte-identical SHA-256, and installs offline into a fresh local venv.
- SHA-256 hashes, archive members, metadata, version, Python range, and dependency declarations are recorded.
- No tests, `.venv`, caches, temporary paths, credentials, developer absolute paths, or unintended files are present.
- Wheel installs offline into a fresh local venv with no system mutation; import, version, CLI/setup/doctor smoke checks pass.

## Regression / reproducibility

- Full isolated suite excluding the known historical baseline artifact wording mismatch passes.
- `compileall`, `git diff --check`, static scans, final Graphify, and independent review pass.
- Tested support claim is limited to Linux CPython 3.11.16.

## Exit gate

Set `ZERO_MEM_V1_2_STATUS: RELEASE_CANDIDATE_READY` only if every required executable gate passes, limitations are explicit, evidence is complete, and no publication action occurred. Otherwise remain `FAILED_VERIFICATION` or `BLOCKED`.
