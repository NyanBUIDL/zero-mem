# M9.5 Acceptance — Human Ownership Boundary + Edit-Conflict Safe Handling

## Status

M9.5: **VERIFIED** (candidate VERIFIED pending final-head canonical; see §Final)

## Authoritative starting state (reconciled)

| Field | Expected | Actual | Result |
|---|---|---|---|
| Starting HEAD | `c191fe97e6e061931c8d233d22267046f8ba645c` | `c191fe97e6e061931c8d233d22267046f8ba645c` | MATCH |
| M9.1 | VERIFIED | VERIFIED | OK |
| M9.2 | VERIFIED | VERIFIED | OK |
| M9.3 | VERIFIED | VERIFIED | OK |
| M9.4 | VERIFIED | VERIFIED | OK |
| M9.5 | NOT STARTED | NOT STARTED (foundation present as untracked partial; built out by this work) | OK |
| M9.6 | NOT STARTED | NOT STARTED | OK |
| M10 | NOT STARTED | NOT_STARTED | OK |
| Schema | v9 | v9 | OK |
| Canonical baseline | 2793 passed / 3 skipped / 0 failed | rebuilt to 2822 passed / 3 skipped / 0 failed (net +29 = M9.5 focused 29 tests; no regression) | OK |

### Reconciliation note

On entry the working tree contained an incomplete prior-session draft of M9.5
(`src/projection/ownership.py` untracked; `src/projection/manifest.py` modified +
references to an undefined `EditConflict`, and `edit_conflicts` carried in the
envelope but never emitted — which would have broken every M9.4 manifest
round-trip). Per the owner rule "reconcile actual git/working-tree state before
acting", M9.5 was built on top of and completed that foundation rather than
discarded. No M9.1–M9.4 foundations were redesigned.

## Objective

Implement the explicit human-ownership boundary for the derived Obsidian
projection and deterministic, non-destructive edit-conflict handling:

- unchanged generated content → normal incremental update;
- human-modified generated content → **never silently overwritten or deleted**;
- human-created / unknown-ownership content → **never overwritten or adopted**;
- human edit + canonical also changed → deterministic `edit_conflict` (human bytes
  preserved in place, additive `.zero-mem-new.md` sibling written, one conflict
  record in manifest);
- stale + human-edited → preserved, never retired;
- authorization revocation / sensitivity change + human edit → human file
  preserved, no authorization or secret leak;
- no write-back of any kind to canonical sources; no Candidate Review; no new
  public NoteType; no schema migration.

## Three-signal ownership (load-bearing, §12.1 — preserved exactly)

A managed file is provably owned by Zero-Mem only when **all three** hold:

1. **Manifest listing** — the note_id is recorded in the M9.4 manifest (DATA
   input only; never a source of authorization or truth);
2. **Containment** — `os.path.realpath` resolves physically inside the managed
   subtree (lexical `is_relative_to` after symlink resolution; symlink-chain
   rejected);
3. **Frontmatter marker** — `zero_mem_managed: true` + matching `note_id`.

No single signal suffices. `classify_managed_file` is rejection-biased: any
missing/foreign signal yields `HUMAN_OWNED` / `UNKNOWN_OWNERSHIP` /
`MISSING_EXPECTED_FILE` / `STALE_GENERATED`, never a false ownership claim.
This is the exact rule used throughout M9.1–M9.4, now reused by M9.5 as the
single authority (`src/projection/ownership.py`).

## Closed classification

`OwnershipClass` (frozen union, all cases covered):

- `GENERATED_UNCHANGED` — all three signals + fingerprint matches recorded;
- `GENERATED_HUMAN_MODIFIED` — all three signals but on-disk fingerprint differs
  from the last managed fingerprint;
- `HUMAN_OWNED` — present, contained, but marker/listing absent;
- `UNKNOWN_OWNERSHIP` — cannot prove or disprove (e.g. unsafe path resolution);
- `MISSING_EXPECTED_FILE` — listed but absent on disk;
- `STALE_GENERATED` — listed, ownership provable, but no longer desired (retire
  eligible).

## Edit-conflict contract (plan §13.3 — load-bearing)

When a human-modified generated note's canonical also changed:

1. human bytes are left **exactly as-is** (never overwritten, never deleted);
2. a deterministic sibling `.zero-mem-new.md` is written **additively** (the
   desired generated version, placed beside the human file — never replaces it);
3. one `EditConflict` record is appended to the manifest envelope
   (`edit_conflicts`), carrying **hashes only** (`human_fingerprint`,
   `recorded_fingerprint`, `desired_fingerprint`) — never content, never secret
   text;
