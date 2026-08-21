# Zero-Mem v1.2.3

## Verified release scope

Zero-Mem v1.2.3 closes the release-critical cross-boundary gaps for:

- Public `zero_mem` local composition with canonical JSONL and derived SQLite state.
- Canonical sidecar capability discovery and normalized read statuses.
- Full Hermes host composition and lifecycle.
- Linux, Windows, and macOS platform qualification.
- Source-bound release evidence and reproducible packaging qualification.

## Qualification

- Full isolated suite: **3301 passed, 5 skipped, 0 failed**.
- Direct public E2E: **PASS**.
- Sidecar E2E: **PASS**.
- Hermes host E2E: **PASS**.
- Platform matrix run `32454255094`: Linux **PASS**, Windows **PASS**, macOS **PASS**.
- Package version: `1.2.3`.
- API version: `1.0`.

## Artifacts

- `zero_mem-1.2.3-py3-none-any.whl`
  - SHA-256: `ae1d03b4c576aab8e9bd2645bc250cc95b37fa910e98f0c89905302462209eee`
- `zero_mem-1.2.3.tar.gz`
  - SHA-256: `8e2ae39c2708031d28965ee3819766b224d27e67c366f4b8fb52913f8221d4f6`

Both artifacts passed fresh-install public smoke tests and are recorded in the source-bound R-05 evidence bundle.

## Architecture and safety

JSONL remains canonical append-only memory-event truth. SQLite and other indexes remain derived and rebuildable. Authorization remains before discovery. No force push, history rewrite, destructive canonical operation, or existing tag movement was performed during engineering qualification.
