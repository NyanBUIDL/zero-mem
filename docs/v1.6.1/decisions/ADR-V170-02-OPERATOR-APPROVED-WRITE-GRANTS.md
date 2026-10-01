# ADR-V170-02 - Operator-approved WRITE grants (verification for single-user installs)

**Status:** ACCEPTED / IMPLEMENTED (repository owner approved shared writes in chat, 2026-10-01)
**Date:** 2026-10-01 - **Task:** T5 - **Design:** `docs/design/SHARED-MEMORY-RUNTIME.md` sections 3, 4D
**Related:** ADR-V141-01 (grant admin stays a trusted control plane), `src/access/admin.py`, `src/access/resolver.py`

## Context

Many agents (Claude Code, Codex, Hermes, OpenClaw) should share one memory (`ks-shared`) while each keeps private
scratch memory. `AGENTS.md` says *"Cross-profile writes require explicit authorization and review/verification
gates."* The M5 pipeline implements that gate: `authorize_write` allows a write to a knowledge space or project only
under an active WRITE grant whose `verification_ref` resolves, through a `verification_lookup`, to a record whose
`verification_status == "verified"` (`resolver.resolve_write_grant`); `GrantAdminService.create` refuses a WRITE grant
that does not verify.

The only production-shaped source of such records is M4 project memory (`project_memory.reader.get_verification`),
which needs a project charter, requirements and an authored verification chain. A single-user machine that just wants
"let Codex write to the shared space" has none of that, and `verification_lookup` had **no production implementation**
(the write/grant services had zero production callers). Without a lookup no WRITE grant can ever exist, so either shared
writes stay impossible or the gate gets bypassed. Bypassing it (for example an unconditional-true lookup) is not acceptable.

## Decision

1. **A WRITE grant is created only by an explicit operator action**, `zero-mem agents grant-write <profile>
   (--space <ks> | --project <id>)`, which requires confirmation (`--yes`, or an interactive `y`). It is not reachable
   from any agent request: there is no MCP/library tool that creates grants, `GrantAdminRequest` has no authority field,
   and the structural read-only tool list of the MCP server is unchanged.
2. **The verification is a canonical operator-approval event.** Before the grant exists the command appends, to the
   canonical memory stream (`events-v1.jsonl`), an `operator_approval` event recording *who* approved (the OS user),
   *what* (`subject_profile`, `operation=WRITE`, `target_type`, `target_id`), *when* and *why* (`basis`, default: this ADR),
   under a fresh `approval_ref` (`opapp-<16 hex>`). The WRITE grant's `verification_ref` is that `approval_ref`.
3. **`OperatorApprovalLookup` is the `verification_lookup`.** It maps `approval_ref -> OperatorApproval` read from those
   canonical events (incrementally, never trusting a torn final line, ignoring malformed or foreign records). It returns
   `verification_status="verified"` only for an approved, not-revoked ref; a revoke is terminal for its ref. It is injected
   into `GrantAdminService` (at grant time) and `authorize_write` (at every write), so a grant whose approval is missing
   or revoked authorizes nothing, even if its derived row looks active.
4. **Least privilege by default.** `zero-mem agents add <profile>` records the profile (canonical `agent_profile` event) and
   grants READ on `ks-shared` only. A new agent can write privately (its own profile) and nothing else. Shared writes need
   `grant-write ... --space ks-shared`; devlog (project-scoped) writes need `grant-write ... --project <id>`. WRITE grants are
   limited to `resource_types=["corpus_source"]` and to exactly one target.
5. **Revocable.** `zero-mem agents revoke <profile> [--space|--project] [--read|--write]` appends the canonical grant revoke
   event and, for WRITE grants, a canonical `operator_approval` revoke event. Either one alone denies the write.
6. **Audited.** Every write decision that is a DENY or uses a grant is recorded as a canonical `policy_decision` event
   through `src/access/audit.py` (requester, operation, target scope, reason code, grant refs; never content) and projected
   to `zm_policy_audit`. Provisioning actions are themselves canonical events (`agent_profile`, `access_grant`,
   `operator_approval`), so the whole history is replayable and survives `zero-mem upgrade` / backup / restore.
7. **Everything stays rebuildable.** Grants replay through the existing `rebuild_policy_state`; approvals are re-read from the
   stream by the lookup; no new table, no schema change (version stays 13).

## What this does and does not give

- It is an **explicit, attributable, revocable, audited operator approval** that satisfies the verification predicate of the
  existing WRITE-grant machinery. It is deliberately **not** an M4 verification record and does not claim the content of what
  agents later write is verified: agent-authored memories keep lifecycle `observed` (AGENTS.md: unverified claims must not
  become active facts).
- The trust boundary is the operating-system account that owns the data root (mode 0700/0600). Anyone who can write the canonical
  stream can forge an approval; the same is already true for grants and every other canonical event. Agents must therefore not be
  given a shell that can run `zero-mem agents grant-write` on their own behalf; the confirmation step is a deliberate friction, not
  an authentication mechanism. A multi-user deployment should replace the lookup with M4 verification records (the injection
  point is unchanged).
- The M4 route is not removed: a deployment that authors verified M4 verification records can still pass
  `project_memory.reader.get_verification` as the lookup.

## Alternatives rejected

- **Unconditional-true / "trusted" lookup**, or letting agents write shared memory with only a READ grant: removes the
  cross-profile gate AGENTS.md requires.
- **A second authorization store for the CLI** (the removed `zero-mem grant` of V141-R2 was exactly that): grants must live in the
  canonical stream the production read path already uses.
- **Requiring M4 verification records for single-user setups:** blocks the feature on infrastructure that has no operator workflow.
- **Auto-granting WRITE to registered agents:** the owner approved shared writes as an explicit per-agent decision, not a default.

## Consequences

- `zero-mem agents add|grant-write|grant-read|revoke|list` (`zero_mem/commands_memory.py`, `zero_mem/provisioning.py`).
- Tests: `tests/unit/test_t5_provisioning.py` (approval-before-grant order, forged grant denied, revoke of either half denies,
  replay after a derived rebuild, torn/malformed lines, least-privilege default) and the write-path tests in
  `tests/unit/test_t5_memory_write.py`.
- Follow-up (T6): the MCP write tools call the same `Memory` write path; they never expose grant administration.
