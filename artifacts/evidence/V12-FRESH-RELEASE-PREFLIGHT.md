# Zero-Mem v1.2.0 Fresh Release Preflight

- **FRESH_RELEASE_PREFLIGHT:** `PASS`
- **Repository:** `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- **Branch:** `NyanBUIDL-Zero-mem`
- **Source HEAD before release mutation:** `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- **Version:** `1.2.0` from `zero_mem.version.__version__`; `pyproject.toml` reads the same dynamic source.

## Gates

- Canonical repository: PASS; local repository root is the requested path.
- Dirty tree: PASS with explicit classification. Existing tracked source/test/package/state changes and v1.2 documentation are release-intended. `.venv` links, `graphify-out/`, machine-audit scratch files, prior v1.1 evidence/artifacts, and disposable test files are excluded from the release file set; no cleanup or reset was performed.
- Secret scan: PASS; no exact credential/key patterns detected in the scanned repository content.
- Release-intended archive member scan: PASS for fresh wheel; 154 members, no tests, `.venv`, cache, temporary, credential, or developer-path members.
- `git diff --check`: PASS.
- `project-state.yaml`: PARSED.
- `implementation-plan.json`: PARSED.
- WP-24 through WP-35 current consistency: PASS; all current status fields are `VERIFIED`, historical non-final references are preserved and classified as historical/superseded.
- `ZERO_MEM_V1_2_STATUS`: `RELEASE_CANDIDATE_READY`.
- Package metadata: PASS; distribution version `1.2.0`, Python declaration `>=3.11,<3.14`, no mandatory dependencies.

## Fresh artifacts

Wheel built twice from the current working tree with `SOURCE_DATE_EPOCH=315532800`; both byte-identical:

- `zero_mem-1.2.0-py3-none-any.whl`
- SHA-256: `6c317f7b0e1f4de14312afb57a586d8f59086ec5db0472eb46360dabeff55295`

The deterministic sdist was built twice from a disposable release-intended source export containing `README.md`, `pyproject.toml`, `src/`, and `zero_mem/`. The repository's `.venv` symlinks were excluded as non-release files; the repository itself was not modified.

- `zero_mem-1.2.0.tar.gz`
- SHA-256: `a202827d78c75d9ba449b6d693943b751c4a18f804fcd655e7a2710b63331a54`
- `tar -tzf`: PASS; 481 members.

## Clean-install smoke

- Fresh external wheel venv: install `--no-index --no-deps`, import/version, `zero-mem --version`, `--help`, `setup`, and `doctor`: PASS.
- Fresh external sdist venv: offline install with `--no-index --no-deps --no-build-isolation`, import/version `1.2.0`: PASS.
- Optional Hermes/Corpus/Obsidian warnings were reported as warnings only; no network or system-wide mutation occurred.

## Remote authority

Before publication mutation:

- `github` = `git@github.com:NyanBUIDL/zero-mem.git` (canonical publication remote).
- `origin` = `/home/lenovo/Hermes Workspace/zero-mem-prep-kTxwTi/repo` (preserved prep remote; not a publication target).
- GitHub `refs/heads/master` = `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`.
- `v1.2.0` tag is absent from `github`.
- No remote configuration change was necessary; prep remote was not deleted or overwritten.

## Decision

`FRESH_RELEASE_PREFLIGHT=PASS`. Conditional release workflow may resume under the user's authorization. This report does not itself create a commit, tag, push, GitHub Release, or PyPI publication.
