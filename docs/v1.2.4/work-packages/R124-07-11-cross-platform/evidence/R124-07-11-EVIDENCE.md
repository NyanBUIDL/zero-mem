# R124-07..11 — Cross-platform remediation and release qualification (work package evidence)

Package: `zero-mem`
Work package: R124-07 (Windows storage/recovery), R124-08 (runtime contract/legacy
tests), R124-09 (CI/packaging), R124-10 (macOS/Linux isolation), R124-11 (evidence/state)
Branch: `codex/v124-full-remediation`
Baseline full SHA: `2d42b384a94fcac62cf3c2424b7f4504051c7661` (release/v1.2.4 HEAD)
Tested full SHA: `e2825ecb7df80a803a0d0f81c818f5a541bb708a` (CI head, run 32548091181)
Verifier: separate verifier agent (fresh detached checkout) — verdict below
Verifier session/run: run `32548091181` (GitHub Actions) + verifier agent verdict artifact
OS/Python/arch: 9-cell matrix (ubuntu/windows/macos × CPython 3.11/3.12/3.13, x64)

## Exact commands (per gate, as executed by the qualification workflow)

```text
python -m pytest tests/unit/test_v124_runtime_modes.py tests/unit/test_v124_storage_topology.py \
  tests/unit/test_v124_hitl_correction.py tests/unit/test_v124_message_contract.py \
  tests/integration/test_v123_hermes_host_composition.py -q            # Gate 1
python -m pytest tests/unit/test_v122_platform_storage.py tests/unit/test_v122_short_write.py \
  tests/unit/test_wp27_recovery.py tests/unit/test_wp25_runtime_ownership.py \
  tests/unit/test_hermes_registration.py -q                             # Gate 2
python -m pytest tests/unit tests/integration -q                        # Gate 3
python -m pytest tests/unit/test_m1_redaction.py tests/unit/test_wp29_authorization.py \
  tests/unit/test_m8_3_authorization_first.py tests/unit/test_m5_authorized_read.py -q  # Gate 4
python -m pytest tests/unit/test_wp27_concurrency.py -q                 # Gate 5
python -m pytest tests/unit/test_wp33_retrieval.py -q                   # Gate 6
python -m build --wheel --sdist --outdir dist                           # Gate 7 (3.11)
python -m pip install dist/*.whl --target "$RUNNER_TEMP/zm-clean" && python -m zero_mem.cli --version  # Gate 8/9
python -m zero_mem.cli --mode=observe --capture-root "$RUNNER_TEMP/zm-smoke" ...         # Gate 10
python - <<'PY' ... Hermes composition smoke ... PY                                       # Gate 11
```

## Results (run 32548091181, head e2825ecb7df80a803a0d0f81c818f5a541bb708a)

| Cell        | Gate1 | Gate2 | Gate3 full | Gate4 | Gate5 | Gate6 | Gates7-11 (3.11) |
|-------------|-------|-------|------------|-------|-------|-------|------------------|
| ubuntu/3.11 | 68    | 52    | 3364 pass / 5 skip | 152 | 5 | 7 | pass |
| ubuntu/3.12 | 68    | 52    | 3364 pass / 5 skip | 152 | 5 | 7 | — |
| ubuntu/3.13 | 68    | 52    | 3364 pass / 5 skip | 152 | 5 | 7 | — |
| windows/3.11| 68    | 52    | 3361 pass / 8 skip | 152 | 5 | 7 | pass |
| windows/3.12| 68    | 52    | 3361 pass / 8 skip | 152 | 5 | 7 | — |
| windows/3.13| 68    | 52    | 3361 pass / 8 skip | 152 | 5 | 7 | — |
| macos/3.11  | 68    | 52    | 3364 pass / 5 skip | 152 | 5 | 7 | pass |
| macos/3.12  | 68    | 52    | 3364 pass / 5 skip | 152 | 5 | 7 | — |
| macos/3.13  | 68    | 52    | 3364 pass / 5 skip | 152 | 5 | 7 | — |

0 failures, 0 collection errors, 0 skipped jobs on every cell.
Windows skip delta (8 vs 5) = documented POSIX-chmod tests + platform skips.

## Raw log paths / checksums (SHA-256)

Artifacts: `gh run download 32548091181`
- `v124-ubuntu-latest-py3.11-logs/ubuntu-latest-py3.11-g3-full.log`:
  `2c071b82f555e11f0eb22a6ef7344ccadf49a67e695dc9b915fe3797195fe83a`
- `v124-windows-latest-py3.11-logs/windows-latest-py3.11-g3-full.log`:
  `144aa48836ebe78838473636c5d0732a34ae633d41efe68b07d2afcae1d0d9aa`
- `v124-macos-latest-py3.11-logs/macos-latest-py3.11-g3-full.log`:
  `3fc1575ca818a5fbdd21389bbcf493ff3da7ff78bdf72f452d6e9c5cc883068f`
- `v124-windows-latest-py3.12-logs/windows-latest-py3.12-g2-platform.log`:
  `7bf15370fe034da557b86052f708593029f7ac6f5224e5eca0fab5117984174a`

## Security scan result

Gate 4 (152 passed) on all 9 cells; canonical JSONL byte-determinism verified
(O_BINARY); no secret leakage in JSONL/SQLite/logs/temp/evidence; Skills and
SOUL/cron ownership boundaries verified by the runtime-ownership and
hermes-integration suites.

## Root causes fixed (R124-07..10)

See `docs/v1.2.4/evidence/V124-REMEDIATION-EVIDENCE.md` — 13 product/test root
causes, each fixed at the source (Windows atomic-promotion identity, CRT
text-mode handles, locale-default read, WAL busy_timeout, macOS /tmp symlink,
POSIX-only benchmark constants, fork→spawn, leaked SQLite connections, CRLF
test seeding, Windows installer layout/junction/shim, packaging version/license/
tooling, corpus-config quoting, PDF binary fixtures, timestamp drift).

## Known limitations

- Windows read-only permission semantics differ (ACLs); two POSIX-chmod tests
  are skipped on Windows with documented reasons.
- The matrix ran on GitHub-hosted runners; the local Linux cell is green with
  the documented TMPDIR/HOME isolation.

## Final verdict

**PASS** — all required gates pass on all 9 cells at the exact tested SHA;
packaging and clean-install gates pass; evidence and state files synchronized.
`v1.2.4` remains `NOT_RELEASE_QUALIFIED` only pending the merge decision on
PR #2 (draft) and the explicit release gate; no tag/release was created.
