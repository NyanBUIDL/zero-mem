# Agent integration: one shared memory over MCP

Claude Code, Codex, Hermes and OpenClaw each start their OWN stdio MCP server process (`zero-mem serve --profile <agent>`),
all on one data root. The server is pinned to that agent's profile, so what an agent can read or write is decided by the
operator's grants, never by what the agent claims. Everything delegates to `zero_mem.memory.Memory` (authorize -> secret
pre-scan -> cross-process lock -> register -> project), the same path as `zero-mem add`.

Design: `docs/design/SHARED-MEMORY-RUNTIME.md` (sections 3-4). Approval model: `docs/v1.6.1/decisions/ADR-V170-02-OPERATOR-APPROVED-WRITE-GRANTS.md`.
Library and CLI: `docs/runbooks/shared-memory-quickstart.md`.

## 1. Set up (operator, once)

```bash
python -m pip install .                  # or: uv pip install -e .   (Python 3.11-3.13); adds the zero-mem and zero-mem-mcp commands
zero-mem setup
zero-mem agents add claude-code codex hermes openclaw          # every agent: READ ks-shared, private write only
zero-mem agents grant-write claude-code --space ks-shared      # only for an agent that may write SHARED memory (asks you to confirm)
zero-mem mcp-config --agent claude-code --enable-write --allow-root ~/notes   # prints the registration (section 4)
```

Do not give an agent a shell that can run `zero-mem agents ...`: that command is the approval.

## 2. What the server exposes

