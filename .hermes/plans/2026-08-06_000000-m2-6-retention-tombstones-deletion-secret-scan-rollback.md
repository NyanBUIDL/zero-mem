# M2.6 — Retention Tombstones, Logical Deletion, Secret Scanning, and Rollback

**Status:** PLAN (READY FOR APPROVAL — Decision B recorded; see §13)
**Milestone:** M2 (increment 6)
**Decision:** B — logical deletion only (canonical JSONL immutable; no physical purge in M2.6)
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` (DOCX authoritative; no `.md` projection present, OQ-1)
**Predecessor state:** M0/M1/M2.1–M2.5 VERIFIED; HEAD `6af8f4e`; schema version 5; working tree clean; canonical 283 passed / 3 skipped; M2.5 focused 12 passed / 3 FTS5-conditional skips.
**Master-spec anchors (translated from DOCX):**
- §7.2 lifecycle taxonomy: `deleted = removed per policy; keep minimal tombstone if needed`.
- §14.3 Retention: `temporary: auto-delete after expiry. session: keep until session/project closes. persistent: keep per user policy. never_store: RAM-only, not persisted.` + `Delete request must remove raw, artifact, index and projection; index uses tombstone/versioning to avoid orphan.`
- §14.4 Governance: `Schema migration has version and rollback. Write-back always has audit log.`

---

## 1. Reconciliation gate (pre-implementation must hold)

- `git rev-parse HEAD == 6af8f4e`; `git status` clean; `CURRENT_SCHEMA_VERSION == 5`.
- `project-state.yaml`: `m2_increment_5_status: verified`, `m2_current_version: 5`.
- `implementation-plan.json`: `increment_5.status == verified`, `canonical_result == "283 passed, 3 skipped"`.
- M2.6 not started (no `zm_tombstones` / `zm_deletion_audit`, no `_apply_tombstone`, no `apply_tombstone` attribute; `tests/unit/test_m2_*.py` contain no tombstone tests yet).
- If any of the above is false at implementation time, STOP and re-raise `STATE RECONCILIATION REQUIRED`.

---

## 2. Scope

M2.6 adds **logical deletion via append-only tombstone records** and the derived projection that makes deletion observable without physically mutating canonical JSONL. It extends the objective secret scanner to every M2-derived surface (including tombstone/audit/deletion tables, FTS, ingest logs, diagnostics, and returned reports), and documents safe rollback/downgrade.

It does **not** add a retention scheduler. Time-based expiration of `temporary`/`session` is **out of scope** (no scheduler approved; see §5). Only **explicit, user/authorized delete requests represented as tombstone records** are handled.

### Architectural rules (binding)
1. JSONL remains canonical and authoritative; SQLite remains derived, disposable, rebuildable.
2. Raw JSONL lines are **never** silently modified, physically deleted, reordered, or rewritten by M2.6.
3. Logical deletion uses **explicit tombstone records** (appended to canonical JSONL) and derived `zm_tombstones` / `zm_deletion_audit` rows.
4. A deletion preserves: source event identity (`deletion_event_id`), target event identity (`target_event_id`), timestamp (`created_at`/`recorded_at`), approved scope (`approved_scope`), reason code (`reason_code`, where supplied), provenance (`verifier`, `evidence_ref`), and verification status (`verification_status`, where supplied on the tombstone envelope).
5. No deletion reason, identity, scope, authorization, or policy is invented. Missing tombstone fields are recorded as NULL and a sanitized diagnostic code, never synthesized.
6. Tombstones are **idempotent** by `deletion_event_id` (PK). Repeating the same tombstone does not change derived state beyond the first apply.
7. Deleted records must not appear in **active** inspection or FTS results unless an explicitly named administrative helper requests deleted records.
8. Historical provenance remains auditable (tombstone + audit retained; `zm_meta` retained; only `zm_lifecycle.current_state` transitions to `deleted`).
9. No raw payload, secret, raw exception text, or replayable input appears in tombstone logs, audit rows, or diagnostics.

---

## 3. Canonical tombstone envelope (ingestion contract)

A deletion is a normal JSONL line (a new canonical event), validated by `validate_envelope`, carrying a `deletion` block. It is append-only and survives rebuild.

```json
{
  "event_id": "del-<uuid>",
  "trace_id": "tr-DEL-<uuid>",
  "event_type": "deletion_request",
  "source": "pre_tool_call",
  "schema_version": 1,
  "created_at": "2026-08-06T00:00:00Z",
  "observed_at": "2026-08-06T00:00:00Z",
  "sequence": 0,
  "lifecycle_status": "deleted",
  "verification_status": "none",
  "confidence": "high",
  "sensitivity": "internal",
  "retention": "persistent",
  "sanitized_content_hash": "sha256:...",
  "sanitized_content": {"text": "delete request for <target_event_id>"},
  "redaction_audit": [],
  "deletion": {
    "target_event_id": "<event_id to delete>",
    "reason_code": "user_request",
    "approved_scope": {"project": "proj-1"},
    "verification_status": "none"
  }
}
```

- `validate_envelope` (in `src/capture/validation.py`) must be extended (minimal, M2.6 scope) to:
  - accept `lifecycle_status == "deleted"`;
  - require a present `deletion` object with `target_event_id` (non-empty str) whenever `lifecycle_status == "deleted"`;
  - optionally accept `deletion.reason_code`, `deletion.approved_scope` (object), `deletion.verification_status`;
  - reject `deletion` on non-`deleted` events (no invented deletion).
- This is the **only** validation change; no other envelope contract is altered.

---

## 4. Migration v6 (exact DDL)

`src/storage/migrations/migrate_6.py` (new). `CURRENT_SCHEMA_VERSION` becomes `6` via the registry in `src/storage/migrations/__init__.py` (add `from . import migrate_6` and register `{6: migrate_6}`). `DERIVED_TABLES` in `ingest.py` is extended to include `zm_tombstones` and `zm_deletion_audit` so `rebuild_from_jsonl` drops/recreates them.

```sql
CREATE TABLE zm_tombstones (
    tombstone_id      TEXT PRIMARY KEY,        -- == deletion_event_id (idempotent PK)
    target_event_id   TEXT NOT NULL,
    target_trace_id   TEXT,                    -- denormalized for project/scope inspection
    reason_code       TEXT,                    -- NULL if not supplied (never invented)
    approved_scope    TEXT,                    -- JSON-encoded approved scope object or NULL
    verifier          TEXT NOT NULL,
    evidence_ref      TEXT,
    deletion_event_id TEXT NOT NULL,           -- == tombstone_id
    current_state     TEXT NOT NULL DEFAULT 'deleted',
    status            TEXT NOT NULL,           -- 'applied' | 'pending_unknown_target'
    created_at        TEXT NOT NULL
);

