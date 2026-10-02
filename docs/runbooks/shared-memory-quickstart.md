# Shared memory quickstart

One local, zero-LLM memory shared by several agents (Claude Code, Codex, Hermes, OpenClaw): persona, workflow,
skills, dev history and your own files. Design: `docs/design/SHARED-MEMORY-RUNTIME.md`; approval model:
`docs/v1.6.1/decisions/ADR-V170-02-OPERATOR-APPROVED-WRITE-GRANTS.md`.

Concepts in four lines:

- **One profile per agent** (`claude-code`, `codex`, ...). `--profile NAME` (or `ZERO_MEM_PROFILE`; default `default`) picks who a command acts as.
- **Scopes:** `private` (default; only that profile), `shared` (the space `ks-shared`, readable by every registered agent) and `project` (devlog of one project).
- **A new agent can read `ks-shared` and write only privately.** Writing to `ks-shared` or a project needs an explicit operator approval (step 3).
- **Secrets are rejected, never stored.** `forget` hides a memory from every read; the raw bytes stay in the canonical corpus.

## 1. Install

```bash
python -m pip install .            # from the repository root; Python 3.11-3.13; optional: ".[pdf]" for PDF files
zero-mem version
```

Data lives under `~/.local/share/zero-mem` (override with an absolute `ZERO_MEM_DATA_ROOT`; the examples below work unchanged with it).

## 2. Set up

```bash
zero-mem setup        # prints READY; creates private dirs, the schema and the corpus root. Safe to repeat.
zero-mem doctor       # read-only health check
```

## 3. Register agents and approve their writes (operator)

```bash
zero-mem agents add claude-code codex           # READ ks-shared + private write only
zero-mem agents grant-write claude-code --space ks-shared --yes --basis "owner approved in chat"
zero-mem agents grant-write claude-code --project zero-mem --yes     # needed for devlog entries of that project
zero-mem agents list                            # who may read/write what
zero-mem agents revoke claude-code --space ks-shared --write        # revoke later (omit --write/--space to revoke everything)
```

`grant-write` is an operator decision: it records an audited approval and refuses to run without `--yes` or an interactive `y`.
Do not give agents a shell that can run it. `agents grant-read NAME --project P` lets an agent read another agent's project devlog.

## 4. Remember

```bash
zero-mem --profile claude-code add "Nyan prefers terse answers and no emojis." --type persona --name style --scope shared
zero-mem --profile claude-code add "Always run pytest before every commit." --type workflow --name commit --scope shared
zero-mem --profile claude-code add "Alice prefers PostgreSQL for storage."          # private fact
zero-mem --profile claude-code devlog "Fixed the flaky lock test" --project zero-mem
zero-mem --profile claude-code devlog --from-git --repo ~/code/zero-mem --project zero-mem   # no LLM: one entry per day from the git log, idempotent
```

`devlog --from-git` is meant for agent hooks (Stop / SessionEnd): see [agent-integration.md](agent-integration.md#7-capture-dev-history-without-an-llm-zero-mem-devlog---from-git).

Types: `persona`, `workflow`, `skill`, `devlog`, `fact` (default), `file`, and the learning-harness types `rule`, `decision`, `gotcha` (versioned by name like `workflow`). Adding again under the same `--name` creates a new version
(the old text is no longer returned); without `--name` the id is the text hash, so repeating a text is a no-op. `add -` reads stdin.

Agents that learn a rule or gotcha should *propose* it instead of writing it: `zero-mem --profile claude-code propose "..." --type rule`; the owner decides with
`zero-mem review list|approve|reject|revoke`, and `zero-mem settings` controls modes, limits, injection (off by default) and the kill switch. Nothing proposed is
recalled until approved: see [learning-harness.md](learning-harness.md).

## 5. Ingest a folder or file

```bash
zero-mem --profile claude-code ingest ./notes --type file --scope shared     # md, txt, csv, json/jsonl chats, docx, xlsx, pptx, pdf*, images
zero-mem --profile claude-code ingest ./notes --type file --scope shared     # again: "3 unchanged" - a changed file becomes a new version
```

Hidden files, `node_modules`, symlinks, empty and unsupported binaries are skipped and listed; a file containing a credential is
rejected and listed (exit code 1). Without OCR installed, images are searchable by metadata only (`pip install ".[ocr]"` adds text).

## 6. Search and context

```bash
zero-mem --profile codex search "release checklist" -k 3            # --type persona (repeatable), --json, --no-private, --project P
zero-mem --profile codex context                                    # persona, workflow, skill descriptions, recent devlog
zero-mem --profile codex context --max-chars 1500 --project zero-mem
```

`search` merges your private memory with `ks-shared`; `context` is deterministic and never exceeds `--max-chars` (default 4000).

## 7. Forget

```bash
zero-mem --profile claude-code forget mem://persona/style           # or the source id / a unique id prefix shown by search --json
```

Forgetting a shared memory needs the same write approval as writing one. A later `add` of the same text brings it back as a new version.

## 8. Backup, upgrade, restore

```bash
zero-mem backup create --output ./zm-backup && zero-mem backup verify ./zm-backup
zero-mem upgrade --check                      # then `zero-mem upgrade` after installing a new version (rebuilds derived state; keeps grants)
zero-mem backup restore ./zm-backup --yes --data-root /new/absolute/root
```

Agents, grants and approvals are canonical events inside the backup, so a restored store keeps its permissions.

## 9. Old notes and the MCP server

```bash
zero-mem import-notes        # migrates <data root>/data/notes/notes-v1.jsonl (the retired notes store) into facts; idempotent; the file is kept
zero-mem --profile codex serve    # execs the stdio MCP server pinned to profile "codex": memory_recall / memory_context only (the lowest token cost)
zero-mem mcp-config --agent codex # prints what to paste into the agent's MCP configuration
```

`serve` takes `--enable-write` (adds `memory_add`, `memory_ingest`, `memory_forget`), `--allow-root DIR` (folders `memory_ingest` may read) and `--tools all` (also lists the 11
legacy read-only M6 tools: `corpus_search`, `memory_query`, `project_*`, ...; about 17 KB more `tools/list` in every session). The server is pinned to
one profile, so an agent cannot read another agent's private memory or name another identity. Registering each agent, the tool list, the security model, what has
been verified with which client and troubleshooting are in [agent-integration.md](agent-integration.md).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok (including "no results") |
| 1 | partial: an ingest/import finished but some items were rejected or skipped for cause |
| 2 | invalid input/usage, or a setup/storage error |
| 3 | denied by authorization: the message names the `agents grant-write` command to ask the operator for |
| 4 | content rejected (credential detected, unsupported, empty) - nothing was stored |
| 5 | not found / nothing to revoke |

Every command also takes `--json` for machine-readable output. Troubleshooting: `zero-mem doctor` (its `memory_*` checks report writable roots, schema, grants, sources / units and the
last write), `zero-mem memory-status [--json]`; if either warns that sources are not projected, run `zero-mem upgrade`.
