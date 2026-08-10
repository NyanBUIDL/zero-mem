# Acceptance — M9.1: Projection contracts, configuration boundary, path-safety foundation

**Status: VERIFIED**
**Milestone M9 (Obsidian projection): IN PROGRESS**

---

## 1. Scope and authority

| Item | Value |
| --- | --- |
| Increment | M9.1 — Projection contracts, config boundary, path-safety foundation |
| Plan authority | `plan-m9.md` §2, §6, §9, §10, §11, §12, §14, §26, §29 (owner-approved) |
| Master spec | `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §12, §14, §17.3 |
| Starting HEAD | `d4891560adfe5f619b9c5c9fcedf2321601a4bd4` |
| Implementation/Tested commit | `532f9efd9e17a9a1a99ac857b1cee89994707319` |
| Evidence/state-binding commit | see §12 |
| Schema version | **v9 — unchanged** (no migration, no projection table) |
| Prior state | M0–M8 VERIFIED; M7.3 corrective fix VERIFIED (`1cb67aa`) |

M9.1 establishes the safe foundation on which all later Obsidian projection
writes depend. It **projects no content**: no Project Home, Decision,
Requirement, Verification, Conflict, Artifact, Research, or Knowledge Index note
is generated, and no production projection pipeline exists yet.

---

## 2. Files changed

### Product code (new)

| File | Purpose |
| --- | --- |
| `src/projection/__init__.py` | Package surface + architectural invariants; `PROJECTION_SCHEMA_VERSION = 9` |
| `src/projection/contracts.py` | Closed vocabularies, request/result/note contracts, sanitized errors, sensitivity policy, three-signal ownership |
| `src/projection/identity.py` | Deterministic note identity, total path-safe slug, content fingerprints |
| `src/projection/paths.py` | Managed-root resolution, physical containment, symlink-escape rejection, constructive safe-path builders |
| `src/projection/config.py` | Explicit-only vault configuration and validation |
| `config/projection.yaml.example` | Operator configuration template (no operator path) |

### Tests (new)

| File | Tests |
| --- | --- |
| `tests/unit/test_m9_1_config.py` | Configuration boundary, unconfigured safety, invalid roots, portability |
| `tests/unit/test_m9_1_paths.py` | Managed root, component validation, traversal matrix, symlink escape, ownership |
| `tests/unit/test_m9_1_identity.py` | Identity determinism, slug totality, filenames, fingerprints |
| `tests/unit/test_m9_1_security.py` | Sensitivity contract, frozen contracts, static security audit, zero side effects |

**No existing product module was modified.** No Hermes core change. No schema
change. No new third-party dependency.

---

## 3. Contracts implemented

**Closed vocabularies**

- `NoteType` — exactly the eight owner-approved §29 Q1 curated types
  (`project`, `decision`, `requirement`, `verification`, `conflict`, `artifact`,
  `research_note`, `knowledge_index`). Vocabulary and directory mapping only;
  **no renderer for any type**.
- `NoteStatus` — `current` / `retired` / `edit_conflict` / `human_modified`.
- `ProjectionStatus` — `ok` / `unavailable` / `busy` / `failed`.

**Value contracts**

- `ProjectionRequest` — carries an explicit `requesting_profile_id`
  (`None` stays `None` = unbound caller); validates resource types against the
  authoritative M5 `RESOURCE_TYPES`; `grants` is an opaque passthrough that M9.1
  never inspects.
- `ProjectedNote` — binds `content_fingerprint` to `content` (a mutated body can
  never travel with a stale fingerprint); `relative_path` is managed-root
  relative and rejects absolute paths, `..`, backslashes, and NUL, so a note
  value cannot smuggle a write target.
- `ProjectionResult` — counts + sanitized reason codes; `unavailable()` is the
  safe silent state.
- `ProjectionError` / `ProjectionConfigError` / `ProjectionPathError` /
  `ProjectionVocabularyError` — messages carry a stable reason code only, never
  the offending path, payload, or operator directory name.

**Versions:** `PROJECTION_VERSION = 1` (renderer contract),
`M9_CONTRACT_VERSION = "m9.1"`, `PROJECTION_IDENTITY_VERSION = "v1"`.

**Deliberately absent at M9.1:** `project()`, `render()`, `write()`, `retire()`,
`authorize()`, manifest behaviour, and any `retire_mode` knob — each is asserted
absent by `TestNonScope`.

---

## 4. Configuration contract

Resolution order (plan-m9.md §2.2), explicit-only:

1. explicit argument to `ProjectionConfig` / `load_projection_config`;
2. environment variable `ZERO_MEM_OBSIDIAN_VAULT`;
3. project-local `config/projection.yaml`, key `vault_root`;
4. nothing configured → `None` → `ProjectionStatus.UNAVAILABLE`.

**No operator path in source.** Static audit asserts `src/projection/` contains
no `/home/`, no `/Users/`, no username, no `Documents/Obsidian`, no
`Path.home()`, no `expanduser`, no `~/Obsidian`, no `os.getcwd`, no `Path.cwd`,
and no hard-coded `/tmp`.

**Unconfigured is normal, safe, and silent.** Verified that nothing is created
in `cwd`, `$HOME`, the repository, a temp directory, or an invented
`~/Obsidian`, and no exception escapes.

**Rejected vault roots** (each with a sanitized reason): relative, `~` form,
nonexistent, a file, a symlink, the home directory, the repository root, an
`.obsidian` directory, a path containing NUL, a non-writable directory.

The config-file reader is a minimal stdlib `key: value` parser — **PyYAML is
deliberately not imported** (§26.2, no new dependency for one scalar) and any
structure it does not understand fails closed.

---

## 5. Managed-root rules

- **Subtree only** (§29 Q2/Q3): M9 owns `<vault_root>/Zero-Mem/` and nothing
  else. The vault root itself is never a write target.
- Managed root must be a strict physical descendant of the vault root; it is
  **not created** by M9.1.
- `.obsidian/` can never be the managed directory and is outside every managed
  root; `is_obsidian_config_path()` provides defence in depth.
- Traversal, absolute injection, separators, and a symlinked managed root are
  all rejected at resolution time.
- A sibling prefix directory (`Zero-Mem-Other/`) is **not** inside `Zero-Mem/`.

---

## 6. Path-safety rules

**Invariant:** the *physical* target must be inside the approved managed root —
not merely a string that begins with it.

Enforcement order in `assert_within_managed_root`: absolute-path check → explicit
symlink walk of the whole chain (**before** any resolution) → `os.path.realpath`
containment (valid for not-yet-existing paths) → strict-descendant check.

Rejected by the component validator: `..`, `.`, empty, `/`, `\`, NUL, control
characters, `C:` drive letters, any colon, mixed separators, leading/trailing
whitespace, leading dots, trailing dots/spaces, over-long names, and Windows
reserved device names (`CON`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`).

