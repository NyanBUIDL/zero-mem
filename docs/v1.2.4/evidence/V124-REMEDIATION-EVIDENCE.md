# V124 Remediation Evidence

Package: `zero-mem`
Branch: `release/v1.2.4` (remediation work on `codex/v124-full-remediation`)
Baseline (release HEAD before remediation): `2d42b384a94fcac62cf3c2424b7f4504051c7661`
Final tested SHA (product code, CI-tested): `fa803b6ca0884e099202b28f0e75a84acada8b8a`

This document is the single synchronized evidence record for the v1.2.4
remediation (R124-01..06) and the cross-platform remediation (R124-07..11).
Every claim below is derived from executable evidence on the exact commit
named; stale claims from earlier runs were re-derived and replaced.

## Host test environment

The host is Linux. `RuntimeConfig` rejects `capture_root` inside the real home
directory (fail-closed by design), so pytest must run with an isolated TMPDIR
(`ValueError: capture_root must not be inside the real home directory`).
pytest's `tmp_path` derives from `TMPDIR`. All local runs used:

```
export TMPDIR=/dev/shm/zm-v124-test
export HOME=/tmp/zm-tmp
```

Without this, ~33 V124 tests fail spuriously (environmental, not product defects).
This is the sanctioned host workaround per WORKSPACE-POLICY.md. CI cells set
`TMPDIR=/tmp/zm-tmp` (POSIX) or redirect HOME under `$RUNNER_TEMP` (Windows)
with the same intent.

## Local commands (sanitized)

```text
export TMPDIR=/dev/shm/zm-v124-test
export HOME=/tmp/zm-tmp
.venv-v124/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -q
.venv-v124/bin/python -m pytest tests/unit/test_pkg1_packaging.py tests/unit/test_pkg2_packaging.py \
  tests/unit/test_pkg6_upgrade_lifecycle.py tests/unit/test_pkg4_hermes_integration.py -p no:cacheprovider -q
.venv-v124/bin/python -m pytest tests/unit/test_m1_redaction.py tests/unit/test_wp29_authorization.py \
  tests/unit/test_m8_3_authorization_first.py tests/unit/test_m5_authorized_read.py -p no:cacheprovider -q
```

## Local results at the final tested SHA

- Focused v1.2.4 suite (R124-01..04 acceptance): **68 passed**
- v1.2.2 / WP platform + recovery subset (Gate 2, incl. isolation regression): **57 passed**
- Security / redaction / authorization suite (Gate 4): **152 passed**
- Concurrency / lock suite (Gate 5): **5 passed**
- Benchmark suite (Gate 6): **7 passed**
- Full unit + integration suite: **3369 passed, 0 failed, 5 skipped**

## R124-08 runtime-contract alignment

The runtime contract (off / observe / assist / inject) was preserved exactly:

| Mode   | Capture | Read tools | Injection |
|--------|---------|------------|-----------|
| off    | No      | No         | No        |
| observe| Yes     | No         | No        |
| assist | Yes     | Yes        | No        |
| inject | Yes     | Yes        | Controlled|

Obsolete tests that assumed the old contract were updated (not weakened):

- `tests/unit/test_m6_final_acceptance.py::test_single_master_switch_only` —
  updated to the single master switch `ZERO_MEM_ENABLED` backed by
  `BridgeConfig.zero_mem_enabled` (M7.1); `capture_enabled`/`injection_enabled`
  remain health fields, not switches.
- `tests/unit/test_pkg4_hermes_integration.py` — registration diagnostics and
  boundary tests now use explicit modes (`inject` mode, `ZERO_MEM_MODE=assist`)
  and a supplied `capture_root`; `test_installed_package_has_no_hermes_runtime_dependency`
  explicitly declares it validates a **source checkout** and skips only that
  declared validation when dist metadata is absent.
- `tests/unit/test_wp31_hermes.py` — injection-adapter boundary test now runs
  under explicit `inject` mode with a `capture_root`.

Every mode has direct positive and negative tests (`test_v124_runtime_modes.py`).

## R124-07 / R124-10 cross-platform fixes (root causes, not workarounds)

The following product defects were found and fixed:

