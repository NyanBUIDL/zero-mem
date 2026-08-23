# ADR-V132-02 — Master spec .docx freeze + hash-anchor (D-03 Option A)

**Date:** 2026-08-23 · **Status:** ACCEPTED · **WP:** V132-06 (audit P2-7)

## Decision

- `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` remains THE authority.
- `docs/MASTER-SPEC.md` is a controlled projection with verification:
  - **Anchor:** SHA-256 of the authoritative .docx at freeze time:
    - SHA-256: `85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a`
  - **Rule:** every time the .docx changes, `docs/MASTER-SPEC.md` MUST be
    regenerated (scripts/convert_master_spec_to_md.py exists for this) and a
    NEW ADR must record the fresh hash BEFORE any spec-touching WP merges.
- Enforcement: `scripts/check_master_spec_hash.py` + unit test
  tests/unit/test_v132_06_master_spec_freeze.py — fail-closed when the live
  .docx hash ≠ the anchor above (docx edited without reconcile).
- No content of the .docx or the projection is modified by this WP.

## Rejected alternative

Switching authority to the markdown projection would contradict AGENTS.md
and require a formal spec amendment outside this remediation scope.

## Rationale

The .docx is hard to diff/version; the anchor makes accidental edits loudly
visible while keeping the authority unchanged (smallest reversible change).
