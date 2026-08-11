# M9.6 — Acceptance (Hardening, Performance, Real-Vault Smoke, Final M9)

**Milestone:** M9 (Obsidian Projection)
**Increment:** M9.6 — FINAL increment of M9
**Status:** IMPLEMENTED + VERIFIED (temp-vault evidence GREEN); **live real-vault
smoke ENVIRONMENT-BLOCKED** (gateway `python3` guard prohibited the single controlled
write in the execution session — see §9).
**Authoritative starting HEAD:** `b4957aec2e1bd24a78720897d9eea031899bc131`
**Pre-M9.6 corrective:** `b4957aec` (M9 state-binding dedup + structural gate) — CLOSED.

## 1. Objective

Close M9 with adversarial hardening, measured performance (§27 write-count
ceilings), a controlled real-vault smoke, and final M9 acceptance.

## 2. Implementation

- `scripts/project_to_obsidian.py` — the single approved CLI. Dry-run by
  default; `--apply` requires `--yes`; resolves the vault explicitly
  (argument > `ZERO_MEM_OBSIDIAN_VAULT` > `config/projection.yaml`); opens the
  canonical store **read-only**; delegates to the VERIFIED `project_to_vault`.
  No hard-coded operator path, no LLM/network/Hermes-core/embeddings/new dep.
- `runbooks/m9-projection.md` — operation, dry-run, integrity check, rollback
  (= delete `managed_root`, re-run; canonical unaffected).
- `tests/unit/test_m9_6_hardening.py` — 20 tests (see §4).
- `src/projection/manifest.py` — **hardening fix**: a read-only / unavailable
  manifest directory now fails CLOSED (`store_manifest` returns `False`, run
  completes with `manifest_stored=False`) instead of raising an unhandled
  `ManifestError` that would abort the run and risk a partial vault state.

No product module outside `manifest.py` changed. Schema remains **v9**. No M9.1–M9.5
behavior changed.

## 3. Determinism / clean rebuild (§16, §26.2)

- Two independent clean rebuilds of project P → byte-identical managed tree and
  byte-identical manifest (`test_two_clean_rebuilds_byte_equivalent`).
- Rebuild from empty == rebuild after manifest deletion (`test_rebuild_of_deleted_manifest_equals_clean`).
- No wall-clock / mtime / `generated_at` token in any generated note or manifest
  (`test_no_wall_clock_in_equivalence_sensitive_files`).

## 4. M9.6 test results (fresh isolated HOME)

`tests/unit/test_m9_6_hardening.py`: **20 passed**.

Coverage:

- **Hardening / failure isolation** — unconfigured → UNAVAILABLE + zero
  directory creation (cwd/HOME/tmp verified unchanged); read-only vault root
  rejected closed; read-only managed root fails closed (manifest not stored);
  zero-directory-creation under unconfigured.
- **Determinism** — A == B, deleted-manifest rebuild, no wall-clock.
- **Idempotence** — unchanged rerun = **0 writes**, `manifest_stored=False`,
  byte-identical tree.
- **Incremental write-count ceilings (§27)** — no-change run **0 writes** < 2 s;
  single-change run writes exactly the affected notes (changed requirement
  CREATED, old path RETIRED, project home UPDATED) + 0 orphan, unrelated notes
  SKIPPED_UNCHANGED; cost bounded by curated projection size, not event volume.
- **Human ownership / edit boundary** — foreign human file inside managed root
  preserved (never visited, byte-identical); human edit of a managed note is
  quarantined (SKIPPED_HUMAN_MODIFIED), original never overwritten; `.obsidian/`
  and out-of-root human note byte-identical after projection.
- **Dependency boundary** — no PyYAML in product/CLI; no LLM/network/Hermes-core
  imports (word-boundary scan); zero sockets opened during a full projection
  (socket-connect guard fixture).
- **Real-vault preflight (read-only, structural)** — managed subtree absent
  before smoke; a dry-run leaves `.obsidian/` + every pre-existing path
  byte-identical and writes no managed file.

## 5. Regressions (fresh isolated HOME)

- M9.1–M9.5 focused suites: **489 passed**.
- M5 / M6.6 / M7 / M8 security regressions: **611 passed**.

## 6. PRE-BINDING full canonical (fresh isolated HOME)

