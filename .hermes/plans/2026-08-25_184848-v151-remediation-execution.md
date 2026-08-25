# Zero-Mem V1.5.1 Remediation — Controlled Execution Plan

**Goal:** Resolve every V1.5.1 remediation checklist item that is technically executable in the local repository, preserve canonical JSONL/derived-state boundaries, and reach a reproducible qualification decision without claiming release readiness early.

**Authority order:** master specification → approved ADRs → `project-state.yaml` → defect registry → tests → roadmap `ZERO-MEM-v1.5.1-REMEDIATION-ROADMAP.vi.md` → implementation. `implementation-plan.json` is historical only.

**Baseline:** `v1.5.0` / `10ad8dadad42108dec02d78b9a927b248eb40ef7`.

**Execution constraints:**
- Active repository only: `zero-mem-v123-engineering/`; evidence/build/venv/test roots only under `zero-mem-dev-data/`.
- Never modify canonical JSONL format, schema, Hermes core, or `project-state.yaml` unless a later gate explicitly permits it.
- No runtime dependency additions; dev extras only when package/build proof exists.
- No Git stage/commit/push/tag/release without separate Git authorization and a clean classification of all dirty paths.
- Graphify is read-only, outside the repository, and is refreshed before and after production edits.
- Every production behavior change follows: defect OPEN → narrow RED test → minimal code → GREEN → relevant regression → full suite → evidence record.

## Definition of done (non-negotiable)

A defect may be marked FIXED only after all are true: baseline RED evidence, focused GREEN, relevant auth/security tests, full unit+integration suite green in clean isolated environment, platform evidence or explicit capability-qualified skip, no unauthorized dependency delta, docs/doctor synchronized, rollback documented, no unclassified generated files.

A release remains **NO-GO** until all local gates pass and GitHub Linux/Windows/macOS × Python 3.11/3.12/3.13 evidence is available.

---

## Phase 0 — Rebaseline and control-plane check

### Checklist
- [ ] Read AGENTS, workspace policy, GitHub policy, master-spec retrieval/access sections, ADR-V150-01, project state, defect registry, roadmap.
- [ ] Classify every existing dirty path as pre-existing test/doc/workflow or current mutation; do not clean destructively.
- [ ] Create a clean baseline worktree/ref execution environment at tag `v1.5.0` without modifying the active tree.
- [ ] Run the same isolated-HOME full suite on baseline with the same interpreter as candidate.
- [ ] Compare every candidate full-suite failure against baseline: `NEW_REGRESSION`, `PRE_EXISTING`, or `ENVIRONMENT_CAPABILITY` with executable evidence.
- [ ] Record Python, SQLite, pytest, platform, HOME/TMP roots, exact commands, exit codes, counts.
- [ ] Capture baseline wheel/sdist hashes/sizes and candidate sizes; runtime dependency delta must be zero.

**Exit:** no unclassified failure is called environmental; baseline/candidate comparison is recorded.

---

## Phase 1 — DEF-020: FTS authorization parity

**Allowed production paths:** `src/access/authorized_read.py`, `src/retrieval/search.py`, `src/retrieval/models.py`.

### Checklist
- [ ] RED: SearchHit has no KS field on baseline.
- [ ] RED: cross-profile space grant succeeds for structured event but not FTS.
- [ ] RED: same profile/project, other KS does not become an FTS candidate.
- [ ] RED: NULL KS is not authorized by a KS grant.
- [ ] RED: multi-space grants return exact union.
- [ ] Implement one typed effective-scope predicate shared by structured and FTS read paths.
- [ ] Ensure all values remain SQLite bound parameters; no caller SQL interpolation.
- [ ] Apply predicate in candidate SQL before `ORDER BY`, snippet generation and `LIMIT`.
- [ ] Ensure defensive post-validation checks membership in at least one effective scope and drops unexpected rows without exposing a boundary oracle.
- [ ] Bind cursor fingerprint to query text, effective scope, policy/fingerprint version, and limit.
- [ ] Verify malformed FTS error remains sanitized; protected text never appears in result/error/log.
- [ ] Run focused tests plus M3 FTS, M5 authorization/cross-profile, M6 memory search regressions.

**Exit:** structured/FTS golden parity, SQL candidate authorization, no corpus projection on event path.

---

## Phase 2 — DEF-021/022: bounded structured and FTS pagination

### Checklist
- [ ] RED/green for `None`, 1, MAX, 0, negative, MAX+1, bool, float, string limits.
- [ ] Validate public limit exactly once at public boundary; invalid input raises `invalid_limit`, never silent clamp.
- [ ] Decode/validate cursor before any candidate query.
- [ ] Structured path: replace per-scope unbounded fetch with one effective-scope SQL OR query where feasible; otherwise prove bounded k-way merge with correct refill/dedup.
- [ ] FTS path: one effective-scope candidate query; query `limit+1`, return at most limit, mint cursor from last returned item only if another candidate exists.
- [ ] Stable ordering `(created_at, event_id)` and keyset query must be SQL-bound.
- [ ] Cursor mismatch tests: changed limit/query/scope/policy/version/malformed cursor.
- [ ] Pagination tests: no missing/duplicates, equal timestamps, deleted row between pages, grant revoke between pages.
- [ ] SQL trace proves `limit=1` emits `LIMIT 2` and no unbounded public page query.
- [ ] `tracemalloc` qualification fixture at 1k/10k/100k rows; document measured peak, not a fabricated threshold.

