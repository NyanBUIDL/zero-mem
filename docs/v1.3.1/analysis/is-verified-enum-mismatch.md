# Analysis — registry #5: `is_verified` enum mismatch (OPEN QUESTION for Gate G6)

**Status:** ANALYSIS ONLY — no behavior change (per V131-FULL-PROMPT WP-8).
**Deferred from:** v1.3.0 closure, registry finding #5.

## 1. The defect

`src/integration/m7/eligibility.py` line 178:

```python
verification = (_attr(item, "verification_status", "verification") or "").lower()
is_verified = verification in ("verified", "confirmed")
```

The M1-approved verification model (`src/capture/event_types.py`,
`VerificationStatus`) has exactly these values:

| Enum value | Meaning |
|---|---|
| `none` | unverified capture |
| `direct_tool_output` | verified by direct tool output |
| `user_confirmation` | verified by explicit user confirmation |
| `deterministic_verification` | verified deterministically (zero-LLM) |
| `approval` | verified by maintainer approval |

Neither `"verified"` nor `"confirmed"` exists in the enum → `is_verified`
is **always False for memory events**. Note `"confirmed"` IS a *Lifecycle*
value (`LifecycleStatus.CONFIRMED`), not a verification value — the check
appears to have conflated the two taxonomies. This is also independently
documented in `src/project_memory/contracts.py` (M4.5): "No `verified` /
`unverified` / `disputed` / `conflict` values exist in the approved model."

## 2. Impact set

- Single call-site: line 178 (`is_verified`), consumed at lines 181–183 in the
  primary/supporting role classification:
  `primary = (is_active and is_verified) or memory_type in ("decision",
  "verified_state", "tool_observation") or lifecycle == "confirmed"`.
- Practical effect today is LIMITED because three of four primary paths do not
  depend on `is_verified`: memory events of type decision / verified_state /
  tool_observation still classify primary via `memory_type`, and lifecycle
  `confirmed` promotes regardless. The dead check only affects events that are
  active + non-promotable-type + relying solely on verification status.
- Behavior baseline was reviewed and approved as-is in v1.3.0 closure; any fix
  changes role classification globally and requires its own gate.

## 3. Options

### Option A — align check to the enum (recommended)

```python
_VERIFIED_STATUSES = {
    VerificationStatus.DIRECT_TOOL_OUTPUT.value,
    VerificationStatus.USER_CONFIRMATION.value,
    VerificationStatus.DETERMINISTIC_VERIFICATION.value,
    VerificationStatus.APPROVAL.value,
}
is_verified = verification in _VERIFIED_STATUSES   # "none" stays unverified
```

- Pros: restores intended semantics ("verified fact outranks self-report",
  AGENTS.md); uses the single approved taxonomy; fail-closed preserved (`none`
  → False).
- Cons/risks: events previously classified supporting may become PRIMARY once
  they carry a real verification status — a global retrieval-role change.
  Requires regression sweep over M7 eligibility tests + benchmark Recall@K
  re-run. Must NOT retroactively promote historical raw traces without a
  documented migration note (append-first: no rewrite needed — classification
  is derived/read-time, so it is rebuildable by design).

### Option B — keep behavior, document mapping only

Formalize that `VerificationStatus` never maps to `is_verified=True`, delete or
comment-out the dead branch, and rely on `memory_type`/`lifecycle` paths.

- Pros: zero behavioral change; smallest possible diff.
- Cons: permanently encodes the conflation; `user_confirmation` /
  `deterministic_verification` events can never be primary on verification
  strength alone — weakens the verified-state contract long-term.

## 4. Recommendation

Option A, executed as its own work package in v1.3.x with:
RED tests enumerating every enum value → implement → focused M7 suite →
full suite → Graphify impact re-check on final tree → release-notes entry.
Estimated scope: ~1 file + tests; no schema/migration impact.

## 5. Decision needed (Gate G6)

- [ ] Approve Option A for a follow-up version, or
- [ ] Approve Option B (freeze semantics), or
- [ ] Defer again with rationale.
