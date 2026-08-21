# V124-05 Evidence — Cross-platform and release qualification

## Environment where this was produced

- OS: Linux x86_64 (Ubuntu 7.0.0-30-generic)
- Python: 3.11.16
- pytest: 9.1.1
- Candidate SHA: 60d7a8feff4ccf000c3f7e8e9f46ec433cbfa9e5 (V124-04 tip)

## Commands run (sanitized)

```text
python -m compileall -q src zero_mem
python -m pytest tests/ -k platform -q
grep -rnE "sys.platform|skipIf.*nt|skipUnless.*posix" tests/   # found no unconditional skips
```

## Results (executed here)

- `compileall src zero_mem`: exit 0
- platform-tagged tests (test_v122_platform_storage.py, test_m5_cross_profile.py): 6 passed on Linux
- No unconditional platform-skip decorators in the test tree
- Platform boundary isolated in `src/storage/platform.py` (Windows/POSIX branches via `os.name == "nt"`)

## Results NOT executable here (reported honestly, not forged)

- Windows / macOS x CPython 3.11/3.12/3.13 matrices
- Wheel + sdist build, clean-install, CLI/sidecar/Hermes smoke on each OS
- Cross-OS path-attack / symlink / reparse suites
- Artifact SHA + SHA-256 checksum reconciliation

## Verdict: NOT_RELEASE_QUALIFIED (cross-OS matrix BLOCKED)

The branch carries completed, verified V124-01..04. V124-05's release gate requires execution on
platforms unavailable in this environment. It must be run by CI / an authorized operator before any
GitHub Release is cut. No tag, release, merge, or force-push was performed.
