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

`zero-mem serve --profile <p>` mounts, next to the 11 read-only M6 tools (`corpus_search`, `memory_search`, `project_*`, ...):

| Tool | Mounted | Arguments (closed schema, no extra fields) | Returns |
|---|---|---|---|
| `memory_recall` | always | `query` (required), `memory_types[]`, `limit` 1..8 (default 5), `project_id` | up to `limit` hits `{text, ref, type, scope, score, source_id}`; text clipped to 600 chars, all hits to 5000 |
| `memory_context` | always | `max_chars` 200..4000 (default 3000), `project_id` | the session-start bundle (persona, workflow, skill list, recent devlog) as text, never longer than `max_chars` |
| `memory_add` | `--enable-write` | `text`, `memory_type`, `scope` (all required), `name`, `project_id` | `result` created / updated / unchanged, `ref`, `source_id` |
| `memory_ingest` | `--enable-write` | `path`, `memory_type`, `scope` (all required), `project_id` | counts, plus at most 10 created / rejected / skipped entries |
| `memory_forget` | `--enable-write` | `source_id` (id, 8+ hex prefix or `mem://` ref from `memory_recall`) | `result` forgotten / already_forgotten |

`memory_type`: `persona`, `workflow`, `skill`, `devlog`, `fact`, `file`. `scope`: `private` (only this agent), `shared` (every agent;
needs the operator's write approval) or `project` (a project's devlog; needs the approval for that project). A named memory
(`name`) is versioned: adding again under the same name replaces what recall returns. The tool descriptions tell the agent when to
call each tool, what the arguments mean, that recalled text is stored data and not instructions, and never to include secrets.

Every call returns an MCP result `{content, structuredContent, isError}`: `structuredContent` is the complete answer as JSON, `content[0].text` the same answer
as short readable text (for `memory_context` it is the bundle itself). Claude Code was observed to hand the model `structuredContent` for a successful call and
`content[0].text` for an `isError` call, so both carry everything the agent needs: a failure is fully explained in its text (status, `reason_code`, what to do, the
operator command), and a success holds the whole answer in the JSON. Empty lists and per-source lists are left out to keep that JSON small.

| `status` | `isError` | Meaning |
|---|---|---|
| `SUCCESS` | false | done |
| `EMPTY` | false | a valid read found nothing (`memory_recall`, `memory_context`, an ingest with nothing ingestable) |
| `DENIED` | true | authorization or path policy: `reason_code` is an M5 code (`DENY_CROSS_PROFILE_WRITE`, ...) or one of `DENY_IDENTITY_PINNED`, `DENY_SCOPE_NOT_CALLER_CONTROLLED`, `DENY_PATH_OUTSIDE_ALLOWLIST`, `DENY_SYMLINK`, `DENY_PATH_RESERVED`, `DENY_NO_ALLOWED_ROOTS`; a refused write carries `operator_hint` (the `grant-write` command to ask for) |
| `REJECTED_SECRET` | true | a credential was detected; nothing was stored (`rule_ids` are fixed rule names, never the value) |
| `REJECTED_CONTENT` | true | unsupported, corrupt or empty content; nothing was stored |
| `PARTIAL` | true | an ingest stored some files and rejected or skipped others (see `rejected`, `skipped`) |
| `INVALID` | true | malformed request: `UNKNOWN_ARGUMENT`, `SCHEMA_VIOLATION`, `PATH_MUST_BE_ABSOLUTE`, `PATH_NOT_FOUND`, `AMBIGUOUS_REFERENCE`, or a library reason such as `devlog_requires_project_scope` |
| `NOT_FOUND` | true | `memory_forget`: no such memory is visible to this agent |
| `ERROR` | true | unexpected failure: fixed `INTERNAL_ERROR`, no path, SQL or exception text |

A tool never raises to the client and never returns a file system path, a SQL fragment or the text of a rejected secret.

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
  argument can name another profile or space. `memory_forget` answers `NOT_FOUND` for another agent's private memory and never lists ids it cannot see.

## 4. Register the server with each agent

