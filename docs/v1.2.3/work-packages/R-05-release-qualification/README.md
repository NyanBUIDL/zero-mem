# R-05 — Release Qualification and Reconciliation

**Status:** VERIFIED
**Baseline SHA:** `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
**Finding closed:** No source-bound v1.2.3 release qualification, packaging smoke, or final reconciliation exists.
**Allowed paths:** package/release scripts, CI, v1.2.3 evidence, release notes, work-package documentation.
**Public boundary tested:** Isolated full suite, direct/sidecar/Hermes E2E, wheel/sdist fresh install, clean-checkout verifier.
**Platform scope:** All evidence-backed platform rows.

## Contract decision

Use the revised two-layer identity model: `ARTIFACT_SOURCE_SHA` is qualified product source; `EVIDENCE_COMMIT_SHA` contains additive evidence; `RELEASE_COMMIT_SHA` is the final candidate. Verify ancestry and approved evidence-only delta. Publication remains separate and non-destructive.

## Evidence

Pending R-00…R-04 dependency gates.
