# M4.7 — Final Acceptance Evidence (Rebuild, performance, final M4 acceptance)

Authoritative spec: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
Approved M4 plan: `.hermes/plans/2026-08-07_000004-m4-project-memory-plan.md`
Prior increments: M4.1–M4.6 VERIFIED (commits on record); M4.6 impl `bd13beb`,
state/evidence `ef0e8cbb` / `e184e81`.

## STATUS: M4.7 — PARTIAL

All M4.7 product gates pass. The FINAL canonical 0-failed hard gate is NOT met
because the external Hermes sidecar writes to real `~/.hermes` during the run,
causing the environmental real-home isolation flake (`test_no_real_hermes_home_writes`).
The sidecar is the Hermes desktop application, which is this agent's own runtime
host; it cannot be safely stopped without ending the session, so the directive's
isolation step (stop/isolate the sidecar) cannot be performed. Per the directive's
escape clause, M4.7 remains PARTIAL and M4 is NOT marked VERIFIED.

## Implementation committed

- `30683b1` — feat(m4.7): deterministic rebuild + idempotent charter update +
  test isolation fixes
  - `src/project_memory/rebuild.py` (NEW): `rebuild_project_memory`,
    `rebuild_all_project_memory`, `event_to_op`. Reprojects the six M4 derived
    tables from canonical JSONL events carrying an explicit `m4` block. The SAME
    per-event projection loop drives both the incremental and full-rebuild paths,
    so incremental==rebuild is structural. `rebuild_all_project_memory` drops the
    six M4 tables and recreates them via `migrate_7.up` directly (because
    `ensure_schema()` is a no-op once the v7 ledger row exists — without this fix
    a full rebuild would leave the six tables missing).
  - `src/project_memory/projector.py`: fixed a real idempotence defect — charter
    `update` previously always bumped `version` even when content was identical,
    making replay non-deterministic (a second replay created a new version). Now
    an `update` whose content already equals the current row is a no-op (version
    preserved), making rebuild deterministic and idempotent.
  - `src/project_memory/__init__.py`: exports the rebuild API.
  - `tests/unit/test_m4_rebuild.py` (NEW, 17 tests): the full M4.7 acceptance matrix.
  - `tests/unit/test_m4_read.py`, `tests/unit/test_m3_fts.py`: seed/idempotence
    correctness fixes + removing `openai` from `sys.modules` after the FTS test so
    it no longer pollutes the global module state and breaks
    `test_no_llm_dependency_imported` (pre-existing cross-test flake).

## Test evidence

