# Acceptance — M9.3: Provenance, links, conflict and supersession presentation

**Milestone:** M9 — Obsidian Knowledge Workspace projection
**Increment:** M9.3 — Provenance, safe links, unresolved-conflict and explicit-supersession presentation
**Status:** VERIFIED
**M9 overall:** IN PROGRESS
**Schema version:** 9 (unchanged — no migration)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §12, §12.6, §12.7, §14, §19, §21, §29 Q1/Q11; `plan-m9.md` §6.2, §11.2, §14.1, §16, §18-§19, §21, §29, §861 (M9.3 scope); `acceptance-m9.1.md`, `acceptance-m9.2.md`; `AGENTS.md`

---

## 1. Commit binding

| Item | Value |
| --- | --- |
| Starting HEAD (M9.2 acceptance) | `9a916f18aeb8cbe4ed159837d4a21395d29658c2` |
| Implementation / tested commit (M9.3 product + tests) | `ae5be21d85b021b1e4656138aa9deb21035410c8` |
| Reconciliation fix commit (pre-acceptance, Option B) | `067b589f5f232ecfa8e8073edeeb0f1d26e791b0` |
| Evidence / state-binding commit | recorded in §12 below |
| Schema version | 9 (no migration, no new table) |
| Hermes core changes | NONE |

---

## 2. Scope delivered

M9.3 extends the VERIFIED M9.2 projections with deterministic, auditable presentation of the *authorized* M4 projection state — it creates, resolves, ranks, or infers **nothing**:

- **Authorized-source provenance block** on every note: source event/trace IDs, artifact refs, resource_type (verbatim), project/profile context, lifecycle, verification status, and explicit supersession IDs. No hidden source identity; unauthorized evidence has zero influence on provenance text, link targets, titles, frontmatter, or conflict presentation. Label order is fixed and the block is identical for identical inputs.
- **Safe wiki links** between already-authorized projected notes, built only from the VERIFIED M9.1 note identity/path contracts. Navigation-only. A link target is *never* constructed from record content; a hostile display label is whitelisted to a stable machine identity; an unresolved authorized reference renders a blind identical marker (`[[conflict:…]]`) so the projection cannot signal the existence of a withheld record.
- **Honest unresolved-conflict presentation** from M4-marked-`conflicted` records, grouped on M4's explicit conflict key. Two surfaces, both using the single owner-approved `conflict` NoteType (see §3 reconciliation):
  - per-conflict **Conflict** notes (one per conflict group, every authorized position, no winner);
  - an aggregate **Unresolved Conflicts** index note (the M9.3 "Conflict Queue" deliverable) listing only conflicts this request may see, with no total-of-all-conflicts count.
- **Explicit supersession / history presentation only** (`supersedes_id` / `replaced_by`). Superseded notes are retained and marked; supersession is never inferred from `effective_at`, note order, file mtime, or M8 recency. Conflict and supersession states remain visually and structurally distinct.

### Files added (product)

| File | Responsibility |
| --- | --- |
| `src/projection/links.py` | `LinkRegistry` / `LinkTarget` (deterministic safe link identity), `note_relative_path`, `safe_link_display`, `wiki_link`. Navigation-only; uses VERIFIED M9.1 `derive_note_id` / `note_filename` / `slug` / path safety. |
| `src/projection/conflicts.py` | Deterministic grouping of AUTHORIZED, M4-marked-`conflicted` records on M4's explicit conflict key. Detection of conflicts is M4's authority; M9.3 only joins already-conflicted records. |

### Files modified (product)

| File | Reason |
| --- | --- |
| `src/projection/render.py` | Provenance block helper, link rendering in Decision/Requirement, `render_conflict` (kept), and `render_conflict_index` (aggregate index note, `NoteType.CONFLICT`). No new public note type. |
| `src/projection/engine.py` | Builds the `LinkRegistry` from the SAME authorized+eligible set the notes render from; adds conflict presentation (index + per-conflict) from authorized conflicts only. |

### Files added (tests)

| File | Contents |
| --- | --- |
| `tests/unit/test_m9_3_provenance_links_conflict.py` | 34 focused tests: provenance completeness + no hidden source, link-target safety + injection, unresolved conflict stays unresolved with all authorized positions and no winner, supersession only from explicit M4, mtime/recency/order never infer supersession, calibration never rendered as truth, cross-profile/project/revoked/sensitivity isolation, path safety, determinism. |

### Files modified (tests)

| File | Reason |
| --- | --- |
| `tests/unit/test_m9_1_security.py` | Reverted to the **8-type owner-approved set** after the pre-acceptance reconciliation (see §3). |

**Not implemented here (later increments, deliberately):** the manifest (M9.4), incremental/unchanged-write suppression, retirement (M9.4), human-edit quarantine (M9.5), Research Note / Knowledge Index bodies, and full backlink graph. M9.3 presents M4 conflict/supersession state; it resolves, ranks, or infers none.