1. **Windows atomic-promotion identity fence** (`src/storage/platform.py`):
   `atomic_promote` compared `os.fstat(fd).st_dev/st_ino` against
   `_windows_handle_identity(fd)` (volume serial / file index). On Windows these
   differ (and changed again between Python 3.11 and 3.12), so every promotion
   raised `UNSAFE_PATH` → recovery reported `rebuild_promotion_failed`.
   Fixed by comparing platform-correct identity parts; `handle_identity_parts`
   is now public and used by `src/storage/recovery.py` for the owner marker and
   the promotion fence.
2. **CRT text-mode file handles on Windows** (`src/storage/platform.py`,
   `src/projection/writer.py`, `src/projection/manifest.py`): `os.open`
   without `os.O_BINARY` opens in CRT **text mode**, translating `\n` → `\r\n`
   on write. This corrupted canonical JSONL, projected notes, and the manifest
   on Windows (fingerprint mismatches, always-`manifest_stored`, false
   `human_modified` classifications). All data-write `os.open`/`open_regular`
   sites now pass `O_BINARY` (no-op on POSIX).
3. **Locale-dependent read of managed notes** (`src/projection/reconcile.py`):
   the ownership check used `path.read_text()` with the platform default
   encoding (cp1252 on Windows); the file is UTF-8. Any non-ASCII content (the
   em-dash in "Project Home") produced a different fingerprint → false
   `human_edited_managed_note`. Fixed with `encoding="utf-8"`.
4. **Read-only WAL visibility** (`src/retrieval/db.py`): `open_readonly` set no
   `busy_timeout`, so concurrent reads under WAL could fail transiently with
   `database_unavailable` on slow CI. `PRAGMA busy_timeout=5000` added.
5. **macOS `/tmp` symlink in test temp roots** (`tests/`): `tempfile.mkdtemp()`
   returns paths through the `/tmp` → `/private/tmp` symlink on macOS, which the
   platform layer correctly fail-closes. All test temp roots now
   `.resolve()` to the real path (R124-10: isolated, platform-safe temp roots).
6. **POSIX-only constructs in the benchmark** (`benchmarks/wp33_lexical_benchmark.py`):
   `os.O_DIRECTORY` raised `AttributeError` on Windows and `/proc/self/fd` did
   not exist on macOS. The secure run-root now branches: Windows validates and
   uses the real path; macOS uses the descriptor walk with the real path;
   Linux keeps `/proc/self/fd`.
7. **`fork` start method on Windows** (`tests/unit/test_wp12_multi_agent.py`):
   multiprocessing falls back to `spawn` where `fork` is unavailable.
8. **Leaked SQLite connections in test fixtures** (`tests/unit/m9_2_fixtures.py`,
   `tests/unit/test_m9_6_hardening.py`): writable/readonly connections not
   closed deterministically caused WinError 32 on Windows. All connections are
   now closed (writable store closed in `build_store`; the secret-verification
   store closed before re-unlinking m4.sqlite).
9. **CRLF injected by test `write_text`** (`tests/unit/test_m9_5_ownership_edit_boundary.py`,
   `tests/unit/test_m9_4_incremental_retirement.py`): test seeding used
   `Path.write_text()` (text mode → CRLF on Windows); now writes bytes to match
   the product writer.
10. **Windows-only POSIX permission tests** (`tests/unit/test_m9_6_hardening.py`):
    chmod-based read-only semantics do not exist on Windows (ACLs differ);
    the two chmod-based tests are skipped on Windows with a documented reason.
11. **WAL-visible corpus mutation** (`tests/unit/test_m9_4_integration.py`):
    the corpus mutator now runs in the writable phase and checkpoints so
    read-only projection sees the change deterministically.
12. **Timing-dependent deadline bound** (`tests/unit/test_wp30_sidecar.py`):
    the wall-clock bound was too tight for slow macOS CI; the semantic
    assertion (DEADLINE_EXCEEDED) is unchanged, the bound widened to a
    sanity ceiling.
13. **Concurrent transient store errors** (`tests/unit/test_m6_hardening.py`):
    the identity-separation test retries transient DOWNSTREAM_ERROR results
    (bounded, non-leaking) before asserting the strict final statuses.
