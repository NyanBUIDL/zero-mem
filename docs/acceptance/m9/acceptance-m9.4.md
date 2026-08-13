# Acceptance — M9.4: Deterministic manifest + incremental update + safe stale retirement

**Milestone:** M9 — Obsidian Knowledge Workspace projection
**Increment:** M9.4 — Manifest (authoritative projection state) + Deterministic rebuild + Incremental update (zero-write rerun) + Safe stale retirement (three-signal ownership)
**Status:** VERIFIED
**M9 overall:** IN PROGRESS
**Schema version:** 9 (unchanged — no migration)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §12, §14, §14.3, §15.1, §16.5, §19, §21, §29 Q1/Q11; `plan-m9.md` §12.1 (three-signal ownership), §14.3 (reconcile decision tree), §15.1 (manifest), §16.5 + §19 (human-edit boundary, fail-safe), §861 (M9.4 scope); `acceptance-m9.1.md`, `acceptance-m9.2.md`, `acceptance-m9.3.md`; `AGENTS.md`

---

## 1. Commit binding

| Item | Value |
| --- | --- |
| Starting HEAD (M9.3 acceptance) | `c51ee6ea9a4a77806b2ad46099d3600b2a0b3145` |
| Implementation / tested commit (M9.4 product + tests) | `c4ef440e0619aec59ca9b3b1b73d2c2696c067a1` |
| Evidence / state-binding commit | recorded in §12 below |
| Final HEAD (after state binding) | recorded in §12 below |
| Schema version | 9 (no migration, no new table) |
| Hermes core changes | NONE |

---

## 2. Scope delivered

M9.4 adds the deterministic lifecycle layer over the VERIFIED M9.1–M9.3 projection: a manifest that is the authoritative *record* of projected state, a deterministic rebuild, an incremental update that suppresses unchanged writes, and a safe stale-retirement path guarded by the three-signal ownership rule (plan-m9.md §12.1). It **creates, resolves, ranks, or infers nothing** about source truth; the manifest is consulted only as a DATA input to the ownership proof, never as a source of authorization, visibility, or truth (plan-m9.md §14 / §22).