---

## 3. Pre-acceptance scope reconciliation — `NoteType.CONFLICT_QUEUE`

Before binding, a scope-deviation check was required: the increment added `NoteType.CONFLICT_QUEUE` as a public curated note type, which had **not** been separately approved. This was reconciled against the authoritative plan/contracts and resolved as **Option B (unapproved new public projection type)** — evidence:

- **plan-m9.md §29 Q1 (owner-approved curated vocabulary, line 932):** exactly eight types — `project, decision, requirement, verification, conflict, artifact, research_note, knowledge_index`. `conflict_queue` is **absent**.
- **acceptance-m9.1.md (line 59-61):** `NoteType` = *exactly those eight Q1 types* — a contract M9.1 defines and M9.2 inherits.
- **plan-m9.md (line 861, M9.3 scope):** names "Conflict Queue **index**" as a deliverable, not a new note type. The directive itself permits "a project-level conflict index/list only if it can be represented without creating a new unapproved public note type."
- The original increment had **altered the M9.1 regression test** (`test_curated_note_types_match_owner_approved_set`) to legitimize the type — exactly the "green tests do not authorize scope" trap the directive warns against.

**Resolution (per directive):** `NoteType.CONFLICT_QUEUE` and its `NOTE_TYPE_DIRECTORIES` entry were **removed**. The M9.3 "Conflict Queue" deliverable is now rendered as an **aggregate `NoteType.CONFLICT` note** (`render_conflict_index`) with a stable aggregate `note_id` (`conflict-index:<resource_type>`), so the M9.1 identity/filename contracts and M9.4's manifest still apply unchanged. The per-conflict `Conflict` projection is retained and unchanged. Conflict visibility is **fully preserved** (every authorized position, no winner, no leak of totals). Authorization, sensitivity, path safety, and determinism are untouched.

**No defect in prior verified increments** — `CONFLICT_QUEUE` was introduced by M9.3 itself and never shipped in a VERIFIED state; it was corrected within the same increment before acceptance.

---

## 4. Focused-failure triage — product vs. test

During M9.3 development, focused tests initially failed. Each was classified before any edit; no product behavior was changed merely to satisfy an assertion. The reconciliation in §3 is the only scope correction; the remaining early failures were test-expectation errors (escaped hostile HTML, the word "unresolved" containing "resolved", an incorrect resource_type expectation for state/charter, a collision-path mismatch, and a wrong exception type). All were corrected to pin real invariants, not to weaken them. See `test_m9_3_provenance_links_conflict.py` for the corrected assertions (e.g. `<script>` → escaped `&lt;script&gt;`, "no position is selected" present, "preferred"/"winner is" absent, recency yields **0** conflict groups for differently-keyed active records).

---

## 5. Acceptance criteria

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Notes render deterministically | PASS — repeated runs byte-identical |
| 2 | Reversed / independent input order equality | PASS |
| 3 | No unauthorized item appears | PASS — cross-profile, cross-project, revoked, resource-type-restricted all denied |
| 4 | Authorization occurs BEFORE rendering | PASS — denial yields zero notes and zero writes |
| 5 | M6.6 `resource_type` isolation preserved | PASS |
| 6 | Sensitivity ceiling `internal`, `secret` never projected | PASS — incl. malformed fail-closed |
| 7 | `raw`/`observed`/`candidate`/`deleted` excluded | PASS |
| 8 | No injection corrupts a note (frontmatter, link, embed, tag, fence, HTML, delimiter) | PASS |
| 9 | Authorized-source provenance on 100% of notes | PASS |
| 10 | Conflict presented unresolved, no winner | PASS |
| 11 | Conflict Queue index shown without a new public note type | PASS — aggregate `NoteType.CONFLICT` |
| 12 | Supersession explicit-only; never inferred | PASS |
| 13 | Conflict vs superseded remain distinct | PASS |
| 14 | Canonical immutability (JSONL + SQLite) | PASS |
| 15 | Human-owned file never overwritten | PASS |
| 16 | Path containment + symlink defense hold | PASS |
| 17 | Real operator vault untouched | PASS (see §11) |
| 18 | Zero LLM / zero network | PASS |

---

## 6. Security properties proven

**Memory is DATA, never instruction.** Content never chooses structure (closed frontmatter field set, fixed category directories from `NOTE_TYPE_DIRECTORIES`); content never reaches the start of a line (single-line fold before context-escape).

**Provenance is authorized-source only.** A note's provenance reflects *its own* M4 fields and the authorized record set. An unauthorized source reference can neither be supplied by a record nor inferred, so no hidden trace/source/trace of a withheld record can surface.

