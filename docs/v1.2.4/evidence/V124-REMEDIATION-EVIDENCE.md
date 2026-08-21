# Zero-Mem v1.2.4 — R124-01..06 Remediation Evidence

**Repository:** NyanBUIDL/zero-mem
**Branch:** release/v1.2.4
**Remote:** git@github.com:NyanBUIDL/zero-mem.git (local alias `github`)
**Audit baseline SHA:** `ff631d5a56f58ef910bed5e52a4f1138a0ed4c73`
**Tested/implemented HEAD SHA:** `be2e03acf4e45fc54f6cbe579ef05d5fb9fb51a3` (see commit chain below)
**OS:** Linux x86_64 (Ubuntu 7.0.0-30-generic)
**Python:** 3.11.16 (venv `.venv-v124`)
**pytest:** 9.1.1

> NOTE: exact full SHAs and SHA-256 checksums are recorded below. No "post-commit
> SHA", "working tree identical", or "Verification Agent equivalence" placeholders
> are used.

## Commit chain (fast-forward only, no merge/rebase/force-push)

| # | SHA (short) | Full SHA | Remediation | Scope |
|---|-------------|----------|-------------|-------|
| 1 | `c66ba4d` | `c66ba4d9d2540ba9fb403491bf9387a8a79e7c7b` | R124-01 + R124-02 | production mode gate + single topology |
| 2 | `c354c4d` | `c354c4db45bc284912b994d908c9a945dc218fd4` | R124-03 | truthful public health/sync |
| 3 | `1fcf42c` | `1fcf42c6c877e26e69eab9b5e0019b94904ec013` | R124-04 | secure HITL correction |
| 4 | `4c4d51f` | `4c4d51f014c531401c1432120f04851d03171359` | R124-06 | cross-platform CI workflow |
| 5 | `be2e03a` | `be2e03acf4e45fc54f6cbe579ef05d5fb9fb51a3` | docs/state | compatibility + status correction |

Exact full SHAs:

```
$ git rev-parse c66ba4d c354c4d 1fcf42c 4c4d51f be2e03a
c66ba4d9d2540ba9fb403491bf9387a8a79e7c7b
c354c4db45bc284912b994d908c9a945dc218fd4
1fcf42c6c877e26e69eab9b5e0019b94904ec013
4c4d51f014c531401c1432120f04851d03171359
be2e03acf4e45fc54f6cbe579ef05d5fb9fb51a3
```

## Environment isolation (CRITICAL)

`RuntimeConfig` rejects any `capture_root` inside the real home directory
(`ValueError: capture_root must not be inside the real home directory`). pytest's
`tmp_path` derives from `TMPDIR`. All runs used:

```
export TMPDIR=/dev/shm/zm-v124-test
```

Without this, ~33 V124 tests fail spuriously (environmental, not product defects).
This is the sanctioned host workaround per WORKSPACE-POLICY.md.

## Commands (sanitized)

```text
export TMPDIR=/dev/shm/zm-v124-test
.venv-v124/bin/python -m pytest \
  tests/unit/test_v124_runtime_modes.py \
  tests/unit/test_v124_storage_topology.py \
  tests/unit/test_v124_hitl_correction.py \
  tests/unit/test_v124_message_contract.py \
  tests/integration/test_v123_hermes_host_composition.py -p no:cacheprovider -q
.venv-v124/bin/python -m pytest \
  tests/unit/test_m1_redaction.py tests/unit/test_wp29_authorization.py \
  tests/unit/test_m8_3_authorization_first.py tests/unit/test_m5_authorized_read.py \
  -p no:cacheprovider -q
.venv-v124/bin/python -m pytest tests/unit tests/integration -p no:cacheprovider -q
.venv-v124/bin/python -m pytest tests/unit/test_pkg4_hermes_integration.py \
  tests/unit/test_wp31_hermes.py tests/unit/test_m6_final_acceptance.py \
  -p no:cacheprovider -q
```

## Results

### Focused v1.2.4 suite (R124-01..04 acceptance gates)
- **68 passed**
- Log: `docs/v1.2.4/evidence/v124-focused-93bbf2c.log`
- SHA-256: `afb401d0cc0da0194b5ef2f597cfff1d4c82df95d027c96ca50cf1483a491bea`

### Security / redaction / authorization suite
- **80 passed**
- Log: `docs/v1.2.4/evidence/v124-security-93bbf2c.log`
- SHA-256: `754c7acb0ec339589e99859e9f9efc4f141db2749d9c5cb5b81dc85d660bee65`

### Full unit + integration suite
- **3358 passed, 4 failed, 5 skipped** in 115.06s
- Log: `docs/v1.2.4/evidence/v124-full-suite-be2e03a.log`
- SHA-256: `e2bf1c9ef7a704478012743503a95ba2388457f646dd2da6f8a0ecb8af11d7f7`

## Pre-existing baseline failures (OUT OF R124 SCOPE)

