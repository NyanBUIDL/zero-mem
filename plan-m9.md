# M9 — Obsidian Projection Plan

**Status:** PLAN READY — awaiting explicit approval. M9 implementation has NOT started.

**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §12 (Obsidian Knowledge Workspace and projection layer), §9.2 (rebuildable derived indexes), §14 (security/retention), §17.3 and §18 (roadmap item 9), plus `AGENTS.md` and `ARCHITECTURE.md`.

**Scope:** a deterministic, local, rebuildable, human-facing Markdown projection of already-authorized Zero-Mem state into an operator-configured Obsidian vault. This document implements no code, no tests, no migration, and writes nothing into the real vault.

---

## 1. State reconciliation

Performed at the start of this planning turn against live `git` and the state artifacts — no stale brief was trusted.

| Fact | Reconciled value |
| --- | --- |
| Repository root | `/home/brian-nguyen/Hermes Workplace/Zero-mem` |
| Branch | `master` |
| HEAD (exact) | `326c722d461608a9b36a85ae2771abf18e1796a4` |
| HEAD subject | `M8.6: state binding — acceptance-m8.6.md + M8/next-state updates` |
| Working tree | clean except pre-existing untracked `output/` (unrelated to M8/M9; left untouched) |
| Schema version | **9** (`src/storage/migrations/migrate_9.py`; no v10 exists) |
| M0–M7 | VERIFIED |
| M8.1–M8.6 | VERIFIED (each with acceptance artifact + impl/tested commit) |
| M8 overall | VERIFIED (`m8_overall_status: "verified"`, `m8_next_incomplete_increment: "none"`) |
| Final M8 canonical | `2323 passed, 3 skipped, 0 failed` (pre-binding and final-head agree) |
| M9 | `m9_status: "not_started"` |
| M10 | `m10_status: "not_started"` |

Cross-checked in `acceptance-m8.6.md` (declares M8 VERIFIED, schema 9, next = M9, "DO NOT BEGIN UNTIL APPROVED"), `project-state.yaml` (`current_milestone: M8`, `next_incomplete_milestone: M9`), and `implementation-plan.json` (`status: m8_verified`, `next_incomplete_milestone: M9`, `m8_schema_version: 9`, M9 entry with spec sections `12`, `14`, `17.3`).

The short prefix `326c722` was **not** treated as commit identity; the full 40-character hash above was resolved from `git rev-parse HEAD`.

**Reconciliation result: PASS.** No mismatch. No `STATE RECONCILIATION REQUIRED` condition.

### 1.1 Operator vault verification (read-only)

Verified read-only during this turn, with no writes, no directory creation, and no `.obsidian/` modification:

```text
test -d "/home/brian-nguyen/Documents/Obsidian/Zero-Mem"   -> directory exists
ls -la "/home/brian-nguyen/Documents/Obsidian/Zero-Mem"    -> contains only .obsidian/
test -d ".../Zero-Mem/.obsidian"                           -> present (valid Obsidian vault marker)
test -w ".../Zero-Mem"                                     -> writable by the owner
```

The vault is a real, initialized, currently-empty Obsidian vault. No `M9 VAULT CONFIGURATION BLOCKER`.

### 1.2 DEFECT FOUND IN PRIOR VERIFIED MILESTONE (M7.3) — reported, not hidden

While establishing the sensitivity boundary M9 must inherit, I found a **live vocabulary mismatch in M7.3 eligibility**. Per the delivery protocol this is reported explicitly here and must be fixed as its own minimal correction — it must **not** be absorbed into M9 work.

**Defect.** `src/integration/m7/eligibility.py:58` ranks sensitivity on an invented ladder:

```python
order = {"low": 0, "medium": 1, "high": 2, "critical": 3}   # unknown -> 99 (fail closed)
```

The authoritative canonical vocabulary is `src/capture/event_types.py::Sensitivity` = `public | internal | private | secret`, which is also what `zm_meta.sensitivity` stores (`migrate_1.py:30`) and what `EventView.sensitivity` returns. **The two vocabularies do not intersect.**

**Observed behavior** (executed against the real M7 fixture store at this HEAD):

```text
canonical vocabulary -> is_eligible(...)
  public   -> eligible=False  reason=sensitivity_ceiling_exceeded
  internal -> eligible=False  reason=sensitivity_ceiling_exceeded
  private  -> eligible=False  reason=sensitivity_ceiling_exceeded
  secret   -> eligible=False  reason=sensitivity_ceiling_exceeded

authorized M3 events for PR1 -> 2 returned (E1, E3), both sensitivity='internal'
  E1 -> eligible=False reason=sensitivity_ceiling_exceeded
  E3 -> eligible=False reason=sensitivity_ceiling_exceeded
```

**Impact and severity.**
- **Direction is fail-closed, so there is no leak and no security regression.** Every real M3 event is *excluded*, never wrongly admitted. The M7 5+3 budget, authorization, and injection guarantees are unaffected.
- The functional consequence is that **no M3 `event`-type evidence can ever enter an EvidenceSet in production**; only M4 project rows (`decision`, `charter`, `state`, …) — which carry no `sensitivity` field and bypass the gate by design — are ever selected. Confirmed: the ordinary project route yields 5 primary + 3 supporting, all M4, `event` never present.
- `tests/unit/test_m7_3_evidence_builder.py::TestSensitivity::test_above_ceiling_excluded` passes **vacuously**: it asserts `"E1" not in ids`, which holds because *all* events are excluded regardless of the `critical` value it writes. The suite is green, so this was not caught.

**Required minimal fix (separate from M9).** Align `_sensitivity_rank` to the canonical closed vocabulary (`public=0, internal=1, private=2, secret=3`, unknown→99 fail-closed), set the default ceiling to a canonical member (recommend `internal`, preserving the current conservative posture), and strengthen the vacuous test to assert that a below-ceiling event **is** admitted while an above-ceiling one is not.

**Disposition.** Recorded here as a finding only. It is **out of M9 scope**, requires its own approval, fix commit, and canonical evidence, and is listed as blocking approval item **Q18-A** in §27. M9's sensitivity design in §11 is written to be correct under the *canonical* vocabulary so it does not inherit or entrench this bug.

---

## 2. Real vault configuration contract

### 2.1 The hard rule

`/home/brian-nguyen/Documents/Obsidian/Zero-Mem` is **operator runtime configuration**, not a product constant. Neither that path, nor `/home/brian-nguyen`, nor `/home/<username>`, nor any `~/Obsidian` guess may appear in reusable implementation logic. Product code receives a vault root; it never discovers one.

### 2.2 Resolution order (deterministic, explicit-only)

M9 introduces one frozen dataclass, `ProjectionConfig`, resolved by exactly this precedence — the same explicit-value-then-environment discipline already used by `BridgeConfig._resolve_identity` (`src/integration/bridge_config.py:89`):

1. **Explicit constructor argument** — `ProjectionConfig(vault_root=...)` passed in-process. Always wins. This is what tests use.
2. **Environment variable** — `ZERO_MEM_OBSIDIAN_VAULT` (absolute path).
3. **Project-local config file** — `config/projection.yaml`, key `vault_root`, joining the existing `config/` convention (`config/schemas/`, `config/policies/`). Optional; absent is normal.
4. **Nothing configured** → `vault_root = None` → projection **unavailable** (see §2.4).

No other source is consulted. The vault root is never derived from `cwd`, repository name, `Path.home()`, session text, `HERMES_PROJECT_ID`, or any memory content.

### 2.3 Validation at construction (fail closed)

`vault_root` must be an absolute path; must exist; must be a directory; must not be a symlink; must be writable; and must not equal `Path.home()` or the repository root. `managed_root` is then derived (§6) and is the only writable surface. Validation failures raise a sanitized `ProjectionConfigError` naming the failed condition — never echoing environment values or secrets. Portability is satisfied by construction: a different operator sets one env var or one config key, with zero code change.

### 2.4 Behavior when no vault is configured

Unconfigured is a **normal, safe, silent state**, not an error:

