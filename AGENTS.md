# Zero-Mem Agent Constitution

This file defines stable, repository-wide rules for human and autonomous agents.
It is intentionally version-neutral. Release status, active work packages, and
temporary execution notes belong in `implementation-plan.json` and the matching
`docs/vX.Y.Z/` directory, not in this file.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**,
and **MAY** are normative.

## 1. Authority and precedence

When instructions conflict, agents MUST apply this order:

1. explicit maintainer instruction for the current task;
2. `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`;
3. accepted specification amendments and ADRs applicable to the target version;
4. this file and mandatory repository governance policies;
5. the approved version master plan and active work package;
6. code comments, generated summaries, projections, and agent claims.

Lower-authority material MUST NOT silently override higher-authority material.
An ambiguity that changes public behavior, security, canonical data, or release
scope is a stop condition and MUST be reported as `ESCALATION_REQUIRED`.

Before work begins, the agent MUST resolve and record:

- repository root, current branch, baseline full SHA, and dirty paths;
- active target version and approved work package;
- applicable master-spec sections, amendments, ADRs, and validation gates;
- files and contracts in scope, dependencies, exclusions, and rollback boundary.

## 2. Product purpose and ownership

Zero-Mem is a local-first, deterministic evidence and memory sidecar for Hermes.
It captures permitted lifecycle evidence, redacts sensitive content, persists
canonical events, builds queryable derived state, and provides bounded,
authorized reads with provenance and freshness.

Hermes remains the orchestration and final-action owner. Hermes owns agent
reasoning, tool selection, final responses, SOUL/persona, cron execution, and
Agent Skill contents. Zero-Mem MUST NOT replace those responsibilities or
silently make user-facing decisions on Hermes's behalf.

Zero-Mem MAY observe skill, cron, task, session, tool, message, and subagent
lifecycle events when the active contract permits it. It MUST NOT rewrite
`SKILL.md`, mutate SOUL/persona, create or execute Hermes crons, or activate an
agent-generated Skill without the required schema, security, test, and review
gates. Agent Skills compatibility MUST preserve the applicable agentskills.io
contract.

## 3. Non-negotiable architecture invariants

1. For v1.2 and later, append-only JSONL is canonical truth for memory events
   and traces. Event identity, sequence, provenance, history, and lifecycle
   records originate there.
2. SQLite, FTS5, indexes, graphs, vectors, materialized views, and Obsidian or
   Markdown workspaces are derived, rebuildable projections. They MUST NOT
   silently rewrite canonical history.
3. Versioned artifacts are authoritative only for their own contents. They do
   not become the canonical memory-event stream.
4. Capture success requires canonical durability. Projection failure MUST NOT
   turn a durable append into capture failure; it MUST produce a truthful typed
   stale, pending, degraded, or unavailable state.
5. Recovery flows from canonical sources to derived state, never in reverse.
6. One runtime composition root MUST own the canonical writer, derived store,
   projection/checkpoint state, authorized read service, and health identity.
   Parallel production topologies for the same contract are forbidden.
7. Authorization MUST occur before retrieval, FTS/SQL discovery, candidate
   counting, snippet creation, or other existence-revealing work.
8. Raw secrets MUST be rejected or redacted before every persistence boundary,
   including canonical events, dead letters, logs, audit records, exceptions,
   temporary files, control-event rationale, and evidence.
9. Raw traces are append-first and retain provenance. Correction, supersession,
   and delete requests create linked canonical control events through an
   authorized HITL path; they MUST NOT silently overwrite or physically erase
   canonical history.
10. Verified state outranks assistant self-report. Conflicts remain visible with
    sources and resolution records; unverified claims MUST NOT become active
    facts.
11. Memory operations MUST use deterministic/local mechanisms by default and
    make zero LLM calls. An LLM MAY be used only in the separately owned final
    reasoning/response layer when explicitly permitted.
12. Host observation MUST be non-interfering: capture failure MUST NOT mutate
    host payloads, return values, exceptions, control flow, or final actions.

Any proposal that changes one of these invariants requires a specification or
ADR decision before implementation.

## 4. Runtime-mode contract

