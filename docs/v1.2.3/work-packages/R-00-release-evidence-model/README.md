# R-00 — Source-Bound Release Evidence Model

**Status:** PARTIAL
**Baseline SHA:** `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
**Finding closed:** Release evidence is not source-contained or clean-checkout-verifiable for v1.2.3.
**Allowed paths:**

- `docs/v1.2.3/work-packages/R-00-release-evidence-model/README.md`
- `docs/v1.2.3/evidence/**`
- `scripts/verify_v122_evidence.py` or a narrowly scoped v1.2.3 successor
- focused verifier tests
- narrowly required v1.2.3 evidence documentation and CI verifier wiring

**Public boundary tested:** Candidate checkout + repository-provided evidence verifier CLI.
**Platform scope:** Linux evidence generation and clean-clone verification. Windows/macOS claims remain unavailable until R-04 real-runner evidence.

## Observable problem

At the baseline, `docs/v1.2.3/evidence/<full-source-sha>/` is absent. The existing verifier is explicitly V122-00 oriented and cannot prove the v1.2.3 release-gate contract from a clean checkout of the candidate source revision.

## Contract decision

R-00 will provide an additive, source-contained v1.2.3 evidence bundle and a fail-closed verifier. The verifier must bind its manifest source SHA to the checkout HEAD, validate every declared log and asset checksum, require a collection result with zero errors, require complete command-to-log hash linkage, and reject platform/release claims that exceed recorded evidence. It must use only repository-relative evidence paths and never alter canonical memory, release refs, or historical v1.2.2 evidence.

Evidence generated before the final candidate commit is development evidence only. Final R-00 closure evidence is regenerated after the final R-00 source commit and independently rerun from a clean clone.

## Rollback plan

All changes are additive release-control documentation, verifier logic, focused tests, and evidence. Reverting an unpushed R-00 commit removes only v1.2.3 derived release-control material; it does not change canonical JSONL, SQLite derived state, release tags, or published evidence.

## Negative cases

- missing evidence bundle or manifest;
- source SHA mismatch;
- missing, altered, symlinked, or escaping log/asset path;
- command/log hash mismatch;
- collection error or inconsistent collection count;
- unsupported platform marked qualified;
- release evidence referring to developer-local absolute paths.

## Evidence requirements

- exact source SHA;
- commands and environment records;
- raw logs with SHA-256 values;
- artifact SHA-256 values where artifacts exist;
- verifier output from the candidate tree and a clean clone;
- independent review against the exact final R-00 tree;
- explicit Linux/Windows/macOS status without inferred qualification.

## Blocking contradiction

The R-00 contract simultaneously requires that the release tag contain the evidence bundle and that `manifest.json` record a full `source_sha` equal to `git rev-parse HEAD` for that same tag. A tracked manifest changes the tagged tree and therefore the commit ID it is required to embed. A later evidence commit changes the target again, while a post-tag evidence commit is excluded by the explicit tag-contained-bundle requirement. No ordinary implementation can produce a self-referential Git commit SHA without changing the stated identity model.

The baseline RED probe, executed from the baseline source tree, rejected the absent required manifest with `manifest_missing` at source SHA `5f1a329b6e5a18833fb4186cad7c91807a40b79e`. An independent read-only R-00 audit independently confirmed the same constraint and additionally found that the current verifier neither validates every `SHA256SUMS.txt` entry against bytes nor enforces a clean checkout/platform/full-suite release schema. Those are repairable only after the non-circular identity rule is decided. The evidence model needs a maintainer-approved non-circular binding rule before R-00 can be implemented or verified.

## Authorization

Authorized by the maintainer authorization envelope for R-00 through R-05. Local commits and fast-forward pushes to `release/v1.2.3` are permitted only after the row’s applicable verification stage. `master`, tags, GitHub Releases, history rewrites, and destructive operations remain prohibited.