- `project()` returns `ProjectionResult(status=UNAVAILABLE, reason="vault_not_configured", notes_written=0)`.
- **No directory is created anywhere.** No write to `cwd`, `HOME`, `/tmp`, the repository, or a guessed `~/Obsidian`.
- No exception propagates into any caller; nothing else in Zero-Mem changes behavior.

This mirrors the M6 `CAPABILITY_UNAVAILABLE` posture and is asserted by test, including a filesystem-mutation check proving zero paths were created.

### 2.5 Obsidian is optional

Projection writes plain UTF-8 Markdown with YAML frontmatter onto an ordinary filesystem. The Obsidian desktop app is an optional viewer. No Obsidian process, account, Sync, REST API, community plugin, or vault lock is required, and the app need not be running. Core note content stays readable in any text editor (spec §12.9).

---

## 3. Goals

1. Make Zero-Mem state **legible to a human**: what this project is, its current verified state, what was decided, what is required, what is verified, what is unresolved.
2. Project **deterministically and idempotently** — same source + same config ⇒ byte-identical output; repeated runs produce no churn.
3. Preserve **provenance**: every generated note carries source refs and trace IDs back to canonical records.
4. Preserve **every upstream boundary**: M5 authorization, M6.6 `resource_type` isolation, M7 memory-as-DATA, M8 non-authority. Projection is a *view*, never a policy bypass.
5. Keep the vault **rebuildable and disposable** — deleting the managed area loses nothing canonical.
6. Never endanger human-owned notes, and never silently mutate canonical state from a vault edit.
7. Stay **zero-LLM, zero-network, zero-embedding**, with no Hermes core change.

## 4. Non-goals

- ❌ Obsidian as canonical storage, retrieval engine, authorization source, or truth authority.
- ❌ Dumping raw events, tool stdout/stderr, or per-millisecond streams into Markdown (spec §12.8).
- ❌ Direct or silent write-back from vault edits into canonical state (§13; Q20 = NO).
- ❌ Copying large artifacts/PDFs/binaries into the vault (§ artifacts, references only).
- ❌ Obsidian Graph View as a graph retrieval engine (spec §10.6 anti-pattern).
- ❌ LLM summarization/rewriting/filename generation; embeddings; vector or ANN indexes.
- ❌ M10 corpus ingestion (600-PDF library) — M9 projects only what Zero-Mem already holds.
- ❌ New M6 tools, Hermes core modification, or any change to the M7 5+3 budget.
- ❌ Background/automatic projection daemons or filesystem watchers.
- ❌ Confidence-percentage UI derived from M8 calibration.

## 5. Authority architecture

```text
JSONL canonical events/history  +  approved project-state records  +  artifact store
        │  (canonical, append-only, source-of-record)
        ▼
derived SQLite (schema v9)  —  rebuildable, disposable
        │
        ▼
M5 AuthorizedReadService  —  SOLE authorization authority
        │  (authorization happens BEFORE any note is rendered)
        ▼
M9 deterministic projection  —  pure render, read-only over authorized views
        │
        ▼
Obsidian vault managed root  —  curated, human-facing, disposable view
```

Invariants, in the same terms M8 froze:

- **Direction is one-way.** Canonical → projection. Nothing flows back without §13's explicit proposal path.
- **Projection is derived and disposable.** Deleting the entire managed root destroys nothing canonical; a rebuild restores it exactly.
- **The vault confers nothing.** Filesystem location, folder name, wiki link, tag, or shared entity name never creates authorization, verification, supersession, or truth.
- **M9 authorizes, then renders.** No note is materialized for an item M5 did not authorize. Projection never re-decides, widens, or post-filters an M5 decision.
- **M9 makes no authority decisions of its own.** It cannot verify, promote, deny, resolve a conflict, or supersede.

---

## 6. Vault layout and managed-root ownership

### 6.1 Ownership model — dedicated managed subtree (Q2/Q3 recommendation)

M9 manages **a dedicated subtree**, never the whole vault root:

```text
/home/brian-nguyen/Documents/Obsidian/Zero-Mem/      <- configured vault_root (NOT managed)
├── .obsidian/                                        <- operator's app config; NEVER touched
├── Zero-Mem/                                         <- managed_root: EXCLUSIVELY Zero-Mem owned
│   ├── _meta/
│   ├── Projects/
│   ├── Decisions/
│   ├── Requirements/
│   ├── Verification/
│   ├── Conflicts/
│   ├── Artifacts/
│   └── Knowledge/
└── <anything else>                                   <- human-owned; NEVER read, written, or deleted
```

`managed_root = vault_root / managed_dir_name`, default `"Zero-Mem"`, configurable. Rationale: whole-vault ownership (option A) would put every human note inside the deletion/retirement domain of a regenerating projector — an unacceptable risk against a real vault the owner already uses. A single clearly-owned subtree makes "may M9 delete this?" answerable by path containment alone.

**Ownership rule, stated absolutely:** M9 may create, update, or retire files **only** strictly inside `managed_root`. Everything outside — including `.obsidian/` and the vault root itself — is read-never-write. The projector does not enumerate, open, or stat files outside `managed_root` (except the one-time root validation in §2.3).

### 6.2 Directory semantics

| Directory | Contents | Source |
| --- | --- | --- |
| `_meta/` | `manifest.json`, `projection-report.md`, `README.md` (explains the area is generated) | projection state |
| `Projects/<project>/` | Project Home (overview + current verified state + next action) | M4 charter + state |
| `Decisions/<project>/` | one note per decision, incl. superseded/conflicted | M4 decisions |
| `Requirements/<project>/` | one note per requirement | M4 requirements |
| `Verification/<project>/` | verification records | M4 verifications |
| `Conflicts/<project>/` | one note per unresolved conflict | conflicted lifecycle rows |
| `Artifacts/<project>/` | artifact **reference** notes (metadata only) | M4 project artifacts |
| `Knowledge/<space>/` | knowledge-space index notes | authorized scope metadata |

Depth is capped at `managed_root/<category>/<scope>/<note>.md` — three levels, no deeper. This covers the spec §12.7 mandatory operational pages (Project Home, Decision Log, Task/Current State, Conflict Queue, Knowledge Space Index) without importing the spec's fuller `00-System/10-Projects/...` numbering, which presumes a vault Zero-Mem exclusively owns. **Q2/Q3 require owner approval.**

### 6.3 Deferred pages

System Home, Profile Home, and Candidate Review are **deferred**. Each depends on either sidecar runtime metrics or a candidate-review queue that does not exist at v9; inventing either would create an Obsidian-specific truth model. Recorded as Q1 for approval.

---

## 7. Projection eligibility

### 7.1 Authorization-first pipeline

```text
explicit ProjectionRequest (requesting_profile_id, project_ids, knowledge_space_ids, resource_types)
    -> M5 AccessRequest per resource type
    -> AuthorizedReadService.m4_charter / m4_requirements / m4_decisions /
       m4_current_state / m4_verifications / m4_artifacts
    -> denial or downstream error  => project NOTHING for that resource type (silent, no note, no stub)
    -> authorized items only
    -> deterministic eligibility filter (§7.2)
    -> render
```

M9 calls the **existing verified M5 surface only**. It never opens SQLite directly, never imports `src.access.policy`, never constructs an `AllowedScope`, and never infers identity — `requesting_profile_id` is supplied explicitly and `None` stays `None`.

A denial produces **no note, no placeholder, and no count** — indistinguishable from "nothing exists", preserving the existence-leak safety M8.3 established.

### 7.2 Eligibility filter (deterministic, closed vocabularies)

Applied to already-authorized items, using only existing authoritative metadata:

| Signal | Rule |
| --- | --- |
| `lifecycle_status` | `active`, `confirmed`, `superseded`, `conflicted`, `archived` project. `deleted` **never** projects. `raw`, `observed`, `candidate` do not auto-project (Q9/Q10). |
| `verification_status` | Recorded and displayed verbatim; never upgraded. |
| `sensitivity` | Canonical ladder `public < internal < private < secret`; ceiling default `internal`; `secret` **never** projects; unknown → fail closed (§11). |
| `resource_type` | Preserved verbatim; drives directory + note type. Never flattened (M6.6). |
| `profile_id` / `project_id` / `knowledge_space` | Carried verbatim; scope is never widened (§9). |
| conflict | `conflicted` rows project as Conflict notes, never as resolved facts. |