**Links are navigation-only and fail closed.** A `LinkTarget` is built from the VERIFIED M9.1 identity of an already-authorized note; the display label is whitelisted to a stable machine identity, so a hostile `[[../../secret]]` label cannot craft a live traversed link. An unresolved authorized reference produces a blind identical marker — it never reveals whether a linked record exists or is withheld.

**No conflict resolution invented.** The Conflict / index notes state verbatim that the conflict is unresolved and that no position is selected as the winner. No scoring, ranking, calibration, or recency promotes a position.

**No inferred supersession.** Supersession renders from explicit `supersedes_id` / `replaced_by` only. Two differently-keyed active records never become a conflict group and never imply a supersession.

**Zero-influence.** Hidden project H material never alters project P output; a denial leaves no stub, count, or placeholder.

---

## 7. Tests re-run on the bound source

All runs used the repository virtualenv under a clean isolated `HOME`.

```
# [1] Focused M9.3 (current final source)
.venv/bin/python3 -m pytest tests/unit/test_m9_3_provenance_links_conflict.py -q
    34 passed in 0.09s

# [2] Directly affected regressions (M9.1 + M9.2)
.venv/bin/python3 -m pytest tests/unit/test_m9_1_security.py \
    tests/unit/test_m9_1_identity.py tests/unit/test_m9_1_paths.py \
    tests/unit/test_m9_1_config.py tests/unit/test_m9_2_projection.py -q
    368 passed in 1.95s

# [3] PRE-BINDING canonical (full, fresh isolated HOME)
OLD_HOME="$HOME"; TEST_HOME="$(mktemp -d)"; export HOME="$TEST_HOME"
.venv/bin/python3 -m pytest tests/ -q
    2755 passed, 3 skipped in 14.54s
export HOME="$OLD_HOME"; rm -rf "$TEST_HOME"
```

**Canonical delta:** 2721 → **2755** passed (+34: the focused M9.3 suite). Skips unchanged at **3** (historical). No deselection, no new xfail, zero failures.

**Ad-hoc reconciliation verification (supporting only — not the canonical suite):** a throwaway script pinned the Option-B behavior — `NoteType` == exactly 8 owner-approved types (`conflict_queue` absent); `render_conflict_index` → `NoteType.CONFLICT`; per-conflict `Conflict` note intact and distinct; engine end-to-end emits `{decision, project, conflict, verification, requirement}` with no `conflict_queue`. Script created under a fresh isolated HOME and deleted after the run; not committed.

---

## 8. Real-vault safety

The operator vault is `${ZERO_MEM_OBSIDIAN_VAULT}` — runtime configuration only. No path to it appears in `src/`, enforced by `test_no_hardcoded_operator_path` and the M9.1 `TestNoHardcodedOperatorPath` suite.

| Check | Result |
| --- | --- |
| Real vault modified | **NO** — zero files with mtime inside the work window |
| `.obsidian/` modified | **NO** — unchanged, predates this session |
| Projection writes during tests | Temporary `tmp_path` managed roots only |
| `.obsidian/` created in any test vault | NO — asserted by `test_obsidian_config_untouched` |

---

## 9. Invariants restated

| Invariant | Status |
| --- | --- |
| Canonical mutation | NONE — JSONL digest and SQLite row counts identical |
| Human-owned overwrite | NONE — collision reported, bytes preserved |
| Unauthorized influence | NONE |
| Deterministic byte-equivalence | PASS |
| Routine LLM calls | 0 |
| Routine external network calls | 0 |
| Hermes core changes | NONE |
| Schema migration | NONE (v9) |
| Write-back to canonical | NONE |
| New public note type beyond Q1 | NONE — `CONFLICT_QUEUE` removed; index uses `conflict` |

---

## 10. Defect found and fixed within this increment

**Reconciliation correction (scope, not a security fail-open):** `NoteType.CONFLICT_QUEUE` was added as a public curated type and the M9.1 contract test was altered to permit it. Plan-m9.md §29 Q1 authorizes only the eight curated types, of which `conflict` is the sole conflict projection type. The type and its directory mapping were removed; the Conflict Queue index is now an aggregate `conflict` note. The M9.1 contract test was reverted to the 8-type set. No product behavior (authorization, sensitivity, path safety, determinism, conflict visibility) changed.

---

## 11. State binding

| Field | Value |
| --- | --- |
| M9.1 | VERIFIED |
| M9.2 | VERIFIED |
| M9.3 | VERIFIED |
| M9.4 | NOT STARTED |
| M9.5 | NOT STARTED |
| M9.6 | NOT STARTED |
| M10 | NOT STARTED |
| Schema | 9 |
| Next incomplete increment | M9.4 |

**Next:** M9.4 — Manifest + Deterministic Rebuild + Incremental Update.
**DO NOT BEGIN UNTIL APPROVED.**