`zero-mem serve --profile <p>` serves ONLY the memory tools (token cost is the product goal, see section 6). The 11 read-only M6 tools (`corpus_search`,
`memory_search`, `memory_query`, `project_*`, ...) are a further 16.6 KB of `tools/list` (17.5 KB with the server's own JSON spacing) and are listed only with `--tools all`:

| Tool | Mounted | Arguments (closed schema, no extra fields) | Returns |
|---|---|---|---|
| `memory_recall` | always | `query` (required), `memory_types[]`, `limit` 1..8 (default 5), `project_id` | up to `limit` hits `{id, type, ref, score, text}`: `text` is at most 280 characters (cut around the matched words, with an ellipsis), `id` is 10 hex characters (what `memory_forget` takes); `truncated: true` when any text was cut or hits were dropped; a `limit` 8 answer is under 3 KB |
| `memory_context` | always | `max_chars` 200..4000 (default 2000), `project_id` | the session-start bundle (persona, workflow, skill list, recent devlog) as `text`, never longer than `max_chars`; `truncated: true` when something was cut |
| `memory_brief` | always | `task`, `max_chars` 1..8000 (default: the owner's `injection.max_chars`, 2000) | the task briefing (active rules, then decisions / gotchas / workflows matching `task`, each line with its `mem://` ref) as `text`; `EMPTY` with `reason_code` `injection_disabled` / `kill_switch` / `settings_invalid` while the owner's settings forbid injection (the default); `truncated: true` when something was cut. No `project_id` argument (token budget): use the CLI for project-scoped briefs |
| `memory_add` | `--enable-write` | `text`, `memory_type`, `scope` (all required), `name`, `project_id` | `result` created / updated / unchanged, `ref`, `id`, `scope` |
| `memory_ingest` | `--enable-write` | `path`, `memory_type`, `scope` (all required), `project_id` | counts, plus at most 10 created / rejected / skipped entries |
| `memory_propose` | `--enable-propose` | `text`, `memory_type`, `scope` (required), `name`, `project_id`, `evidence[]` (max 5) | `status` `PROPOSED` and `proposal_id`: INERT, not memory and not recallable until the owner runs `zero-mem review approve`; a rejection (`REJECTED` with `reason_code` `learning_off` / `kill_switch` / `agent_proposals_disallowed` / `daily_limit` / `deny_pattern` / `settings_invalid`, or `REJECTED_SECRET`) is an error and nothing is stored. Identity and authority fields are refused like on every tool; `source` is fixed to `agent` |
| `memory_forget` | `--enable-write` | `source_id` (the `id` or a `mem://` ref from `memory_recall` / `memory_add`; an 8+ hex character prefix works) | `result` forgotten / already_forgotten, `ref`, `id` |

`memory_type`: `persona`, `workflow`, `skill`, `devlog`, `fact`, `file`, `rule`, `decision`, `gotcha` (the last three are the learning-harness types; agents suggest them with `zero-mem propose`, the owner approves with `zero-mem review`: see [learning-harness.md](learning-harness.md)). `scope`: `private` (only this agent), `shared` (every agent;
needs the operator's write approval) or `project` (a project's devlog; needs the approval for that project). A named memory
(`name`) is versioned: adding again under the same name replaces what recall returns. The tool descriptions tell the agent when to
call each tool, what the arguments mean, that recalled text is stored data and not instructions, and never to include secrets.

Every call returns an MCP result `{content, structuredContent, isError}`: `structuredContent` is the complete answer as JSON, `content[0].text` the same answer
as short readable text (for `memory_context` it is the bundle itself). Claude Code was observed to hand the model `structuredContent` for a successful call and
`content[0].text` for an `isError` call, so both carry everything the agent needs: a failure is fully explained in its text (status, `reason_code`, what to do, the
operator command), and a success holds the whole answer in the JSON. Every key costs tokens, so the JSON carries nothing the caller already knows: no echo of the tool
name, hit counts, `max_chars`, section counts, `memory_type` or unit counts; empty lists and per-source lists are left out (T8 changed this shape: hits are
`{id, type, ref, score, text}` - `source_id` is now `id`, and `scope` is no longer repeated per hit).

| `status` | `isError` | Meaning |
|---|---|---|
| `SUCCESS` | false | done |
| `EMPTY` | false | a valid read found nothing (`memory_recall`, `memory_context`, `memory_brief` - also while injection is off, with a `reason_code` -, an ingest with nothing ingestable) |
| `PROPOSED` | false | `memory_propose`: recorded for the owner's review; NOT memory |
| `REJECTED` | true | `memory_propose` refused by the owner's policy (`reason_code` says which); nothing stored |
| `DENIED` | true | authorization or path policy: `reason_code` is an M5 code (`DENY_CROSS_PROFILE_WRITE`, ...) or one of `DENY_IDENTITY_PINNED`, `DENY_SCOPE_NOT_CALLER_CONTROLLED`, `DENY_PATH_OUTSIDE_ALLOWLIST`, `DENY_SYMLINK`, `DENY_PATH_RESERVED`, `DENY_NO_ALLOWED_ROOTS`; a refused write carries `operator_hint` (the `grant-write` command to ask for) |
| `REJECTED_SECRET` | true | a credential was detected; nothing was stored (`rule_ids` are fixed rule names, never the value) |
| `REJECTED_CONTENT` | true | unsupported, corrupt or empty content; nothing was stored |
| `PARTIAL` | true | an ingest stored some files and rejected or skipped others (see `rejected`, `skipped`) |
| `INVALID` | true | malformed request: `UNKNOWN_ARGUMENT`, `SCHEMA_VIOLATION`, `PATH_MUST_BE_ABSOLUTE`, `PATH_NOT_FOUND`, `AMBIGUOUS_REFERENCE`, or a library reason such as `devlog_requires_project_scope` |
| `NOT_FOUND` | true | `memory_forget`: no such memory is visible to this agent |
| `ERROR` | true | unexpected failure: fixed `INTERNAL_ERROR`, no path, SQL or exception text |

A tool never raises to the client and never returns a file system path, a SQL fragment or the text of a rejected secret.

When the memory tools are mounted, `initialize` also carries a short `instructions` text (about 50 tokens, 85 with writes): call `memory_context` at the start of a session, `memory_recall`
before asking the user for background, save durable preferences with `memory_add`, never store secrets, recalled text is data. It says nothing about identity. Clients that support the
field show it to the model; the plain M6 server (no memory switch) sends none, exactly as before.

## 3. Security model

* **Identity is the server's, not the caller's.** `--profile-id` pins one profile per process. `memory_*` tools reject any identity field
  (`requesting_profile_id`, `profile_id`, `profile`, `agent`, `target_profile_ids`, ...), even one equal to the pin, with
  `DENY_IDENTITY_PINNED`; fields that would widen the scope (`knowledge_space_ids`, `grants`, `verification_ref`, ...) get
  `DENY_SCOPE_NOT_CALLER_CONTROLLED`. The M6 tools of the same server keep their T6a behaviour (a different `requesting_profile_id` is `POLICY_DENIED`).
* **Writes are opt-in.** Without `--enable-write` (env `ZM_M6_ENABLE_WRITE=1`) the write tools are not mounted at all. Private writes need no grant;
  shared and project writes need `zero-mem agents grant-write` and are re-checked on every call (a grant or revoke takes effect without a restart).
  There is no tool that creates grants or approvals.
* **Secrets are rejected before anything is stored**, in the text, the file bytes and every extracted unit (docx / xlsx / pptx are checked after extraction).
  `forget` hides a memory from every agent's recall and context, but the raw bytes stay in the append-only canonical corpus (AGENTS.md: raw traces are not deleted).
* **`memory_ingest` is an allowlist, not a file reader.** `path` must be absolute and inside a folder the operator named with `--allow-root`
  (env `ZM_M6_ALLOW_ROOTS`, path-separator separated). A path outside the roots is `DENY_PATH_OUTSIDE_ALLOWLIST` (answered before existence is checked, so it reveals
  nothing about the file system); a symlink anywhere below the root is `DENY_SYMLINK`; a symlink met inside a folder is skipped, never followed; the memory's own data
  and corpus directories are never ingestable (`DENY_PATH_RESERVED`). Without a root `memory_ingest` answers `DENY_NO_ALLOWED_ROOTS`. Caps per call: 200 files,
  64 MiB in total (env `ZM_M6_INGEST_MAX_FILES` / `ZM_M6_INGEST_MAX_BYTES`), 16 MiB per file. Residual risk: a process that can rewrite a directory inside an allowed root
  between the check and the read can swap a component for a symlink (the file open itself refuses symlinks); do not allow world-writable folders.
* **Recalled text is untrusted data.** It comes from other agents and from imported files; the descriptions say so, but a client should still treat it as input, not as instructions.
* Private memory of one agent is never returned to another: the library reads only the agent's own rows, `ks-shared` and projects it was granted READ on, and no tool
  argument can name another profile or space. `memory_forget` (and `Memory.forget`, T8) only ever considers sources the caller can READ: another agent's private memory, a
  project without a read grant and a shared space the caller cannot read all answer exactly like an id that does not exist (`NOT_FOUND`, no existence oracle), and an
  ambiguous `mem://` ref lists only candidates the caller can read (so two agents holding the same text privately each forget their own copy by the plain ref). A readable
  shared or project memory without the operator's write approval is `DENIED` with the `grant-write` hint. An agent with a write-only grant on a project cannot forget
  entries it cannot read: grant it the read too (`zero-mem agents grant-read <agent> --project <p>`).

## 4. Register the server with each agent

`zero-mem mcp-config --agent <claude-code|codex|hermes|openclaw> [--profile P] [--name zero-mem] [--enable-write] [--enable-propose] [--allow-root DIR]... [--tools memory|all] [--json]`
prints the registration without touching any state. The default tool set is `memory` (nothing extra is printed); `--tools all` adds `--tools all` to the printed `serve`
arguments so the client also lists the 11 legacy M6 read tools. It uses the absolute interpreter that runs `zero-mem` (a venv's `python`, never a resolved system
interpreter), the arguments of `zero-mem serve`, and an environment that pins `ZERO_MEM_DATA_ROOT` (plus `ZERO_MEM_CORPUS_ROOT` / `XDG_*_HOME` when you set them),
so the server finds the same data whatever environment the client launches it with. The profile defaults to the agent name.

```text
claude-code   claude mcp add zero-mem -s user -e ZERO_MEM_DATA_ROOT=/data/zm -- /venv/bin/python -m zero_mem.cli serve --profile claude-code
              (or the printed .mcp.json: {"mcpServers": {"zero-mem": {"type": "stdio", "command": ..., "args": [...], "env": {...}}}})
codex         [mcp_servers.zero-mem]                     # append to ~/.codex/config.toml
              command = "/venv/bin/python"
              args = ["-m", "zero_mem.cli", "serve", "--profile", "codex"]
              [mcp_servers.zero-mem.env]
              ZERO_MEM_DATA_ROOT = "/data/zm"
              (or: codex mcp add zero-mem --env ZERO_MEM_DATA_ROOT=/data/zm -- /venv/bin/python -m zero_mem.cli serve --profile codex)
hermes        hermes mcp add zero-mem --command /venv/bin/python --env ZERO_MEM_DATA_ROOT=/data/zm --args -m zero_mem.cli serve --profile hermes
              (or the printed mcp_servers block for $HERMES_HOME/config.yaml: command / args / env / enabled: true)
openclaw      openclaw mcp set zero-mem '{"command": "/venv/bin/python", "args": ["-m", "zero_mem.cli", "serve", "--profile", "openclaw"], "env": {...}}'
              (or: openclaw mcp add zero-mem --command /venv/bin/python --arg=-m --arg=zero_mem.cli ... --env ZERO_MEM_DATA_ROOT=/data/zm)
```

Notes from running the real clients: Hermes needs its MCP SDK (`pip install 'hermes-agent[mcp]'`) and `hermes mcp add` connects, lists the tools and asks which to enable; OpenClaw **ignores a
`PYTHONPATH` entry for stdio servers**, so zero-mem must be installed into the interpreter the registration names (do not rely on running from a checkout). The registration pins
`ZERO_MEM_DATA_ROOT` explicitly because a client may launch a server with a reduced environment.

Equivalent forms: `zero-mem-mcp --profile-id <p> --enable-memory [--enable-write] [--allow-root DIR] [--tools memory]` (the console script; the data root comes from `ZERO_MEM_DATA_ROOT`) and
`python -m src.integration.m6.mcp_server ...` with the same flags. A bare `zero-mem-mcp --store-path <db> --profile-id <p>` is the read-only M6 server with the original 11 tools,
and `zero-mem-mcp --enable-memory` without `--tools memory` still lists those 11 next to the memory tools (the T6a / T6b surface is pinned); only `zero-mem serve` and `mcp-config`
default to the memory-only set. Register one server per agent profile; do not share one server between agents.

### Environment switches of the server

| Flag | Environment | Effect |
|---|---|---|
| `--profile-id P` | `ZM_M6_PROFILE_ID` | the pinned profile (required for the memory tools) |
| `--enable-memory` | `ZM_M6_ENABLE_MEMORY=1` | mounts `memory_recall`, `memory_context` and `memory_brief` (`serve` always does) |
| `--enable-write` | `ZM_M6_ENABLE_WRITE=1` | also mounts `memory_add`, `memory_ingest`, `memory_forget` (implies `--enable-memory`) |
| `--enable-propose` | `ZM_M6_ENABLE_PROPOSE=1` | also mounts `memory_propose` (implies `--enable-memory`); `zero-mem serve` / `mcp-config` take the same flag. Needs no write grant: proposals are inert until the owner approves them ([learning-harness.md](learning-harness.md)) |
| `--tools all|memory` | `ZM_M6_TOOLS` | `memory`: list and serve ONLY the memory tools (needs `--enable-memory`); `all` (the module's default): the 11 M6 tools too. `zero-mem serve` passes `memory` unless given `--tools all` |
| `--allow-root DIR` (repeatable) | `ZM_M6_ALLOW_ROOTS` | folders `memory_ingest` may read |
| `--store-path DB` | `ZM_M6_STORE_PATH` | must be the data root's database when the memory tools are enabled (default: the data root's) |
| | `ZM_M6_INGEST_MAX_FILES`, `ZM_M6_INGEST_MAX_BYTES` | ingest caps (200, 64 MiB) |

Start order does not matter: a client may launch every agent's server - or an operator may run `zero-mem add` / `agents add` / `setup` - at the same moment on a data root nobody
initialised. First-run setup is serialized under `<data root>/.layout.lock` inside `Layout.ensure()` itself (`zero_mem/memory_layout.py`; `zero-mem setup` shares it), so the
library, the CLI and the MCP server are all safe (T8; T6b had fixed only the server, through `memory_bootstrap.ensure_layout`, now a thin alias). Without the lock most of the
simultaneous starts failed with "unable to initialize derived store". A transient failure is retried with a short jittered back-off; a configuration error or a lock held for more
than a minute is reported at once.

The server refuses to start (exit 2, one stderr line) for: memory tools without a pinned profile, a store path that is not the data root's database, an `--allow-root` that
is relative, missing, a file or `/`. `--allow-root` without the memory switches is ignored with a warning.

## 5. What has been verified, and what has not

Three levels of evidence, all dated 2026-10-01 (transcripts in `docs/defects/closures/T6b.md`):

* **A - real client CLI**: the printed snippet was executed verbatim by the client's own CLI (isolated config home), and the client connected to the server.
* **B - our own stdio test client** (`tests/unit/t6b_helpers.py`): a JSON-RPC subprocess driver; no real agent involved.
* **C - documented from the client's spec / help only**, never run.

| Item | Level | Evidence |
|---|---|---|
| The command / args / env printed for claude-code, codex, hermes and openclaw starts a pinned stdio server from a foreign working directory | **B** | `test_t6b_cli.py::test_the_printed_registration_really_starts_a_server_for_every_agent`; every server in `test_t6b_e2e_agents.py` is launched from the printed registration |
| The 5 tools, identity pin, grants, secrets, allowlist, forget, context bound, 4 servers (named after the 4 agents) writing concurrently on one data root | **B** only: the four "agents" are four stdio test-client sessions | `test_t6b_toolset.py`, `test_t6b_mount.py`, `test_t6b_pathguard.py`, `test_t6b_e2e_agents.py` |
| `zero-mem` and `zero-mem-mcp` from a fresh `uv venv` + `uv pip install -e .`, foreign cwd, no `PYTHONPATH` | **A/B** (editable install; no wheel build) | closure doc |
| **Claude Code 2.1.286**: `claude mcp add` accepts the printed command and writes an entry equal to the printed `.mcp.json`; `claude mcp list` reports `Connected`; a scripted `claude -p --mcp-config <printed .mcp.json> --strict-mcp-config` session in which the **model called** `memory_add` (shared, with a grant), `memory_recall`, `memory_add` with a secret (`REJECTED_SECRET`, `is_error`) and `memory_context` and reported the statuses correctly | **A**, including model-driven calls | closure doc (tool_use / tool_result transcript) |
| Claude Code hands the model `structuredContent` for a success and `content[0].text` for an error; tools appear as `mcp__<server name>__<tool>` | observed in that session, not a documented guarantee | same |
| **Codex 0.159.3**: `codex mcp get` parses the printed `config.toml` block; `codex mcp add` with the printed command writes the same entry; a `codex exec` startup spawned the server from that block and completed `initialize` (client `2025-06-18`, server `2024-11-05`), `notifications/initialized` and `tools/list` (recorded with a tee shim) | **A** for config and handshake; a model-driven call was **NOT exercised** (no model access) | closure doc |
| **hermes-agent 0.19.0**: `hermes mcp add` with the printed command connected, found the tools and saved the entry; the printed `config_yaml` block is accepted by `hermes mcp test`; `hermes mcp list` shows it enabled | **A**; a model-driven call was **NOT exercised** (no model access) | closure doc |
| **OpenClaw 2026.6.35**: `openclaw mcp set` and `openclaw mcp add` with the printed commands saved the entry; `openclaw mcp doctor` ok; `openclaw mcp probe` connected and listed the tools | **A**; a model-driven call was **NOT exercised** (no model access) | closure doc |
| A real Codex / Hermes / OpenClaw model choosing and calling the memory tools | not verified | needs a model provider for that client |
| Windows, macOS, a wheel build, Python 3.11 / 3.12 | not verified | |

T8 additions (2026-10-01, transcripts in `docs/defects/closures/T8.md`):

| Item | Level | Evidence |
|---|---|---|
| The memory-only default (`serve` with no `--tools`): `tools/list` is the memory tools only, a legacy tool is `UNSUPPORTED_TOOL`, `--tools all` lists 13 / 16, the printed `mcp-config` default adds nothing and `--tools all` adds `--tools all` | **B** | `tests/unit/test_t8_token_footprint.py` (real stdio servers) |
| **Claude Code 2.1.286, model in the loop**, registered with exactly what `zero-mem mcp-config --agent claude-code --enable-write` printed (default tool set): connected, listed the 5 memory tools and no legacy tool, and the model called `memory_context`, `memory_recall`, `memory_add` and a second `memory_recall`, reading the compact results (`{"status":"SUCCESS","hits":[{"id","type","ref","score","text"}]}`) correctly | **A**, including model-driven calls | closure doc (tool_use / tool_result transcript) |
| Hook snippets that run `zero-mem devlog --from-git`: Claude Code (real `claude -p`), Codex (`SessionStart` / `SessionEnd` hooks run, trust flag needed), Hermes (`hermes hooks test`), OpenClaw (`hooks list/info/enable/check` + handler run by node) | **A** for Claude Code; **A, partly** for the others (see section 7 for what each did and did not exercise) | closure doc |
| Simultaneous first start (6 processes, 5 rounds) through `Layout.ensure`, `Memory.open`, `zero-mem add` / `agents add` / `setup`, and the MCP tool set | **B** | `tests/unit/test_t8_first_run_race.py` |
| `forget` cannot leak other agents' ids or confirm that an unreadable source exists | **B** (library level, two profiles on one data root; also through the tool) | `tests/unit/test_t8_forget_hardening.py`, `test_t6b_toolset.py` |

`protocolVersion` is `2024-11-05` (what the M6 server has always spoken); `structuredContent` is part of newer revisions, so a client that ignores it still gets
the answer in `content[0].text` (recall hits, the context bundle, the write summaries and every failure explanation).

Token cost: see the next section (T8 made the memory-only tool set the default and compacted every description and result).

## 6. Token footprint (zero token cost is the product goal)

What a session pays for: `tools/list` and `initialize.instructions` once, then every tool result. T8 made the memory-only set the default of `serve` / `mcp-config`,
shortened every description (keeping the "when to call" guidance: recall BEFORE asking the user, context once at session start, DENIED means tell the user and do not retry,
never include secrets), and made results compact. Measured with real stdio servers (`zero-mem serve --profile claude-code ...`) on a seeded store (30 private facts, 18 shared
persona / workflow entries, 13 skills, 6 devlog days, 2 ingested documents); sizes are JSON characters of the compact `structuredContent`, tokens are about characters / 4
(a client hands the model one of `structuredContent` and `content[0].text` - Claude Code was observed to use `structuredContent` on success - and the wire carries both):

| | before (T6b, `a343f6b`) | after (T8) |
|---|---|---|
| `tools/list` of the default read-only server | 13 tools, 18,736 chars (~4,684 tokens) | 2 tools, 1,560 chars (~390 tokens) |
| `tools/list` with `--enable-write` | 16 tools, 22,565 chars (~5,641 tokens) | 5 tools, 4,472 chars (~1,118 tokens) |
| `tools/list` with `--enable-write --tools all` | 16 tools, 22,565 chars | 16 tools, 21,013 chars (legacy tools opt-in) |
| `initialize.instructions` (read / write) | 235 / 510 chars | 211 / 347 chars |
| `memory_recall`, default 5 hits | 3,652 chars (~913 tokens) | 1,876 chars (~469 tokens) |
| `memory_recall`, `limit` 8 | 4,811 chars (~1,203 tokens) | 2,608 chars (~652 tokens) |
| `memory_recall`, `limit` 8 over ingested documents | 4,370 chars | 2,242 chars |
| `memory_context`, default (full store) | 3,176 chars (~794 tokens) | 2,047 chars (~512 tokens) |
| `memory_add` / `memory_forget` / `memory_ingest` (2 files) | 167 / 144 / 174 chars | 103 / 87 / 151 chars |
| an error (`INVALID`) | 122 chars | 102 chars |

T15 added `memory_brief` to the default read set: the compact `tools/list` of the default read-only server grows from 1,587 to 2,037 characters (+450, 2 -> 3 tools; as the server sends it, 1,715 -> 2,189), with `--enable-write` from 4,553 to 5,003; `--enable-propose` adds another 1,428 characters (opt-in). `initialize.instructions` is unchanged (211 / 347 characters; 321 / 457 with `--enable-propose`). Details in `docs/defects/closures/T15.md`.

A session that lists the tools and calls `memory_context` once costs 22,147 -> 3,818 characters (~5.5K -> ~0.95K tokens, -83%) read-only, and 26,251 -> 6,866 characters
(~6.6K -> ~1.7K tokens, -74%) with writes. `tests/unit/test_t8_token_footprint.py` pins the budgets (`tools/list` of the six tools <= 5.05 KB and of the three read tools <= 2.03 KB (T15 raised both pins by 450 for `memory_brief`),
descriptions <= 420 characters, a `limit` 8 recall answer <= 3 KB in both representations, `memory_context` default 2000) so they cannot creep back.

What else keeps it small: hit text is cut at 280 characters around the words that matched (a hit never hides what it matched), hit ids are 10 characters, results omit everything
the caller already knows (section 2), `memory_context` is deterministic and bounded, and nothing in the memory path calls an LLM.

## 7. Capture dev history without an LLM: `zero-mem devlog --from-git`

```bash
zero-mem agents grant-write claude-code --project myproject --yes       # operator, once: the agent may write that project's devlog
zero-mem agents grant-read  codex       --project myproject             # operator: who else may read it (memory_context / memory_recall project_id)
zero-mem --profile claude-code devlog --from-git --repo ~/code/myproject --project myproject [--since v1.2 | --days 14]
```

It runs `git log` and writes ONE devlog source per day, `mem://devlog/<project>/<YYYY-MM-DD>`, whose text lists that day's commits, newest first - short hash, subject and the files
changed, never a diff:

```text
git commits:
- 3f9a2c1 feat: add widgets [src/widgets.py, tests/test_widgets.py +2]
- 7be10d4 fix: typo in the readme [README.md]
```

* **Idempotent.** The text is a pure function of the commits: a second run reports `unchanged` (no new version, no new blob); a new commit on a day that was already written makes a new
  version of that day's source (`updated`) and nothing else changes. Hooks may therefore run it after every turn or session.
* **Days are always whole.** `--since REF` (a commit, tag or branch) selects the days that have commits newer than REF; `--days N` (default 7, today included) selects the last N days.
  Each selected day is written with ALL of its commits, so a run can never replace a day with a partial one.
* **Bounded.** At most 40 commits a day (`... and N more commit(s)`), 3 files a commit (`+N`), 120 characters a subject. `--project` defaults to the repository directory name.
* **Safe.** Git runs with a fixed argument list (no shell, no pager, no prompt, `GIT_*` variables of a calling hook are dropped); a `--since` that starts with `-` is refused. Commit text is
  untrusted data: control characters are dropped and everything goes through the normal write path (the project write grant; the secret pre-scan - a day whose commit subject or
  file name carries a credential is REJECTED, never stored, and the other days still are).
* Exit codes: 0 ok (also "no commits"), 2 bad input (`--repo` is not a git repository, unknown `--since`, `git` missing), 3 denied (no write grant: the message names the
  `agents grant-write` command; one audit event, then it stops), 4 a day was rejected for a credential.
* The hook must use the SAME data root as the MCP server: if the registration pins `ZERO_MEM_DATA_ROOT` (see `zero-mem mcp-config --agent X --json`, key `env`), export the same
  value in the hook command.

Hook snippets (replace `myproject`; `zero-mem` must be on the hook's `PATH`). What was actually run (2026-10-01, this sandbox has no model access except for Claude Code):

**Claude Code** - `~/.claude/settings.json` (or `.claude/settings.json` of the project). `Stop` runs after every assistant turn, `SessionEnd` when the session ends; use either or both
(the second run is `unchanged`):

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "timeout": 30,
          "command": "zero-mem --profile claude-code devlog --from-git --repo \"$CLAUDE_PROJECT_DIR\" --project myproject >/dev/null 2>&1 || true" } ] }
    ],
    "SessionEnd": [
      { "hooks": [ { "type": "command", "timeout": 30,
          "command": "zero-mem --profile claude-code devlog --from-git --repo \"$CLAUDE_PROJECT_DIR\" --project myproject >/dev/null 2>&1 || true" } ] }
    ]
  }
}
```

VERIFIED with Claude Code 2.1.286: a real `claude -p "Reply with the single word: ok" --setting-sources project --settings <file with these hooks>` run in a git repository (3 commits on 2 days)
fired the `Stop` hook (stdin payload `hook_event_name: "Stop"`, `cwd` = the project; the command created both days) and then the `SessionEnd` hook (both days `unchanged`);
`$CLAUDE_PROJECT_DIR` was the project directory. Not exercised: an interactive session, a hook that fails or times out.

**Codex** - `~/.codex/config.toml` (or the project's `.codex/config.toml`); the command runs in the session's working directory through a shell:

```toml
[[hooks.SessionEnd]]
[[hooks.SessionEnd.hooks]]
type = "command"
command = "zero-mem --profile codex devlog --from-git --project myproject"
timeout = 3
```

PARTLY VERIFIED with Codex 0.159.3: hooks declared like this were loaded and the `SessionStart` and `SessionEnd` command hooks ran (cwd = the session directory; shell syntax such as
`>>` and `$PWD` works) when started with `--dangerously-bypass-hook-trust`. WITHOUT that flag a freshly added hook did NOT run: Codex requires a one-time review/trust of every new hook
(`/hooks` in the TUI), so approve it there. Codex clamps a `SessionEnd` hook to 3 seconds (`warning: clamping SessionEnd hook timeout to 3s`): `zero-mem devlog --from-git` takes
about 0.3 s, but keep the repository small or use `Stop`. NOT verified: the `Stop` event (it needs a completed model turn, which this sandbox cannot run), the TUI trust flow, and
`SessionEnd` after a normal (non-interrupted) exit.

**Hermes** - `~/.hermes/config.yaml`. Hermes runs the command WITHOUT a shell (`shlex.split`, no `$VAR`, pipes or redirections) in its own working directory and does not pass the
project, so give `--repo` explicitly (or start Hermes in the repository and drop it):

```yaml
hooks:
  on_session_end:            # after every turn that produced a final answer; on_session_finalize fires when the session really ends
    - command: "zero-mem --profile hermes devlog --from-git --repo /home/me/code/myproject --project myproject"
      timeout: 30
