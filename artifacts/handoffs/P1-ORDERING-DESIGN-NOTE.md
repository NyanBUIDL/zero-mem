# P1 — EvidenceSet Ordering + Scale-Harness — Design Note (NO CODE)

## Metadata
- Package: `zero-mem` (tree: `zero-mem-v123-engineering`)
- Date: 2026-08-22
- Scope: DESIGN ONLY. No source change. `src/integration/m7/budget.py`,
  `eligibility.py`, `authorized_read.py`, and calibration are left untouched.
- Decision requested from maintainer at bottom.

---

## 1. Problem — state starvation in the PROJECT EvidenceSet

Observed (P1 benchmark, synthetic M4 corpus): project-state queries B01 ("current step")
and B06/B09 ("docker login status") return ZERO state evidence in the bounded set. The
cause is `_order_key` in `src/integration/m7/budget.py`:

```python
def _order_key(item, elig):
    role_rank     = 0 if elig.as_primary else 1
    verified_rank = 0 if verification in ("verified","confirmed") else 1
    lifecycle_rank= 0 if lifecycle == "active" else 1
    return (role_rank, verified_rank, lifecycle_rank, created_at or "", evidence_id or "")
```

All M4 rows in the synthetic corpus share `created_at = 2026-08-05` (production M4 rows
also commonly share an ingestion/effective timestamp). After role/verified/lifecycle all
tie, the final tie-break is `evidence_id` ascending, so **decision records (D1–D5) and
charter/requirement (C1/R1) always sort ahead of state records (S1, S3)**. With
`max_primary = 5`, the state records are pushed past the budget entirely.

This is not a correctness bug in the sort (it is deterministic and documented); it is an
*ordering policy* gap: M4 **state** is the resource type that answers "what is the
current step / current status", yet it has lowest tie-break priority among same-role
items.

The M8.5 calibration layer (`m8_integration.py`) is observation/ordering-metadata only in
the current build; it does not currently re-rank upstream EvidenceSets (the design stays
"calibration is ordering-only metadata"), so it cannot rescue the starved state today.

## 2. Candidate options (each with risk / token impact)

### Option A — freshness-prioritize active state (smallest, localized)
In `_order_key`, insert a `state_rank` component that ranks `resource_type == "state"`
(and lifecycle `active`) ahead of other same-role items, e.g.:

```
(role_rank, state_rank, verified_rank, lifecycle_rank, created_at, evidence_id)
```

- **Impact**: B01/B06/B09 state queries surface S1/S3 in primary; decisions still
  present in supporting if budget allows.
- **Risk**: changes ordering for ALL routes that mix state with decisions, not just
  PROJECT. Could demote a decision that a non-state query actually needs. Needs a
  route-conditioned variant to limit blast radius.
- **Token**: ~zero runtime cost; one deterministic tuple component.

### Option B — route-conditioned state priority in the PROJECT route only
Same state_rank idea, but applied only when the route is `PROJECT` (or the request has
explicit project intent). Keeps GLOBAL/SESSION/RESEARCH/USER ordering untouched.

- **Impact**: narrowest blast radius; directly targets the observed failure.
- **Risk**: requires threading route/request context into `select_evidence` (currently
  `_order_key` sees only `EvidenceItem` + `EligibilityResult`). Slightly larger surface.
- **Token**: ~zero runtime; moderate wiring change.

### Option C — let M8.5 calibration re-rank state (deferred)
Promote calibration from metadata-only to a real re-rank key that already models state
freshness/currentness, and order by it.

- **Impact**: principled long-term fix (one producer of currentness).
- **Risk**: M8.5 is explicitly contract-locked as "ordering-only metadata" in the
  current tree; enabling it as a ranking signal is a larger ADR-level change and risks
  changing many ordering guarantees at once. Does not meet the "smallest change" bar
  for this finding.
- **Token**: calibration still zero-LLM, but more code review surface.

## 3. Recommendation
**Option B** (route-conditioned state priority) as the primary candidate: it fixes the
measured starvation with the smallest blast radius and keeps the ordering deterministic
and zero-LLM. **Option A** is the fallback if wiring route context proves heavier than
expected, with a documented cross-route regression check. **Option C** should stay out
of scope for a P1-level fix and be its own ADR.

Before implementing ANY ordering change, a regression baseline must be captured: the
"after" benchmark must keep B01/B03/B06/B09/B10 improved AND all existing non-state
queries (B21/B23/B25/B26/B27) unchanged in their primary composition.

---

## 4. Scale harness plan (N=500 / N=5,000 events) — DO NOT RUN YET

Goal: a production-scale token-savings + Recall@K estimate; the current synthetic corpus
(27 events, full-history ≈182 tokens) is a functional baseline only.

### Generator design
- Deterministic seeded generator producing N memory events across the same five resource
  families (charter/requirement/decision/state/verification + research facts across
  3 knowledge spaces), with:
  - procedurally generated gold labels (auto-derived from a template → gold-id map, no
    hand-labeling);
  - guaranteed `created_at` distribution (not all identical) to remove the tie-break
    artifact and to expose ordering behavior at scale;
  - a fixed fraction of stale/superseded pairs and conflict pairs (reuse existing
    E-DOCKER / E-FUND patterns) so stale-safety and conflict metrics remain non-trivial.
- Emit the same canonical JSONL → `ingest_file` → `rebuild_project_memory` pipeline the
  current harness uses (never bypass the product path).

### Runtime / storage estimate
- N=500: ~10–30 s ingest + query sweep (single process); SQLite on-disk tens of MB.
- N=5,000: ~1–3 min peak; SQLite maybe a few hundred MB; still single-process,
  deterministic, no LLM. Acceptable for a batch gate, not for CI-per-commit.
- Keep determinism: seed fixed; double-run byte-equality assertion must still hold.

### Gate integration
- Run as a *scheduled/CI-staged* gate (not per-commit) with a fixed N and a recorded
  latency budget. Wire it to the same `--json` output shape so the token-savings ratio
  and mean Recall@K/MRR are comparable across runs. Add a storage-footprint report
  (DB file size before/after).

### Decision requested
1. Which ordering option (A / B / C) should be authorized for a follow-up WP?
2. Is the N=500/5,000 scale harness authorized to be built and run (as a gate, not
   per-commit)? If yes, at which N first?

No source code was written for Part 3; this note and the hyphen-fix handoff are the only
new artifacts.