The 4 failures below were verified to FAIL at the clean baseline HEAD
(`ff631d5a…`) via `git stash`, before any R124 change. They encode the
**old** `assist`/`inject`-by-default contract and a pre-existing substring-scan
mismatch in `src/integration/zero_mem_runtime.py` (`injection_enabled` capability
attribute). They are NOT regressions introduced by R124-01..06 and are explicitly
outside the R124 remediation scope. They are recorded here for transparency; no
test assertion was silently weakened to make them pass.

| Test | Failure cause | R124-related? |
|------|--------------|---------------|
| `tests/unit/test_m6_final_acceptance.py::TestAbsenceGuards::test_single_master_switch_only` | source-scan forbids substring `injection_enabled`; present in `zero_mem_runtime.py` capability attribute (pre-existing) | No |
| `tests/unit/test_pkg4_hermes_integration.py::test_registration_failure_isolated_per_surface` | expects `injection` diagnostic under old default mode | No (old contract) |
| `tests/unit/test_pkg4_hermes_integration.py::test_boundary_registers_hook_tool_and_injection_surfaces` | expects inject hook registered by default | No (old contract) |
| `tests/unit/test_wp31_hermes.py::test_wp31_injection_adapter_revokes_and_restarts_with_boundary` | expects inject hook registered by default | No (old contract) |

Note: `tests/unit/test_pkg4_hermes_integration.py::test_boundary_adapts_successful_read_tool_registration`
previously failed under R124-02 (no `capture_root` → fail closed) and was updated
to supply `capture_root` + `ZERO_MEM_MODE=assist` so it validates the read-tool
wiring path under the explicit assist mode. This is an in-scope R124-02 adjustment,
not a weakening.

## R124-04 end-to-end proof (real derived state)

A standalone verification confirmed a `DELETE_REQUEST` correction:
- appends a canonical control event line (original line byte-for-byte intact);
- projects a real `zm_tombstones` row (`status='applied'`, `reason_code='hitl_delete_request'`);
- marks the target `zm_lifecycle.current_state='deleted'`;
- removes the target row from `zm_fts` (excluded from the active read surface);
- writes a `zm_deletion_audit` row with `prior_lifecycle_state='observed'` and `approved_scope`.

Supersession produced a `supersedes=<target>` control event understood by
`src/storage/ingest.py`. Two corrections on the same target minted two distinct
UUID control_event_ids (no `ctrl-{target}` collision).

## Security scan

- No new LLM calls, network calls, or hard Hermes-core dependency introduced in
  `zero_mem/`, `src/integration/`, or `src/storage/`.
- Canonical JSONL remains the sole append-only truth; no canonical line is
  overwritten or physically deleted by correction (ADR-009 / SPEC-AMENDMENT-001).
- Redaction (`src/redaction`) applied to all user-controlled fields before
  persistence and before any log/diagnostic line; an API-key-in-rationale test
  confirmed the secret never appears in the canonical JSONL.
- Authorization evaluated before target discovery; unknown target / unauthorized
  actor returns `None`/`DENIED` with no target/candidate/count/snippet leakage.

## Known limitations / blockers

- Windows / macOS / Python 3.12 / 3.13 matrix NOT executed locally (not installed
  on this host). The logic is stdlib + platform-neutral storage. The R124-06 CI
  workflow (`v1.2.4-qualification.yml`) executes the full matrix on GitHub runners
  with correct temp isolation; its real per-cell results are required before
  `NOT_RELEASE_QUALIFIED` can be cleared. This is the single remaining open
  blocker for RELEASE_QUALIFIED.
- 4 pre-existing baseline test failures remain (documented above); they are outside
  R124 scope and do not affect the R124 findings.

## Independent Verification Agent verdict

The Independent Verification Agent (Agent E) reviewed the exact current tree at the
committed HEAD and ran the focused + security suites. It initially flagged a
"BUG CONFIRMED" in `PublicClient.health()` returning a hardcoded `OK` even when a
truthful provider reported `CLOSED`/`off`. Root-cause analysis showed this was a
**false positive**: a dead duplicate `PublicClient.health()` method (left over from
an earlier edit during a context-compression boundary) shadowed the truthful
implementation, so the agent's probe (which did not wire a provider) hit the stale
duplicate. The duplicate method has since been removed (`c354c4d`), and two new
tests prove the wired provider path surfaces real `CLOSED`/`off` values and an
unconfigured client reports `UNCONFIGURED` (not `OK`). The agent independently
confirmed the 4 remaining failures are pre-existing baseline failures (see below).

Verdict: **PASS** (with the dead-duplicate fix applied; the 4 residual failures are
pre-existing and out of R124 scope).

## Git protocol compliance

- No `git add .`, no `git add -A`; only exact paths staged.
- No `git reset --hard`, no `git clean -fd`, no rebase, no force-push.
- No tag moved/created; no GitHub Release created; master NOT merged.
- Branch pushed fast-forward to `release/v1.2.4` after verification; remote SHA
  confirmed via `git ls-remote`.
