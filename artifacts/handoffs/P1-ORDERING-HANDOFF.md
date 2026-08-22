# P1 — EvidenceSet Ordering (Option B) + Benchmark Gold Correction — Handoff

## Metadata
- Package: `zero-mem` (tree: `zero-mem-v123-engineering`)
- Branch: `v124-post-release-closure`
- Date: 2026-08-22
- Authorized scope: Part 2 of P1-ORDERING-B-SCALE (local only, no push/tag/release/merge/remote)
- Status: **IMPLEMENTED + VERIFIED** (focused 93 passed, full 3378 passed, benchmark shows B01/B06/B09 state hit)

## Root cause (corrected from the design note's first framing)
The design note described "state starvation" as `_order_key` tie-break pushing `S*` state
below `D*` decisions. The precise mechanism, confirmed by direct probe, is:

1. M4 state records (`m4_current_state`) surface as `ProjectStateView` with `id` = the
   `zm_project_state` **rowid** (`1`=step active, `2`=docker failed superseded,
   `3`=docker fixed active). The m4 `identity` field ("S1"/"S2"/"S3") is **ignored** by
   the state projector (`classify_event_for_m4` for `STATE` requires only `domain`+`op`;
   state is keyed by `state_key`), so `_to_evidence_item` surfaces `id` (rowid) as the
   `evidence_id`.
2. State records classify as **supporting** (not primary): `verification_status="none"`
   and `memory_type="state"` is not in the promotable set
   (`decision`/`verified_state`/`tool_observation`), so `as_primary=False`.
3. With the old order key `(role, verified, lifecycle, created_at, evidence_id)`, the
   step state (id `1`, latest `effective_at` 08-10) sorted LAST in the supporting pool
   and was dropped by `max_supporting=3` (supporting was `[C1, R1, 3]` — step `1` absent).

The decision/state competition the design note described was actually a
charter/requirement/state competition *within the supporting pool*; decisions (D*) live
in the primary pool and were never the direct tie-break cause.

## Fix — Option B (route-conditioned active-state priority)
`src/integration/m7/budget.py`:
- Added `route: Optional[MemoryRoute] = None` to `select_evidence` and `_order_key`.
- New `state_rank` component placed AFTER the primary/supporting role split but BEFORE
  the verified/lifecycle/tie-break ranks:

```python
state_rank = 0 if (
    route is MemoryRoute.PROJECT
    and item.resource_type == "state"
    and (item.lifecycle or "").lower() == "active"
) else 1
return (role_rank, state_rank, verified_rank, lifecycle_rank,
        item.created_at or "", item.evidence_id or "")
```

`src/integration/m7/evidence_builder.py`: passes `route=route` into `select_evidence`.

Because `state_rank` is gated on `route is MemoryRoute.PROJECT`, non-PROJECT routes
(SESSION/USER/RESEARCH/GLOBAL) and `route=None` callers are byte-for-byte unchanged.
The 5-primary/3-supporting/8-total budget and the token budget are untouched.

Also corrected the benchmark gold labels (the previous `"S1"/"S2"/"S3"` referenced the
ignored m4 `identity`; the real evidence_id is the rowid `"1"/"2"/"3"`), and the
isolation probe's `OWNED_M4` set, in `benchmarks/run_memory_benchmark.py`.

## Changed files
- `src/integration/m7/budget.py` — `_order_key` state_rank (Option B) + `route` param
- `src/integration/m7/evidence_builder.py` — pass `route` to `select_evidence`
- `tests/unit/test_m7_3_evidence_builder.py` — `TestProjectStatePriority` (3 tests)
- `benchmarks/run_memory_benchmark.py` — gold labels `S*`→rowid `*`, `OWNED_M4`

## Verified evidence (real command output)
Focused tests:
```
.venv-v124/bin/python -m pytest tests/unit/test_m7_3_evidence_builder.py tests/unit/test_m7_2_memory_router.py -q --disable-warnings --no-header -p no:cacheprovider
93 passed in 0.94s
```

Full suite (ISOLATED TMPDIR/HOME):
```
.venv-v124/bin/python -m pytest tests/unit tests/integration -q --disable-warnings --no-header -p no:cacheprovider
3378 passed, 5 skipped in 93.10s   # baseline 3375 + 3 new, 0 failed
```

Benchmark before → after (`zero-mem-dev-data/evidence/p1-ordering/`):
| query | before evidence | after evidence | before r@8 | after r@8 |
|---|---|---|---|---|
| B01 current step | `[D2,D3,D4,D5,C1,R1,3]` (no `1`) | `[...,C1,1,3]` (step `1` present) | 0.0 | **1.0** |
| B03 | (no state) | `1` present | 0.0 | **1.0** |
| B06 docker fixed | (no `3` semantics) | `3` present, `2` absent (stale-safe) | 0.0 | **1.0** |
| B09 | (no state) | `3` present, `2` absent | 0.0 | **1.0** |
| B10 | (no state) | `1` present | 0.0 | **1.0** |
| B29 (as-of history) | 0 | `2` still absent (correct limitation) | 0.0 | 0.0 |

Aggregate: `mean_recall@8` 0.4167 → **0.625**, `mean_mrr` 0.3698 → **0.4026`,
`active_recall_on_stale` 0.4286 → **0.7143**, `stale_safe_rate` 1.0,
`deterministic_repeat` True, `isolation_ok` True. Non-state queries (B21/B23/B25/B26/B27)
unchanged. `C-QUANT-HYPHEN` still hits (previous WP).

## Risks
- `state_rank` promotes state only **within** the supporting pool for the PROJECT route;
  state records remain `supporting` (not `primary`) because eligibility still classifies
  them `as_primary=False`. Promoting state to primary would require changing
  `eligibility.py`/`memory_type` promotion, which is OUT of scope for this WP.
- The benchmark gold now depends on `zm_project_state` rowid values (`1`/`2`/`3`), which
  are insertion-order-derived. For the deterministic synthetic corpus they are stable and
  re-run byte-equal (verified), but a real corpus should key state evidence by `state_key`
  (a separate, larger design question, not addressed here).
- `mean_recall@5` is unchanged (0.2083) because state evidence is supporting, not primary;
  recall@5 only counts PRIMARY gold hits. This is the honest bound of the Option B fix.

## Reproduce
```bash
cd "/home/lenovo/Hermes Workspace/zero-mem-v123-engineering"
export TMPDIR=/dev/shm/zm-v124-test && export HOME=/tmp/zm-tmp && mkdir -p "$TMPDIR" "$HOME"
.venv-v124/bin/python -m pytest tests/unit/test_m7_3_evidence_builder.py -q --disable-warnings --no-header -p no:cacheprovider
.venv-v124/bin/python benchmarks/run_memory_benchmark.py --json | python -c "import sys,json; d=json.load(sys.stdin); print([(r['id'],r['recall@8'],r['evidence_ids']) for r in d['rows'] if r['id'] in ('B01','B06','B09')])"
```

## Authorization
Local commits authorized: `02f7870` (fix), `140c643` (test), `e016172` (bench gold).
NOT authorized / NOT performed: push, tag, release, merge, remote modification,
`src/access/*`, `src/retrieval/*`, eligibility.py, calibration, schema/migration.

## Unexpected untracked files (flagged, NOT committed)
`docs/README.md` and `docs/VERSION-TEMPLATE.md` appeared during this session (timestamps
14:32 local). They are Vietnamese documentation templates UNRELATED to this WP. They were
left untracked and un-staged (exact-path staging only). Needs maintainer attention.