```

PARTLY VERIFIED with hermes-agent 0.19.0: `hermes hooks list` shows the entry, `hermes --accept-hooks hooks test on_session_end` fired it with a synthetic payload (exit 0, 2 days created),
`hermes --accept-hooks hooks test on_session_finalize` fired it again (`unchanged`). A hook needs the first-use consent allowlist: confirm at the TTY prompt, or run
`hermes --accept-hooks` / set `HERMES_ACCEPT_HOOKS=1` / `hooks_auto_accept: true`; `hermes hooks doctor` reports `not allowlisted` until then. NOT verified: a real Hermes session firing
`on_session_end` / `on_session_finalize` (needs a model provider).

**OpenClaw** - OpenClaw has internal hooks (a directory with `HOOK.md` + `handler.ts`) but no "session ended" event; `command:new` / `command:reset` (the user starts a fresh
session) and `command:stop` are the closest. Put this in `~/.openclaw/hooks/zero-mem-devlog/` (managed hooks; `$OPENCLAW_STATE_DIR/hooks/` when that is set) and run
`openclaw hooks enable zero-mem-devlog`:

```markdown
---
name: zero-mem-devlog
description: "Record the git history of the project in zero-mem (no LLM) when a session ends"
metadata:
  { "openclaw": { "emoji": "📓", "events": ["command:new", "command:reset", "command:stop"], "requires": { "bins": ["zero-mem"] } } }