CREATE TABLE zm_deletion_audit (
    audit_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tombstone_id      TEXT NOT NULL,
    target_event_id   TEXT NOT NULL,
    target_trace_id   TEXT,
    action            TEXT NOT NULL,           -- 'logical_delete'
    prior_lifecycle_state TEXT,               -- captured before transition (provenance)
    reason_code       TEXT,
    approved_scope    TEXT,
    deletion_event_id TEXT NOT NULL,
    verifier          TEXT NOT NULL,
    evidence_ref      TEXT,
    diagnostic_code   TEXT,                    -- sanitized, fixed vocabulary
    recorded_at       TEXT NOT NULL
);

CREATE INDEX idx_zm_tombstones_target      ON zm_tombstones(target_event_id);
CREATE INDEX idx_zm_tombstones_status      ON zm_tombstones(status);
CREATE INDEX idx_zm_deletion_audit_target  ON zm_deletion_audit(target_event_id);
CREATE INDEX idx_zm_deletion_audit_tomb    ON zm_deletion_audit(tombstone_id);
```

- **Foreign keys**: not enforced via SQLite FK (`PRAGMA foreign_keys=ON` is set on the connection, but `zm_tombstones.target_event_id` references `zm_meta.event_id` only when the target exists; for `pending_unknown_target` the target is absent by design, so no FK constraint is declared — avoids orphan-blocking and keeps rebuild order-independent).
- **Deterministic order**: `MIGRATIONS` is a sorted `dict[int, module]`; `ensure_schema` applies 1→6 in ascending order. `migrate_6.up` is idempotent (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`).
- **v5 → v6 upgrade**: `migrate_6.up` creates the two tables + indexes. No data migration (tables start empty; tombstones arrive via ingestion).
- **v6 → v5 downgrade**: `migrate_6.down` drops `idx_zm_deletion_audit_tomb`, `idx_zm_deletion_audit_target`, `idx_zm_tombstones_status`, `idx_zm_tombstones_target`, `zm_deletion_audit`, `zm_tombstones` (in dependency order). Returns to v5 with all prior tables intact.
- **Transaction rollback**: `up`/`down` run inside the existing `ensure_schema`/`downgrade_to` transaction; on exception the surrounding rollback fires; `zm_migrations` is only updated after a successful apply (no partial schema advancement).
- **Unknown-future rejection**: inserting a `zm_migrations` row with `version > CURRENT_SCHEMA_VERSION` (e.g. 7) makes `ensure_schema` raise `UnsupportedSchemaVersion` before applying anything — no partial advance. `downgrade_to(v >= current)` is rejected; `downgrade_to(valid_lower)` applies only the needed `down` steps.