- **Manifest (`_meta/manifest.json`)** — `ProjectionManifest` / `ManifestEntry`, deterministic JSON (sorted keys, note_id-ordered entries, no absolute runtime paths). Records `note_id`, `note_type`, `resource_type`, `resource_id`, `project_id`, `relative_path`, `content_fingerprint`, `source_trace_ids`, `status` (CURRENT / RETIRED). In-manifest relative-path containment + traversal/path-escape rejection. Duplicate *active* note_id rejected; a RETIRED entry may legitimately share a note_id with a CURRENT one (path-drift / safe-retirement case).
- **Deterministic rebuild** — `rebuild()`: fresh vault → desired set → write all, manifest written LAST. Two independent vaults of identical source produce byte-equivalent `_meta/manifest.json` and tree. Reverse source order yields identical manifest bytes.
- **Incremental update / zero-write rerun** — `reconcile()`: create / skip-unchanged (zero bytes) / overwrite (gated) / retire. An identical second run writes **0** note bytes and does **not** rewrite an already-current manifest. A single authorized change writes exactly the affected set (e.g. a requirement content change → that requirement re-created at its new deterministic path + the old path retired + the Project Home that embeds it updated); unrelated notes are untouched and leave no orphan.
- **Safe stale retirement (three-signal ownership)** — a previously-managed file is retired (deleted) only when ALL three signals hold: (1) listed in the prior manifest, (2) contained within the managed root (path-resolution containment), (3) carries the Zero-Mem managed marker + this note_id in frontmatter. A human-owned / foreign / symlink-chain / unsafe file is **never** deleted or silently overwritten — it is recorded as `SKIPPED_UNSAFE_OWNERSHIP` / `SKIPPED_HUMAN_MODIFIED` and its bytes remain intact. A managed note the human edited in place (marker + id still match, but the on-disk fingerprint no longer equals the prior manifest's) is NOT silently overwritten; M9.5 owns the real edit-resolution.
- **Path / symlink safety** — manifest-driven resolution rejects traversal (`../`), absolute paths, and symlink chains that would escape the root; a hostile symlinked managed dir does not resolve to outside the root.

### Files added (product)

| File | Responsibility |
| --- | --- |
| `src/projection/manifest.py` | `ProjectionManifest` / `ManifestEntry`, deterministic serialization, `from_notes`, `load_manifest` / `store_manifest`, in-manifest path containment + traversal rejection (`resolve_entry_path`, `validate_manifest_relative_path`), `empty_manifest`, ownership-proof helpers. |
| `src/projection/reconcile.py` | `reconcile()` (desired-set reconcile + safe stale retirement + manifest LAST), `rebuild()`, `ReconcileResult`, three-signal ownership gating (`_reconcile_desired`, `_retire_stale`, `_record_retire`). |

### Files modified (product)

| File | Reason |
| --- | --- |
| `src/projection/writer.py` | `overwrite_note` / `retire_note` (gated, force_managed only), `WriteStatus` adds `UPDATED` / `RETIRED` / `SKIPPED_UNSAFE_OWNERSHIP` / `SKIPPED_HUMAN_MODIFIED`, `__all__`. |
| `src/projection/engine.py` | `project_to_vault()` — M9.2 pipeline → `reconcile()`, manifest as DATA input only; exports `project_to_vault`. |
| `src/projection/render.py` | Populate manifest-bound fields (`content_fingerprint`, `resource_id`, `project_id`, `source_trace_ids`) on rendered notes. |
| `src/projection/contracts.py` | `NoteStatus.RETIRED` semantics + manifest-bound `ProjectedNote` fields/validation. |
| `src/projection/__init__.py` | Export `manifest`, `reconcile`, `writer` extensions. |

### Files added (tests)

| File | Contents |
| --- | --- |
| `tests/unit/test_m9_4_manifest_lifecycle.py` | 16 tests: manifest determinism/byte-equivalence, reverse-order equivalence, sorted keys, duplicate active note_id / duplicate managed path rejection, path-escape rejection on load, lives at `_meta/manifest.json`, ownership-proof helpers. |
| `tests/unit/test_m9_4_incremental_retirement.py` | 13 tests: zero-write rerun, manifest-not-rewritten-when-unchanged, one-change exact write set, create-new-authorized, three-signal retirement (proven deletes / not-proven preserves / human-owned never deleted / human-modified not silently overwritten), symlink-chain refusal, path-escape on load. |
| `tests/unit/test_m9_4_integration.py` | 9 tests: end-to-end through VERIFIED M9.2 pipeline — all M9 note types present, two clean rebuilds byte-equivalent, unchanged rerun zero writes, one-change exact write set, authorization-revoked retires all, cross-profile denied, sensitivity (secret backstop + honest private-state contract), Conflict preserved / no `conflict_queue`, canonical store immutability. |

### Files modified (tests)

| File | Reason |
| --- | --- |
| `tests/unit/test_m9_1_security.py` | Minimal regression-update: M9.4 approved `manifest.py` / `reconcile.py`, so the M9.1 non-scope guards (`NOT_YET_IMPLEMENTED_MODULES`, `test_no_manifest_or_render_surface_yet`) now exempt the approved M9.4 surfaces while keeping the M9.1 read/validate-only boundary pinned. No security intent weakened. |

**Not implemented here (later increments, deliberately):** human-edit quarantine/resolution (M9.5), Research Note / Knowledge Index bodies (M9.6), full backlink graph, and the deferred full-repository audit (M10). M9.4 manages the lifecycle of already-authorized notes; it authorizes, resolves, ranks, or infers none.

---

## 3. Pre-acceptance scope reconciliation — `conflict_queue` / NoteType vocabulary

No new public note type was introduced. M9.4 preserves the eight owner-approved M9 Q1 types (`project, decision, requirement, verification, conflict, artifact, research_note, knowledge_index`). Conflict projection uses `NoteType.CONFLICT`; no `CONFLICT_QUEUE` exists. The end-to-end integration test `test_e2e_conflict_projection_preserved_no_queue` pins this: `conflict_queue` is absent from the manifest's note-type set, and Conflict notes are present. (This had been corrected in M9.3; M9.4 confirms it through the full pipeline.)

---

## 4. Three-signal ownership (plan-m9.md §12.1)

| Signal | Check | Enforced by |
| --- | --- | --- |
| 1. Manifest listing | prior manifest lists this exact `note_id` | `_retire_stale` / `_reconcile_desired` `listed` |
| 2. Containment | resolved path inside managed root (`assert_within_managed_root`) | `_reconcile_desired` `contained` |
| 3. Frontmatter marker | file carries `zero_mem_managed: true` + this `note_id` | `_on_disk_marked_managed` |

Retirement / overwrite proceed only when ALL three hold. Human-owned, foreign, symlink-escaping, or otherwise unprovable files fail closed to `SKIPPED_UNSAFE_OWNERSHIP` / `SKIPPED_HUMAN_MODIFIED` — bytes preserved, never deleted, never silently overwritten.

---

## 5. Determinism evidence

- **Manifest bytes:** two independent vaults from identical source + config produce identical `_meta/manifest.json` (verified by `test_manifest_deterministic_json_bytes` and `test_e2e_two_clean_rebuilds_byte_equivalent`).
- **Reverse-order equivalence:** desired notes supplied in reverse order serialize to identical manifest bytes (`test_rebuild_reverse_source_order_byte_equivalent`).
- **Zero-write rerun:** identical second run writes 0 note bytes and does not rewrite an already-current manifest (`test_unchanged_rerun_writes_zero_notes`, `test_unchanged_rerun_manifest_not_rewritten_when_unchanged`, `test_e2e_unchanged_rerun_writes_zero`).

---

## 6. Fail-safe guarantees

- **Human-owned overwrite / delete: NONE** — collision reported (`SKIPPED_*`), bytes preserved (`test_human_owned_same_name_never_deleted`, `test_stale_retirement_ownership_not_proven_preserves`).
- **Human-modified silent overwrite: NONE** — a managed note the human edited in place is not silently overwritten; recorded `SKIPPED_HUMAN_MODIFIED` (`test_human_modified_managed_note_not_silently_overwritten`).
- **Unsafe stale deletion: NONE** — three-signal gating; symlink-chain / traversal / absolute paths rejected before any delete (`test_retire_through_hostile_symlink_chain_refused`, `test_manifest_path_escape_rejected_on_load`, `test_e2e_canonical_store_unchanged_by_projection`).
- **Manifest path escape: NONE** — `../` / absolute rejected on load and on resolve.
- **Unauthorized influence: NONE** — manifest is DATA only; authorization comes from M5 grants via the M9.2 pipeline.
- **Stale-manifest authorization bypass: NONE** — a prior manifest never elevates visibility; denied grants retire all (`test_e2e_authorization_revoked_retires_all`).
- **Conflict projection preserved: PASS** — `NoteType.CONFLICT` present; `conflict_queue` public type ABSENT.

---

## 7. Tests re-run on the bound source

All runs used the repository virtualenv under a clean isolated `HOME`.

```
# [1] Focused M9.4 (current final source) — 3 files
.venv/bin/python3 -m pytest tests/unit/test_m9_4_manifest_lifecycle.py \
    tests/unit/test_m9_4_incremental_retirement.py \
    tests/unit/test_m9_4_integration.py -q
    38 passed in 0.72s

# [2] Directly affected regressions
.venv/bin/python3 -m pytest tests/unit/test_m9_1_security.py \
    tests/unit/test_m9_1_identity.py tests/unit/test_m9_1_paths.py \
    tests/unit/test_m9_1_config.py -q
    296 passed
.venv/bin/python3 -m pytest tests/unit/test_m9_2_projection.py \
    tests/unit/test_m9_3_provenance_links_conflict.py -q
    106 passed
.venv/bin/python3 -m pytest tests/unit/test_m5_*.py -q
    250 passed
.venv/bin/python3 -m pytest tests/unit/test_m6_*.py tests/unit/test_m6_*.py -q  # under isolated HOME
    387 passed
.venv/bin/python3 -m pytest tests/unit/test_m7_3_*.py tests/unit/test_m7_5_* \
    tests/unit/test_m7_6_* tests/unit/test_m7_4_* tests/unit/test_m7_1_* \
    tests/unit/test_m7_2_* -q
    359 passed
.venv/bin/python3 -m pytest tests/unit/test_m8_*.py -q
    497 passed

# [3] PRE-BINDING canonical (full, fresh isolated HOME)
OLD_HOME="$HOME"; TEST_HOME="$(mktemp -d)"; export HOME="$TEST_HOME"
.venv/bin/python3 -m pytest tests/ -q
    2793 passed, 3 skipped, 0 failed
export HOME="$OLD_HOME"; rm -rf "$TEST_HOME"
```

**Canonical delta:** 2755 → **2793** passed (+38: the focused M9.4 suite). Skips unchanged at **3** (historical). No deselection, no new xfail, zero failures.

> Note: `test_m6_hermes_adapter.py` (part of the M6.6 set) fails under the **real** HOME because its default `capture_root` (`data/traces`) resolves inside `/home/brian-nguyen`, which the bridge guard rejects — an environment-only condition, not an M9.4 regression (M9.4 touches only `src/projection/`). Under the isolated HOME used for every canonical/regression run above it passes (59 passed). The PRE-BINDING canonical therefore ran under isolated HOME and is green.

---

## 8. Real-vault safety

The operator vault is `${ZERO_MEM_OBSIDIAN_VAULT}` — runtime configuration only. No path to it appears in `src/`, enforced by the M9.1 `TestNoHardcodedOperatorPath` suite.

| Check | Result |
| --- | --- |
| Real vault modified | **NO** — zero projection writes outside `tmp_path` managed roots |
| `.obsidian/` modified | **NO** — untouched; M9.4 never inspects or creates it |
| Projection writes during tests | Temporary `tmp_path` managed roots only |
| `.obsidian/` created in any test vault | NO |
| Pre-existing unrelated `output/` | **present, untouched** — not staged, not committed, not used |

---

## 9. Invariants restated

| Invariant | Status |
| --- | --- |
| Canonical mutation | NONE — `m4.sqlite` digest identical before/after projection (`test_e2e_canonical_store_unchanged_by_projection`) |
| Human-owned overwrite / delete | NONE — collision reported, bytes preserved |
| Human-modified silent overwrite | NONE — `SKIPPED_HUMAN_MODIFIED`, bytes preserved |
| Deterministic byte-equivalence | PASS |
| Fresh rebuild byte-equivalence | PASS |
| Reverse-order equivalence | PASS |
| Unchanged rerun note writes | 0 |
| Unchanged rerun manifest writes | 0 (already-current manifest not rewritten) |
| One-change write set | exact affected set (changed requirement re-created + old path retired + embedding Project Home updated; unrelated untouched; no orphan) |
| Three-signal ownership | PASS |
| Unsafe stale deletion | NONE |
| Manifest path escape | NONE |
| Unauthorized influence | NONE |
| Stale-manifest authorization bypass | NONE |
| Conflict projection preserved | PASS |
| `conflict_queue` public NoteType | ABSENT |
| Schema migration | NONE (v9) |
| New dependencies | NONE |
| Routine LLM calls | 0 |
| Routine external network calls | 0 |
| Hermes core changes | NONE |
| Write-back to canonical | NONE |
| Real vault modified | NO |
| `.obsidian` modified | NO |

---

## 10. Defect found and fixed within this increment

**Prior-increment test drift (M9.1 non-scope guards).** `test_m9_1_security.py` asserted `manifest.py` did not exist and that `def load_manifest` / `def retire` / `def build_manifest` were globally absent — true at M9.1 closure but invalidated by the **approved** M9.4 increment, which delivers exactly those surfaces. Fixed minimally: `NOT_YET_IMPLEMENTED_MODULES` dropped `manifest.py` (kept `projector.py` as a permanent drift sentinel); `test_no_manifest_or_render_surface_yet` now asserts the M9.4-approved surfaces (`load_manifest`, `rebuild`, `retire`/`retire_note`) do **not** leak into the M9.1 module set (M9.1 stays read/validate-only), while the global-absence premise is updated to reflect M9.4 approval. No product behavior, authorization, sensitivity, path safety, determinism, or security intent changed.

**Path-drift retirement (product).** Initial discovery: an authorized note whose rendered filename embeds content (e.g. a requirement statement) left an orphaned old file when only the content changed. Fixed: `_retire_stale` now also retires a prior ACTIVE entry whose `note_id` is still desired but whose `relative_path` drifted, using the OLD entry's three-signal proof; the new path is created by the desired loop. Verified by `test_e2e_one_change_exact_write_set` (exactly one `do-x` file remains on disk, no orphan) and the ad-hoc one-change probe.

---

## 11. State binding

| Field | Value |
| --- | --- |
| M9.1 | VERIFIED |
| M9.2 | VERIFIED |
| M9.3 | VERIFIED |
| M9.4 | VERIFIED |
| M9.5 | NOT STARTED |
| M9.6 | NOT STARTED |
| M10 | NOT STARTED |
| M9 overall | IN PROGRESS |
| Schema | 9 |
| Next incomplete increment | M9.5 |

**Next:** M9.5 — Human Ownership + Edit Boundary.
**DO NOT BEGIN UNTIL APPROVED.**

---

## 12. Evidence / state-binding commit record

| Item | Value |
| --- | --- |
| Implementation / tested commit | `c4ef440e0619aec59ca9b3b1b73d2c2696c067a1` |
| Evidence / state-binding commit (acceptance + project-state) | `852247dd6a7f094863c7726bbf838cabf4bd2048` |
| Planning-artifact advance commit (implementation-plan.json + baseline test) | `fc5ac815e2fdf7b166cdcde849c8adfff3041a58` |
| Final HEAD | `fc5ac815e2fdf7b166cdcde849c8adfff3041a58` |
| Pre-binding canonical | 2793 passed, 3 skipped, 0 failed (isolated HOME) |
| Final canonical (FINAL-HEAD) | 2793 passed, 3 skipped, 0 failed (isolated HOME) |