**Exit:** no normal page query fetches a whole result set; no result exceeds server ceiling.

---

## Phase 3 — DEF-023: registry append happy path

### Checklist
- [ ] RED benchmark proves old full-rewrite/superlinear path.
- [ ] Blob put is idempotent and happens before registry append on new source.
- [ ] New record is appended once with blob_ref present; no `_update_record()` happy-path rewrite.
- [ ] Same source/content retry returns existing record without duplicate line.
- [ ] Inject blob failure: no dangling registry record.
- [ ] Inject registry append failure after blob put: no in-memory phantom record; only unreachable orphan blob is possible.
- [ ] Reload/restart reconstructs indexes exactly; legacy unbound record repair remains explicit and tested.
- [ ] Partial trailing line remains fail-closed.
- [ ] Preserve POSIX 0600/0700 behavior; capability-qualified Windows behavior.
- [ ] Same-process concurrent registration does not duplicate.
- [ ] Measure 100/500/1000/5000 source inputs: total time, time/source, registry bytes, peak memory.

**Exit:** new blob ingest is O(1) amortized relative to registry size; no runtime dependency.

---

## Phase 4 — deadline/admission saturation

**Allowed production paths must be discovered from actual dispatcher ownership before editing.**

### Checklist
- [ ] Find dispatcher/worker/admission owner through Graphify and direct source reading.
- [ ] Register a dedicated defect if one is absent; no untracked runtime repair.
- [ ] RED tests: fast, slow, simulated hung work, queued timeout, close race.
- [ ] Verify typed `DEADLINE_EXCEEDED` deadline behavior.
- [ ] Verify admitted count never exceeds `max_concurrency + max_queue`.
- [ ] Verify queued timeout cancels before work starts; running completion returns slot exactly once.
- [ ] Verify close cannot produce negative admitted count or duplicate callback.
- [ ] Run 100 timeout sequence and measure thread count / pending futures boundedness.
- [ ] Add progress handler only if per-request SQLite connection ownership is proven; reset it in finally and test races. Otherwise retain bounded-query remediation and document deferred cancellation ADR.

**Exit:** no easy reproducible timeout path indefinitely saturates workers.

---

## Phase 5 — CI and portability

### Checklist
- [ ] Workflow triggers: PR/master push/v* tag/workflow_dispatch.
- [ ] Job timeout, fail-fast false, always-upload logs, Ubuntu/Windows/macOS × Python 3.11/3.12/3.13.
- [ ] Fresh install uses declared extras only; default wheel runtime dependency list stays empty.
- [ ] Replace OS shell-only tests with Python equivalents or capability-qualified skips.
- [ ] Capability-probe symlink tests; keep unrelated security tests active on Windows.
- [ ] Verify Windows process kill behavior and POSIX-only installer guards.
- [ ] Clean wheel install outside source tree: import `zero_mem` and `src.access`; CLI `--version`, `--help`, setup, doctor JSON.
- [ ] Inspect wheel/sdist for tests, real corpus, secrets, venv/build artifacts.
- [ ] Do not claim GitHub matrix pass until remote workflow result exists.

---

## Phase 6 — doctor, documentation, version/release honesty

### Checklist
- [ ] Re-run DEF-019 doctor tests and verify event-path KS grant message does not require corpus store.
- [ ] Corpus store status describes `corpus_unit_search` only.
- [ ] README/version packaging claim uses current dynamic version or neutral wording.
- [ ] SPDX license passes build metadata.
- [ ] `project-state.yaml` duplicate-key machine check passes; do not update release state until qualification passes.
- [ ] Release notes document cursor incompatibility if fingerprint behavior changed, fixed defects, known limitations, and rollback.
- [ ] Assert doctor/docs claims against executable tests where possible.

---

## Phase 7 — qualification and closure

### Checklist
- [ ] Full unit+integration suite green in clean isolated HOME on the candidate tree.
- [ ] Targeted authorization/redaction/backup/restore/rebuild/upgrade/package suites green.
- [ ] Compileall, machine-state validation, build, clean-wheel smoke all green.
- [ ] Compare candidate artifact hashes/sizes/dependency metadata to baseline.
- [ ] Current-tree Graphify refresh and direct source review for canonical/derived, authorization-before-ranking, path safety, error sanitization, concurrency, unbounded reads, secret leakage.
- [ ] Write handoff in `artifacts/handoffs/` with observed/changed/verified/risk/next, command evidence and local Git status.
- [ ] Update defect entries only with actual evidence; do not update `project-state.yaml` to released/verified without gates.
- [ ] Review exact dirty paths, `git diff --check`, no generated artifacts in repo.
- [ ] Stop at maintainer gate: local commit/release/push remain not granted unless separately authorized.

## Rollback

- Retrieval: revert code only; schema unchanged. New cursors may become invalid; restart at page 1.
- Registry: revert blob-first implementation; canonical registry format remains readable. Do not delete possible orphan blobs without verified maintenance tooling.
- CI/docs: independently reversible; historical release evidence is append-only.
- No V1.6 multi-knowledge-space migration is permitted in this plan.
