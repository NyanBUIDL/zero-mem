# Zero-Mem v1.3.1 Release Notes (draft — Gate G6)

**Status:** IMPLEMENTATION_COMPLETE, local-only. Not tagged/pushed/published
without `APPROVE-RELEASE-V131.md` created by the maintainer.

## Remediation of v1.3.0 release-integrity defect

- **v1.3.0 tag was published while `zero_mem/version.py` still read `"1.2.4"`**
  (`pyproject.toml` derives the distribution version from that attribute), so a
  build from the v1.3.0 tag self-reported 1.2.4. The tag itself is NOT rewritten;
  v1.3.1 carries the corrected version string.
- New unit test `tests/unit/test_v131_version_integrity.py` asserts
  `importlib.metadata.version("zero-mem") == zero_mem.version.__version__`.

## Behavior change (intentional)

- **Redaction gate (WP-6):** already-redacted markers `«redacted:…»` are stripped
  before secret-marker scanning, so previously redacted lines pass the gate while
  real secrets still fail closed.

## Tooling / docs

- pymupdf declared as tooling-only optional extra `pdf-advanced`
  (AGPL warning); no new runtime dependency (WP-2, ADR-V131-01).
- Superseded banners on stale release-status docs; single source of truth for
  release status is `project-state.yaml` (WP-3).
- Corpus ingest/projection script fixes and portability fixes (WP-4/5/7).
- WP-8 is_verified enum mismatch documented as an open decision; no behavior change.