**Content-controlled text never determines a path.** A note path is
*constructed* from a closed category enum + sanitized scope slug + identity-derived
filename. Hostile titles (`../../secret`, `/home/user/file`, `A/B/C`,
`..\..\foo`, `CON`, `NUL`, bidi overrides, zero-width characters, NFC/NFD pairs,
`#tag [[link]] |pipe`, `---\nfake: yaml`, 5000 characters, NUL) were each proven
to stay inside `Zero-Mem/Decisions/<scope>/` and contribute only to the display
half of the leaf filename.

Bounds: depth ≤ 3, relative path ≤ 240 bytes, component ≤ 112 characters.

---

## 7. Symlink protection (load-bearing)

Every case rejected **before** any write is attempted (nothing in the module
writes at all):

| Case | Result |
| --- | --- |
| `Zero-Mem/safe-link -> /outside`, write `safe-link/file.md` | rejected `symlink_on_path_chain` |
| Nested `Decisions/proj -> /outside` | rejected |
| Existing parent symlink `Decisions -> /outside` | rejected |
| Target filename beneath escaping symlink (`Artifacts -> /outside`) | rejected |
| File symlink `note.md -> /outside/outside.md` | rejected |
| Managed root itself a symlink to outside | rejected `managed_root_is_symlink` |
| Symlink pointing back *inside* the managed root | rejected (ownership must stay decidable) |

`test_lexical_check_alone_would_have_passed` proves the guard is physical:
`Path.is_relative_to()` returns `True` for the escaping path while
`is_within_managed_root()` returns `False`.

