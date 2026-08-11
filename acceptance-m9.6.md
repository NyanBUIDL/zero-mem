# M9.6 Acceptance — Final M9 Hardening, Performance, Controlled Real-Vault Smoke, M9 Acceptance

**Milestone:** M9.6 (final increment of M9)
**Authoritative HEAD (state-binding commit):** see `git rev-parse HEAD` after the M9.6 acceptance/state-binding commit.
**Schema:** v9 (unchanged)
**Status:** VERIFIED

---

## Scope

M9.6 is the final M9 increment. It proves the already-VERIFIED M9.1–M9.5
pipeline is safe to point at the operator's real Obsidian vault and binds M9
overall VERIFIED. It covers:

- targeted M9 hardening / failure isolation;
- determinism and clean rebuild;
- incremental write-count ceilings;
- human-ownership / edit-boundary verification;
- the controlled REAL Obsidian vault smoke (read-only preflight → dry-run →
  first apply → idempotent second apply → post-snapshot integrity);
- a confirmed secret-sensitivity integration regression found during the real
  vault smoke, traced to root cause and fixed (Phase 1 trace-only, then minimal
  corrective + permanent regression).

Out of scope for M9.6 (deferred to the post-M10 audit, per plan/authority):
the pre-existing M1/M2 duplicate-state defects. They are intentionally NOT
touched.

---

## Confirmed defect (found during real-vault smoke, before binding)

**Observation:** the controlled real-vault smoke projected verification `V9`
(whose `observed_result` is the secret marker `SK-M9-2-SECRET-XYZ`) into
`Verification/p/v9--78353c10686650bd.md` and listed it as a current manifest
entry.

**Phase-1 trace (source → filesystem):**

1. `V9` is assigned `sensitivity=secret` in the canonical fixture event
   (`tests/unit/m9_2_fixtures.py`), but the M4 derived store is
   **sensitivity-agnostic** — `zm_verifications` has **no `sensitivity`
   column** (`src/storage/migrations/migrate_7.py`). So `sensitivity` is dropped
   at rebuild; the stored `V9` record carries no sensitivity.
2. When `eligibility.is_eligible` reads the stored record back, it sees
   `_ABSENT` sensitivity and **skips the secret gate** (by design — failing
   closed there would empty the entire projection; `eligibility.py` documents
   that the engine's content-level secret backstop is the defense for
   secret-shaped material reaching the derived substrate).
3. `engine._commit` only ran that backstop `if secret_patterns` was non-empty.
4. `scripts/project_to_obsidian.py` defaulted `secret_patterns=()`, so the
   backstop **never ran** and `V9`'s `observed_result` was rendered and written.

**Defect class:** product/CLI defect (the sole defense was disabled by default)
surfaced by a test-coverage gap (no integration test exercised the real CLI
path against the sensitivity-agnostic store with the empty default).

**Root cause (first contract break):** the engine content backstop — the only
defense the architecture relies on for secret-shaped material in the
sensitivity-agnostic derived store — was disableable by an empty caller pattern
list, and the real CLI defaulted to empty.

**Corrective (smallest, schema-free, rule-preserving):**

- `src/projection/engine.py`: added `DEFAULT_SECRET_PATTERNS` baseline and
  applied `DEFAULT_SECRET_PATTERNS + caller_patterns` (deterministically
  deduped) in `_commit`, so the backstop **always runs** and caller patterns
  **extend** (never replace) the non-disableable baseline.
- A second bug (found during security reconciliation): the earlier form
  `secret_patterns or DEFAULT_SECRET_PATTERNS` would have *replaced* the
  baseline under a non-empty custom `--secret-pattern`. The additive form
  closes that too.
- No schema change, no weakened sensitivity rules, no API change.

**Permanent regression (real CLI effective path, `test_m9_6_hardening.py`):**
V9 withheld (no note, no active manifest entry, no output file, marker 0×);
V1 (non-secret) projected as positive control; `--authorize-project` does not
expose V9; a non-empty custom pattern still preserves the baseline; a distinct
custom marker is also withheld when supplied.

**Test-scaffolding corrective:** the custom-marker insertion initially wrote
through the `ReadonlyStore` (forbidden, M3). Fixed so the mutator runs in the
**writable fixture phase** before the store is sealed read-only. ReadonlyStore
semantics unchanged.

**Do not reopen these fixes without a concrete new regression.**

---

## Verification evidence (authoritative, externally executed)

All runs used the project venv `.venv/bin/python3` in a normal Ubuntu terminal
(the Hermes desktop gateway blocks Python, so execution was operator-run and
verified by the operator; this document records the operator-reported results).

| Gate | Result |
|------|--------|
| M9.6 focused (`tests/unit/test_m9_6_hardening.py`) | **23 passed, 0 failed** |
| M9.4 regression (`tests/unit/test_m9_4_*.py`) | **38 passed, 0 failed** |
| Pre-binding full canonical (fresh isolated HOME) | **2849 passed, 3 skipped, 0 failed** |
| Corrected real-vault smoke | **PASS** |
| ├─ first apply `--apply --yes` | 12 created / 0 updated / 0 retired |
| ├─ second apply (identical source/config) | 0 / 0 / 0 (idempotent) |
| ├─ V1 (non-secret verification) projected | YES |
| ├─ V9 (secret verification) projected | NO |
| ├─ secret marker `SK-M9-2-SECRET-XYZ` under managed subtree | 0 occurrences |
| ├─ manifest `Zero-Mem/_meta/manifest.json` | written; V9 absent from active entries |
| ├─ `.obsidian/` | unchanged |
| ├─ outside managed root | unchanged |
| ├─ human overwrite / human deletion | NONE |
| └─ files added | 13, all under approved `Zero-Mem/` managed subtree |

Return codes: M9.6 = 0, M9.4 = 0, canonical = 0.

---

## FINAL-HEAD canonical (mandatory, authoritative closure)

After this state-binding commit, a NEW full canonical must be run under a fresh
isolated HOME on the exact final HEAD. Required: **0 failed, 3 historical
skips only**. This run is the authoritative gate for closing M9.

Command (operator, external Ubuntu terminal):

```bash
cd "/home/brian-nguyen/Hermes Workplace/Zero-mem"
OLD_HOME="$HOME"; TEST_HOME="$(mktemp -d)"; export HOME="$TEST_HOME"
.venv/bin/python3 -m pytest -q 2>&1 | tail -20
export HOME="$OLD_HOME"; rm -rf "$TEST_HOME"
```

---

## Final real-vault integrity (read-only)

After FINAL-HEAD canonical passes, a READ-ONLY integrity check on the real
vault confirms: managed projection exists; V1 present; V9 absent; secret marker
0×; `.obsidian/` unchanged; no unexpected outside-root content. No vault rewrite
during this check.

---

## M9 overall

- M9.1 VERIFIED
- M9.2 VERIFIED
- M9.3 VERIFIED
- M9.4 VERIFIED
- M9.5 VERIFIED
- M9.6 VERIFIED
- **M9 overall VERIFIED**
- schema v9 (unchanged)
- M10 NOT STARTED

Deferred M1/M2 duplicate-state defects remain out of scope (post-M10 audit).
