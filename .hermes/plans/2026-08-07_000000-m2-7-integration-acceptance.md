# M2.7 — Full M2 Integration Verification and Final Acceptance

**Status:** PLAN (final M2 increment)
**Milestone:** M2 (increment 7)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (DOCX authoritative); `implementation-plan.json` (plan); `project-state.yaml` (state).
**Predecessor state:** M2.1–M2.6 VERIFIED; schema v6; Decision B recorded; canonical 318 passed, 3 skipped; working tree clean; HEAD `96d1e9a`.
**Scope:** Integration verification + final acceptance of M2 as a whole. **No new product features. No M2.1–M2.6 redesign.** Only the smallest correction if a verified integration defect appears.

## Objective

Prove that the M2 derived layer (migrations 1–6, ingestion, lifecycle/verification projection,
relations/scopes/artifact registry, relational indexes, FTS5 over sanitized content, retention
tombstones / logical deletion) behaves coherently end-to-end and reproduces identical derived state
across incremental ingestion vs `rebuild_from_jsonl`, repeated rebuilds, and repeated ingestion —
while canonical JSONL stays byte-for-byte immutable and no secret, no ranking, no M3 behavior exists.

## Architectural rules (unchanged from M0/M2)

1. JSONL is the authoritative append-only source of record.
2. SQLite is derived, disposable, non-canonical, rebuildable.
3. M2.7 must not physically delete, truncate, rewrite, reorder, or compact canonical JSONL.
4. Logical deletion only (Decision B): tombstone events reproduce deleted state; canonical JSONL immutable.
5. No LLM/network calls. No writes to real `~/.hermes`. No installed-Hermes source modification.
6. No M3 behavior (retrieval ranking, query routing, semantic/vector retrieval, memory selection,
   prompt/context injection, profile authorization policy, MCP, Obsidian sync).

## Integration fixtures (representative canonical JSONL corpus)

A single corpus file `corpus.jsonl` (temp dir) with this exact composition:

- valid records across lifecycle states: `raw, observed, candidate, confirmed, active, superseded,
  conflicted, archived, deleted` (the `deleted` ones are tombstone/deletion events).
- duplicate event IDs (same `event_id`, same content) → `DUPLICATE_EVENT_ID`.
- duplicate content hashes (different `event_id`, same `sanitized_content_hash`) → `DUPLICATE_CONTENT_HASH`.
- event-ID/content conflicts (same `event_id`, different content) → `EVENT_ID_CONTENT_CONFLICT`.
- one malformed record (invalid JSON or missing required field) → `INVALID_RECORD`, ingestion continues.
- supersession pair: two `active` events on the same `active_key` → first `superseded`, `supersedes` edge.
- relations: `parent_trace_id` (→ `child_of`) and explicit `relation_ids` (→ `derived_from`).
- scopes: `project_id`, `profile_id`, and a `knowledge_space` mapping (via explicit scope field if present).
- artifact references: `artifact_refs`/`related_artifacts` carrying `artifact_id` + `content_hash`.
- sanitized FTS content: `sanitized_content` present on several records.
- retention values: `temporary, session, persistent` (never `never_store` — M1 captures RAM-only).
- known-target tombstones: deletion event whose `target_event_id` already present → `applied`.
- unknown-target tombstones: deletion event whose target arrives later (out-of-order) → `pending_unknown_target` then `applied`.
- repeated tombstones: same `deletion_event_id` appearing twice → second is `DUPLICATE_EVENT_ID`.

All fixtures use synthetic `event_id`/`trace_id`. Secret corpus = `SK-M2-7-PROBE-XYZZY` (synthetic).

## Exact commands

1. Focused M2.7 integration tests:
   `.venv/bin/python -m pytest tests/unit/test_m2_integration.py -q`
2. All M2 focused test files:
   `.venv/bin/python -m pytest tests/unit/test_m2_sqlite_foundation.py tests/unit/test_m2_ingest.py tests/unit/test_m2_rebuild.py tests/unit/test_m2_relations.py tests/unit/test_m2_indexes.py tests/unit/test_m2_tombstones.py tests/unit/test_m2_integration.py -q`
3. Migration-focused tests:
   `.venv/bin/python -m pytest tests/unit/test_m2_sqlite_foundation.py -q`
4. Complete normal canonical suite (no deselect):
   `.venv/bin/python -m pytest tests/ -q`

## Parity definitions

`verify_rebuild_parity(store_a, store_b)` already compares (see `src/storage/ingest.py`):
`zm_meta`, `zm_lifecycle`, `zm_provenance`, `zm_relations`, `zm_scopes`, `zm_artifacts`,
`zm_tombstones`, `zm_deletion_audit`, and `zm_fts` (when FTS5 available). M2.7 reuses it directly.

Incremental vs rebuild (§2): build `inc` via `ingest_file` over `corpus.jsonl`; build `reb` via
`rebuild_from_jsonl([corpus.jsonl])`. Assert `verify_rebuild_parity(inc, reb) is True`.
Add explicit table-level comparisons for `zm_ingest_checkpoint` (last_line_number + consumed_prefix_hash
must match when both consumed the same lines) and `zm_ingest_log` outcome counts (semantic equality:
same multiset of `(outcome, line_number)` modulo nondeterministic path column).