The active version documentation defines exact configuration and migration
details. Production behavior MUST preserve this capability boundary:

| Mode | Capture | Explicit authorized reads | Automatic injection |
|---|---:|---:|---:|
| `off` | No | No | No |
| `observe` | Yes | No | No |
| `assist` | Yes | Yes | No |
| `inject` | Yes | Yes | Controlled only |

Each table cell MUST have direct executable coverage. `off` MUST register no
Zero-Mem hook or tool and MUST open no writer or derived store. `observe` is the
backward-safe default unless an approved versioned migration explicitly says
otherwise. Missing, invalid, or contradictory configuration MUST fail closed;
health and status surfaces MUST report effective behavior, not requested intent.

## 5. Work discovery and state machine

Current release status is not stored in this file. Agents MUST read
`implementation-plan.json`, then the matching `docs/vX.Y.Z/00-START-HERE.md`,
master plan, agent protocol, validation specification, code traceability map,
and work-package record. If a required file does not exist, the agent MUST use
the latest applicable approved authority and record the gap.

The normative package state machine is:

```text
PLANNED -> APPROVED -> IN_PROGRESS -> IMPLEMENTED
                                   -> BLOCKED
IMPLEMENTED -> INDEPENDENTLY_VERIFIED -> BRANCH_READY
BRANCH_READY -> RELEASE_QUALIFIED
```

- Exactly one package MAY own a shared public contract or composition root at a
  time. Independent packages MAY run in parallel only when file ownership,
  public contracts, data migrations, and integration boundaries do not overlap.
- An agent MUST select the smallest complete vertical slice whose dependencies
  are independently verified. A vertical slice includes production wiring,
  negative behavior, tests, documentation, and evidence.
- `IMPLEMENTED` means code exists; it does not mean verified.
- `INDEPENDENTLY_VERIFIED` requires the hard gate in Section 9.
- `BRANCH_READY` means the approved branch gates pass at an exact SHA.
- `RELEASE_QUALIFIED` additionally requires the complete platform, packaging,
  artifact, provenance, security, and release gates. Branch-ready or a successful
  focused suite MUST NOT be presented as release-qualified.
- A delivery run MAY continue to the next approved, non-overlapping package
  after independent verification. It MUST stop on a hard gate, missing authority,
  failed dependency, scope expansion, or required maintainer decision.

Only the designated state owner MAY update status, and only from executable
evidence for the exact tested SHA. Agents MUST NOT use documentation wording to
promote code state.

## 6. Required implementation workflow

For every package, agents MUST perform these steps in order:

1. **Inspect:** record branch, full baseline SHA, worktree state, environment,
   active authority, dependencies, and current executable call path.
2. **Lock the contract:** define inputs, outputs, statuses, side effects,
   failure semantics, ownership, bounds, compatibility, and migration behavior.
3. **Establish acceptance:** add or identify happy-path, negative, security,
   failure, restart, and platform tests before changing the implementation.
4. **Implement:** change the smallest production vertical slice; reuse the
   canonical writer, authorization layer, runtime composition root, and platform
   abstraction instead of creating a parallel path.
5. **Integrate:** prove the public production path from real entry point through
   persistence/projection/read or control result. Internal helpers alone are not
   acceptance evidence.
6. **Validate:** run focused, dependency, integration, security, concurrency,
   recovery, compatibility, and documentation checks applicable to the change.
7. **Review independently:** apply Section 9 against a clean checkout or detached
   exact SHA.
8. **Record evidence:** write sanitized, reproducible results using Section 10.
9. **Update state:** promote only after every required gate passes; otherwise
   record `BLOCKED` with evidence and an explicit unblock condition.
10. **Integrate safely:** follow repository Git/GitHub policy; do not publish or
    release unless that separate action is explicitly authorized.

Mocks, unit tests of an internal class, `compileall`, self-review, documentation,
or a claimed architecture diagram MUST NOT substitute for production-path proof.

## 7. Change-coupling rule

When a public field, event type, status, mode, schema, storage identity, or
failure semantic changes, the same package MUST update all applicable items:

1. normative contract or schema;
2. producer and host mapping;
3. runtime composition and consumer/adapter;
4. migration and backward behavior;
5. public API, CLI, health, and sync surfaces;
6. positive, negative, security, restart, and platform tests;
7. code traceability and operator/runbook documentation;
8. evidence bound to the exact tested full SHA.

Partial updates MUST remain `IMPLEMENTED` or `BLOCKED`; they MUST NOT be labeled
verified. New network services, vector databases, LLM calls, deep Hermes-core
changes, or duplicate persistence paths are out of scope unless an approved
contract explicitly requires them.

## 8. Subagent and parallel-work rules

A lead agent MAY delegate bounded tasks only after contract, file ownership,
inputs, outputs, dependencies, validation commands, and stop conditions are
written down. Each subagent MUST receive one independently reviewable scope.

Subagents MUST NOT:

- edit the same production contract or composition root concurrently;
- change architecture, schema, public semantics, dependencies, or release state
  outside their assigned scope;
- merge, tag, release, force-push, delete, or rewrite history unless separately
  and explicitly authorized;
- mark their own work independently verified;
- conceal failed, skipped, flaky, or unavailable checks.

The lead agent owns reconciliation, integration tests, evidence completeness,
and final state transitions. Parallel outputs MUST be integrated sequentially
and revalidated together. If overlap or contradiction appears, agents MUST stop
the affected work and reconcile the contract before further implementation.

## 9. Independent-verification hard gate

Independent verification is valid only when all conditions below are met:

- the verifier is a separate agent session or human reviewer and did not author
  the implementation under review;
- verification runs from a clean checkout or detached exact tested full SHA;
- the verifier independently executes the required commands before accepting
  the implementer's verdict;
- production entry points and negative/security paths are exercised, not only
  internal units or mocks;
- the record contains verifier identity, session/run identifier, baseline and
  tested full SHAs, environment, exact commands, raw log paths, checksums, and
  pass/fail/skip/error counts;
- the verifier records limitations, blockers, and a `PASS`, `FAIL`, or `BLOCKED`
  verdict without editing the result to match the implementation claim.

The same agent, same session/context, self-issued reviewer label, or implementer
rerun is not independent verification. If an independent verifier or required
environment is unavailable, the package MUST remain `IMPLEMENTED` or `BLOCKED`.
Dependent work MAY proceed only when the approved plan explicitly allows it;
`BRANCH_READY`, `RELEASE_QUALIFIED`, tag, or release claims are forbidden.

## 10. Validation and evidence

Every changed module requires applicable schema/migration coverage, unit and
failure tests, structured diagnostics, provenance, security/redaction coverage,
and rollback/runbook documentation. Validation depth MUST match the risk and the
active version's `VALIDATION_SPEC.md`.

The minimum evidence record is machine-readable and human-readable and contains:

```text
package_id
authority_and_acceptance_ids
baseline_full_sha
tested_full_sha
verifier_id_and_session
clean_checkout_or_detached_sha
os_python_architecture_and_tool_versions
exact_sanitized_commands
pass_fail_skip_error_counts
raw_log_paths_and_sha256_checksums
production_e2e_result
security_and_secret_scan_result
compatibility_migration_and_recovery_result
known_limitations_and_blockers
verdict_and_timestamp
```

Evidence MUST distinguish pass, fail, skip, error, not-run, and unavailable.
Missing logs, missing checksum, abbreviated or mismatched SHA, a collection
error, or an unexplained skip is a failed gate, not a pass. Secrets, tokens,
private user content, and machine-specific credentials MUST be sanitized before
evidence is committed.

Required production acceptance includes, where applicable:

- direct API and real Hermes host/plugin entry points;
- capture -> canonical append -> projection -> authorized read -> restart;
- runtime-mode registration and no-op behavior;
- canonical/derived identity, watermark, lag, health, and sync truthfulness;
- authorization denial before discovery and non-leakage;
- HITL preview -> explicit confirmation -> linked control event -> rebuild;
- secret rejection/redaction across every persistence and diagnostic surface;
- bounded overload, concurrency, corruption, recovery, and rollback behavior;
- Windows, Linux, and macOS behavior for every platform claimed as supported;
- wheel/sdist clean install and smoke tests from the exact candidate SHA.

