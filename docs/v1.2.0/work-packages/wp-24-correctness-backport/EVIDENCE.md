# WP-24 Evidence — Correctness Backport

**WP:** WP-24
**Status:** `VERIFIED`
**Baseline SHA:** `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
**Workspace:** `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
**Branch:** `NyanBUIDL-Zero-mem`
**Authorization:** `AUTONOMOUS_EXECUTION_AUTHORIZATION`, scope `WP-24..WP-35`; architecture escalation required; destructive data operations and release publication not authorized.

## Pre-existing state

Before WP-24, the worktree already contained modifications to `AGENTS.md`, `docs/architecture/ARCHITECTURE.md`, `implementation-plan.json`, `project-state.yaml`, v1.2 scaffolding, and V11 publication-preflight artifacts. These are not attributed to WP-24. The pre-existing baseline test `tests/baseline/test_project_artifacts.py::test_master_spec_and_derived_agents_exist` still expects the historical string `SQLite + JSONL`, while current `AGENTS.md` uses the approved v1.2 refinement wording; this remains an existing governance/test mismatch and was not rewritten as a shortcut.

## Changed implementation

- `zero_mem/core.py`: added frozen `AppendReceipt`; `EventWriter.append()` now returns durability evidence; capture normalizes concrete receipts and returns `CAPTURED` only when event identity, non-negative sequence, and canonical durability are proven.
- `zero_mem/__init__.py`: exported `AppendReceipt` as part of the public core boundary.
- `src/storage/capture_boundary.py`: exposed `canonical_durable` and `reason_code` on the existing concrete `AppendResult` without changing append/lock/sequence/dedup behavior.
- `zero_mem/recovery.py`: removed obsolete `memories` query; added read-only `zm_meta`/`zm_ingest_checkpoint` schema and watermark inspection with typed missing/corrupt/incompatible/stale/ready outcomes.
- Directly affected test fixtures now return durable receipts, and WP-14 recovery fixture uses the actual `zm_*` schema.
- `tests/unit/test_wp24_correctness_backport.py`: added focused receipt and real-schema recovery tests.

No migration, canonical JSONL write, SQLite repair, new runtime dependency, tag, push, or publication was performed.

## Commands and results

- Canonical workspace invariant: passed. Root `/home/lenovo/Hermes Workspace/zero-mem-v1.1`; remote `git@github.com:NyanBUIDL/zero-mem.git`; branch `NyanBUIDL-Zero-mem`; baseline SHA recorded above.
- Graphify code-only final local-tree analysis: `7073 nodes, 20870 edges, 185 communities`; `diagnose()` is connected to `_checkpoint_for()` and `_prefix_hash()`. Disposable output: `/home/lenovo/graphify-zero-mem-v1.2-final-verified`, outside the repository; Graphify remains read-only corroboration only.
- RED test: `.venv/bin/python -m pytest tests/unit/test_wp24_correctness_backport.py -q` failed at collection because `AppendReceipt` did not yet exist (expected missing-contract failure).
- Focused final regression: `.venv/bin/python -m pytest tests/unit/test_wp24_correctness_backport.py tests/unit/test_wp14_recovery.py tests/unit/test_m2_ingest.py tests/unit/test_m8_1_rebuild.py tests/unit/test_wp02_core_boundaries.py tests/unit/test_wp08_public_api.py tests/unit/test_wp11_sync_async.py tests/integration/test_wp08_generic_client.py -q` → `82 passed in 4.29s`.
- Full regression excluding the pre-existing failing baseline artifact assertion: `3172 passed, 5 skipped in 51.13s` (`tests/baseline/test_project_artifacts.py` intentionally isolated; its known failure is recorded above).
- Syntax/diff checks: `python -m compileall -q ...` → exit 0; `git diff --check` → pass.
- Package evidence from final build path: wheel and sdist built locally with `python -m build --wheel --sdist --no-isolation` from the parent directory to avoid the repository's local `packaging/` module shadowing build's third-party package. Final artifacts: `artifacts/evidence/wp24-package-check-final5/`; wheel SHA-256 `2f871a83e0d78becfac9207fe34a44072307daf16ebc92476cc94e27c1b71765`; sdist SHA-256 `47d7ad5d1db8f7fc85a28934691e703e8774afdc77341a1b58ffebe16dde575a`.

## Acceptance mapping

- Durable receipt and false-success prevention: executable focused tests pass.
- Real derived schema and stale/ready diagnosis: executable focused tests pass; no `memories` query remains in `zero_mem/recovery.py`.
- Canonical/derived boundary: recovery is read-only; no canonical repair or derived-to-canonical rewrite.
- Security/path: no secret values added; fixtures use `tmp_path`; no developer path in runtime code.
- Artifact baseline: local wheel/sdist build and SHA-256 evidence exists; final release qualification remains WP-35.

## Independent review and self-review

Independent review iterations identified and closed: forged receipts without explicit durability, arbitrary reason-code leakage, bool sequence acceptance, malformed checkpoint exceptions, cross-source basename fallback, missing prefix-hash verification, checkpoint identity/sequence mismatch, non-contiguous canonical sequences, and derived-count mismatch. Final implementation and focused/full regressions were rerun after each correction. Final self-review found no future-WP implementation, canonical/derived boundary violation, unbounded retry/queue, swallowed append failure, secret leakage, or developer-specific runtime path.

## Current verification state

WP-24 is `VERIFIED`. Current focused acceptance rerun: `84 passed`. The only full-suite limitation is the pre-existing baseline artifact assertion requiring the historical `SQLite + JSONL` wording in `AGENTS.md`; it remains documented and was not weakened or deleted.