Repeated rebuild (§3): `rebuild_from_jsonl` twice; assert `verify_rebuild_parity` True and
row counts identical (no duplicate rows).

Repeated ingestion (§4): `ingest_file` twice on a fresh store; assert `count_metadata` unchanged,
no duplicate `zm_relations`/`zm_scopes`/`zm_artifacts`/`zm_tombstones`, and checkpoint
`last_line_number`/`consumed_prefix_hash` identical (first-write-wins).

## Migration-path verification (§9)

Reuse `tests/unit/test_m2_sqlite_foundation.py`:
- fresh `ensure_schema()` → v1..v6 deterministic.
- reopen at v6 idempotent.
- unknown future version (ledger `CURRENT_SCHEMA_VERSION + 1`) rejected without mutation.
- adjacent downgrades `v6→v5`, `v5→v4`, `v4→v3`, `v3→v2`, `v2→v1` all work.
- failed migration (injected `OperationalError`) does not partially advance schema version.

## Crash / resume verification (§10)

Use the existing checkpoint + consumed-prefix integrity in `ingest_file`:
- **crash before commit**: simulate by raising inside the per-line transaction → `transaction_failed`,
  checkpoint NOT advanced (reuse `test_m2_ingest.py::test_transaction_failed_*` pattern).
- **crash after commit**: committed lines persist; re-run `ingest_file` does not reinsert (idempotent
  by `event_id`).
- **explicit resume**: append new valid lines to `corpus.jsonl`; re-run `ingest_file`; only the new
  lines are processed (checkpoint advances to new last line).
- **consumed-prefix integrity**: (a) append-only growth (new lines added after checkpoint) is accepted;
  (b) modifying bytes within the consumed prefix → `source_changed` (consumed_prefix_mismatch),
  ingestion halts; (c) truncating below the checkpoint → `source_changed` (truncation_below_checkpoint),
  ingestion halts. Both are SAFE stops, no silent merge (reuse `test_m2_ingest.py` source-integrity tests).
M2.7 adds one integration test that drives these through the representative corpus.

## Secret-scan verification (§11)

- Normal run: `scan_sqlite_for_secrets(store, [SECRET]) == []` after ingesting the corpus
  (clean sanitized content only).
- Injected: insert a synthetic secret into `zm_meta` (a benign column), into `zm_tombstones`, and into
  `zm_deletion_audit` fixtures; assert `SECRET` is detected by `scan_sqlite_for_secrets`.
- Diagnostics: assert `SECRET` is NOT present in `str(report)` or `str(report.failures)`.
- Acceptance artifacts / test output: the M2.7 test file itself must not print `SECRET` (use `caplog`
  or assert on returned structures only).

## JSONL immutability (§12)

Record `hashlib.sha256(corpus.read_bytes())` and `len(corpus.read_bytes())` before and after every
operation (`ingest_file`, `rebuild_from_jsonl`, re-ingest, append-then-resume). Assert equality except
for the explicit append-resume case where the appended bytes are themselves the new canonical event.
No M2 operation rewrites/truncates/reorders/compacts/deletes the canonical file.

## Real ~/.hermes isolation (§13)

Baseline-aware: capture exact real `~/.hermes` entry set; run all operations with an isolated
temporary `HERMES_HOME` (and store paths explicitly under `tmp_path`); assert real `~/.hermes`
unchanged after, excluding only the unrelated `kanban.db*` sidecar family mutated by a background
process. Do NOT globally ignore every `.wal`/`.shm`/`.journal`.

## Cleanup verification (§ cleanup)

M2.7 test uses `tmp_path` (pytest auto-cleaned). Any ad-hoc verifier scripts use `tempfile` with the
`hermes-verify-` prefix and are removed before committing. No caches/`__pycache__` committed; run
`find . -name __pycache__ -type d -prune -exec rm -rf {} +` at the end.

## Final state-binding procedure

1. Mark M2.7 VERIFIED and M2 VERIFIED in `project-state.yaml` (`m2_increment_7_status`, `m2_status: verified`).
2. Append `increment_7` to `implementation-plan.json` (status verified, evidence, commits, counts).
3. Write `acceptance-m2-final.md` (full M2 final acceptance evidence, cross-referencing M2.1–M2.6).
4. Commit evidence + state (final evidence/state-binding commit).
5. Run `.venv/bin/python -m pytest tests/ -q` once more on final HEAD; confirm clean tree.

## Rollback and failure reporting

- M2.7 introduces NO schema change (schema stays v6). Rollback of M2.7 is a pure test/evidence revert.
- If a verified integration defect requires a smallest correction to M2.1–M2.6, fix only that,
  document it in `acceptance-m2-final.md`, and re-run the full suite before marking M2 VERIFIED.
- M1 timing flake (`test_mapping_is_deterministic`) is a SEPARATE maintenance task: if it fails during
  the canonical run, stop M2.7 before final verification, apply the smallest deterministic-time fix in
  a separate M1 maintenance commit, then re-run. Do not deselect or weaken the test.

## Explicit exclusions (no M3 / no new behavior)

No retrieval ranking, no query routing, no semantic/vector retrieval, no memory selection, no
prompt/context injection, no profile authorization policy, no MCP, no Obsidian synchronization,
no physical purge of canonical JSONL, no retention scheduler.