---
# zero-mem devlog
On `/new`, `/reset` and `/stop`, runs `zero-mem devlog --from-git` for the checkout named by `ZERO_MEM_DEVLOG_REPO`.
```

```typescript
import { execFile } from "node:child_process";

// Fire and forget: /new, /reset and /stop must not wait for it. zero-mem is idempotent, so running it often is fine.
const handler = async (event) => {
  if (event.type !== "command" || !["new", "reset", "stop"].includes(event.action)) {
    return;
  }
  const repo = process.env.ZERO_MEM_DEVLOG_REPO;
  if (!repo) {
    return;
  }
  const project = process.env.ZERO_MEM_DEVLOG_PROJECT || "myproject";
  execFile(
    "zero-mem",
    ["--profile", "openclaw", "devlog", "--from-git", "--repo", repo, "--project", project],
    { timeout: 30000 },
    () => {},
  );
};

export default handler;
```

PARTLY VERIFIED with OpenClaw 2026.6.35: `openclaw hooks list` / `info` found the hook as `ready` (source `openclaw-managed`, requirement `zero-mem` on `PATH` met), `openclaw hooks enable`
and `check` accepted it, and the handler, run by `node` with a synthetic `command:new` event, spawned `zero-mem` and wrote the devlog. NOT verified: a running Gateway delivering a real
`/new` (needs a gateway and a model provider).

## 8. Health: `zero-mem doctor` and `zero-mem memory-status`

`zero-mem doctor` has four read-only memory checks (PASS or WARN, never FAIL; no paths, no content): `memory_data_root` (data and corpus roots writable), `memory_schema`
(derived schema version current), `memory_grants` (active grants, read / write split, agents), `memory_sources` (sources and how many are forgotten, units, sources not yet
projected - `run zero-mem upgrade` - and the time of the last write). `zero-mem memory-status [--json]` prints this profile's view (counts, its grants, drift) and, in `--json`, a
`runtime` block with the same facts. A backup / restore round trip of a populated store (recall and context identical for every agent, forget and grants survive) is pinned by
`tests/unit/test_t8_backup_roundtrip.py`.

## 9. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The client lists only `memory_recall` / `memory_context` (and the write tools) and no `corpus_search` / `project_*` | by design since T8: register with `--tools all` (`zero-mem mcp-config --tools all`) if you need the 11 legacy read tools |
| The client lists 11 tools and no `memory_recall` | it was registered with `zero-mem-mcp --store-path ...` (the read-only M6 server). Register `zero-mem serve --profile P` (or add `--enable-memory`) |
| `memory_add` is "unsupported" / missing | the server was started without `--enable-write` (by design) |
| `memory_propose` is "unsupported" / missing | the server was started without `--enable-propose` (by design); register `zero-mem mcp-config --enable-propose` |
| `memory_brief` returns `EMPTY` with `injection_disabled` | by design: injection is off until the owner runs `zero-mem settings set injection.enabled true` (per profile: `injection.profiles.<p>.enabled`); preview what it would say with `zero-mem brief --preview` |
| `DENIED` `DENY_CROSS_PROFILE_WRITE` with an `operator_hint` | the agent has no write approval for that space or project: the operator runs the printed `zero-mem agents grant-write ...`; meanwhile use `scope=private` |
| `DENIED` `DENY_IDENTITY_PINNED` | the client sent `requesting_profile_id` (or another identity field): remove it, the server knows who the agent is |
| `DENIED` `DENY_PATH_OUTSIDE_ALLOWLIST` / `DENY_NO_ALLOWED_ROOTS` | the folder is not under an `--allow-root`; re-register with the folder (the agent cannot widen it) |
| `REJECTED_SECRET` | the text or file contains a credential-like value; remove it. Nothing was stored |
| `memory_recall` is `EMPTY` for something another agent saved | it was saved `private`, or `forgotten`, or the reader was never registered (`zero-mem agents add`), or the writer's call was `DENIED` |
| the server's stderr says `profile 'X' cannot read the shared space` | the profile was never registered (or `--profile-id` has a typo): run `zero-mem agents add X`; until then the agent only sees its own private memory |
| server exits at once with `ERROR: --store-path is not the database of the zero-mem data root` | `ZERO_MEM_DATA_ROOT` differs between `serve` and the registered `--store-path`; use `serve` or drop `--store-path` |
| `ERROR` `INTERNAL_ERROR` | no detail is returned by design: read the server's stderr and run `zero-mem doctor` |
| the client says the server "Connection closed" / fails to start | the interpreter in the registration cannot import `zero_mem` (not installed there, or the client ignores `PYTHONPATH`, as OpenClaw does): `pip install` zero-mem into that interpreter or re-run `zero-mem mcp-config` from the right one |

Rollback: unregister the server in the client (`claude mcp remove zero-mem -s user`, delete the TOML block, ...). Nothing else changes; memories stay in the data root.
`zero-mem agents revoke <agent> --write` withdraws an agent's shared-write approval immediately.

## Windows note: stop agent servers before upgrade or restore

A running `zero-mem serve` process keeps a read connection to the derived SQLite database open (T7). Windows does not let
SQLite files be replaced or deleted while a connection holds them, so `zero-mem upgrade`, `backup restore` and a manual
rebuild can fail with `PermissionError` while agent MCP servers are running. Stop the agents' servers first, run the
command, then restart them. Linux and macOS are not affected. (Recorded in the defect registry addendum; two connection tests
are skipped on Windows for this reason.)