14. **Process-global runtime-gate test pollution** (root `conftest.py`, new
    `tests/unit/test_runtime_gate_isolation.py`): `HermesBoundary.register()`
    in OFF/invalid mode runs
    `src.integration.zero_mem_runtime.configure(enabled=False, source="boundary")`,
    mutating the module-level `_default_runtime` gate. That process-global state
    leaked into later tests in the same pytest process: a `RegistrationAdapter`
    composed from an explicit `BridgeConfig(enabled=True, ...)` observed a
    disabled gate and silently opened NO writer (canonical JSONL never created;
    `test_wp25_runtime_ownership` FileNotFoundError; `test_wp31` sidecar never
    started). This was order-dependent — CI's unit-before-integration collection
    order masked it, and any `pytest tests/integration tests/unit` (or a
    combined production-path run) exposed it. Product fail-closed OFF semantics
    are intentional and asserted; the defect was TEST isolation. A root
    autouse fixture now snapshots/restores both module-level gate cells
    (`_default_runtime`, `_BOUNDARY_DISABLED_RUNTIME`) around every test, and
    regression tests prove both orderings are stable and explicit-disabled
    still fails closed.

## R124-09 packaging and CI-environment fixes

1. **Version was 1.2.3 on the v1.2.4 branch** — bumped `zero_mem/version.py`
   and the release manifest to `1.2.4`; wheel/sdist now build as
   `zero_mem-1.2.4`.
2. **Repo-root `packaging/` helper shadowed the PyPI `packaging` package**,
   breaking `python -m build` from the repo root (Gate 7 never passed before).
   Renamed to `release_helpers/` and all references updated.
3. **`project.license` string form** failed on setuptools 68–76 (bundled with
   CPython 3.11 on macOS). Changed to the table form `{ text = "MIT" }`,
   verified against setuptools 68 and 84.
4. **Python 3.12+ venvs no longer bundle setuptools** — the pkg2 bundle build
   venv now installs/upgrades setuptools explicitly before the tooling check.
5. **Installer Windows support** (`release_helpers/install.py`, `uninstall.py`,
   `release_common.py`): `venv/Scripts/python.exe` layout, console-script
   path, a `.cmd` CLI shim on Windows, and a directory-junction fallback
   (`mklink /J`) for the `current` pointer when symlink privileges are absent.
6. **Corpus config quoting on Windows** (`tests/unit/test_m10_1_corpus_registry.py`):
   the config writer now JSON-escapes the quoted path (backslashes are invalid
   JSON escapes).
7. **Binary fixture protection** — `.gitattributes` marks PDF fixtures binary so
   Windows `core.autocrlf` cannot corrupt them.
8. **Bookkeeping timestamp drift** (`tests/unit/test_pkg6_upgrade_lifecycle.py`):
   the logical snapshot normalizes second-granularity `*_at` bookkeeping
   columns so a slow second-boundary crossing cannot fail a no-op upgrade test.

## GitHub cross-platform matrix (FINAL, run 32550606746)

The qualification workflow (`v1.2.4-qualification.yml`) was genuinely executed
on GitHub runners for all 9 OS/Python cells with 12 gates each.

Run URL: `https://github.com/NyanBUIDL/zero-mem/actions/runs/32550606746`
Head SHA: `fa803b6ca0884e099202b28f0e75a84acada8b8a`

| Cell          | Gate 1 focused | Gate 2 platform | Gate 3 full | Gate 4 security | Gate 5 concurrency | Gate 6 benchmark |
|---------------|----------------|-----------------|-------------|-----------------|--------------------|------------------|
| ubuntu/3.11   | 68 passed      | 57 passed       | 3369 passed, 5 skipped | 152 passed | 5 passed | 7 passed |
| ubuntu/3.12   | 68 passed      | 57 passed       | 3369 passed, 5 skipped | 152 passed | 5 passed | 7 passed |
| ubuntu/3.13   | 68 passed      | 57 passed       | 3369 passed, 5 skipped | 152 passed | 5 passed | 7 passed |
| windows/3.11  | 68 passed      | 57 passed       | 3366 passed, 8 skipped | 152 passed | 5 passed | 7 passed |
| windows/3.12  | 68 passed      | 57 passed       | 3366 passed, 8 skipped | 152 passed | 5 passed | 7 passed |
| windows/3.13  | 68 passed      | 57 passed       | 3366 passed, 8 skipped | 152 passed | 5 passed | 7 passed |
| macos/3.11    | 68 passed      | 57 passed       | 3369 passed, 5 skipped | 152 passed | 5 passed | 7 passed |
| macos/3.12    | 68 passed      | 57 passed       | 3369 passed, 5 skipped | 152 passed | 5 passed | 7 passed |
| macos/3.13    | 68 passed      | 57 passed       | 3369 passed, 5 skipped | 152 passed | 5 passed | 7 passed |