### M4.7 focused suite (tests/unit/test_m4_rebuild.py)
- 17 passed. Covers: rebuild entrypoint reconstructs all six tables; incremental
  == rebuild parity (normalized row comparison); repeated rebuild determinism
  (rebuild #1/#2/#3 identical, no drift/new ids); conflict preserved (no winner);
  explicit supersession chains retained (D10<-D11<-D12); key integrity
  (decision_key/state_key never derived from trace_id; NULL preserved; multiple
  NULL-key active decisions coexist); active uniqueness after rebuild; idempotence
  (duplicate events -> no duplicate rows/links); TRUE READ-ONLY after rebuild (no
  mutation); M3 source-event composition; JSONL immutability (sha256 unchanged
  across rebuild + reads); SQLite integrity across read workload; secret safety
  (synthetic secret absent from all M4 tables/results, present only in M2 substrate
  not surfaced by M4); no LLM/network (socket/urlopen guarded); transaction
  rollback (malformed duplicate CREATE raises sanitized error + rolls back,
  no partial row); performance baseline recorded.

### Combined M4 focused suites (1–7)
- 243 passed (schema 32 + projector 38 + decision 40 + state 35 + verification/artifact
  49 + read 32 + rebuild 17).

### Prior-milestone regression
- M3 (query/integration/verification/relations/fts/pagination): passed.
- M2 (relations/rebuild/indexes/sqlite_foundation/tombstones/integration/
  ingest): passed EXCEPT the environmental real-home isolation flake.

### Fresh OS-safe ad-hoc verification (directive §25, 19 checks)
- 19/19 PASS against committed paths (HEAD 30683b1). Script removed after run.
  Covers schema v7, rebuild entrypoint, charter/requirement/decision/state/
  verification/artifact rebuild, incremental==rebuild, repeated determinism,
  explicit supersession, conflict/no-winner, decision_key + state_key integrity,
  verification no-auto-promotion, M4.6 TRUE READ-ONLY, JSONL unchanged, schema
  remains v7, secret safety.

### Performance baseline (acceptance-m4.7-performance.md)
- 120-event / 3-project corpus, 120 M4 rows: full rebuild 9.75 ms; active Charter
  lookup 0.005 ms; Requirement listing 0.126 ms; active Decision lookup 0.013 ms;
  State lookup 0.005 ms; Verification lookup 0.005 ms; artifact listing 0.045 ms.
  Deterministic, no caching added, approved indexes used, no pathological behavior.

### Full canonical suite (authoritative)
- Run 1: 858 passed, 3 skipped, 2 failed — both failures
  `tests/unit/test_m2_ingest.py::test_no_real_hermes_home_writes` and
  `tests/unit/test_m2_relations.py::test_no_real_hermes_home_writes` (environmental
  real-home flake).
- Run 2: 859 passed, 3 skipped, 1 failed — only
  `tests/unit/test_m2_ingest.py::test_no_real_hermes_home_writes` (the other passed,
  confirming intermittency driven by sidecar timing).
- In BOTH runs the only failures are `test_no_real_hermes_home_writes`, caused by
  the external Hermes sidecar mutating real `~/.hermes` (state.db, projects.db,
  auth.json, .update_check, kanban.db-shm) concurrently during the run. No M4.7
  product test failed. No M4.7-regression in any prior milestone.

## Why the final 0-failed gate is not met

The directive requires the FINAL canonical run to end with 0 failed, and explicitly
states the historical real-home environmental-flake exception is NOT sufficient for
final M4 completion. It instructs isolating/stopping the external background Hermes
process(es) that mutate `~/.hermes` for the duration of the run.

The mutating processes are:
- `hermes_cli.main gateway run` (background gateway)
- `hermes_cli.main serve` (background serve)
- the Hermes desktop application (`apps/desktop/release/linux-unpacked/Hermes`),
  which is THIS agent's own runtime host (this conversation runs inside it).

Stopping the desktop application would terminate the session; a `pkill` attempt
against the sidecar was correctly aborted by the self-termination safety guard and
did not stop the desktop. Therefore the sidecar cannot be safely isolated, and the
required clean run cannot be obtained from within this session.

Per the directive's escape clause: "If the external sidecar cannot be isolated and
this prevents obtaining the required clean run: M4.7 remains PARTIAL. Do not mark
M4 VERIFIED."

## Exact remaining criteria to reach M4 VERIFIED

1. Isolate/stop the external Hermes sidecar (quit the Hermes desktop app, or stop
   the gateway + serve + desktop) for the duration of the test run. Do NOT delete
   user data or modify `~/.hermes` to make the test pass.
2. Run the complete canonical suite with no deselection:
   `.venv/bin/python -m pytest tests/ -q`
   Expected when the sidecar is isolated: 859 passed, 3 skipped, 0 failed (the 3
   skips are capability-dependent and legitimately documented).
3. Re-run on the final state-binding HEAD; it must also be 0 failed.
4. Only then: mark M4.7 VERIFIED, mark M4 VERIFIED, update project-state.yaml +
   implementation-plan.json, commit the final state-binding, and emit the
   "M4: VERIFIED" final report.

## What is verified and safe to rely on now

- Rebuild is deterministic, idempotent, and parity-equivalent to incremental
  projection (proven by 17 focused tests + 19/19 ad-hoc + combined 243).
- Conflicts and explicit supersession chains are preserved exactly (no winner, no
  inferred edges).
- Active uniqueness, key integrity, secret safety, JSONL immutability, TRUE
  READ-ONLY retrieval, and M3 composition all hold after rebuild.
- No LLM/network calls are made by the rebuild path (guarded test).
- Schema remains v7; no migration v8; no M5 code introduced.

## No M5 implementation

No authorization, profile permission policy, context injection, automatic memory
selection, LLM ranking, semantic/vector search, Obsidian sync, MCP integration,
autonomous conflict resolution, or automatic requirement/decision generation was
implemented. M5 has not started.
