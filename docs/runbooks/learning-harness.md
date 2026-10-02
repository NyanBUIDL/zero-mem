# Learning harness (owner-controlled core)

How an AI agent remembers project **rules, decisions and gotchas** safely. Local, zero-LLM, zero runtime dependencies; Python 3.11-3.13 on
Windows, macOS and Linux. Design and gates: [ADR-V170-03](../v1.6.1/decisions/ADR-V170-03-LEARNING-HARNESS-GATES.md); plan:
[LEARNING-HARNESS-PLAN.md](../plans/LEARNING-HARNESS-PLAN.md). Wave 1 (T14) is settings, types, proposals and review (sections 1-7); wave 2 adds the task briefing `zero-mem brief` / `Memory.brief`, the MCP tools
`memory_brief` and `memory_propose`, and the eval harness (T15, sections 8-11). The automatic learner comes with T16.

## 1. Concepts

| Term | Meaning |
|---|---|
| memory types `rule`, `decision`, `gotcha` | Like `workflow`: versioned by `--name` (`mem://rule/<name>`), scopes `private` / `shared` / `project`. Written by the owner with `zero-mem add --type rule ...`, or created by approving a proposal. |
| **proposal** | An agent's (or the owner's) suggestion, stored as an append-only `learning_proposal` event in the canonical stream. **Inert**: not a corpus source, so `recall`, `context`, `search` and the MCP tools can never return it. |
| **review** | The owner's decision (`zero-mem review ...`): approve (optionally with an edit), reject, revoke, expire. |
| **approval** | Commits the proposal through the normal write path **as the proposer's profile**. The owner's approval is itself the grant for that single write: the agent still cannot write shared memory directly. |
| **injection** | Putting memory into an agent's context automatically. **Off by default**; the owner's settings and `resolve_injection` decide, and `Memory.brief` (section 8) obeys them. |

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
* Nothing pushes memory into an agent's context: `brief` returns content only when an agent or hook ASKS for it and the owner enabled injection; no hook is installed for you, and `context` ignores `injection.*`.
* The deterministic learner (`zero-mem learn`) only FILES proposals from user statements in transcripts / git / text; see [agent-integration section 7a](agent-integration.md). Agents can also propose through `zero-mem propose` or, with `--enable-propose`, the MCP tool `memory_propose`. Every proposal waits for your review.
* Proposals are not merged across profiles, not ranked, not de-conflicted against existing rules, and a same-name approval simply versions the source.
* Expiry never deletes: pending proposals stay in the stream, expired approved items stay as sources.

## 8. The task briefing (`zero-mem brief`, `Memory.brief`)

What an agent needs at the start of a task, in one bounded text. Deterministic, zero LLM calls, same authorization path as `recall` (own private memory, the
shared space, and the one project asked for).

```bash
zero-mem [--profile P] brief [--task TEXT] [--max-chars N] [--project ID] [--preview] [--json]
```

```python
bundle = memory.brief(task="write a database migration", max_chars=None, project_id=None, preview=False)   # -> BriefBundle
bundle.text; bundle.status; bundle.reason; bundle.sources; bundle.items; bundle.sections; bundle.omitted; bundle.truncated; bundle.as_dict()
```

**Content, in this order**, filled within `max_chars` (default `injection.max_chars`, 2000; at most 8000), and only for the types in `injection.types`
(default `rule, decision, gotcha`; add `workflow`, `skill`, `persona`, `devlog` to widen it):

1. `## Rules`: every active `rule` (newest version of each name, expired ones excluded). Always included, but while other sections have content they take at most 60% of the
   budget; whatever the later sections leave unused goes back to the rules.
2. `## Decisions`, `## Gotchas`, `## Workflows`, `## Skills`: items matching `--task` (the existing lexical retrieval, one query per type, best score first, ties by ref). Each line ends with
   `(matched: <task words found in it>)`. **No task, no matched items.**
