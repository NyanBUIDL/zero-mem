# Zero-Mem v1.2.4 Full Remediation — Completion Handoff

## Metadata

- Package: `zero-mem`
- Branch: `codex/v124-full-remediation` (local + pushed to `github` = NyanBUIDL/zero-mem)
- Baseline (release/v1.2.4 HEAD before remediation): `2d42b384a94fcac62cf3c2424b7f4504051c7661`
- **Final tested product SHA (CI-tested): `fa803b6ca0884e099202b28f0e75a84acada8b8a`**
- **Final branch head (docs-only + verdict artifact): `7ba3b3ffa0444243eedff0ec9eddde15266b0fc5`**
- Product tree identical across both (verified: `git diff --stat fa803b6..HEAD -- . ':!docs' ':!implementation-plan.json' ':!project-state.yaml'` = empty)
- Worktree: `/home/lenovo/Hermes Workspace/zero-mem-v123-engineering`
- Date: 2026-08-22
- Status: **RELEASE_QUALIFIED for all qualification gates**; publication remains operator-owned (PR #2 draft, no tag, no release)

## Executive result

All v1.2.4 qualification gates now pass on the exact final product SHA:

- Windows Gate 2 (platform storage/recovery/path-attack): **PASS** on Python 3.11/3.12/3.13
- Full suite: **PASS** on all 9 OS/Python cells (ubuntu/windows/macos x 3.11/3.12/3.13)
- Security/redaction/authorization, concurrency/lock, benchmark gates: **PASS** on all 9 cells
- Packaging + clean-install + CLI + sidecar + Hermes composition smoke: **PASS** on all three 3.11 cells
- Independent verifier (fresh detached checkout, ran before reading conclusions): **PASS** (machine-readable verdict artifact committed)
- No blocking findings; no v1.2.4 tag created; no GitHub Release created; PR #2 remains draft and unmerged

## Core architecture / data flow

- Canonical memory truth = append-only JSONL under `<capture_root>/canonical/`; SQLite + indexes are derived/rebuildable.
- Runtime modes (off/observe/assist/inject) govern writer-open, capture, read-tool and injection registration:
  `off` no/never; `observe` capture-only; `assist` + authorized reads; `inject` + controlled pre_llm_call.
- `HermesBoundary` composes one `ZeroMemRuntime` (one writer, one derived store, one bounded projection worker).
- Read path: canonical append → projection watermark → authorized read (authorization evaluated before discovery).
- HITL correction: propose (side-effect-free) → confirm → append linked control event → rebuild projection; delete-request tombstones without removing canonical bytes.
- Redaction applied before persistence/log; secrets never enter JSONL/SQLite/logs/temp/evidence.

## Important code/document map

| Block | Path | Responsibility |
|---|---|---|
| CM-STORAGE-001 | `src/storage/platform.py` | O_BINARY data writes, Windows identity fence (`handle_identity_parts`), leaf-only private-dir chmod |
| CM-STORAGE-002 | `src/storage/recovery.py` | Recovery rebuild with platform-correct identity fence |
| CM-STORAGE-003 | `src/storage/jsonl_capture.py`, `src/storage/sqlite_store.py` | Canonical writer / derived store |
| CM-RUNTIME-001 | `src/integration/zero_mem_runtime.py` | RuntimeMode, master gate, single runtime composition |
| CM-RUNTIME-002 | `zero_mem/hermes_integration.py` | `open_hermes_boundary`, mode resolution, OFF gate, `_BOUNDARY_DISABLED_RUNTIME` |
| CM-INTEG-001 | `src/integration/hermes_registration.py` | RegistrationAdapter (consults module-level runtime gate) |
| CM-INTEG-002 | `src/integration/bridge_config.py` | BridgeConfig, capture_root safety |
| CM-PROJ-001 | `src/projection/writer.py`, `manifest.py`, `reconcile.py` | Derived notes/manifest, UTF-8 fingerprint |
| CM-RETR-001 | `src/retrieval/db.py` | Read-only store with busy_timeout |
| CM-PKG-001 | `release_helpers/` (renamed from `packaging/`) | Install/uninstall/build tooling |
| CM-DOC-001 | `docs/v1.2.4/evidence/V124-REMEDIATION-EVIDENCE.md` | Single synchronized evidence record |
| CM-DOC-002 | `docs/v1.2.4/work-packages/R124-07-11-cross-platform/evidence/` | WP evidence + machine-readable verifier verdict |
| CM-STATE-001 | `implementation-plan.json`, `project-state.yaml`, `docs/v1.2.4/MASTER_PLAN.md`, `COMPATIBILITY.md` | State files (synchronized to fa803b6/32550606746) |

## Work completed (with evidence)

- **R124-07 Windows storage/recovery**: fixed O_BINARY CRT text-mode corruption, Windows atomic-promotion identity fence, leaf-only chmod (no EPERM on `/tmp`), recovery identity parts.
- **R124-08 runtime contract**: off/observe/assist/inject matrix preserved; obsolete legacy tests updated (not weakened); every mode has direct positive/negative tests.
- **R124-09 packaging/CI**: version 1.2.3→1.2.4; `packaging/`→`release_helpers/` (PyPI shadow); license table form; Windows installer layout/junction/shim; corpus-config quoting; PDF binary attributes; timestamp normalization.
- **R124-10 macOS/Linux isolation**: macOS /tmp symlink resolve; fork→spawn; leaked SQLite connections closed; CRLF test seeding fixed; WAL busy_timeout; **NEW: process-global runtime-gate test pollution fixed** (root `conftest.py` autouse fixture + `tests/unit/test_runtime_gate_isolation.py`; proven failing without fixture, green with it, both file orders stable).
- **R124-11 evidence/state**: all evidence re-derived from run `32550606746` (head fa803b6) with fresh SHA-256 checksums; state files synchronized; independent verifier verdict committed.

## CI runs (all 9 cells green, identical counts)

- `32550606746` at fa803b6 — primary qualification run (product code)
- `32551024972` at c519d43 — docs-only head re-qualification
- `32551282933` at 7ba3b3f — final head re-qualification

Matrix (every cell): Gate 1 68 | Gate 2 57 | Gate 3 3369 (POSIX) / 3366 (Windows), 5-8 skipped | Gate 4 152 | Gate 5 5 | Gate 6 7; Gates 7-11 pass on 3.11 cells.

## Local verification (Linux x86_64, CPython 3.11.16, TMPDIR=/dev/shm/zm-v124-test HOME=/tmp/zm-tmp)

- Gate 1: 68 passed; Gate 2: 57 passed; Gate 4: 152 passed; Gate 5: 5 passed; Gate 6: 7 passed
- Full suite: 3369 passed, 5 skipped, 0 failed
- Clean wheel install from site-packages: `zero-mem 1.2.4`; CLI --version/--help OK; sidecar smoke OK; Hermes composition smoke OK (capture→projection→read)

## Risks / known limitations

- Windows read-only permission semantics are ACL-based; two POSIX-chmod tests are skipped on Windows with documented reasons (unchanged, documented).
- Windows-built wheel contains CRLF in `.py` files (git autocrlf on runner checkout); content identical after normalization — wheel bytes are not byte-identical across OS, only functionally identical. Canonical JSONL IS byte-identical (O_BINARY).
- The 9-cell matrix ran on GitHub-hosted runners; local reproduction is green on the Linux host cell with documented TMPDIR/HOME isolation. Windows/macOS cells were not reproduced on local hardware (no local Windows/macOS available).
- `project-state.yaml` `v124_release_qualified: false` reason text was updated to reference fa803b6; the operator must flip publication status at release time (per policy, publication requires separate authorization).

## Next steps (in dependency order, operator-owned)

1. Review draft PR #2 (`codex/v124-full-remediation` → `release/v1.2.4`), merge decision.
2. After merge: verify release SHA invariant (`MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA`) per GITHUB-POLICY.md §5.
3. Create immutable tag `v1.2.4` only after qualification + operator authorization.
4. Build artifacts from the exact tag SHA; verify hashes; create GitHub Release.
5. Update `project-state.yaml` publication status at that point.

## Authorization status

- Implementation: authorized (remediation prompt, additive commits only).
- Git publication: push of `codex/v124-full-remediation` authorized and completed; draft PR #2 exists (OPEN, MERGEABLE, head = 7ba3b3f).
- NOT authorized / NOT performed: merge, tag creation, GitHub Release, force-push, rebase, reset, history rewrite, `git add .`.
- No v1.2.4 tag exists; no GitHub Release for v1.2.4 exists.

## Self-check

- `git diff --check` clean at final head and before every commit.
- Working tree clean at final head.
- Evidence references fa803b6 as tested product SHA and run 32550606746; state files agree (implementation-plan.json, project-state.yaml, MASTER_PLAN.md, COMPATIBILITY.md, evidence files).
- Independent verifier verdict artifact committed and JSON-valid (verdict PASS).
- 16 production-path checks all PASS (verifier) + combined local run (216 passed, incl. previously-failing pollution combination).
