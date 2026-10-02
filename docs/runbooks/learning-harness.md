# Learning harness (owner-controlled core)

How an AI agent remembers project **rules, decisions and gotchas** safely. Local, zero-LLM, zero runtime dependencies; Python 3.11-3.13 on
Windows, macOS and Linux. Design and gates: [ADR-V170-03](../v1.6.1/decisions/ADR-V170-03-LEARNING-HARNESS-GATES.md); plan:
[LEARNING-HARNESS-PLAN.md](../plans/LEARNING-HARNESS-PLAN.md). This is wave 1 (settings, types, proposals, review). The task-aware briefing, MCP
`memory_propose` / `memory_brief`, eval and the automatic learner come later (T15 / T16).

## 1. Concepts

| Term | Meaning |
|---|---|
| memory types `rule`, `decision`, `gotcha` | Like `workflow`: versioned by `--name` (`mem://rule/<name>`), scopes `private` / `shared` / `project`. Written by the owner with `zero-mem add --type rule ...`, or created by approving a proposal. |
| **proposal** | An agent's (or the owner's) suggestion, stored as an append-only `learning_proposal` event in the canonical stream. **Inert**: not a corpus source, so `recall`, `context`, `search` and the MCP tools can never return it. |
| **review** | The owner's decision (`zero-mem review ...`): approve (optionally with an edit), reject, revoke, expire. |
| **approval** | Commits the proposal through the normal write path **as the proposer's profile**. The owner's approval is itself the grant for that single write: the agent still cannot write shared memory directly. |
| **injection** | Putting memory into an agent's context automatically. **Off by default**; this phase only provides the owner's settings and `resolve_injection` (the T15 briefing consumes it). |

Lifecycle (derived by replaying the stream; nothing mutates a source to change a status):

```
proposed -> approved -> revoked        (review revoke: the existing forget tombstone)
         |           -> superseded     (a newer approved version of the same name)
         -> rejected | expired | withdrawn
```

Rules of the road: nothing becomes active without the owner; every decision is an audited canonical event (proposer, approver, proposal
id, resulting source id, time); everything is deterministic (no LLM); secrets are rejected before anything is stored.

## 2. Quick start

```bash
zero-mem agents add claude-code                                       # the agent can read ks-shared, write privately
zero-mem --profile claude-code propose "Run pytest -q before every commit." --type rule --name tests --evidence pr#12
zero-mem review list                                                  # pending proposals
zero-mem review show p-3f9a1c0d2b7e
zero-mem review approve p-3f9a1c0d2b7e --yes                          # or --edit "reworded text" --name tests
zero-mem --profile codex search "pytest"                              # now recalled (ks-shared) by every agent with READ
zero-mem review revoke mem://rule/tests --yes                         # later: stop recalling it
```

## 3. Settings (`settings.toml`)

Location: `<config root>/settings.toml` (`zero-mem settings path`; `$XDG_CONFIG_HOME/zero-mem/` or `~/.config/zero-mem/`); override with the environment
variable `ZERO_MEM_SETTINGS`. TOML (parsed with `tomllib`), UTF-8, at most 64 KiB, **closed schema**: an unknown table, key or wrong type makes
the whole file invalid. A missing file means the defaults below.

| Key | Default | Meaning |
|---|---|---|
| `learning.mode` | `"suggest"` | `off`: no new proposals. `suggest`: agents propose, the owner approves. `auto_low_risk`: accepted but **reserved** - it behaves exactly like `suggest` in this phase and never auto-approves (TODO: later phase). |
| `learning.max_proposals_per_day` | `20` | Per proposing profile and UTC day (0 to 1000). A merged duplicate does not count. |
| `learning.allow_agent_proposals` | `true` | `false`: only `source="user"` proposals are accepted (sources `agent` and `learner` are refused). |
| `learning.proposal_ttl_days` | `30` | A pending proposal older than this reads as `expired` (1 to 3650). |
| `learning.active_ttl_days` | `0` | `0`: approved items never expire. Otherwise an item approved through a proposal stops being returned by recall/context once its latest approval is older than this. Not deleted; a newer approval renews it. Owner-written memories (`zero-mem add`) never expire. |
| `injection.enabled` | `false` | Global default for injection. |
| `injection.max_chars` | `2000` | 1 to **8000** (hard cap). |
| `injection.types` | `["rule","decision","gotcha"]` | Subset of `rule decision gotcha workflow skill persona devlog`. |
| `injection.profiles.<name>.{enabled,max_chars,types}` | unset | Per-profile override; each key optional. |
| `injection.projects.<name>.{enabled,max_chars,types}` | unset | Per-project override; each key optional. |
| `safety.kill_switch` | `false` | `true`: no proposals accepted, no approvals, no injection. Reads of existing memory (recall, context, search), reject, revoke and expire still work. |
| `safety.deny_patterns` | `[]` | Extra regexes (case-insensitive, at most 50 of 200 characters; nested unbounded quantifiers such as `(a+)+` are refused). A proposal (text, name, evidence) or approved edit that matches is rejected. Matched against the first 16 KiB only. |

**Precedence** (`resolve_injection(profile, project) -> (enabled, max_chars, types)`), evaluated per field:
`[injection.projects.<project>]` > `[injection.profiles.<profile>]` > `[injection]` > built-in defaults. A field a more specific table does not set is
inherited. `safety.kill_switch = true` and the fail-safe override everything and give `(False, 0, ())`.