3. `## Recent devlog`: the project's newest entries (at most 5; needs `--project`).
4. `## Persona`, last.

Every line starts with the item's ref (`- mem://gotcha/db-locked: ...`) so the agent can cite it. A line is at most 300 characters. Proposals, rejected / withdrawn / revoked
items, forgotten sources, items past `active_ttl_days`, unreadable projects and other profiles' private memory never appear (they are never corpus sources the profile may read).
Truncation is explicit: `truncated`, per-section `sections` (lines included) and `omitted` (candidates that did not fit). `context()` is unchanged.

**Settings gate.** `resolve_injection(profile, project)` decides. While injection is disabled, the kill switch is on, or the settings file is unusable, a normal call returns an
EMPTY bundle (`status: disabled`, `text: ""`) with `reason` `injection_disabled` / `kill_switch` / `settings_invalid`, reads nothing and never raises. The CLI prints nothing on
stdout and one explanation on stderr, exit 0 (a session-start hook must not fail because injection is off). `--preview` (owner view) returns what WOULD be injected under the
settings that apply (kill switch and fail-safe ignored for the content), plus the `reason` it is currently off; it is meant for the owner's terminal and for `eval`. An explicit `--max-chars`
overrides the setting up to the 8000 hard cap; `injection.types` and the on/off state are always the owner's.

Exit codes: 0 ok (also when disabled), 2 invalid input (`--max-chars` outside 1..8000, bad project id).

## 9. MCP: `memory_brief` and `memory_propose`

* `memory_brief(task?, max_chars?)` is in the default read set (with `memory_recall`, `memory_context`). While injection is off it answers `EMPTY` with `reason_code`
  `injection_disabled`; once the owner enables it for the profile it returns `{status: SUCCESS, text}`. It has no `project_id` (the tool list is kept tiny: +450 characters),
  so project-scoped rules and the devlog need the CLI (`zero-mem brief --project`).
* `memory_propose(text, memory_type, scope, name?, project_id?, evidence?)` is mounted only with `--enable-propose` (env `ZM_M6_ENABLE_PROPOSE=1`), accepted by `zero-mem serve` and
  `zero-mem mcp-config`. It calls `Memory.propose(source="agent")` as the pinned profile; the schema is closed (no identity, authority or `source` field; a spoofed one is
  `DENIED`). It returns `{status: PROPOSED, proposal_id, message}`: nothing is memory, nothing is recallable until `zero-mem review approve`. A rejection is an error
  (`isError: true`): `REJECTED` with `reason_code` (`learning_off`, `kill_switch`, `agent_proposals_disallowed`, `daily_limit`, `deny_pattern`, `settings_invalid`) or `REJECTED_SECRET`.
  No write grant is needed to propose.

```bash
zero-mem mcp-config --agent claude-code --enable-propose   # register; the output lists the operator steps
zero-mem review list                                        # the owner decides, out of band
```

## 10. Eval: does the memory deliver?

Owner-written cases, replayed through `Memory.brief(preview=True)`: they measure the content even while injection is off (reported separately as `injection_off_cases`).

```bash
zero-mem eval init [PATH]                  # write an example cases file (default ./brief-eval.jsonl; --force to overwrite)
zero-mem [--profile P] eval run FILE [--json]   # exit 0 all pass, 1 any failure, 2 unusable file
zero-mem eval history [-n N] [--json]      # the trend of recorded runs
zero-mem eval safety [--json]              # build a throw-away store, assert the invariants; exit 1 on a violation
```

A case is one JSON object per line (closed schema; at most 500 cases; ids unique):

```json
{"id": "db-locked", "task": "the database is locked when two agents write", "must_include": ["mem://gotcha/db-locked"], "must_not_include": ["TODO-unapproved"], "profile": "codex", "project": "my-project", "max_chars": 1500}
```