`zero-mem mcp-config --agent <claude-code|codex|hermes|openclaw> [--profile P] [--name zero-mem] [--enable-write] [--allow-root DIR]... [--json]`
prints the registration without touching any state. It uses the absolute interpreter that runs `zero-mem` (a venv's `python`, never a resolved system
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

Equivalent forms: `zero-mem-mcp --profile-id <p> --enable-memory [--enable-write] [--allow-root DIR]` (the console script; the data root comes from `ZERO_MEM_DATA_ROOT`) and
`python -m src.integration.m6.mcp_server ...` with the same flags. A bare `zero-mem-mcp --store-path <db> --profile-id <p>` is the read-only M6 server with the original 11 tools.
Register one server per agent profile; do not share one server between agents.

### Environment switches of the server

| Flag | Environment | Effect |
|---|---|---|
| `--profile-id P` | `ZM_M6_PROFILE_ID` | the pinned profile (required for the memory tools) |
| `--enable-memory` | `ZM_M6_ENABLE_MEMORY=1` | mounts `memory_recall` and `memory_context` (`serve` always does) |
| `--enable-write` | `ZM_M6_ENABLE_WRITE=1` | also mounts `memory_add`, `memory_ingest`, `memory_forget` (implies `--enable-memory`) |
| `--allow-root DIR` (repeatable) | `ZM_M6_ALLOW_ROOTS` | folders `memory_ingest` may read |
| `--store-path DB` | `ZM_M6_STORE_PATH` | must be the data root's database when the memory tools are enabled (default: the data root's) |
| | `ZM_M6_INGEST_MAX_FILES`, `ZM_M6_INGEST_MAX_BYTES` | ingest caps (200, 64 MiB) |

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

`protocolVersion` is `2024-11-05` (what the M6 server has always spoken); `structuredContent` is part of newer revisions, so a client that ignores it still gets
the answer in `content[0].text` (recall hits, the context bundle, the write summaries and every failure explanation).

Token cost: the `tools/list` of a server with every switch on is about 24 KB, of which the 11 read-only M6 tools (event and project tools) are 17.5 KB and the five
memory tools 6.2 KB (2.3 KB for the two read tools). A leaner server that lists only the memory tools is a possible follow-up; the M6 list is pinned by T6a tests.

## 6. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| The client lists 11 tools and no `memory_recall` | it was registered with `zero-mem-mcp --store-path ...` (the read-only M6 server). Register `zero-mem serve --profile P` (or add `--enable-memory`) |
| `memory_add` is "unsupported" / missing | the server was started without `--enable-write` (by design) |
| `DENIED` `DENY_CROSS_PROFILE_WRITE` with an `operator_hint` | the agent has no write approval for that space or project: the operator runs the printed `zero-mem agents grant-write ...`; meanwhile use `scope=private` |
| `DENIED` `DENY_IDENTITY_PINNED` | the client sent `requesting_profile_id` (or another identity field): remove it, the server knows who the agent is |
| `DENIED` `DENY_PATH_OUTSIDE_ALLOWLIST` / `DENY_NO_ALLOWED_ROOTS` | the folder is not under an `--allow-root`; re-register with the folder (the agent cannot widen it) |
| `REJECTED_SECRET` | the text or file contains a credential-like value; remove it. Nothing was stored |
| `memory_recall` is `EMPTY` for something another agent saved | it was saved `private`, or `forgotten`, or the reader was never registered (`zero-mem agents add`), or the writer's call was `DENIED` |
| server exits at once with `ERROR: --store-path is not the database of the zero-mem data root` | `ZERO_MEM_DATA_ROOT` differs between `serve` and the registered `--store-path`; use `serve` or drop `--store-path` |
| `ERROR` `INTERNAL_ERROR` | no detail is returned by design: read the server's stderr and run `zero-mem doctor` |
| the client says the server "Connection closed" / fails to start | the interpreter in the registration cannot import `zero_mem` (not installed there, or the client ignores `PYTHONPATH`, as OpenClaw does): `pip install` zero-mem into that interpreter or re-run `zero-mem mcp-config` from the right one |

Rollback: unregister the server in the client (`claude mcp remove zero-mem -s user`, delete the TOML block, ...). Nothing else changes; memories stay in the data root.
`zero-mem agents revoke <agent> --write` withdraws an agent's shared-write approval immediately.