---

## 5. Retention-class behavior (exact)

| Retention value | Enforced at capture? | What M2.6 projects | Expiration as tombstone? | External scheduler? | In M2.6? |
|---|---|---|---|---|---|
| `never_store` | Yes — M1 does NOT persist (RAM-only, per §14.3) | Nothing (never reaches JSONL/SQLite) | n/a | n/a | Out of scope (capture-time, M1) |
| `temporary` | No (persisted; would expire later) | Row kept; eligible for explicit tombstone | No automatic expiry | **Required, not approved** | Explicit tombstone only; auto-expiry OUT of scope |
| `session` | No | Row kept; eligible for explicit tombstone | No automatic expiry on session close | **Required, not approved** | Explicit tombstone only; auto-expiry OUT of scope |
| `persistent` | No | Row kept; eligible for explicit tombstone | No (per user policy) | n/a | Explicit tombstone only |

- **No retention scheduler is added.** Time-based expiration of `temporary`/`session` requires an external scheduler, which is **not approved** in M2.6 (explicit exclusion §11). M2.6 supports only **explicit tombstones** that a caller appends to JSONL.
- M2.6 does **not** interpret `retention` to auto-generate deletions. A `temporary`/`session` record is deleted **only** when an explicit tombstone references it.

---

## 6. Tombstone state behavior (deterministic outcomes)

New code path in `ingest.py`: `_apply_tombstone(conn, env)` called within the same per-line transaction as the tombstone's `NEW_EVENT` insert (alongside `_seed_lifecycle_and_provenance`, `_project_relations_scopes`, `_seed_fts`). It is **not** a separate transaction.

Let `T = deletion.target_event_id`.