`must_include` / `must_not_include` entries starting with `mem://` match a ref in the briefing (exact; a trailing `/` matches a prefix such as `mem://gotcha/`); anything else is a
case-insensitive substring of the briefing text. `profile` defaults to `--profile`; `max_chars` to the injection setting.

Per case: PASS / FAIL, `missing`, `forbidden`, characters used versus the budget, `truncated`, latency. Aggregates: `recall` (found / required `must_include`), `forbidden_hits`,
`truncated` count, latency average and maximum, `injection_off_cases`. Each `run` appends one summary line to `<data root>/eval-history.jsonl` (private file, counts only: no task text, no
paths, only the cases file's base name; trimmed to the newest 250 lines once it passes 500; corrupt lines are skipped when reading).

`eval safety` never touches your store or settings. It asserts that pending, rejected, expired (`active_ttl_days`), forgotten and superseded items never appear in `brief` (live or preview),
`context` or `recall`; that another profile's private items never appear; that the kill switch, a disabled injection and an unusable settings file empty the live briefing; that `max_chars` is
never exceeded (1..8000, 8001 refused); and that repeated calls are identical. A control check proves the approved items DO appear, so the others cannot pass vacuously.

## 11. Worked example

Every command below was run against a temporary `ZERO_MEM_DATA_ROOT` / `ZERO_MEM_SETTINGS` (millisecond figures and ids vary).

```text
$ zero-mem setup
READY
$ zero-mem agents add codex
added  codex  (read ks-shared; private write only)
$ zero-mem agents grant-write codex --space ks-shared --yes
granted  codex may write to space 'ks-shared'  (approval opapp-f624f97b36ee49bc)
$ zero-mem --profile codex add "Never force push to main." --type rule --scope shared --name no-force-push
created  mem://rule/no-force-push  (shared, 1 unit(s))
$ zero-mem --profile codex add "The derived SQLite database can report 'database is locked' under concurrent writers; retry with a short backoff." --type gotcha --scope shared --name db-locked
created  mem://gotcha/db-locked  (shared, 1 unit(s))
```

`cases.jsonl` (written with `zero-mem eval init cases.jsonl`, then edited):

```json
{"id": "force-push", "task": "clean up the history of main", "must_include": ["mem://rule/no-force-push"], "must_not_include": ["TODO-unapproved"]}
{"id": "db-locked", "task": "the database is locked when two agents write", "must_include": ["mem://gotcha/db-locked"], "max_chars": 1500}
{"id": "migrations", "task": "write a database migration", "must_include": ["mem://rule/migrations-reversible"]}
```

Injection is off, so the owner previews, then measures; the third case fails because nobody wrote the migration rule yet:

```text
$ zero-mem --profile codex brief --task "write a database migration" --preview
zero-mem: preview: this is what WOULD be injected; injection_disabled - injection is off (owner: zero-mem settings set injection.enabled true)
## Rules
- mem://rule/no-force-push: Never force push to main.
## Gotchas
- mem://gotcha/db-locked: The derived SQLite database can report 'database is locked' under concurrent writers; retry with a short backoff. (matched: database)
$ zero-mem --profile codex eval run cases.jsonl
eval cases.jsonl
PASS force-push  chars 62/2000  48.1 ms
PASS db-locked  chars 241/1500  1.6 ms
FAIL migrations  chars 233/2000  1.2 ms
     missing: mem://rule/migrations-reversible
summary: 2/3 passed; recall 0.6667 (2/3); forbidden hits 0; truncated 0; latency avg 16.94 ms max 48.06 ms
note: injection is OFF for 3 case(s): results show what WOULD be injected (preview). Turn it on with: zero-mem settings set injection.enabled true
[exit 1]
```

Adding the right rule moves the case from FAIL to PASS:

```text
$ zero-mem --profile codex add "Every database migration must be reversible and tested on a copy of the data." --type rule --scope shared --name migrations-reversible
created  mem://rule/migrations-reversible  (shared, 1 unit(s))
$ zero-mem --profile codex eval run cases.jsonl
eval cases.jsonl
PASS force-push  chars 176/2000  52.4 ms
PASS db-locked  chars 355/1500  1.7 ms
PASS migrations  chars 347/2000  1.2 ms
summary: 3/3 passed; recall 1.0 (3/3); forbidden hits 0; truncated 0; latency avg 18.45 ms max 52.41 ms
note: injection is OFF for 3 case(s): results show what WOULD be injected (preview). Turn it on with: zero-mem settings set injection.enabled true
[exit 0]
```

A live call (what a hook or an agent gets) is empty until the owner turns injection on; a proposal appears only after approval:

```text
$ zero-mem --profile codex brief --task "write a database migration"
zero-mem: no briefing: injection_disabled - injection is off (owner: zero-mem settings set injection.enabled true)
$ zero-mem settings set injection.enabled true
ok  injection.enabled set
$ zero-mem --profile codex brief --task "write a database migration" --max-chars 600
## Rules
- mem://rule/migrations-reversible: Every database migration must be reversible and tested on a copy of the data.
- mem://rule/no-force-push: Never force push to main.
## Gotchas
- mem://gotcha/db-locked: The derived SQLite database can report 'database is locked' under concurrent writers; retry with a short backoff. (matched: database)
$ zero-mem --profile codex propose "Prefer small pull requests." --type rule --name small-prs
proposed  p-f7f04d0b9d6d  rule (shared)  - pending owner review: zero-mem review list
$ zero-mem --profile codex brief --task "pull request size"        # pending: not in the briefing
## Rules
- mem://rule/migrations-reversible: Every database migration must be reversible and tested on a copy of the data.
- mem://rule/no-force-push: Never force push to main.
$ zero-mem review approve p-f7f04d0b9d6d --yes
approved  p-f7f04d0b9d6d  -> mem://rule/small-prs  (created)
$ zero-mem --profile codex brief --task "pull request size"
## Rules
- mem://rule/migrations-reversible: Every database migration must be reversible and tested on a copy of the data.
- mem://rule/no-force-push: Never force push to main.
- mem://rule/small-prs: Prefer small pull requests.
$ zero-mem eval history
when (UTC)            file                  cases pass fail recall  forbidden trunc  lat avg ms
2026-10-02T03:12:11Z  cases.jsonl               3    2    1 0.6667          0     0       16.94
2026-10-02T03:12:11Z  cases.jsonl               3    3    0 1.0000          0     0       18.45 up
$ zero-mem eval safety
PASS setup
PASS control_visible_items_present
PASS pending_never_in_brief_context_or_recall
PASS rejected_never_in_brief_context_or_recall
PASS expired_never_in_brief_context_or_recall
PASS forgotten_never_in_brief_context_or_recall
PASS superseded_version_never_in_brief_context_or_recall
PASS other_profile_private_never_appears
PASS own_private_still_visible_to_owner
PASS deterministic_repeat
PASS budget_never_exceeded
PASS injection_disabled_empties_non_preview_brief
PASS kill_switch_empties_brief
PASS settings_invalid_fails_safe
safety suite: all invariants hold
```

Wiring a session-start hook is the owner's choice and not done for you: a hook runs `zero-mem --profile P brief --task "..."` and injects its stdout; with injection off it prints nothing.

## 12. Limits of the briefing

* Lexical matching only (the existing retriever; no embeddings): a task that shares no word with a rule's, gotcha's or decision's text matches nothing. The eval harness is how the owner finds such gaps.
* Rules are not task-matched: a large rule set is cut at 60% of the budget when anything else could be shown (see `omitted`); keep rules few and short, or raise `injection.max_chars`.
* `memory_brief` over MCP has no `project_id`; project-scoped items and the devlog are reachable through the CLI only.
* `eval` replays preview content; it does not test an agent's behaviour, only what the memory would put in front of it.

