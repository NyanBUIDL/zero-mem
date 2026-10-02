# ADR-V170-03 - Learning harness gates (inert proposals, owner approval, kill switch, fail-safe)

**Status:** ACCEPTED / IMPLEMENTED (repository owner asked for an owner-controlled learning harness in chat, 2026-10-02)
**Date:** 2026-10-02 - **Task:** T14 - **Plan:** `docs/plans/LEARNING-HARNESS-PLAN.md` - **Runbook:** `docs/runbooks/learning-harness.md`
**Related:** ADR-V170-02 (operator approvals), AGENTS.md ("Unverified claims must not become active facts", "inject memory automatically ... before
controlled-injection gates pass", "Cross-profile writes require explicit authorization and review/verification gates")

## Context

An agent should remember project rules, decisions and gotchas across sessions. AGENTS.md forbids automatic injection before controlled-injection gates
pass and forbids unverified claims becoming active facts; ADR-V170-02 already gives shared writes an explicit, attributable, revocable operator approval.
The harness must let an agent *suggest* knowledge without any path by which a suggestion changes what any agent sees until the owner says so, and must
give the owner switches to stop all of it.

## Decision

1. **Injection is off by default.** `[injection] enabled = false`. Per-profile and per-project overrides exist, resolve with the documented precedence
   (project > profile > global; per field), are capped at 8000 characters, and are consulted only by a caller that asks (`resolve_injection`). This phase
   injects nothing.
2. **Proposals are inert.** `Memory.propose` appends a `learning_proposal` event to the canonical stream (the same stream and conventions as
   `agent_profile`, `access_grant`, `operator_approval`). A proposal is not a corpus source and never reaches the retrieval projection, so recall,
   context, search and MCP cannot return it. Rejections (secret, deny pattern, kill switch, mode off, per-day limit, agent proposals disallowed, invalid
   input, unusable settings) store nothing. Duplicates collapse with a bounded `seen` counter and bounded evidence.
3. **Owner approval is the single-write grant.** `Reviewer.approve` (the `zero-mem review approve` command, confirmation required) commits the text through
   the normal write path (schema, caps, secret pre-scan, versioning) as the proposer's profile and skips only `authorize_write`: the owner's approval of
   *that* proposal stands in for the WRITE grant for *that one* write. The `approve` event records proposer, approver, proposal id, resulting source id,
   scope, version and basis (this ADR). No standing grant is created, so the agent still cannot write shared memory on its own. An edit by the owner keeps
   the original in the record and is re-scanned (secrets, deny patterns). There is no approve (or settings) method on `Memory` and no MCP tool for it;
   `Memory` can only list, read and withdraw the calling profile's own proposals.
4. **Everything is derived from the append-only stream.** State is a bounded replay (`ProposalLog`: incremental, byte pre-filtered, torn tail never trusted,
   malformed or forged records ignored, terminal states final, `MAX_REPLAY_EVENTS` cap that makes new proposals fail closed). Revocation reuses the forget
   tombstone; supersession is a new version of the same name; TTLs are evaluated at read time (pending proposals by `proposal_ttl_days`, approved items by
   `active_ttl_days`); no source is mutated or deleted to express a status. No schema change.
5. **Kill switch.** `[safety] kill_switch = true` refuses new proposals and approvals and zeroes injection; reads of existing memory, reject, revoke and
   expire keep working so the owner can clean up.
6. **Fail safe.** A settings file that cannot be read, parsed or validated (closed schema) never crashes a read: learning off, injection off, a `doctor`
   WARN. Defaults with no file are safe: mode `suggest`, injection off.
7. **`auto_low_risk` is reserved.** It is accepted by the schema but behaves exactly as `suggest`; nothing is auto-approved in this phase (tested). Enabling
   it needs a follow-up ADR.
8. **Deterministic, zero dependencies.** TOML via `tomllib`; no LLM, no network; atomic settings writes (temp + `os.replace` under the DEF-090 retry);
   Windows-safe (no POSIX-only calls, UTF-8 everywhere, `/`-normalized refs).

## Write path split (amendment, T17 review of PR #4)

`rule` / `decision` / `gotcha` are ordinary memory types for reading, but not for agent writes. `Memory.add`, `Memory.ingest` and the MCP `memory_add` /
`memory_ingest` refuse them (`denied`, `learned_type_requires_proposal`; the MCP enums omit them), otherwise an agent could create an immediately
recallable source and bypass `learning.mode`, the kill switch, deny patterns and owner approval. Two paths may write them: the Reviewer's approval apply
path, and the owner's direct write (`zero-mem add|ingest|import-notes --type ...`) through `Memory._owner_add` / `_owner_ingest`, an internal entry point
that the default API and MCP layer never use (not a caller-supplied string). The owner CLI has the trust level of `review approve`: agents must not be given
a shell that can run it. Approval is compensating (a failed approval record undoes the commit; retry is idempotent) and active-TTL expiry reads the
provenance of the current version, so an owner-written replacement never expires.

## What this does and does not give

- It gives an auditable, revocable, owner-gated path from "an agent noticed something" to "every agent recalls it", with the owner able to switch the
  whole thing off at any time.
- It does not authenticate the proposer (`source` is a label) or the owner: the trust boundary is the operating-system account that owns the data root,
  exactly as in ADR-V170-02. Agents must not be given a shell that can run `zero-mem review` or `zero-mem settings`.
- It does not claim approved content is *verified* true: approved memories keep lifecycle `observed`; the approval records who accepted them.

## Alternatives rejected

- **Agents writing rules directly with a grant**: no review step; conflicts with "unverified claims must not become active facts".
- **Storing proposals as low-trust corpus sources**: they would be retrievable (even if filtered) and would need a status column on the derived store.
- **Mutating a source to expire or revoke it**: breaks append-only provenance and replay equivalence.
- **A standing WRITE grant created by approval**: widens one decision into a permanent capability.
- **Dedupe across profiles**: would reveal one profile's pending proposals to another.

## Consequences

- `zero_mem/learning_settings.py`, `zero_mem/learning.py`, `zero_mem/commands_learning.py`; `Memory.propose / proposals / proposal / withdraw /
  injection_policy`; memory types `rule`, `decision`, `gotcha` (context sections Rules, Decisions, Gotchas).
- Tests: `tests/unit/test_t14_settings.py`, `test_t14_proposals.py`, `test_t14_cli.py`, `test_t14_concurrency.py`.
- Follow-ups: T15 (task-aware briefing consuming `resolve_injection`, MCP `memory_propose`, `zero-mem eval`), T16 (deterministic learner, hooks).