**Fail safe.** A file that cannot be read, is not valid TOML or violates the schema never crashes a read: learning is off (new proposals are
refused with reason `settings_invalid`, approvals are blocked), injection is off, and `zero-mem doctor` shows a `learning_settings` WARN. Fix it with
`zero-mem settings validate` / `settings set`, or delete the file to return to the defaults.

CLI (`--json` on each):

```bash
zero-mem settings show                       # effective values and whether the file is valid
zero-mem settings set learning.mode off      # dotted key, validated as a whole, written atomically
zero-mem settings set injection.profiles.claude-code.enabled true
zero-mem settings set injection.types rule,gotcha          # or a JSON list
zero-mem settings set safety.deny_patterns '["internal-host-\\d+"]'    # JSON list of regexes
zero-mem settings unset injection.projects.my-project      # whole override, or one field
zero-mem settings validate                   # exit 2 when unusable
zero-mem settings path
```

`settings set/unset` rewrite the file in a canonical form (comments you add by hand are not kept) and refuse to touch a file that is currently invalid.

## 4. Proposing

```bash
zero-mem --profile claude-code propose "TEXT" --type rule|decision|gotcha|workflow|skill|persona|devlog|fact \
         [--scope shared|private|project] [--project ID] [--name NAME] [--evidence REF ...] [--source agent|user|learner]
```

Library: `Memory.open("claude-code").propose(text, "rule", name="tests", scope="shared", evidence=["pr#12"])` returns a `ProposalResult`
(`proposed`, `merged`, `rejected` with a reason, `rejected_secret`, `invalid`, `error`; nothing raises). `Memory.proposals(status=None)`, `Memory.proposal(id)`
and `Memory.withdraw(id)` only ever see the calling profile's own proposals.

Rejected, nothing stored: secret in the text / name / evidence (same pre-scan as writes), `deny_pattern`, `kill_switch`, `learning_off`,
`agent_proposals_disallowed`, `daily_limit`, `settings_invalid`, invalid type / scope / name / evidence / size (text at most 8 KiB, evidence at most 5
items of 200 characters). A duplicate **pending** proposal from the same profile (same normalized text, type, scope, project and name) is merged: `seen`
increases and new evidence is appended, bounded to 10 items. Duplicates from different profiles stay separate (profiles never learn about each other's proposals).
`source` is a provenance label, not authentication; the safety boundary is the owner's approval.

## 5. Review workflow (owner only)

```bash
zero-mem review list [--status pending|approved|rejected|expired|withdrawn|revoked|superseded|all] [--profile P] [--json]
zero-mem review show ID [--json]                      # text, evidence, history, final (edited) text
zero-mem review approve ID [--edit TEXT] [--name N] [--yes]
zero-mem review reject ID [--reason R]
zero-mem review revoke SOURCE_OR_REF [--reason R] [--yes]
zero-mem review expire                                # record expired pending proposals; list approved items hidden by active_ttl_days
```

* `approve` and `revoke` refuse without `--yes` or an interactive `y` (like `agents grant-write`). With `--edit` the owner's text is stored and the original
  stays in the record. Approval commits a normal source (lifecycle `observed`, scope fields of the target, provenance `proposal`, `proposer`, `approver`),
  or reports `rejected_secret` / `blocked` and leaves the proposal pending. Approving a proposal whose name already exists is a new version
  (the previous approval becomes `superseded`).
* `revoke` appends the existing forget tombstone (raw bytes are kept) and marks the proposal `revoked`; it works on any non-global source.
* `expire` applies `proposal_ttl_days` (reads already treat old pending proposals as expired; this records it) and lists items past `active_ttl_days`.

Exit codes as in the [quickstart](shared-memory-quickstart.md#exit-codes): 3 for a policy refusal (kill switch, limits, deny pattern), 4 for a secret, 5 not found.

**Do not give agents a shell that can run `zero-mem review` or `zero-mem settings`.** The confirmation is friction, not authentication: anyone who can
write the data root can forge canonical events (the same trust boundary as ADR-V170-02). Give agents only the library / MCP surface; neither has an approve or
settings method.

## 6. Safety model

1. Injection is off by default and capped (8000 characters); the kill switch and an unusable settings file turn it off everywhere.
2. Proposals are inert canonical events; only an owner action creates a source.
3. Owner approval is the single-write grant: recorded with proposer, approver, proposal id and source id; no standing grant is created.
4. Secrets and `deny_patterns` are checked before a proposal is stored and again on any edit; text, name and evidence are all scanned.
5. Per-profile daily limit, bounded text / evidence / seen counters, bounded replay (`MAX_REPLAY_EVENTS`; beyond it new proposals are refused).
6. Everything derives from the append-only stream; a derived-database rebuild or `zero-mem upgrade` yields the same proposal states.

## 7. What is NOT automatic

* Nothing is approved automatically (`auto_low_risk` is reserved and behaves as `suggest`).
* Nothing is injected into any agent's context: no hook, no `context` change driven by `injection.*` (T15 adds the briefing that reads those settings).
* No MCP proposal tool yet (T15), no learner extracting candidates from transcripts / corrections / git (T16), no eval harness (T15).
* Proposals are not merged across profiles, not ranked, not de-conflicted against existing rules, and a same-name approval simply versions the source.
* Expiry never deletes: pending proposals stay in the stream, expired approved items stay as sources.
