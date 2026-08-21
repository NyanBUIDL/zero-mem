# V124-05 — Cross-platform and release qualification

Status: NOT_RELEASE_QUALIFIED (locally-executable portion done; cross-OS/Python matrix BLOCKED)
Owner: Lead Delivery Agent
Baseline SHA: 60d7a8feff4ccf000c3f7e8e9f46ec433cbfa9e5
Depends on: V124-01..04 (all IMPLEMENTED_VERIFIED and pushed)

## Authority and problem

- Master plan V124-05: remove POSIX-only assumptions outside the platform backend; verify
  Windows/Linux/macOS on CPython 3.11–3.13; wheel/sdist clean-install + Hermes smoke from the
  candidate SHA; evidence manifest with SHA, commands, environment, logs, checksums, support matrix.
- Exit gate: no unconditional skip for the core path; full suite, security, concurrency, benchmark,
  packaging and E2E pass on every published platform.

## What was executed in THIS environment

- OS: Linux x86_64 only. Python 3.11.16 only. (Windows, macOS, Python 3.12, Python 3.13 are NOT
  installed and cannot be executed here.)
- `python -m compileall -q src zero_mem` -> exit 0 (entire package imports/parses cleanly).
- `tests/unit/test_v122_platform_storage.py` + `tests/integration/test_m5_cross_profile.py` (platform
  tagged) -> 6 passed on Linux.
- Grep of the test tree found NO unconditional `sys.platform`/`skipIf(nt)`/`skipUnless(posix)` skips:
  the core path is not skipped on an unsupported OS (it would simply need to run there).
- `src/storage/platform.py` is the single platform boundary: all `os.name == "nt"` Windows branches are
  localized here; no POSIX-only assumption leaks into capture/projection/read/correction modules.

## What is BLOCKED (cannot be executed here; must run in CI or on the target OS)

- Windows x CPython 3.11 / 3.12 / 3.13
- macOS x CPython 3.11 / 3.12 / 3.13
- Wheel + sdist build from the exact candidate SHA and clean-install + CLI/sidecar/Hermes smoke on each.
- Cross-OS path-attack / symlink / reparse / promotion-cleanup suites (the Windows reparse branch in
  platform.py is not exercised by a Windows run here).
- Secret scan + unintended-file scan across the built artifacts.

## Honesty statement

Per Section 2 and Section 8 of the autonomous prompt, `BLOCKED`/`UNAVAILABLE` must NOT be converted into
`PASS`. The cross-platform matrix is genuinely unexecuted in this environment. Therefore the final
status is **NOT_RELEASE_QUALIFIED** until an authorized operator or CI runs the published matrix and the
release qualification checklist passes. The branch is pushed with completed, verified V124-01..04 work;
V124-05's missing execution is recorded, not forged.
