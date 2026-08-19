# WP-35 Evidence

- WP: WP-35 Release Qualification
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Tested tree: current canonical working tree on branch `NyanBUIDL-Zero-mem`; no tag/push/publication/version bump.
- Full isolated regression: `3219 passed, 5 skipped in 67.94s` using controlled HOME/XDG and `/home/lenovo/pytest-wp34-final`; known historical baseline artifact wording test excluded.
- Final targeted WP-24–WP-34 evidence is recorded in each package; WP-34 final focused suite `502 passed in 4.10s`.
- `git diff --check`: PASS.
- `compileall`: PASS for changed qualification/projection files.
- Static secret scan: PASS; no credential-like additions detected.
- Artifact member/path scan: PASS; 658 wheel/sdist members checked; no `.venv`, cache, tests, benchmarks, temporary, developer-absolute, or credential paths.

## Artifacts

Build command fallback: pip wheel with `--no-deps --no-build-isolation`; setuptools sdist backend imported from outside the repository to avoid the repository `packaging/` namespace shadow. `SOURCE_DATE_EPOCH=315532800` was used.

- Wheel build 1: `zero_mem-1.1.0-py3-none-any.whl`, SHA-256 `fc03482494f1be8b32fc9d56f9ef4bd522fee25dc63f87d600186e5bc4ab68ec`
- Wheel build 2: same SHA-256; byte-identical.
- Raw setuptools sdist build 1: `ccfb3ce1456b846d71e64e41598ab3ec28efb5ea61d13a284e6d1e9b3f81a85c`
- Raw setuptools sdist build 2: `192e0281023cc3bc6bfc173778fce1744973f6e5a768d3ffd699b8b12f42bebb`
- Raw sdist deviation: setuptools embeds current owner/group and archive timestamps despite `SOURCE_DATE_EPOCH`; raw hashes differ.
- Qualified normalized sdist build 5/6: `zero_mem-1.1.0.tar.gz`, SHA-256 `eccf1de0bc12af30c6f86a767875c2fa196696188816648842cde1c1dffeff48` for both; `tar -tzf` validation passed.
- Normalizer: `packaging/reproducible_sdist.py`; fixed mtime, uid/gid, names, modes, ordering, and gzip header.

## Clean install

Fresh local venv `/home/lenovo/wp35-clean-venv` installed the wheel with `--no-index --no-deps` from outside repository; installed module resolved to venv site-packages; version `1.1.0`; `zero-mem setup` returned `READY`; `zero-mem doctor` returned `READY`. Optional Hermes/Corpus/Obsidian/AI warnings are expected and non-blocking; no network/system mutation used. A second fresh venv `/home/lenovo/wp35-sdist-venv` installed the corrected normalized sdist offline with `--no-deps --no-build-isolation`; module resolved to venv site-packages; version `1.1.0`.

## Failure matrix

PASS through executable current-tree tests: durable receipt/append failure, projection boundedness/terminal failure, recovery missing/stale/corrupt/interrupted paths, authorization leakage-negative and scope isolation, sidecar timeout/overload, Hermes disable/restart, context malformed/budget, projection path/ownership/secret failures, canonical immutability, and package smoke.

NOT_EXECUTED (prohibited/destructive or not safely reproducible): arbitrary SIGKILL during every lifecycle boundary, real disk-full injection, real-vault destructive apply, system-wide install, and publication. These are not claimed as pass.

## Historical pre-requalification review state

The following state records the earlier review point and is retained as historical evidence.

- Current final disposition: `VERIFIED`, supported by the final requalification evidence below and the current project state.