`test_rejection_happens_before_any_write` confirms the outside directory is
unchanged and no file was created there.

---

## 8. Sensitivity rules

Uses the **one canonical vocabulary** — `SENSITIVITY_ORDER` is derived
programmatically from `src/capture/event_types.py::Sensitivity`, so a second
ladder cannot drift into existence (the M7.3 defect class is structurally
prevented).

| Rule | Enforced |
| --- | --- |
| Default projection ceiling | `internal` |
| `public` at `internal` ceiling | projectable |
| `internal` at `internal` ceiling | projectable |
| `private` at `internal` ceiling | excluded |
| `secret` at **any** ceiling | unconditionally excluded |
| Unknown/malformed sensitivity | fails closed (excluded) |
| Unknown/malformed ceiling | fails closed (excludes everything) |
| `secret` as a ceiling | rejected outright |
| Memory text attempting to raise the ceiling | ineffective (treated as data) |

**M7 retrieval default remains `private`; M9 projection default is `internal`.**
`test_m7_retrieval_default_ceiling_unchanged` asserts both values and that they
differ — the M7.3 corrective fix is untouched and not duplicated.

Eligibility here is **necessary, never sufficient**: M5 authorization and the
full §7.2 filter still gate any future note.

---

## 9. Ownership foundation

Three-signal test (§12.1) via `OwnershipSignals`: `inside_managed_root` **and**
`has_managed_marker` **and** `listed_in_manifest`. Every two-of-three
combination returns `False`.

- Path containment alone is exposed as `path_ownership_signal()` — named a
  *signal*, never a decision.
- `test_existing_human_file_at_generated_target_is_not_claimed`: a human file
  sitting exactly at a generated target path is **not** owned and its content is
  unchanged — a filename collision is never ownership.
- `.obsidian/` paths are rejected by containment.
- M9.1 deletes nothing and retires nothing; the manifest signal is materialized
  by M9.4 and consumed by M9.5.

---

## 10. Real-vault non-modification proof

Operator vault: `~/Documents/Obsidian/Zero-Mem` (runtime configuration; never
referenced in product source or tests).

Before/after metadata listings (`type size mtime path`) captured under
`/tmp/hermes-verify-m91/`:

```
=== VAULT DIFF ===      -> IDENTICAL   (6 entries)
=== .obsidian DIFF ===  -> IDENTICAL   (5 entries)
$ ls -a <vault>         -> .  ..  .obsidian
```

- **Real vault modified: NO** — byte-for-byte identical listing.
- **`.obsidian/` modified: NO** — identical listing.
- No `Zero-Mem/` managed directory was created in the real vault.
- No mkdir, touch, write, rename, delete, manifest, note, or permission change.

All write/path/security tests used `tempfile.TemporaryDirectory(prefix="hermes-verify-m91-")`.

---

## 11. Security and boundary audit

Enforced by executable static tests over `src/projection/*.py` (AST-based,
docstrings and comments stripped):

| Guarantee | Evidence |
| --- | --- |
| Routine LLM calls | **0** — no LLM/embedding SDK importable or referenced |
| Routine external network calls | **0** — no `requests`/`httpx`/`urllib`/`socket`/`http`, no URL literal |
| New third-party dependency | **NONE** — stdlib + `src.capture` / `src.m8` only (no PyYAML) |
| Authorization reach | none — no `GrantAdmin*`, no `Authorized*Service`, no `src.access` import, no `def authorize`/`can_read` |
| Identity inference | none — no `getuser`, no `getpass`, no `HERMES_PROFILE_ID`/`HERMES_PROJECT_ID` |
| Canonical store access | none — no `src.storage`, no JSONL, no `sqlite3` |
| Write operations | none — no `open(`, `write_text`, `mkdir`, `shutil`, `unlink`, `rename`, `touch` |
| Schema change | none — no `CREATE TABLE`, `ALTER TABLE`, or migration |
| Hermes core change | none — no `import hermes` |
| Write-back surface | none — no `write_back`/`propose_change`/`apply_edit` |
| Subprocess / eval | none in product code |

**Zero side effects:** SHA-256 of `project-state.yaml` and
`implementation-plan.json` identical before/after exercising configuration and
path resolution; a temp-vault tree snapshot is unchanged after building config
and resolving note/meta paths.