No Obsidian-specific status, score, or truth field is invented anywhere.

### 7.3 Memory-type policy

| Type | Projection treatment |
| --- | --- |
| `verified_state` | Auto-projects. Rendered as **Current verified state** with verifier + evidence ref. |
| `decision` | Auto-projects as a Decision note; explicit supersession chain shown. |
| `user_statement` | Projects only as provenance context, labeled **Stated by user** — never as verified fact. |
| `assistant_claim` | **Never auto-projects as fact.** If projected at all, isolated under a `> [!warning] Unverified assistant claim` callout, excluded from Current State, with `verification: none` in frontmatter. |
| `tool_observation` | Metadata/reference only. No stdout/stderr bodies (spec §12.8). |
| `verification` | Projects as a Verification record (method, command ref, observed result, tested commit). |
| `inference` | Clearly non-authoritative: `> [!note] Inference — not verified`, never in Current State. |
| unresolved conflict | Stays visibly unresolved (§19). |

These types are never collapsed into generic prose; the note template renders each in its own labeled section so a reader cannot mistake a claim for a verified fact.

---

## 8. Metadata contract

Every Zero-Mem-managed note carries YAML frontmatter with exactly this closed field set. Fields are emitted in this fixed order with sorted keys for determinism, and **only** fields justified by the spec §12.4/§12.9 note model are present.

```yaml
---
zero_mem_managed: true            # ownership marker — the authoritative "M9 owns this file"
note_id: zm-decision-3f2a9c4b     # stable machine identity (§9)
note_type: decision               # closed: project | decision | requirement | verification |
                                  #         conflict | artifact | knowledge_space
projection_version: 1             # contract version of the renderer (§14)
content_fingerprint: sha256:1a2b… # hash of the rendered managed body (§14/§17)
resource_type: decision           # verbatim from M5/M6.6 — never flattened
resource_id: DEC-014              # canonical identifier
project_id: hermes-external-zero-mem
profile_id: developer             # null when unbound; never inferred
knowledge_spaces: []              # verbatim; empty list when none
lifecycle_status: active          # closed M1 enum, verbatim
verification_status: direct_tool_output  # closed enum, verbatim
conflict_status: none             # none | conflicted
supersedes: null                  # explicit M4 field only
replaced_by: null                 # explicit M4 field only
source_trace_ids: [T-8842]        # provenance back to canonical
source_event_ids: [E-1190]        # provenance back to canonical
artifact_refs: []                 # safe references only, never stored_path
generated_by: zero-mem/m9
---
```

**Deliberately excluded:** SQLite rowids, internal cursors, grant IDs/records, `stored_path`, absolute filesystem paths, raw content bodies, secrets, calibration scores presented as truth, and wall-clock generation timestamps (§16 determinism). Spec §12.9 requires `note_id`, `note_type`, `source_trace_ids`, `status`, `verification`, `sensitivity`, and `projection_version` on 100% of generated notes; this contract satisfies that — `lifecycle_status` carries `status`, `verification_status` carries `verification`.

**Sensitivity field note:** the *projected* sensitivity is not emitted as a note-level field by default, because a note is only materialized when it is already at or below the ceiling; emitting it adds no reader value and risks becoming a pseudo-authorization label. If the owner prefers it visible for auditability, it is added as `sensitivity:` verbatim — recorded as **Q18** for approval.

---

## 9. Deterministic note identity

Titles are never identity. They change, collide, and carry unsafe characters.

**Machine identity (authoritative):**

```text
note_id = "zm-" + note_type + "-" + sha256(
              canonical_json({
                "note_type":      <closed enum>,
                "resource_type":  <verbatim>,
                "resource_id":    <canonical id>,
                "project_id":     <verbatim or null>,
                "profile_id":     <verbatim or null>,
              })
          )[:16]
```

Derived from canonical identifiers only — never from a title, ordering, wall clock, `uuid4()`, or `random`. Rebuild reproduces it exactly. This reuses the existing `src/m8/identity.py` discipline (`canonical_json` + stable digest); M9 will call those verified helpers rather than reimplement hashing.

**Human filename (display only):**

```text
filename = slug(display_title)[:80] + "--" + note_id_suffix + ".md"
```

`slug()` is deterministic and total: Unicode NFC normalize → casefold → keep `[a-z0-9-]` → collapse runs → strip leading/trailing dashes. Empty or fully-stripped slug falls back to the note type. The `note_id` suffix guarantees uniqueness even under identical or empty titles, so **titles can never collide**, and a title change renames the file without changing identity (the manifest handles the rename as a retire+create pair, §18).

---

## 10. Path safety

The projector writes into a real vault the owner uses. Path safety is treated as a security boundary, not a formatting concern. **Memory-controlled text never determines a filesystem path** — it only ever contributes to a slug that is then sanitized, truncated, and suffixed.

### 10.1 The safe-path invariant

Every write target must satisfy, in order:

1. **Constructed, not concatenated.** `path = managed_root / <closed-enum category> / slug(scope) / filename`. Category comes from a closed enum; scope and filename come from `slug()`. No caller-supplied path fragment is ever joined raw.
2. **No traversal.** After slugging, no component may be `.`, `..`, empty, or contain `/`, `\`, or NUL. `slug()` structurally cannot emit these.
3. **Physical containment.** `path.resolve()` must be `managed_root.resolve()` or a descendant, checked with `Path.is_relative_to`. This is verified on the **resolved** path, so it defeats symlinks — a lexical check alone is explicitly insufficient.
4. **No symlink anywhere on the chain.** Walk from `managed_root` to the final parent; if any component `is_symlink()`, abort with `unsafe_path`. Prevents `managed_root/Projects -> /etc` escapes.
5. **Reserved-name rejection.** Windows device names (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`, `LPT1-9`, with or without extension) are rejected/suffixed for cross-platform vault portability, as are names ending in `.` or space.
6. **Length bounds.** Each component ≤ 80 chars after slugging (excluding the `--<suffix>.md` tail); full path ≤ 240 bytes. Over-long input truncates deterministically — never hashes into a new random name.
7. **Case-collision safety.** The manifest tracks casefolded paths; two distinct notes may not map to paths differing only by case (macOS/Windows are case-insensitive). Detected collisions fail closed rather than silently overwriting.
8. **Unicode ambiguity.** NFC normalization before slugging; zero-width, bidi-override, and control characters are stripped, so visually-identical distinct names cannot be produced.

Any violation → the note is **skipped** with a sanitized `unsafe_path` reason in the report. Never a partial write, never a fallback location, never an exception carrying the offending path into logs.

### 10.2 Attacks explicitly covered

`../../../etc/passwd` as a project name; absolute `/etc/cron.d/x` as a title; `foo/bar` separator injection; `..%2f` encoded traversal; NUL truncation; a symlinked category directory; `CON.md`; a 5000-character title; `Decision` vs `decision` case collision; RTL-override and zero-width homoglyph titles. Each becomes a named test in §23.

---

## 11. Authorization and sensitivity

### 11.1 Authorization

M5 is the sole authority (§7.1). Additionally: **filesystem co-location is not authorization.** Two projects' notes sitting in one vault, linking to each other, sharing a tag, or naming the same entity grants nothing. Each note is materialized only because *its own* item was authorized for the requesting profile — the same per-candidate rule M8.3 enforced for graph neighbors.

Revocation is honored on the next run: M9 holds no cache across invocations, re-authorizes every item every run, and retires notes that are no longer authorized (§18).

### 11.2 Sensitivity

Uses the **canonical closed vocabulary** `public < internal < private < secret` from `src/capture/event_types.py::Sensitivity` — deliberately *not* the mismatched `low/medium/high/critical` ladder found in M7.3 (§1.2). M9 must not inherit or entrench that bug.

- Default ceiling: **`internal`**. Only `public` and `internal` project by default.
- **`secret` never projects, at any ceiling, unconditionally.**
- Unknown/missing/unparseable sensitivity → rank 99 → **fail closed** (excluded).
- Ceiling is configurable upward only by explicit operator configuration, never by memory content or request text.