- **active → deleted**: `UPDATE zm_lifecycle SET current_state='deleted' WHERE event_id=T`. FTS row for T removed (see §7). Audit records prior state `active`. Target remains excluded from active inspection (§7). No other active event is affected.
- **archived → deleted**: same UPDATE; prior state `archived`.
- **superseded → deleted**: same UPDATE; prior state `superseded`.
- **conflicted → deleted**: same UPDATE; prior state `conflicted`.
- **duplicate tombstone** (same `deletion_event_id` re-ingested): M2.2 `_resolve_outcome` returns `DUPLICATE_EVENT_ID` → `_apply_tombstone` is **not** re-run (it runs only on `NEW_EVENT`). Derived state unchanged. Idempotent.
- **tombstone before the referenced event** (T not yet in `zm_meta`): insert `zm_tombstones(status='pending_unknown_target')` + audit with `diagnostic_code='target_not_yet_present'`. Retained as a **pending derived record** (not a failure, not an `invalid_record`). When T later arrives as a `NEW_EVENT`, ingest checks `zm_tombstones WHERE target_event_id=T AND status='pending_unknown_target'` and applies (sets `status='applied'`, transitions lifecycle, removes FTS). This is order-dependent and **identical** between incremental ingest and `rebuild_from_jsonl` (both process JSONL lines in the same file order).
- **tombstone for an unknown event** (T never appears in the corpus): stays `pending_unknown_target` permanently (auditable; never invented). Not reported as a failure.
- **later valid event after a tombstone** (a NEW_EVENT for T arrives after T was already deleted): this is a normal new-event that re-inserts zm_meta for T. M2.6 does **not** auto-revive a deleted record. Rule: if a pending tombstone for T exists, it is applied to the newly inserted T (transition to `deleted`, FTS removed). If T was already `applied`, the tombstone is a one-shot; a second arrival of T without a new tombstone remains `active`/`observed` (no silent re-deletion without a tombstone). This avoids inventing deletion from mere re-ingestion.
- **rebuild ordering involving tombstones**: identical to incremental by construction (deterministic file-order replay). `verify_rebuild_parity` extended (§8) to include tombstone + audit + lifecycle states.