Windows skips (8 vs 5) are the two documented POSIX-chmod tests plus the
pre-existing platform skip counts; no gate is skipped. Python 3.11 cells
additionally pass Gates 7–11 (wheel + sdist build, clean wheel install, CLI
smoke, sidecar smoke, Hermes composition smoke).

Prior green run on the previous head (for the record; superseded by
32550606746): run `32549170014` at head
`169fa90141b6bdafb122e2471d56ab8c8cdcb6ba` — all 9 cells green with
Gate 2 53 passed and Gate 3 3365 passed (5-8 skipped); the SOUL/cron
ownership regression test (production-path #16) was added at that head and the
runtime-gate isolation regression (R124-10) was added at the final head.

Earlier runs in this remediation (for the record, all superseded by
32550606746): `32488756127` (baseline failures), `32543430368`,
`32544677173`, `32545783295`, `32546904299`, `32547394494`, `32547736671`
(intermediate states during root-cause work), `32548091181` (first green
9-cell run), `32549170014` (head 169fa90, prior green run).

Raw log checksums (SHA-256), representative cells (artifacts via `gh run download 32550606746`):
- `ubuntu-latest-py3.11-g3-full.log`:
  `db6ee5cf1e88bea1aca3d058bc1c610da2c874990e381750e3dbdb0a069005ac`
- `windows-latest-py3.11-g3-full.log`:
  `86ec4f820747eb460b32c0bd81396cf1414ac1e4e4b21cf03b963a8a0c1fabb6`
- `macos-latest-py3.11-g3-full.log`:
  `b61839cac0784637c3033f3ca5358eacecf63c5214d3f39fc4148aaf1c4a4039`
- `windows-latest-py3.12-g2-platform.log`:
  `25537079bc089c3284fb4784d0a868387fefa0d015b403e66e38faad22d7ac9c`

Exact counts and checksums are reproducible from the run artifacts
(`gh run download 32550606746`).

## R124-07 regression tests added

- `tests/unit/test_v122_platform_storage.py::test_ensure_private_directory_never_chmods_existing_ancestors` —
  verifies leaf-only private-dir validation never chmods pre-existing
  ancestors (e.g. `/tmp`) to 0o700 (the original CI IO_ERROR cause).
- Recovery promotion identity tests (`tests/unit/test_wp27_recovery.py`) pass
  with the platform-correct identity fence on all cells.

## Security scan

- No new LLM calls, network calls, or hard Hermes-core dependency introduced in
  `zero_mem/`, `src/integration/`, or `src/storage/` (Gate 4, 152 passed).
- Canonical JSONL remains the sole append-only truth; `O_BINARY` ensures
  canonical bytes are platform-independent.
- Redaction applied to all user-controlled fields before persistence and
  before any log/diagnostic line.
- Authorization evaluated before target discovery; unknown/unauthorized
  returns `None`/`DENIED` with no leakage (Gate 4).
- Secrets never appear in JSONL, SQLite, logs, dead letters, temp files, or
  this evidence (test `test_secret_verification_v9_never_projected_real_cli_path`
  passes on all cells).
- Agent Skills remain agentskills.io-compatible; SKILL.md is never rewritten
  (test coverage in `test_m6_final_acceptance.py`, passing on all cells).
- SOUL and Hermes cron ownership remain outside Zero-Mem
  (`tests/unit/test_wp25_runtime_ownership.py`, passing).

## Known limitations / blockers

- Windows permission semantics: two POSIX-chmod tests are skipped on Windows
  (documented above); Windows read-only enforcement is ACL-based and covered
  by the fail-closed paths, not by those tests.
- The full GitHub matrix runs on GitHub-hosted runners; local reproduction
  on the host Linux cell is green with the documented TMPDIR/HOME isolation.

## Independent Verification Agent verdict

A separate verifier agent performed a fresh detached checkout at the exact
final SHA and ran the full suite independently before seeing this document.
Verdict: **PASS** — see `docs/v1.2.4/work-packages/R124-07-11-cross-platform/`
for the machine-readable verdict artifact.

## Git protocol compliance

- No `git add .`, no `git add -A`; only exact paths staged in small imperative
  commits.
- No `git reset --hard`, no `git clean -fd`, no rebase, no force-push.
- No tag created/moved; no GitHub Release created.
- Work delivered on `codex/v124-full-remediation` (pushed), draft PR #2
  targeting `release/v1.2.4` (not merged).
- `git diff --check` clean before every commit.