### 11.3 Secret safety

Layered, because the vault is plaintext on disk and may be synced by the operator:

1. Redaction already happened at the M1 capture boundary; raw secrets are not in canonical storage.
2. `secret`-class items are excluded before rendering.
3. `stored_path` is never projected — artifacts appear only as `safe_reference`, reusing the verified `is_safe_reference()` guard (`src/project_memory/contracts.py:350`) that already rejects absolute paths, traversal, and secret-shaped values.
4. Private tool output, raw stdout/stderr, and large bodies are never rendered (spec §12.8) — metadata and references only.
5. A **secret-scan test** greps the entire generated managed root for bearer tokens, `-----BEGIN … PRIVATE KEY-----`, `api_key=`, `password=`, and OAuth-secret patterns, reusing the M1 redaction pattern set, and asserts zero hits (spec §12.9).

**M9 may narrow visibility but must never widen it.** No item becomes more visible by being projected.

---

## 12. Generated vs human-owned content

### 12.1 Three-signal ownership test

A file is Zero-Mem-managed **only if all three hold**:

1. it lies strictly inside `managed_root` (§6.1);
2. its frontmatter contains `zero_mem_managed: true`;
3. its `note_id` is present in the manifest (§15).

If **any** signal is missing, the file is treated as **human-owned** and is never modified or deleted. This is the smallest robust design: containment alone would delete a human note dropped into the managed folder; frontmatter alone would be spoofable elsewhere in the vault; the manifest alone would go stale. Requiring all three fails safe in every direction.

### 12.2 Consequences

- A human file inside `managed_root` without the marker → left untouched, reported as `human_owned_skipped`.
- A managed note the human edited → detected by fingerprint (§17), never blindly overwritten.
- Anything outside `managed_root` → outside M9's universe entirely.
- Managed-block markers inside otherwise-human files are **not** used. Mixed-ownership files would make the "may I delete this?" question ambiguous; whole-file ownership keeps it decidable.

---

## 13. Human edit and write-back semantics

### 13.1 Decision: PROJECTION-ONLY for M9 (Option A)

**Q20 answer: NO — an Obsidian edit may never enter canonical state during M9.**

Editing a generated note in Obsidian has **zero** effect on canonical memory. No JSONL append, no M4 mutation, no lifecycle change, no verification, no conflict resolution. This follows the spec's `write_policy: propose_then_review` default (§21) and the standing architecture rule that canonical writes require explicit authorization and review/verification gates. Option C (direct write-back) is rejected outright.

### 13.2 Why not proposal-based write-back (Option B) now

The spec §12.6 does describe an eventual change queue (`user edits → change queue → schema/permission/conflict validation → approved write-back record → canonical update`). That is the correct long-term design, but it needs an authorized-write path, a candidate/proposal store, and a review workflow — none of which exist at v9. Building it inside M9 would mean inventing a write surface while also introducing the projection surface, doubling risk on a milestone whose main job is a *read-only view*.

**M9.5 therefore delivers the detection and quarantine half only**: it reliably notices human edits, refuses to destroy them, and records them in a structured, machine-readable form that a future milestone can consume as proposals. The plan explicitly does **not** promise write-back in M9. Recorded as **Q5** — if the owner wants proposal export inside M9, it is an additive, still-read-only extension of M9.5.

### 13.3 Edit-collision behavior

When a managed note's on-disk fingerprint differs from the manifest's recorded fingerprint (i.e. a human edited it) **and** the canonical source has also changed:

1. **Do not overwrite.** The human's file stays exactly as-is on disk.
2. Write the newly-rendered content to a **sibling** `<name>.zero-mem-new.md` inside `managed_root`.
3. Record `status: edit_conflict` for that `note_id` in the manifest, with both fingerprints.
4. Surface it in `_meta/projection-report.md` under **Edit conflicts**.
5. Resolution is a human action. M9 picks no winner — the same "no silent resolution" rule the whole system applies to conflicts.

If the note was edited but the canonical source did **not** change, M9 leaves it alone entirely and reports `human_modified` — no sibling file, no churn.

---

## 14. Projection versioning

### 14.1 Two distinct version identities

- **`projection_version`** (integer, currently `1`) — the *renderer contract* version: layout, frontmatter field set, section structure. It changes only when M9's own output format changes, never per run. A bump means "every note must be re-rendered."
- **`content_fingerprint`** (`sha256:<hex>`) — the *content* identity of one rendered note body. It changes when and only when that note's rendered content changes.

Together these answer "is this note current?" without any wall clock. Note-level granularity is chosen (**Q6**): manifest-level-only would force full rewrites, and section-level would be over-engineered.

### 14.2 Updates preserve auditability without note sprawl

A projection update **replaces** the note body and records the transition in the manifest (previous fingerprint → new fingerprint). It does **not** create a timestamped historical copy. Historical auditability lives where it belongs — canonical JSONL and the M4 supersession chain, both of which are complete and queryable. Generating thousands of dated Markdown copies would bloat the vault while duplicating history that canonical storage already holds losslessly.

Superseded *domain* records still appear as notes (§20) because M4 models supersession explicitly; that is domain history, not projection history.

### 14.3 Reconstructing prior projection state

Prior projection output is reconstructible by rebuilding from canonical state at the corresponding commit — the vault is derived, so its history is the source's history. Because the vault is a plain-file tree, an operator who wants literal snapshots can also keep it under their own version control; M9 neither requires nor manages that.

### 14.4 Retiring obsolete projections

On a `projection_version` bump, every managed note is re-rendered; notes whose type no longer exists are retired per §18.

---

## 15. Manifest and projection links

### 15.1 Decision: filesystem manifest, not a SQLite table (Q7)

`managed_root/_meta/manifest.json` — a single deterministic JSON file, keys sorted, newline-terminated:

```json
{
  "manifest_version": 1,
  "projection_version": 1,
  "managed_dir_name": "Zero-Mem",
  "notes": [
    {
      "note_id": "zm-decision-3f2a9c4b",
      "note_type": "decision",
      "resource_type": "decision",
      "resource_id": "DEC-014",
      "project_id": "hermes-external-zero-mem",
      "relative_path": "Decisions/hermes-external-zero-mem/adopt-sqlite--3f2a9c4b.md",
      "content_fingerprint": "sha256:1a2b…",
      "source_trace_ids": ["T-8842"],
      "status": "current"
    }
  ]
}
```

`status` ∈ `current | retired | edit_conflict | human_modified`.

**Why the filesystem, not `zm_projection_links` in SQLite:**

- The manifest must live and die *with the vault*. If the vault is deleted, moved, or restored from the operator's backup, a SQLite table would immediately describe a filesystem that no longer matches.
- It keeps **schema at v9** (§21) — no migration, no canonical/derived reclassification.
- The vault stays self-describing and portable: everything M9 needs to reason about the projection travels with the folder.
- The spec's `projection_links(trace_id, obsidian_path, projection_version)` sketch (§9.2) is satisfied *semantically* by this manifest; the spec does not mandate the storage medium.

The manifest is **derived and rebuildable**: deleting it and re-running produces an identical manifest, because every field derives from canonical state plus the deterministic renderer. It is regenerated atomically (§22) as the final step of a run, so a crash never leaves it describing notes that were not written.

### 15.2 Manifest is not authority

The manifest records what was projected. It never establishes truth, authorization, verification, or supersession. A note absent from the manifest is unmanaged (§12.1), not unauthorized.

---

## 16. Deterministic rebuild and idempotence

### 16.1 The testable property

```text
same canonical/project source + same projection config + same projection_version
        ⇒ vault projection A

clean managed root + rebuild from the same inputs
        ⇒ vault projection B

A == B   byte-for-byte, across manifest, file contents, filenames, links, and metadata
```

### 16.2 Determinism rules