**No missing relationships are invented.** If `approved_scope` references a project/scope not present, the scope is still recorded on the tombstone (it is the deletion's scope, not an inferred relation); no `zm_scopes`/`zm_relations` row is synthesized from a tombstone.

---

## 7. Index and FTS behavior

- **Active indexes**: `zm_meta` rows are **not deleted** on tombstone (provenance retained). `zm_lifecycle.current_state` becomes `deleted`, so active-key/lifecycle inspections that filter `current_state='active'` naturally exclude the target. No index DROP is needed; indexes remain valid and rebuildable.
- **FTS**: on a successful tombstone apply, `DELETE FROM zm_fts WHERE event_id=T` (only when `FTS5_AVAILABLE`). FTS is a derived, rebuildable index; physical removal of the target's FTS row is safe and avoids orphan matches. When FTS5 is unavailable, there is no FTS row to remove (no-op). Rebuild recreates FTS identically from non-deleted events' `sanitized_content`.
- **Active inspection exclusion**: `get_trace`, `find_by_trace_id`, `list_events_in_scope`, `search_fts` exclude deleted targets by default:
  - `get_trace(store, event_id)`: returns `None` if the event's `zm_lifecycle.current_state == 'deleted'` (unless an `include_deleted=True` flag is passed — but per rule 7, the *default* active helper must exclude; the explicit admin helper is the sanctioned route). Simpler and safer: keep `get_trace` returning the row (it is explicit single-event lookup by id, acceptable for admin/audit), but `find_by_trace_id` / `list_events_in_scope` / `search_fts` **exclude** deleted. Decision: `find_by_trace_id` and `list_events_in_scope` add `WHERE event_id NOT IN (SELECT event_id FROM zm_lifecycle WHERE current_state='deleted')`; `search_fts` already excludes deleted because the FTS row was removed. `get_trace` remains idempotent (returns the row; callers needing active view should check `get_lifecycle`). This keeps the single-event helper usable for audit while active multi-row helpers exclude deleted.
  - **Explicit administrative helpers** (the only sanctioned route to deleted records):
    - `list_deleted(store, scope_type=None, scope_id=None) -> list[event_id]` (optionally filtered by project/profile scope).
    - `get_tombstone(store, tombstone_id) -> Optional[dict]`.
    - `get_deletion_audit(store, target_event_id=None, tombstone_id=None) -> list[dict]`.
- **Downgrade (v6 → v5)**: `zm_fts` is untouched by downgrade (it is a v5 object). The deleted targets' FTS rows remain absent (they were deleted at ingest); after downgrade the target rows still exist in `zm_meta`/`zm_lifecycle` with `current_state='deleted'` (those columns predate v6) but `zm_tombstones`/`zm_deletion_audit` are dropped. This is acceptable: the tombstone/audit history is lost on downgrade, but `zm_lifecycle.current_state='deleted'` still marks the deletion, and a re-`ensure_schema` to v6 re-creates the tables (empty); re-ingest (or `rebuild_from_jsonl`) re-derives tombstones/audit from canonical JSONL. No JSONL change.
- **Capability-dependent FTS**: all FTS removal is guarded by `migrate_5.FTS5_AVAILABLE`; tests cover both available and unavailable builds (skip-path when unavailable).

---

## 8. Rebuild parity (incremental vs rebuilt)

- `rebuild_from_jsonl` drops all `DERIVED_TABLES` (now including `zm_tombstones`, `zm_deletion_audit`), re-runs `ensure_schema()` (recreating v6), then re-ingests every file in order via `ingest_file`. Because tombstones are ordinary JSONL lines and pending-apply is order-dependent and deterministic, the rebuilt layer equals the incrementally ingested layer.
- `verify_rebuild_parity(store_a, store_b)` is extended to also compare:
  - `zm_tombstones`: `{(tombstone_id, target_event_id, status)}`
  - `zm_deletion_audit`: `{(target_event_id, action)}`
  - `zm_lifecycle`: already compared (includes `current_state='deleted'`)
  - `zm_fts`: already compared (deleted targets absent)
- Acceptance: incremental store vs full-rebuild store → `verify_rebuild_parity == True`.
- **Repeated rebuild determinism**: running `rebuild_from_jsonl` twice on the same inputs yields identical `zm_migrations` ledger `[1..6]` and identical derived state.

---

## 9. Secret scanning (objective, all surfaces)

`scan_sqlite_for_secrets(store, secret_corpus)` is extended to also scan:
- `zm_tombstones`: `tombstone_id, target_event_id, target_trace_id, reason_code, approved_scope, evidence_ref, deletion_event_id`
- `zm_deletion_audit`: `tombstone_id, target_event_id, target_trace_id, reason_code, approved_scope, deletion_event_id, evidence_ref, diagnostic_code`
- `zm_fts`: already scanned (M2.5)
- `zm_ingest_log`: already scanned
- (prior tables unchanged)

No secret corpus token may appear in any scanned blob. The function returns the list of found tokens (empty = clean).

**Tests must prove (synthetic secrets):**
- `test_secret_scan_covers_tombstones`: inject a synthetic secret into a `zm_tombstones` row → detected.
- `test_secret_scan_covers_deletion_audit`: inject into `zm_deletion_audit` → detected.
- `test_secret_absent_normal_ingestion`: normal redacted ingestion (M1-style benign `sanitized_content`) → scanner returns `[]` across all tables.
- `test_deletion_diagnostics_sanitized`: a deletion with a synthetic secret placed in a field that *would* be scanned (e.g. `reason_code`) → the returned `IngestionReport` / `IngestionFailure` / audit `diagnostic_code` contain **only fixed sanitized codes** (`target_not_yet_present`, `logical_delete`, `applied`, etc.); the secret string never appears in `str(report)`.
- `test_no_secret_in_deletion_audit_log`: the `zm_deletion_audit` row for a benign tombstone contains no secret corpus token.

Per architecture rule 9, `sanitized_content` is the M1-redacted form; secrets cannot appear by construction. The injected-secret tests deliberately violate that to prove the scanner covers the new tables (defense-in-depth).

---

## 10. Exact files (implementation — not created now)

- `src/storage/migrations/migrate_6.py` (new): DDL + `up`/`down` + idempotent guards.
- `src/storage/migrations/__init__.py`: register `{6: migrate_6}`; `CURRENT_SCHEMA_VERSION=6`.
- `src/storage/ingest.py`:
  - `DERIVED_TABLES` += `("zm_tombstones", "zm_deletion_audit")`.
  - `_apply_tombstone(conn, env)` (new): applies/await-pending tombstone within the per-line txn.
  - wire `_apply_tombstone` into `_commit_outcome` `NEW_EVENT` branch when `env` has a `deletion` block.
  - pending-apply hook in `NEW_EVENT` insert: after `zm_meta` insert, check `zm_tombstones WHERE target_event_id=event_id AND status='pending_unknown_target'` and apply.
  - `find_by_trace_id` / `list_events_in_scope`: exclude `current_state='deleted'`.
  - admin helpers: `list_deleted`, `get_tombstone`, `get_deletion_audit`.
  - `scan_sqlite_for_secrets`: scan `zm_tombstones` + `zm_deletion_audit`.
  - `verify_rebuild_parity`: include tombstone + audit snapshots.
  - docstring: update module docstring (M2.6 now in scope; M2.7 still excluded).
  - `__all__`: add `list_deleted`, `get_tombstone`, `get_deletion_audit`, `apply_tombstone` (exposed name for the new behavior); ensure `not hasattr(ingest, "build_fts")`-style negative assertions in earlier increments still hold (no `apply_tombstone` is fine to expose; M2.7 behavior remains absent).
- `src/capture/validation.py`: extend `validate_envelope` to accept `lifecycle_status=='deleted'` + required `deletion.target_event_id`; reject `deletion` on non-deleted events. Minimal, no other contract change.
- `tests/unit/test_m2_tombstones.py` (new): focused M2.6 suite (see §12).
- `acceptance-m2-increment-6.md` (new): acceptance evidence.
- `project-state.yaml` + `implementation-plan.json`: bind M2.6 VERIFIED (after acceptance).

---

## 11. Explicit exclusions (M2.6 must NOT implement)

- Physical purge of canonical JSONL (see §13 — Decision B: NOT implemented in M2.6; deferred to a separate future milestone with an explicit policy). M2.6 implements logical deletion only.
- Background retention scheduler / auto-expiry of `temporary`/`session`.
- Retry or backoff; dead-letter store; replay.
- Authorization or access-control enforcement (scopes are recorded, not enforced — M5).
- Semantic search, retrieval ranking, query routing, MCP, Obsidian, prompt/context injection.
- M2.7 integration acceptance; M3+ behavior.
- Physical deletion of `zm_meta` rows (provenance retained; only `zm_lifecycle.current_state` transitions).

---

## 12. Tests (acceptance mapping)

All map to a focused automated test in `tests/unit/test_m2_tombstones.py`, an existing canonical test, or a narrowly justified ad-hoc verifier.

| # | Criterion | Test |
|---|---|---|
| T1 | migration v5 → v6 (tables + schema version) | `test_migration_v5_to_v6` (assert `store.get_schema_version()==CURRENT_SCHEMA_VERSION`, tables exist, `CURRENT_SCHEMA_VERSION==6`) |
| T2 | downgrade v6 → v5 drops tombstone tables | `test_downgrade_v6_to_v5_drops_tombstone_tables` |
| T3 | tombstone creation (applied) | `test_tombstone_marks_target_deleted` (insert target then tombstone; `get_lifecycle(target).current_state=='deleted'`, `zm_tombstones.status=='applied'`, audit row present) |
| T4 | duplicate tombstone idempotence | `test_duplicate_tombstone_idempotent` (re-ingest same `deletion_event_id`; counts `duplicate_event_id==2`, single tombstone/audit row) |
| T5 | active → deleted | `test_active_to_deleted` |
| T6 | archived → deleted | `test_archived_to_deleted` |
| T7 | superseded → deleted | `test_superseded_to_deleted` |
| T8 | conflicted → deleted | `test_conflicted_to_deleted` |
| T9 | unknown-target tombstone | `test_tombstone_unknown_target_pending` (`status=='pending_unknown_target'`, auditable, not a failure) |
| T10 | tombstone before referenced event (rebuild ordering) | `test_out_of_order_tombstone_rebuild` (tombstone line precedes target; both incremental and rebuild yield `applied`) |
| T11 | repeated rebuild determinism | `test_rebuild_determinism` (two rebuilds identical; `verify_rebuild_parity` True) |
| T12 | incremental/rebuild parity | `test_incremental_vs_rebuild_parity` (`verify_rebuild_parity` True with tombstones present) |
| T13 | deleted excluded from active helpers | `test_deleted_excluded_from_active_inspection` (`find_by_trace_id`/`list_events_in_scope` omit deleted; `search_fts` omits deleted target) |
| T14 | deleted retrievable via admin helper | `test_list_deleted_and_get_tombstone` (`list_deleted`/`get_tombstone`/`get_deletion_audit` return the deleted record + audit) |
| T15 | historical provenance retained | `test_provenance_retained_after_delete` (`get_provenance(target)` + `zm_meta` row still present; audit has `prior_lifecycle_state`) |
| T16 | JSONL byte-for-byte unchanged | `test_jsonl_byte_for_byte_unchanged` (read source before/after ingest) |
| T17 | secret scan across all derived tables | `test_secret_scan_covers_tombstones`, `test_secret_scan_covers_deletion_audit`, `test_secret_absent_normal_ingestion` |
| T18 | sanitized deletion diagnostics | `test_deletion_diagnostics_sanitized` (secret in `reason_code` → report/audit contain only fixed codes; secret absent from `str(report)`) |
| T19 | no real `~/.hermes` writes | `test_no_real_hermes_home_writes` (baseline-aware, isolated `HERMES_HOME`, exclude only unrelated `kanban.db` sidecars) |
| T20 | no LLM/network | `test_no_llm_or_network_calls` (monkeypatch `socket.socket` → AssertionError; no `import openai`/requests in path) |
| T21 | no M2.7/M3 behavior | `test_no_later_m2_tables` (assert `zm_tombstone` absent — wait, `zm_tombstones` IS M2.6; exclude `zm_rollback`/M2.7 names; assert no `rank_results`/`retrieve_top_k`/`apply_retention_schedule` attributes) |
| T22 | FTS capability behavior | `test_fts_removes_deleted_target` (FTS5 available → deleted target absent from `search_fts`; unavailable → `search_fts` returns `[]`) |
| T23 | unknown-future rejection | existing `test_unknown_future_schema_version_rejected` in `test_m2_sqlite_foundation.py` (unchanged; asserts v7 insert rejected, no partial advance) — canonical regression guard. |

Canonical regression: full `pytest tests/ -q` must pass (expect 283→~?; new focused suite adds ~23 tests; the pre-existing M1 timing flake `test_mapping_is_deterministic` is a separate maintenance item, NOT fixed in M2.6).

---

## 13. Physical purge decision boundary — DECISION B (logical deletion only)

**Decision approved (user, this plan): Option B — logical deletion only.**

- Canonical JSONL remains **immutable and append-only**. M2.6 must **not** physically delete, rewrite, truncate, or compact canonical JSONL.
- The spec §14.3 wording *"Delete request must remove raw, artifact, index and projection"* is **resolved for M2.6** as follows:
  - "Delete raw JSONL" is **not implemented** in M2.6.
  - Deletion is represented by an **explicit append-only deletion event** (a tombstone line in canonical JSONL).
  - SQLite projects that event into **tombstone** (`zm_tombstones`), **lifecycle** (`zm_lifecycle.current_state='deleted'`), **audit** (`zm_deletion_audit`), and **index/FTS** (FTS row removed/excluded) state.
  - Deleted records are **excluded from active helpers and FTS**.
  - Historical provenance remains available through **explicitly named administrative inspection helpers** (`list_deleted`, `get_tombstone`, `get_deletion_audit`).
  - `rebuild_from_jsonl` reproduces the deleted state **exactly** (tombstones are canonical lines; pending-apply is order-deterministic).

**Specification conflict resolved:** the immutable-JSONL architecture guarantee (AGENTS.md + M2.1–M2.5 acceptance) takes precedence over the spec's "remove raw" phrasing for M2.6. No code in M2.6 edits canonical JSONL. The `zm_lifecycle`/`zm_meta` rows are retained (provenance); only the derived `current_state` transitions and the FTS index row are altered — both derived and rebuildable.

**Physical purge is deferred** to a separate future milestone. If/when authorized, it requires an explicit policy covering all of:
- authorization (who may purge, under what gate);
- compliance requirements (retention law, jurisdiction);
- backups (pre-purge snapshot + restore guarantee);
- audit retention (how long purge audit survives);
- key destruction (if encrypted artifacts are involved);
- rebuild implications (canonical-edit effect on `rebuild_from_jsonl` parity);
- irreversible deletion confirmation (explicit, non-silent, double-confirmed).

**Option A (physical-purge module) and Option C (trailing-line-only physical removal) are NOT implemented in M2.6.** Until a future milestone defines the policy above, M2.6 ships **logical deletion only**.

---

## 14. Rollback procedure / runbook

- **Application-level rollback of a mistaken tombstone**: because JSONL is canonical and append-only, "undeleting" is represented by appending a new canonical line that transitions the target's `zm_lifecycle.current_state` back (e.g. a correction event) — not by editing JSONL. M2.6 does not auto-undelete; an explicit correction record is the sanctioned path (deferred detail; within M2.6 we retain `zm_meta` so a correction can re-mark `active`/`observed`).
- **Schema rollback**: `store.downgrade_to(5)` drops `zm_tombstones`/`zm_deletion_audit` and their indexes, returning to v5 (prior tables intact; `zm_lifecycle.current_state='deleted'` markers remain). Re-run `rebuild_from_jsonl` to fully regenerate the derived layer from canonical JSONL (no JSONL change).
- **Disaster recovery**: SQLite is disposable. Delete the `.sqlite` file and `rebuild_from_jsonl` from canonical JSONL → identical derived state (including tombstones/audit, since they are canonical lines).
- **No partial schema advancement**: a failed `up` rolls back the transaction; `zm_migrations` is not updated; `ensure_schema` reports the last good version.

---

## 15. M1 timing flake (separate maintenance, not M2.6)

`tests/unit/test_hermes_payload_fixtures.py::test_mapping_is_deterministic` is an **intermittent M1 timing flake** (`redaction_audit.observed_at` uses fresh `datetime.now()` per `map_hook_payload` call; fails only when two calls straddle a millisecond). It is pre-existing, unrelated to M2.6, and must **not** be modified inside the M2.6 implementation (single-increment attribution). It is recorded here as a maintenance requirement:
- **M2.7 final acceptance requires the complete canonical suite without deselecting** this test, after the maintenance fix (make `RedactionAudit.observed_at` deterministic) is committed in a separate M1 maintenance change.

---

## 16. Acceptance summary (M2.6 VERIFIED requires all of)

- T1–T23 focused tests pass; canonical suite green (M1 flake tracked separately per §15).
- Schema version 6; v5↔v6 upgrade/downgrade verified; unknown-future rejected; no partial advance.
- Tombstone create / duplicate-idempotent / active|archived|superseded|conflicted→deleted / unknown-target-pending / out-of-order rebuild / repeated-rebuild determinism / incremental↔rebuild parity all verified.
- Deleted excluded from active inspection + FTS; retrievable via admin helpers; provenance retained.
- JSONL byte-for-byte unchanged; no real `~/.hermes` writes; no LLM/network.
- Secret scanner covers `zm_tombstones` + `zm_deletion_audit` + all prior surfaces; benign ingestion clean; diagnostics sanitized.
- **Decision B recorded (§13): logical deletion only; canonical JSONL immutable; no physical purge in M2.6; A/C not implemented; physical purge deferred with required policy.** M2.6 implements logical deletion only.
- `project-state.yaml` + `implementation-plan.json` bound; `acceptance-m2-increment-6.md` written.

---

## 17. Deliverable status

M2.6 PLAN: READY FOR APPROVAL
Decision: B — logical deletion only
Working tree change: M2.6 plan file only