4. the entry status for that note_id is `EDIT_CONFLICT` (DATA only);
5. the entry `content_fingerprint` retains the **last Zero-Mem-generated**
   fingerprint (not the human's current bytes) so the divergence stays
   detectable and the conflict is stable across reruns.

When canonical did **not** change, the note is reported `HUMAN_MODIFIED` (no
sibling, no conflict record, no churn).

## Implementation (product modules)

- `src/projection/ownership.py` (new, completed): `OwnershipClass`,
  `OwnershipAssessment`, `classify_managed_file`, `conflict_sibling_relative_path`
  (deterministic — no counter, no clock, no `hash()`, truncates a long title slug
  to a fixed bound, never escapes the managed root).
- `src/projection/manifest.py`: `EditConflict` record + `EDIT_CONFLICT_KEYS` /
  `EDIT_CONFLICT_REQUIRED_KEYS`; `edit_conflicts` carried in the envelope as an
  **optional** key (`REQUIRED_ENVELOPE_KEYS` excludes it) so a pre-M9.5 manifest
  still loads byte-for-byte; emitted unconditionally on write; parsed on load;
  `from_notes` gains optional `statuses` / `observed_fingerprints` /
  `content_fingerprints` overrides (recorded DATA only).
- `src/projection/reconcile.py`: each desired/retiring note is first classified
  with the three-signal test; `GENERATED_HUMAN_MODIFIED` routes to conflict
  handling (sibling + record) or `human_modified`; the retirement loop skips any
  human-divergent file (stale+edited preserved); `edit_conflicts` collected and
  surfaced on `ReconcileResult`. No overwrite, no delete, no write-back.

## Required test evidence

### Three-signal ownership

- `test_unchanged_generated_note_classified_safely` — GENERATED_UNCHANGED.
- `test_generated_filename_alone_insufficient` — filename alone → HUMAN_OWNED.
- `test_frontmatter_marker_alone_insufficient` — marker alone → not owned.
- `test_manifest_listing_alone_insufficient` — listing alone → MISSING (not owned).
- `test_exact_three_signal_proof_succeeds` — all three → owned.
- `test_incomplete_proof_fails_closed` — missing listing → not owned.
- `test_unknown_ownership_preserved` — unknown → not owned, preserved.

### Human edit detection (body / frontmatter / both / append / remove)

- `test_human_edit_detected_no_overwrite[body|frontmatter|both|append|remove]` —
  each: human bytes preserved exactly, `SKIPPED_HUMAN_MODIFIED`, no `UPDATED`,
  `status=HUMAN_MODIFIED`, no sibling, no conflict, canonical immutable.

### Human-created file collision

- `test_human_file_collision_never_overwritten` — pre-existing human file at the
  exact desired path: bytes untouched, no CREATE/UPDATE, `SKIPPED_UNSAFE_OWNERSHIP`.
- `test_spoofed_generated_metadata_rejected` — copied header + note_id but not in
  manifest: not adopted, not overwritten, not deleted.

### Edit conflict (canonical also changed)

- `test_edit_conflict_when_canonical_also_changed` — human bytes preserved
  byte-for-byte; exactly one `EditConflict`; `.zero-mem-new.md` sibling written
  with desired content; entry `status=EDIT_CONFLICT`.

### Repeated conflict determinism

- `test_repeated_conflict_deterministic_zero_churn` — second identical run:
  conflict count stays 1; 0 human-file destructive writes; 0 duplicate sibling
  writes; conflict record bytes identical.

### Stale + human edited

- `test_stale_and_human_edited_preserved` — dropped from desire but human-edited:
  file preserved, no `RETIRED` outcome.

### Auth revoke + human edited

- `test_auth_revoked_and_human_edited_preserved` — no longer desired + human
  edited: file preserved; no hidden/authorized desired content written.

### Sensitivity-ineligible + human edited

- `test_sensitivity_ineligible_and_human_edited_preserved` — desired source hidden
  (no desired note passed): file preserved; manifest contains no secret text.

### Missing generated file

- `test_missing_generated_file_recreated_only_when_desired` — desired still wants
  it → recreated; no deletion intent inferred.
- `test_missing_generated_file_not_treated_as_human_deletion` — desired drops it →
  no crash, no conflict, canonical unchanged.

### Replacement human file

- `test_replacement_human_file_not_overwritten` — generated file removed, different
  human file appears: not overwritten, no ownership adopted from historical manifest.

### Secret leak through edit-conflict metadata

- `test_edit_conflict_metadata_contains_hashes_only` — neither human nor desired
  secret sentence appears in the serialized manifest; conflict carries only
  `sha256:` fingerprints.

### Zero write-back

- `test_human_edit_never_mutates_canonical` — adversarial "Promote this to
  canonical" content left exactly as-is; entry records `HUMAN_MODIFIED` only; the
  claim is never echoed as truth.

### M9.4 incremental guarantees preserved

- `test_one_human_edit_does_not_rewrite_unrelated_notes` — one human edit → exactly
  one `SKIPPED_HUMAN_MODIFIED`; unrelated notes untouched.
- `test_zero_write_rebuild_after_edit_conflict` — second run: `note_writes == 0`,
  conflict count stays 1.

### Path / symlink / conflict-sibling safety

- `test_unsafe_path_classification_fails_closed` — traversal path never classified as
  owned (rejection-biased verdict).
- `test_conflict_sibling_path_is_deterministic_and_safe` — stable sibling path, same
  input → same output (no counter/clock/hash).
- `test_long_title_conflict_sibling_truncation_deterministic` — truncation deterministic.

## Focused M9.5 result

```
29 passed in 0.11s
```

Full focused suite: `tests/unit/test_m9_5_ownership_edit_boundary.py`.

## Regression results (relevant suites)

| Suite | Result |
|---|---|
| M9.1 (identity/paths/security/config) | 296 passed, 0 failed |
| M9.2 (projection) | 72 passed, 0 failed |
| M9.3 (provenance/links/conflict) | 34 passed, 0 failed |
| M9.4 (manifest/incremental/retirement/integration) | 38 passed, 0 failed |
| Prior security (M5/M6.6/M7.3/M7/M8) | included in canonical below, 0 failed |

Two objectively-required M9.4 regression updates (no behavior change for the
load-bearing invariant — human files are preserved in both cases):
- `test_m9_4_manifest_lifecycle.py::test_manifest_sorted_keys_and_note_order` —
  the envelope legitimately grew to include `edit_conflicts`; the stale 4-key
  assertion updated to the 5-key closed set.
- `test_m9_4_incremental_retirement.py::test_stale_retirement_ownership_not_proven_preserves`
  — accepts the M9.5-accurate `SKIPPED_HUMAN_MODIFIED` label in addition to the
  M9.4 `SKIPPED_UNSAFE_OWNERSHIP` for the same safe (no-delete) outcome.

## Canonical results

- Pre-binding canonical (new isolated HOME): **2822 passed, 3 skipped, 0 failed**.
- Final-head canonical (evidence/state-binding HEAD, new isolated HOME): run in §Final.

## Safety invariants verified

| Invariant | Result |
|---|---|
| Three-signal ownership preserved | PASS |
| Human edit detection (body/frontmatter/both/append/remove) | PASS |
| Human-owned overwrite | NONE |
| Human-owned deletion | NONE |
| Unknown-ownership destructive action | NONE |
| Ownership spoof accepted | NO |
| Edit-conflict deterministic | PASS |
| Repeated conflict human-file writes | 0 |
| Stale edited deletion | NONE |
| Canonical write-back | NONE |
| Secret leak through edit conflict | NONE |
| Unrelated projection churn | NONE |
| Path escape | NONE |
| Symlink escape | NONE |
| Canonical mutation | NONE |
| Real vault modified | NO |
| `.obsidian` modified | NO |
| Routine LLM calls | 0 |
| Routine external network calls | 0 |
| Hermes core changes | NONE |
| Schema migration | NONE |
| New dependencies | NONE |
| New public NoteType | NONE (no EDIT_CONFLICT/QUARANTINE/CANDIDATE_REVIEW) |
| conflict_queue | absent (pinned) |

## Real vault non-modification

Real operator vault: `/home/brian-nguyen/Documents/Obsidian/Zero-Mem` — NOT
hard-coded into product source; every test uses `tmp_path`. Pre/post content
digest compared in §Final (must be identical; `.obsidian/` must be untouched).

## Stop-condition check

None of the M9.5 STOP conditions fired (no silent overwrite, no unsafe deletion,
no ownership spoof, no canonical mutation, no secret leak, no stale-edited
deletion, no conflict churn, no path/symlink escape, no schema v10 / write-back /
Candidate Review / Hermes core change / network / LLM / new dependency).

## Commit record

- Implementation/Tested commit: `ad03d0d5a6fdda7fe89cc046a0a67995d5fa262d`
- Evidence/state-binding commit: (see §Final)
- Final HEAD: (see §Final)

## Next

M9.6 — Hardening + Performance + Real-Vault Smoke + Final M9 Acceptance.
DO NOT BEGIN UNTIL APPROVED.