1. **No wall clock in equivalence-sensitive output.** No `generated_at`, no `datetime.now()`, no run ID in note bodies, frontmatter, or the manifest. Domain timestamps sourced from canonical records are fine — they are inputs, not run artifacts. Any human-facing run time lives only in `_meta/projection-report.md`, which is **excluded from the equivalence set** and listed as such.
2. **Total ordering everywhere.** Notes, frontmatter keys, list items, links, and manifest entries sort by explicit deterministic keys (`note_id` as final tiebreaker) — never by dict insertion, `set` iteration, or database row order.
3. **No randomness.** No `uuid4`, no `random`, no `hash()` (PYTHONHASHSEED-dependent), no `os.urandom`. Only `hashlib.sha256` over `canonical_json`.
4. **Insertion-order independence.** Reversing the source query order yields identical output — the same property M8 proved for graph edges.
5. **Fixed encoding.** UTF-8, LF newlines, single trailing newline, no BOM.
6. **Locale independence.** Sorting is by code point, not locale collation.

### 16.3 Idempotence

A second run over unchanged sources must produce **zero** filesystem writes: no semantic change, no duplicate sections, no filename churn, no `projection_version` churn, and — verified by running `git status` on a git-initialized temp vault — **no diff at all**. Unchanged notes are not rewritten even with identical bytes, so `mtime` stays stable and Obsidian's file watcher does not fire.

---

## 17. Incremental updates

### 17.1 Change detection

Each note's `content_fingerprint` is `sha256` over the **rendered managed body** (frontmatter + content, excluding nothing, since nothing volatile is present). Per note:

| Manifest fingerprint | On-disk fingerprint | Newly rendered | Action |
| --- | --- | --- | --- |
| absent | — | new | **create** |
| matches | matches | identical | **skip** (no write, no mtime change) |
| matches | matches | different | **update** (atomic replace) |
| matches | **differs** | identical | `human_modified` — leave alone |
| matches | **differs** | different | `edit_conflict` — §13.3 |
| present | file missing | any | **recreate** |
| present | — | no longer eligible | **retire** (§18) |

On-disk fingerprints are computed by reading only files the manifest already lists — M9 never walks outside `managed_root` and never opens human-owned files it did not itself create.

### 17.2 Dirty set and backlinks

The dirty set is `{notes whose rendered content changed} ∪ {notes whose outbound links changed}`. Because links are rendered from canonical relationships (not from scanning the vault), a backlink change always shows up as a content change in the *referring* note, which the fingerprint catches. There is no separate backlink index to invalidate — a deliberate simplification that removes a whole class of staleness bugs.

Obsidian computes backlinks itself at display time from wiki links, so M9 does not maintain a backlink store.

### 17.3 Cost

An unchanged run reads the manifest and hashes the listed files — no rendering of unchanged notes beyond what is needed to compute the comparison, and zero writes. Cost scales with **curated projection size**, not raw event volume.

---

## 18. Deletion and retirement

| Source condition | Projection behavior |
| --- | --- |
| `deleted` / tombstoned | Note is **retired**. |
| `archived` | Retired by default; configurable to project read-only into an archive area (Q15). |
| `superseded` | **Not** retired — kept and clearly marked superseded (§20). |
| Project/entity renamed | Identity is unchanged (§9), so the note is rewritten at the new display filename and the old path retired — no duplicate. |
| No longer authorized | Retired (revocation honored, §11.1). |
| Note type removed from config | Retired. |
| `projection_version` bump | Re-rendered, not retired. |

### 18.1 Retirement mechanism (Q15)

Default: **delete the managed file and mark `status: retired` in the manifest.** Deletion is safe *only* because of the three-signal ownership test (§12.1) — M9 deletes exclusively files it created, which are inside `managed_root`, carry `zero_mem_managed: true`, and are listed in the manifest. Any file failing any signal is never deleted, full stop.

Canonical history is untouched; the note is a view and reconstructible.

A `retire_mode: "tombstone"` alternative (replace the body with a short "this record was retired" stub, preserving inbound links) is offered for approval under **Q15** — it avoids broken links at the cost of leaving files behind.

**Absolute rule: M9 never deletes a human-owned file, anywhere, under any configuration.** Empty managed directories left after retirement are removed only if they are inside `managed_root` and contain nothing at all.

---

## 19. Conflict representation

Unresolved conflicts must **remain visibly unresolved**. A Conflict note renders:

- `conflict_status: conflicted` in frontmatter;
- a prominent `> [!warning] Unresolved conflict` callout at the top;
- **every** authorized conflicting position, side by side, in deterministic order, each with its own provenance (trace IDs, verification status, source);
- the authoritative resolution **only if** M4 records one — rendered verbatim as the recorded resolution.

**M9 never chooses a winner.** It does not rank, score, hide the weaker side, prefer the newer entry, or use M8 calibration to imply which position is right. Positions the requesting profile is not authorized to see are simply absent — never summarized, never counted.

A Conflict Queue index note lists open conflicts for the project (spec §12.7).

---

## 20. Supersession

Explicit **M4 supersession is the only authority**. Projection renders `supersedes` / `replaced_by` exactly as recorded, and:

- current records render normally;
- superseded records keep their notes, marked `> [!info] Superseded` with a wiki link to the replacement;
- the chain is navigable in both directions.

**M9 never infers supersession** from file mtime, `projection_version`, note ordering, manifest position, a newer domain timestamp, or M8 temporal recency. If M4 records no supersession, the projection shows none — even if two records look contradictory (that is a *conflict*, §19, not a supersession).

---

## 21. M8 metadata usage

Graph, temporal, and calibration metadata may aid **navigation and display only**. The invariants M8 froze carry forward verbatim:

- `graph ≠ truth` — links are navigation, never evidence of correctness.
- `temporal recency ≠ truth` — newer is not righter, and never implies supersession.
- `calibration ≠ truth`, `calibration ≠ verification`, `calibration ≠ authorization`.

**Explicitly forbidden:** any UI of the form `Confidence: 92% true`, any percentage or score presented as likelihood of truth, any sorting that implies correctness, and any badge derived from a calibration bucket. If calibration appears at all, it is a neutral, clearly-labeled diagnostic (e.g. `calibration_bucket: <verbatim>`) — never adjacent to a truth claim. Default: **omit it**, pending **Q11-adjacent** approval.

---

## 22. Markdown and security threat model

Projected content is **DATA**, never instruction. All content reaching a note is memory-controlled and therefore hostile by assumption.

### 22.1 Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| **Frontmatter injection** — content containing `---`, `: `, or newlines breaking the YAML block | All values emitted via a strict serializer that quotes and escapes every scalar; multi-line values are folded or truncated to a single line. Never string-interpolated into YAML. |
| **Frontmatter escape via `---`** | Any `---` at line start in a value is neutralized; the closing delimiter is emitted by the serializer, not by content. |
| **Code-fence breakout** — content containing ``` | Fenced blocks use a fence longer than any run in the content (CommonMark rule). |
| **Wiki-link corruption** — `[[`, `]]`, `|` in titles | Link *targets* are always generated filenames (slugged, §9), never raw content. Display text has `[]|` escaped. Content-derived text can never synthesize a link target. |
| **Tag injection** — `#tag` from content creating false taxonomy | Tags are generated from closed enums only. Content-derived `#` is escaped. |
| **HTML / script injection** — `<script>`, `<iframe>`, event handlers | HTML-special characters escaped; raw HTML never passed through. |
| **Obsidian embed abuse** — `![[secret-note]]` transcluding another note | `![[` is escaped in all content-derived text. Embeds are never content-generated. |
| **Prompt injection** — `system: ignore previous instructions` | Content stays inert: it is never executed, and if later retrieved it flows through M7's DATA envelope unchanged. M9 adds no new instruction-bearing channel and does not weaken M7's guards. |
| **Path injection** | §10. |
| **Length/DoS** — a 10 MB field | Per-field truncation with an explicit `…[truncated]` marker, mirroring M7's `_MAX_FIELD_LEN` discipline. |
| **NUL / control characters** | Stripped before rendering. |

### 22.2 The structural rule

**Content is only ever emitted inside a value position that has been escaped for its context.** Content never determines a path, a link target, a tag, a frontmatter key, a fence length, or a note boundary. Every one of these comes from a closed enum or a deterministic generator. This is what makes the "memory as data" guarantee structural rather than best-effort.