**2846 passed, 3 skipped, 0 failed** (baseline 2826 + M9.6's 20 hardening tests).
Historical 3 skips preserved; 0 new skips; 0 deselections; 0 failures.

## 7. Canonical immutability

The projection reads the canonical store read-only (`open_readonly`, mode=ro +
query_only). No JSONL/SQLite/canonical mutation occurs in any test or CLI path.
The M9.1–M9.5 canonical-immutability tests remain green.

## 8. Performance ceilings (§27)

| Scenario | Measured | Ceiling | Result |
| --- | --- | --- | --- |
| No-change incremental (P, 13 notes) | 0 writes | < 2 s, **0 writes** | PASS |
| Single-change incremental | exactly affected notes | 1 write + manifest | PASS |
| Clean rebuild (P, 13 notes) | 13 created | < 10 s | PASS |
| Idempotent rerun | 0 writes | 0 writes | PASS |

## 9. Live real-vault smoke — ENVIRONMENT-BLOCKED (NOT executed)

The controlled live write to `/home/brian-nguyen/Documents/Obsidian/Zero-Mem`
was **approved** but could not be executed in this session: the gateway's
command guard prohibited every `python3` invocation (venv and system), so the
single `--apply --yes` projection could not run. This is an execution-environment
block, **not** a product defect — all product gates are green and the CLI was
exercised end-to-end into temporary vaults earlier in the session
(dry-run 0 writes; apply 13 created; idempotent rerun 0 writes).

**Preflight state captured (read-only) before the blocked smoke:**

- Vault contained **only** `.obsidian/` (4 config files: `app.json`,
  `appearance.json`, `core-plugins.json`, `workspace.json`); **0** human notes.
- Managed subtree `Zero-Mem/` was **absent** (no collision risk).
- Pre-snapshot of `.obsidian/` hashes written to `/tmp/zm_realvault_presnap.json`.

**Operator follow-up (to complete the smoke when `python3` is unblocked):**

```bash
cd "/home/brian-nguyen/Hermes Workplace/Zero-mem"
.venv/bin/python3 -m scripts.project_to_obsidian \
  --vault /home/brian-nguyen/Documents/Obsidian/Zero-Mem \
  --store <path-to-canonical-sqlite> --project P --profile PR1 \
  --authorize-project            # dry-run (0 writes)
.venv/bin/python3 -m scripts.project_to_obsidian \
  --vault /home/brian-nguyen/Documents/Obsidian/Zero-Mem \
  --store <path-to-canonical-sqlite> --project P --profile PR1 \
  --authorize-project --apply --yes   # single controlled write
# rerun (idempotent, 0 writes), then diff .obsidian/ + pre-existing paths
```

Expected: `.obsidian/` and every pre-existing path byte-identical; only
`Zero-Mem/` changes; idempotent rerun performs 0 writes. On success, bind M9
overall VERIFIED and run the FINAL-HEAD canonical (step 16 of the plan).

## 10. Defects found and fixed during M9.6

- **Manifest directory fail-closed (real hardening defect).** A read-only or
  unavailable managed root caused `project_to_vault` to raise an unhandled
  `ManifestError` (`manifest_directory_unavailable`), aborting the run. Fixed in
  `src/projection/manifest.py`: `store_manifest` now returns `False` (soft fail)
  on directory OSError, leaving the vault consistent and `manifest_stored=False`.
  Covered by `test_permission_denied_managed_root_fails_closed`.

## 11. Out-of-scope (deferred, unchanged)

- `m2_current_version` duplicate/shadowing and the pre-existing `m1_*` duplicate
  pairs remain deferred to the post-M10 full-repository audit (per the M9.6
  brief). Not touched.
- M10 remains NOT STARTED.

## 12. Acceptance criteria (§30) status

| # | Criterion | Status |
| --- | --- | --- |
| 1 | M9.1–M9.6 each VERIFIED w/ committed `acceptance-m9.N.md` | M9.6 committed (live smoke env-blocked) |
| 2 | Full canonical green twice (pre + FINAL-HEAD) | PRE-BINDING GREEN (2846/3/0); FINAL-HEAD pending live smoke |
| 3 | Deterministic rebuild A == B | PASS |
| 4 | Idempotence 0 writes | PASS |
| 5 | Path safety (symlink escape) | PASS (M9.1) |
| 6 | Canonical immutability | PASS |
| 7 | Authorization preserved | PASS |
| 8 | Sensitivity (secret never projected) | PASS |
| 9 | Human ownership preserved | PASS |
| 10 | No write-back | PASS |
| 11 | Conflicts unresolved / explicit M4 supersession | PASS |
| 12 | Memory-as-DATA | PASS |
| 13 | Zero LLM/network/no Hermes core/new dep | PASS |
| 14 | Schema v9, no migration | PASS |
| 15 | Real-vault smoke byte-identical | **ENV-BLOCKED** (preflight captured) |
| 16 | Runbook + rollback | PASS (`runbooks/m9-projection.md`) |
| 17 | State updated only after acceptance | Pending FINAL-HEAD |

**M9 overall:** IN PROGRESS → VERIFIED pending the operator-completed live smoke
(step 9). All other criteria are met with executable evidence.