---

## 12. Test evidence

Interpreter: `.venv/bin/python3` (Python 3.11.15), normal terminal execution.

**Focused M9.1**

```
$ .venv/bin/python3 -m pytest tests/unit/test_m9_1_config.py \
    tests/unit/test_m9_1_paths.py tests/unit/test_m9_1_identity.py \
    tests/unit/test_m9_1_security.py -q
292 passed in 1.12s
```
**292 passed, 0 failed.**

**Relevant regressions** (explicit files; no `-k` subset expression)

```
$ .venv/bin/python3 -m pytest \
    tests/unit/test_m1_capture_boundary.py tests/unit/test_m1_event_contract.py \
    tests/unit/test_m1_redaction.py tests/unit/test_m5_access_policy.py \
    tests/unit/test_m5_authorized_read.py tests/unit/test_m5_cross_profile.py \
    tests/unit/test_m5_grants.py tests/unit/test_m5_linked.py \
    tests/unit/test_m5_policy_rebuild.py \
    tests/unit/test_m7_3_sensitivity_vocabulary.py \
    tests/unit/test_m7_3_evidence_builder.py tests/unit/test_m7_5_hardening.py \
    tests/unit/test_m8_6_integration.py tests/baseline/ -q
458 passed in 2.40s
```
**458 passed, 0 failed** (M1 path/config safety, M5 authorization boundaries,
M7.3 sensitivity vocabulary, M7.5 hardening, M8.6 integration, baseline gates).

**Pre-binding canonical** (clean isolated HOME, at `532f9ef`)

```
$ OLD_HOME="$HOME"; TEST_HOME="$(mktemp -d)"; export HOME="$TEST_HOME"
$ .venv/bin/python3 -m pytest tests/ -q
2645 passed, 3 skipped in 21.12s
$ export HOME="$OLD_HOME"; rm -rf "$TEST_HOME"
```
**2645 passed, 3 skipped, 0 failed** — no deselection, no new skip/xfail.
Baseline was 2353 passed; 2353 + 292 new M9.1 tests = **2645** exactly.

**Final-head canonical** — see §14.

**Known historical skips: 3** (unchanged pre-existing baseline).

---

## 13. Baseline gate advance

`tests/baseline/test_project_artifacts.py` asserted the M8-complete state
(`plan["status"] == "m8_verified"`, `next_incomplete_milestone == "M9"`,
`m9_status: "not_started"`). The legitimate M9.1 state transition makes those
assertions objectively stale, exactly as happened at M8.1 (corrective commit
`de0de0f`). The gate is advanced to the M9.1-bound state in the evidence commit:

- `plan["status"] == "m9_in_progress"`, `current_milestone_status == "m9_in_progress"`
- `plan["m9_increment_1_status"] == "verified"`, `m9_next_incomplete_increment == "M9.2"`
- `plan["m9_schema_version"] == 9`, `next_incomplete_milestone == "M9"`
- `project-state.yaml`: `m9_overall_status: "in_progress"`,
  `m9_increment_1_status: "verified"`, `m9_increment_2_status: "not_started"`,
  `m10_status: "not_started"`

No gate was weakened or removed; M8 assertions are preserved intact.

---

## 14. Closure

| Marker | Value |
| --- | --- |
| M9.1 | **VERIFIED** |
| M9 overall | **IN PROGRESS** |
| Schema version | **9** |
| Starting HEAD | `d4891560adfe5f619b9c5c9fcedf2321601a4bd4` |
| Implementation/Tested commit | `532f9efd9e17a9a1a99ac857b1cee89994707319` |
| Evidence/state-binding commit | recorded at commit time |
| Focused M9.1 | 292 passed, 0 failed |
| Relevant regressions | 458 passed, 0 failed |
| Pre-binding canonical | 2645 passed, 3 skipped, 0 failed |
| Real vault modified | **NO** |
| `.obsidian/` modified | **NO** |
| Routine LLM calls | **0** |
| Routine external network calls | **0** |
| Hermes core changes | **NONE** |
| M9.2 | **NOT STARTED** |
| M10 | **NOT STARTED** |

**Next: M9.2 — Deterministic project / state / decision / requirement projection.
DO NOT BEGIN UNTIL APPROVED.**