---

## 23. Schema decision

### **Schema impact: NONE. Schema remains v9. No migration in M9.**

M9 introduces no table, column, index, or migration. All projection state lives in `managed_root/_meta/manifest.json` (§15.1). Rationale:

- Projection state is **derived and rebuildable** — the architecture prefers keeping such state out of the canonical/derived store when it has a natural home.
- The manifest must share the vault's lifecycle; a SQLite table would desynchronize the moment the vault is moved, deleted, or restored.
- Avoiding a migration removes all risk to the 2323-test canonical baseline.
- No canonical-vs-derived reclassification is needed.

If a future milestone needs cross-vault or cross-profile projection analytics, a derived `zm_projection_links` table can be added then, rebuildable from manifests — recorded as **Q8** but **not proposed for M9**.

---

## 24. API and invocation

### 24.1 Minimal internal API

New package `src/projection/` (no such module exists today — verified), following existing `src/m8/` conventions: frozen dataclasses, closed enums in a `vocabulary.py`, pure functions, no ambient state.

```text
src/projection/
├── __init__.py          # public surface: project(), ProjectionConfig, ProjectionRequest, ProjectionResult
├── contracts.py         # ProjectionConfig, ProjectionRequest, ProjectionResult, ProjectedNote,
│                        # ProjectionLink, NoteType, NoteStatus, ProjectionStatus
├── config.py            # resolution order (§2.2) + validation (§2.3)
├── paths.py             # slug(), safe_path(), containment + symlink invariant (§10)
├── identity.py          # note_id derivation (§9), reusing src/m8/identity helpers
├── render.py            # deterministic frontmatter + Markdown rendering, escaping (§22)
├── manifest.py          # manifest read/write, fingerprint compare, ownership test (§12/§15)
├── writer.py            # atomic write, retirement, dry-run (§25)
└── projector.py         # orchestration: authorize -> filter -> render -> diff -> write
```

Core types (shape, not implementation):

- `ProjectionConfig` — `vault_root`, `managed_dir_name`, `sensitivity_ceiling`, `note_types`, `retire_mode`, `dry_run`.
- `ProjectionRequest` — `requesting_profile_id`, `project_ids`, `knowledge_space_ids`, `resource_types`, `grants`.
- `ProjectionResult` — `status`, `reason`, `created/updated/skipped/retired/conflicted` counts, `notes`, `warnings`.
- `ProjectedNote` — `note_id`, `note_type`, `relative_path`, `content`, `content_fingerprint`, `links`.
- `ProjectionManifest` / `ProjectionLink` — §15.

No generic document framework, no plugin system, no template engine, no renderer registry.

### 24.2 Invocation (Q16)

**Explicit, operator-triggered, foreground, synchronous.** A CLI entry point under the existing `scripts/` convention:

```text
scripts/project_to_obsidian.py --project <id> --profile <id> [--dry-run] [--vault <path>]
```

Plus the in-process `project(config, request, service)` function for tests and future callers.

**No** background daemon, **no** filesystem watcher, **no** post-capture hook, **no** cron, **no** automatic projection on state change. Predictable control is the safety property: the vault only changes when the operator asks. `--dry-run` prints the full plan (create/update/skip/retire/conflict per note) and writes nothing — the default recommended first run against the real vault.

M9 adds **no new M6 tool**. Exposure through MCP is deferred; recorded as a non-goal.

---

## 25. Atomic write safety and concurrency

### 25.1 Atomic per-note write

```text
render -> validate (path invariant + frontmatter parses + fence balance)
       -> write to <target>.tmp-<note_id> inside the SAME managed directory
       -> fsync
       -> os.replace(tmp, target)        # atomic on POSIX, same filesystem
```

Same-directory temps guarantee same-filesystem atomicity and keep every intermediate file inside `managed_root`. No temp file in `/tmp`, no cross-device rename. On any validation failure the temp is removed and the target is untouched.

### 25.2 Crash behavior

Notes are written first, the manifest last (also atomically). A crash mid-run leaves some notes updated and a manifest describing the previous state — the next run detects the mismatch by fingerprint and converges. **A partial run never produces a misleading "current state"**: individual notes are always internally complete (never half-written), and the Project Home note — the one a human reads for current state — is written **last among notes**, so it is never newer than the records it summarizes. Orphan `.tmp-*` files inside `managed_root` are cleaned at the start of the next run.

### 25.3 Concurrency (Q16-adjacent)

A single **advisory lock file** at `managed_root/_meta/.projection.lock`, acquired with `O_CREAT|O_EXCL` (atomic on POSIX) and holding the owning PID:

- Second concurrent run → exits immediately with `status=BUSY`, writing nothing.
- Stale lock (PID not alive) → reclaimed with a reported warning.
- Human edits during a run → the run either wrote before the edit (next run detects `human_modified`/`edit_conflict`) or after (the human's editor may warn on save); either way **no silent lost update**, because the next run always compares on-disk fingerprints rather than assuming it owns the bytes.

No distributed locking, no lock server, no lease renewal — a local single-writer advisory lock is sufficient for a local vault.

---

## 26. Testing strategy

Tests live in `tests/unit/test_m9_*.py`, following existing naming, and are additive to the 2323-test canonical baseline.

### 26.1 Real-vault testing policy — MANDATORY

**Every automated test uses an OS-safe temporary vault** (`tempfile.mkdtemp()`), never the operator's real vault. This is enforced structurally, not by convention:

- Tests construct `ProjectionConfig` with an explicit `vault_root` pointing at a temp directory.
- A session-scoped guard fixture asserts `ZERO_MEM_OBSIDIAN_VAULT` is unset (or overrides it) so an operator env var can never leak into a test run.
- A guard test asserts no test artifact path resolves under `Documents/Obsidian`.

**Destructive, path-attack, symlink-escape, permission-failure, and crash-recovery tests must NEVER target the real vault.**

The real vault is touched exactly once, at **M9.6**, as a controlled final smoke test: `--dry-run` first, human review of the printed plan, then a single real projection of one project, then verification that `.obsidian/` and every human-owned path are byte-identical before and after. Requires explicit owner go-ahead at that point.

### 26.2 Test matrix

**Determinism** — same source → identical output; reversed insertion order → identical output; rebuild from clean → identical manifest, contents, filenames, links; no wall-clock value in any equivalence-sensitive file; `PYTHONHASHSEED` variation → identical output.

**Idempotence** — second unchanged run: zero writes, zero mtime change, zero `git diff` in a git-initialized temp vault, no duplicate sections, no filename churn.

**Path safety** — `..` traversal; absolute-path injection; `/` and `\` separator injection; NUL; encoded traversal; Unicode NFC/homoglyph/bidi/zero-width; reserved device names; trailing dot/space; 5000-char titles; case-only collision; **symlink escape** (symlinked category dir, symlinked file target, symlinked `managed_root` component) — every one must fail closed inside the temp vault.

**Canonical safety** — after any projection: JSONL byte-identical (hash before/after); SQLite unchanged (no writes; opened read-only); M4 truth-state unchanged; no lifecycle/verification/supersession mutation.

**Scope isolation** — cross-profile content never projected; cross-project never leaks; knowledge-space isolation; `resource_type` isolation (M6.6) preserved; denial produces no note and no existence signal.

**Sensitivity** — `secret` never projected at any ceiling; unknown sensitivity fails closed; canonical vocabulary honored (`public`/`internal`/`private`/`secret`); redacted content stays redacted; secret-pattern scan over the whole managed root returns zero hits; `stored_path` never appears.

**Human ownership** — human file inside `managed_root` preserved across create/update/retire cycles; manual edit detected; no silent overwrite; `edit_conflict` produces a sibling file and leaves the original byte-identical; file outside `managed_root` never touched; `.obsidian/` never touched.

**Provenance** — every note carries `source_trace_ids`, `note_id`, `projection_version`, `content_fingerprint`; manifest round-trips; frontmatter parses as valid YAML in every generated note.

**Conflicts** — unresolved stays unresolved; all authorized positions present; no winner chosen; unauthorized positions absent.

**Supersession** — only explicit M4 semantics; mtime/version/order/recency never infer supersession; chain navigable.

**Markdown injection** — frontmatter injection via `---` and `:`; wiki-link corruption via `[[`/`]]`/`|`; fence breakout; HTML/script; `![[embed]]`; tag injection; prompt-injection text (`system: ignore previous instructions`) present in a note stays inert DATA and, when retrieved via M7, remains DATA.

**Failure isolation** — read-only vault; permission denied mid-run; invalid/nonexistent/relative/`$HOME`/repo-root vault root; atomic-write interruption (simulated crash between note and manifest write); orphan temp cleanup; concurrent-run `BUSY`; stale lock reclaim. Every failure is sanitized, fails closed, and leaves the vault consistent.

**Dependency boundaries** — zero LLM calls (import/callsite assertion); zero network (socket guard fixture, as used in prior milestones); no Hermes core import; no embedding/vector library; no new third-party dependency (stdlib only — `pathlib`, `hashlib`, `json`, `unicodedata`, `tempfile`, `os`).

**Unconfigured** — no vault configured → `UNAVAILABLE`, zero directories created anywhere (asserted by snapshotting `cwd`, `HOME`, and `/tmp` before/after).

**M8 regression** — the full existing suite must stay green: M5 authorization, M6.6 `resource_type` isolation, M7 memory-as-DATA, M7 EvidenceSet 5+3 budget, M8 graph/temporal/calibration non-authority. M9 changes no existing file, so this is a pure additive-regression check.

---

## 27. Performance plan

Measured with `time.perf_counter` over temp-vault fixtures; reported as recorded measurements with a generous ceiling, not invented microsecond thresholds — matching the M8 approach.

| Scenario | Shape | Ceiling |
| --- | --- | --- |
| No-change incremental run | ~200 notes, nothing changed | < 2 s, **0 writes** |
| Single-note change | ~200 notes, 1 changed | < 2 s, **exactly 1 write** + manifest |
| Medium project projection | 1 project, ~200 notes, from clean | < 10 s |
| Full curated workspace rebuild | ~1000 notes, from clean | < 30 s |

The load-bearing assertions are the **write counts** (0 and 1), which prove idempotence and incrementality independently of machine speed. Cost must scale with **curated projection size**, not raw event volume — asserted by holding note count fixed while multiplying underlying event volume and confirming runtime does not scale with it.

---

## 28. Proposed increments

Six increments. The suggested decomposition was evaluated and **adopted with one substantive change**: path-safety and the config boundary are pulled entirely into M9.1 ahead of any file being written, because every later increment writes into a real vault and must inherit a proven-safe path layer. No increment writes to the operator's real vault except M9.6.

Each increment ends with: full canonical suite green under clean isolated HOME, an `acceptance-m9.N.md` artifact, and a STOP for review. **No increment auto-starts the next.**

---

### M9.1 — Projection contracts, config boundary, path-safety foundation

- **Objective:** establish `ProjectionConfig`/`ProjectionRequest`/`ProjectionResult`, the vault-root resolution contract, and the proven-safe path layer. No note is written by this increment.
- **Scope:** `src/projection/{__init__,contracts,config,paths,identity}.py`, `config/projection.yaml.example`.
- **Schema impact:** NONE.
- **Filesystem impact:** none beyond `managed_root` creation in temp vaults during tests. Nothing written to the real vault.
- **Authorization boundary:** none exercised yet; `requesting_profile_id` carried verbatim, never inferred.
- **Path/write safety:** the entire §10 invariant, implemented and adversarially tested before any writer exists.
- **Tests:** config resolution precedence; unconfigured → `UNAVAILABLE` + zero directory creation; invalid roots rejected; full path-attack matrix incl. symlink escape; `note_id` determinism and collision resistance; slug totality.
- **Regressions:** full suite green (purely additive).
- **Acceptance:** every path attack fails closed; unconfigured creates nothing anywhere; identity is reproducible across processes with varying `PYTHONHASHSEED`.
- **Non-goals:** rendering, writing, manifest, authorization.
- **Stop condition:** any path attack escaping `managed_root` → halt.
- **Commit boundary:** `feat(m9.1): projection contracts, vault config boundary, path safety`

---

### M9.2 — Deterministic project / state / decision / requirement projection

- **Objective:** first real notes — authorized, deterministic, safely rendered.
- **Scope:** `src/projection/{render,writer,projector}.py`; note templates for Project Home, Decision, Requirement, Current State.
- **Schema impact:** NONE.
- **Filesystem impact:** creates notes inside temp-vault `managed_root` only.
- **Authorization boundary:** M5 `AuthorizedReadService` for every read; denial ⇒ no note, no existence signal.
- **Path/write safety:** M9.1 layer + atomic write (§25.1).
- **Tests:** determinism; reversed-order equality; authorization filtering; scope isolation (profile/project/knowledge-space/`resource_type`); sensitivity ceiling with canonical vocabulary; `secret` never projected; the full Markdown/frontmatter injection matrix; canonical immutability (JSONL + SQLite byte-identical after run).
- **Regressions:** M5/M6.6 isolation tests unchanged and green.
- **Acceptance:** notes render deterministically; no unauthorized item appears; no injection corrupts a note; canonical untouched.
- **Non-goals:** manifest, incrementality, conflicts, human-edit handling, retirement.
- **Stop condition:** any cross-profile/project leak, or any canonical mutation → halt.
- **Commit boundary:** `feat(m9.2): deterministic project/state/decision/requirement projection`

---

### M9.3 — Provenance, links, conflict and supersession presentation

- **Objective:** make notes auditable and navigable; render conflicts and supersession honestly.
- **Scope:** provenance block in `render.py`; safe wiki-link generation; Conflict and Verification note types; Conflict Queue index.
- **Schema impact:** NONE.
- **Filesystem impact:** additional note types in temp vaults.
- **Authorization boundary:** links may only target notes the same request authorized — a link never reveals an unauthorized note's existence.
- **Path/write safety:** link targets are generated filenames only; never content-derived.
- **Tests:** provenance completeness (`source_trace_ids`/`note_id`/`projection_version` on 100% of notes); link-target safety and injection; unresolved conflict stays unresolved with all authorized positions and no winner; supersession only from explicit M4; mtime/recency/order never infer supersession; M8 calibration never rendered as truth.
- **Regressions:** M8 non-authority tests green.
- **Acceptance:** every note traces to canonical; no conflict silently resolved; no inferred supersession; no confidence-as-truth UI.
- **Non-goals:** manifest/versioning, incrementality.
- **Stop condition:** projection choosing a conflict winner, or a link leaking an unauthorized note → halt.
- **Commit boundary:** `feat(m9.3): provenance, safe links, conflict and supersession presentation`

---

### M9.4 — Manifest, versioning, deterministic rebuild, incremental updates

- **Objective:** the manifest and the create/update/skip/retire decision engine; prove rebuild equality and idempotence.
- **Scope:** `src/projection/manifest.py`; fingerprint diffing; retirement; orphan-temp cleanup; advisory lock.
- **Schema impact:** NONE (filesystem manifest, §15.1/§23).
- **Filesystem impact:** `_meta/manifest.json`; retirement deletes only three-signal-owned files.
- **Authorization boundary:** revoked authorization ⇒ retirement on next run.
- **Path/write safety:** manifest written atomically, last; deletion gated on the three-signal ownership test.
- **Tests:** rebuild-from-clean byte equality (A == B); idempotent second run with **zero** writes and empty `git diff`; single-change run writes exactly one note; retirement of deleted/archived/unauthorized; rename → no duplicate; crash between note and manifest write converges on next run; concurrent run returns `BUSY`; stale lock reclaim.
- **Regressions:** full suite green.
- **Acceptance:** A == B byte-for-byte; unchanged run performs zero writes; retirement never touches a human file.
- **Non-goals:** human-edit conflict semantics (M9.5).
- **Stop condition:** non-deterministic output, or any write during an unchanged run → halt.
- **Commit boundary:** `feat(m9.4): projection manifest, deterministic rebuild, incremental updates`

---

### M9.5 — Human ownership boundary and edit/write-back policy

- **Objective:** guarantee human-owned content is never destroyed, and edits are detected and quarantined — **without** any canonical write-back.
- **Scope:** three-signal ownership test; `human_modified` / `edit_conflict` handling; `.zero-mem-new.md` sibling; `_meta/projection-report.md`; `_meta/README.md`.
- **Schema impact:** NONE.
- **Filesystem impact:** sibling conflict files and the report, inside `managed_root` only.
- **Authorization boundary:** unchanged; a human edit grants nothing and changes no authority.
- **Path/write safety:** files failing any ownership signal are never written or deleted.
- **Tests:** human file inside `managed_root` survives create/update/retire; edited managed note never overwritten; `edit_conflict` leaves the original byte-identical and creates exactly one sibling; edited-but-source-unchanged → untouched, no sibling; `.obsidian/` and out-of-root files byte-identical after every operation; **no canonical mutation from any vault edit** (JSONL/SQLite/M4 hashes unchanged).
- **Regressions:** full suite green.
- **Acceptance:** zero silent overwrites; zero human-file deletions; **zero canonical writes originating from the vault**.
- **Non-goals:** proposal-based write-back (Q5, deferred beyond M9).
- **Stop condition:** any human-owned file modified or deleted, or any vault-originated canonical write → halt.
- **Commit boundary:** `feat(m9.5): human ownership boundary and edit-conflict policy`

---

### M9.6 — Hardening, performance, real-vault smoke, final M9 acceptance

- **Objective:** close M9 with adversarial hardening, measured performance, and the single controlled real-vault projection.
- **Scope:** `scripts/project_to_obsidian.py`; failure-isolation hardening; performance harness; `runbooks/m9-projection.md` (operation, dry-run, rollback = delete `managed_root` and re-run); `acceptance-m9.md`.
- **Schema impact:** NONE.
- **Filesystem impact:** **the only increment permitted to write to the operator's real vault**, and only after: (1) all temp-vault tests green, (2) a `--dry-run` whose printed plan the owner reviews, (3) explicit owner go-ahead.
- **Authorization boundary:** the real-vault run uses one explicit profile and project; nothing global.
- **Path/write safety:** pre/post byte-identity verification of `.obsidian/` and every pre-existing vault path.
- **Tests:** read-only vault; permission denied; disk-full simulation; dependency-boundary assertions (zero LLM, zero network, no Hermes core, no embeddings, no new dependency); the §27 performance matrix; the complete regression suite.
- **Regressions:** full canonical suite twice — pre-binding and FINAL-HEAD post-binding (authoritative).
- **Acceptance:** all M9.1–M9.6 criteria hold; real-vault smoke leaves every human-owned path and `.obsidian/` byte-identical; performance ceilings met with 0/1 write counts; M9 marked VERIFIED with committed evidence.
- **Non-goals:** M10 corpus ingestion; MCP tool exposure; write-back.
- **Stop condition:** any real-vault run altering a non-managed path → immediate halt and rollback.
- **Commit boundary:** `feat(m9.6): hardening, performance, real-vault smoke, M9 acceptance`

---

## 29. Open approvals

Resolved with a recommendation, but **all require owner sign-off before M9.1**.

| # | Question | Recommendation | Status |
| --- | --- | --- | --- |
| Q1 | Curated note types | Project Home, Decision, Requirement, Verification, Conflict, Artifact ref, Knowledge index. System/Profile/Candidate Review deferred. | **APPROVAL REQUIRED** |
| Q2 | Managed root inside vault | `<vault>/Zero-Mem/` | **APPROVAL REQUIRED** |
| Q3 | Whole-vault vs subtree | **Subtree** (option B) | **APPROVAL REQUIRED** |
| Q4 | Human edit semantics | Detect, never overwrite, quarantine as `edit_conflict` | Recommended |
| Q5 | Write-back | **Projection-only in M9**; proposal export deferred | **APPROVAL REQUIRED** |
| Q6 | Version granularity | Per-note fingerprint + global `projection_version` | Recommended |
| Q7 | Manifest representation | Filesystem `_meta/manifest.json` | **APPROVAL REQUIRED** |
| Q8 | v9 vs v10 | **v9 — NONE** | **APPROVAL REQUIRED** |
| Q9 | Auto-project eligibility | `active`/`confirmed`/`superseded`/`conflicted`/`archived`; never `deleted` | Recommended |
| Q10 | Human-approval eligibility | `raw`/`observed`/`candidate` excluded by default | **APPROVAL REQUIRED** |
| Q11 | Conflict rendering | All authorized positions, no winner, warning callout | Recommended |
| Q12 | Supersession rendering | Keep superseded notes, marked, linked; explicit M4 only | Recommended |
| Q13 | Filename identity | `slug(title)[:80] + "--" + note_id_suffix + ".md"` | Recommended |
| Q14 | Incremental invalidation | Content fingerprint; no separate backlink index | Recommended |
| Q15 | Stale-note retirement | Delete managed file + manifest `retired`; `tombstone` mode offered | **APPROVAL REQUIRED** |
| Q16 | Invocation | Explicit CLI + in-process call; no daemon/watcher | Recommended |
| Q17 | Performance targets | §27 table; 0/1 write-count assertions load-bearing | Recommended |
| Q18 | Sensitive-content policy | Canonical vocabulary; ceiling `internal`; `secret` never; unknown fails closed | **APPROVAL REQUIRED** |
| **Q18-A** | **M7.3 sensitivity vocabulary defect (§1.2)** | **Fix separately, before or independently of M9; not inside M9** | **DECISION REQUIRED** |
| Q19 | Cross-profile/project composition | Per-item M5 authorization; co-location grants nothing | Recommended |
| Q20 | May Obsidian edits enter canonical state in M9? | **NO** | **APPROVAL REQUIRED** |

---

## 30. Final M9 acceptance criteria

M9 is VERIFIED only when **all** hold, each backed by executable evidence:

1. M9.1–M9.6 each VERIFIED with a committed `acceptance-m9.N.md`.
2. Full canonical suite green under clean isolated HOME, run **twice** — pre-binding and FINAL-HEAD post-binding (authoritative) — with no regression against the 2323-test M8 baseline.
3. Deterministic rebuild proven: A == B byte-for-byte across manifest, contents, filenames, links, metadata.
4. Idempotence proven: unchanged re-run performs **zero** writes and produces an empty `git diff`.
5. Path safety proven: the entire §10 attack matrix fails closed, including symlink escape.
6. Canonical immutability proven: JSONL and SQLite byte-identical before/after every projection.
7. Authorization preserved: no cross-profile, cross-project, cross-knowledge-space, or `resource_type` leak; denial reveals no existence.
8. Sensitivity preserved: `secret` never projected; unknown fails closed; secret-pattern scan over the managed root returns zero hits.
9. Human ownership proven: no human-owned file ever modified or deleted; `.obsidian/` untouched; edit conflicts quarantined, never overwritten.
10. No write-back: zero canonical mutations originating from vault edits.
11. Conflicts remain visibly unresolved; supersession only from explicit M4.
12. Memory-as-DATA preserved: injection payloads inert; M7 guarantees unweakened.
13. Zero LLM calls, zero network calls, no embeddings, no new dependency, **no Hermes core change**.
14. Schema remains **v9**; no migration.
15. Real-vault smoke completed with `.obsidian/` and every human-owned path byte-identical before and after.
16. Runbook and rollback documented (rollback = delete `managed_root`, re-run; canonical unaffected).
17. `project-state.yaml` and `implementation-plan.json` updated only after acceptance passes.

---

## 31. Planning-turn attestation

- Real Obsidian vault modified during planning: **NO** (read-only `test -d` / `ls -la` only).
- Product source modified: **NO**.
- Migrations created: **NO**. Schema changed: **NO** (remains v9).
- Projected Markdown notes created: **NO**.
- M9 tests created: **NO**.
- M9 implementation started: **NO**.
- M10: **NOT STARTED**.
- Defect found in prior verified milestone (M7.3): **reported in §1.2**, dispositioned out of M9 scope, tracked as Q18-A.