## 11. Security, privacy, and destructive operations

- Treat all captured content, paths, prompts, tool arguments, traces, artifacts,
  logs, and evidence as untrusted input.
- Apply strict schemas, size/time/result bounds, safe path resolution, atomic
  writes, least privilege, and fail-closed authorization.
- Do not expose existence through IDs, counts, snippets, timing detail, errors,
  health payloads, or logs before authorization.
- Do not execute generated code or Skills outside an approved sandbox and review
  path. Sandbox escape, network access, credential access, and host filesystem
  mutation require explicit policy and tests.
- Do not install system-wide dependencies or perform destructive data, schema,
  history, branch, tag, remote, release, or filesystem operations without
  explicit authorization, an exact target, a checkpoint/backup, and a tested
  rollback plan.
- Canonical traces, superseded decisions, and evidence MUST NOT be deleted to
  make a test or audit appear clean.

## 12. Cross-platform contract

Core behavior MUST use the repository platform abstraction and MUST NOT embed
unguarded POSIX- or Windows-only assumptions. Filesystem identity, locking,
atomic replacement, sync, symlink/reparse-point handling, permissions, path
normalization, process lifecycle, and cleanup require target-OS tests.

Support claims require real execution on every declared OS and supported Python
version. A conditional skip is acceptable only with a precise reason and an
executed equivalent gate elsewhere; it does not qualify an untested platform.
Local success on one operating system MUST NOT be generalized to the support
matrix.

## 13. Git, GitHub, and release governance

Before any Git or GitHub mutation, the agent MUST read
[`docs/governance/GITHUB-POLICY.md`](docs/governance/GITHUB-POLICY.md), inspect
repository identity and status, classify every dirty path, and obey all stop
conditions. Stage only named, authorized paths; never use broad staging to absorb
unrelated or user-owned changes.

A commit, pushed branch, passing local test, tag, GitHub Release, and qualified
artifact are different states. Agents MUST NOT force-push, rewrite protected
history, move published tags, bypass required checks, or infer publication
authorization from implementation authorization.

Release qualification requires successful remote CI for the exact candidate SHA,
the declared OS/Python matrix, clean-install artifacts, artifact hashes and source
provenance, independent audit, zero open blocking findings, and the release SHA
invariant defined by repository policy. Creating a workflow file is not evidence
that the workflow ran successfully.

## 14. Mandatory stop conditions

The agent MUST stop the affected operation and report `BLOCKED` or
`ESCALATION_REQUIRED` when any of these conditions applies:

- authority, target version, approved scope, repository identity, or ownership
  is ambiguous;
- an architecture invariant, security boundary, or public semantic requires an
  unapproved change;
- dependencies are not independently verified and no written waiver exists;
- canonical and derived paths cannot be proven to share the approved topology;
- a required production E2E, security gate, migration, recovery test, platform,
  independent verifier, or remote CI result is unavailable or fails;
- a test passes only by weakening authorization, redaction, evidence, assertions,
  platform coverage, or by skipping a core path;
- the worktree contains unknown/unclassified changes or integration would
  overwrite another owner;
- exact-SHA evidence is missing, contradictory, stale, or not reproducible;
- completion would require destructive operations, external publication, deep
  Hermes-core modification, or scope expansion without explicit authorization;
- Git/GitHub governance declares a stop condition.

A stop is a valid safety result. Agents MUST NOT convert it into partial success,
silently reduce acceptance criteria, guess owner intent, or claim completion.

## 15. Definition of done

A work package is done only when:

- the approved contract is implemented through the real production path;
- all required positive, negative, security, recovery, compatibility, platform,
  and integration gates pass at the exact tested full SHA;
- canonical data, provenance, authorization, privacy, and Hermes ownership
  invariants remain intact;
- documentation, traceability, migrations, runbooks, rollback, and evidence match
  executable behavior;
- independent verification passes and no blocking finding remains;
- the state owner records the correct state without implying release readiness.

If any item is missing, report what is implemented, what is unverified or
blocked, the evidence available, and the exact unblock condition. Do not report
the package, branch, or release as complete.