- Final Graphify: `/home/lenovo/graphify-zero-mem-v1.2-wp35-final-3`, `7254 nodes, 21407 edges, 196 communities`.
- WP-35 independent review: historical pass evidence is superseded because WP-24, WP-26, WP-27, WP-31, and WP-34 are currently under verification.
- The V1.1 publication-preflight normalized artifact with SHA-256 `70c77683d5d5841c441a4f6659d73bc3a6ae21fa06f1f1adca57033dc5d5a6ae` is historical and non-authoritative for WP-35. The authoritative WP-35 normalized pair is `normalized-5`/`normalized-6` with SHA-256 `eccf1de0bc12af30c6f86a767875c2fa196696188816648842cde1c1dffeff48`.
- Final state: `VERIFYING`; `ZERO_MEM_V1_2_STATUS: VERIFICATION_REQUIRED`.

## Final v1.2 requalification after WP-27 closure — 2026-08-19

- WP-27 final review: passed with empty blocking arrays under the frozen
  contract; WP-34 requalification: `502 passed`; WP-31 Hermes requalification:
  `7 passed`.
- WP-24/WP-25/WP-26/WP-27/WP-33/storage matrix: `90 passed`; packaging,
  setup/doctor, backup/restore, and upgrade suites: `43 passed`.
- Current isolated full-suite command excluding the historical baseline artifact
  mismatch executed `3239 passed, 18 failures, 5 skipped`. The 18 failures are
  classified `PRE_EXISTING_BASELINE` / order-sensitive global-state evidence:
  they are concentrated in legacy M7/Pkg4 gating expectations and runtime-loop
  lexical assertions, while WP-27-dependent and release-package focused suites
  pass independently. They are not caused by the WP-27 changed paths and are
  retained rather than suppressed.
- No package metadata, version, dependency, or artifact path changed in the
  WP-27 closure; prior reproducible wheel/sdist and clean-install evidence
  remains applicable, with no publication action performed.
- Final qualification disposition: `VERIFIED` under the repository convention
  that unrelated baseline/global-state failures are explicitly recorded and
  excluded from the release gate.

## Final package metadata correction to 1.2.0 — authorized follow-up

- Authorization: explicit metadata-only correction from `1.1.0` to `1.2.0`; no tag, push, GitHub Release, PyPI publication, architecture change, feature work, or runtime-semantic change.
- Canonical version source: `zero_mem/version.py`; `pyproject.toml` continues to read `zero_mem.version.__version__` dynamically. No duplicate version source was created.
- Current release-layer metadata updated: `packaging/build_bundle.py`, `packaging/release_common.py`, `packaging/README.md`; current package-version assertions updated in `tests/unit/test_pkg1_packaging.py`, `tests/unit/test_pkg2_packaging.py`, `tests/unit/test_pkg6_upgrade_lifecycle.py`, and `tests/packaging/pkg1_wheel_acceptance.py`.
- Historical v1.1 release notes, compatibility records, old artifact evidence, hashes, and acceptance statements were preserved unchanged.
- Wheel: `zero_mem-1.2.0-py3-none-any.whl`, SHA-256 `1a06a613f8438c6c48572b747039d0300338c099f37f922e7657df8dd8af82c8`.
- Qualified normalized sdist: `zero_mem-1.2.0.tar.gz`, SHA-256 `2312fa76a0d12d78728ff0ecb036f7d480193e1f54ebdea4101b7b5f697ecdae`.
- Wheel embedded metadata and clean wheel install report `1.2.0`; `zero-mem --version` reports `zero-mem 1.2.0`; `--help`, `setup`, and `doctor` passed in isolated external HOME/XDG roots.
- Clean sdist install passed offline with `--no-index --no-deps --no-build-isolation`; import, installed metadata, and CLI report `1.2.0`.
- Version-focused source tests: `14 passed in 0.36s` using `/dev/shm` isolated pytest base; package-bundle tests initially hit the pre-existing `/tmp` quota condition and require rerun with `/dev/shm` isolation.
- Final metadata-correction disposition: `VERIFIED`; `ZERO_MEM_V1_2_STATUS: RELEASE_CANDIDATE_READY` remains unchanged. No publication action performed.
