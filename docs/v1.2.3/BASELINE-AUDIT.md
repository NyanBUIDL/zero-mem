# Zero-Mem v1.2.3 Baseline Audit

**Audit mode:** read-only reconnaissance before implementation
**Repository:** `NyanBUIDL/zero-mem`
**Root:** `/home/lenovo/Hermes Workspace/zero-mem-v123-engineering`
**Branch:** `release/v1.2.3`
**HEAD:** `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
**Remote:** `github = git@github.com:NyanBUIDL/zero-mem.git`
**Remote heads observed:** `master=135f25f8941a1c68a01f63e389f52b60416fa008`; `release/v1.2.3=5f1a329b6e5a18833fb4186cad7c91807a40b79e`; `v1.2.3` tag absent; `v1.2.2=7dac79de5918afaeae3acbed1e1c7917fcff2023`
**Working tree:** `?? docs/v1.2.3/work-packages/R-00-release-evidence-model/README.md` only; classified as expected governance artifact, pre-existing before this execution.
**Current verified milestone:** M10.7 recorded verified; `project-state.yaml` notes canonical test proof at historical HEAD `2e6213700022581a37673cc0bab4a0aaa4facfcd`, later state/acceptance commits not canonically re-proven.
**Feature freeze:** active.
**Current v1.2.3 implementation:** release-control documentation exists; R-00 README is PARTIAL; no v1.2.3 evidence bundle; current verifier is V1.2.2-oriented.
**Current v1.2.3 tests:** legacy verifier tests exist (`4 passed`); no complete R-00…R-05 black-box suite.
**Current v1.2.3 evidence:** absent under `docs/v1.2.3/evidence/`.
**Current v1.2.3 work packages:** R-00 README only; R-01…R-05 not yet present at baseline.
**Platform status:** Linux host available; Windows/macOS real-runner qualification not yet evidenced.
**Release state:** no v1.2.3 tag or GitHub Release observed; PKG-7 historical state is not v1.2.3 evidence.
**Known contradictions:** release-control docs preserve an older self-circular manifest/tag rule and state planning-only authorization; current execution directive explicitly authorizes R-00…R-05 and supersedes the self-circular rule with `ARTIFACT_SOURCE_SHA -> EVIDENCE_COMMIT_SHA -> RELEASE_COMMIT_SHA`. Historical docs will not be rewritten.
**Known regression risks:** public API currently permits unavailable reads without a configured runtime; legacy sidecar wrapper advertises non-read capabilities and delegates canonical reads; Hermes plugin factory currently returns capture registration only; full M10 canonical proof is historical rather than exact current HEAD.

## Commands executed

- `git rev-parse --show-toplevel`
- `git branch --show-current`
- `git rev-parse HEAD`
- `git status --short --untracked-files=all`
- `git remote -v`
- `git branch -vv`
- `git ls-remote github refs/heads/master refs/heads/release/v1.2.3 refs/tags/v1.2.3 refs/tags/v1.2.2`
- `python scripts/verify_v122_evidence.py` (expected CLI usage failure; no manifest argument)
- `PYTHONPATH=. pytest -q tests/unit/test_v122_evidence_verifier.py` -> `4 passed`
- Graphify `0.9.43`, code-only extraction on disposable archive -> `7513 nodes, 22438 edges`; advisory only.

## Authorization

Current user directive authorizes row-scoped source, test, documentation, evidence, verifier, CI, packaging, local commit and fast-forward release-branch push operations. Force push, history rewrite, tag movement/deletion, destructive canonical operations, and master mutation remain prohibited.
