# T6b closure evidence - MCP write tools, recall/context and per-agent configuration

Task T6b of `docs/plans/SHARED-MEMORY-RUNTIME-PLAN.md` (design `docs/design/SHARED-MEMORY-RUNTIME.md` sections 3 and 4B/4C; approval model ADR-V170-02).
Branch `worktree-agent-a74ffed57480f91e8`, fast-forwarded to `e66f0d8` (= "Merge T5 memory library, CLI, provisioning (DEF-057)"). Commit: the commit that adds this file
(`git log -1 -- docs/defects/closures/T6b.md`). `docs/defects/DEFECT-REGISTRY.md` was NOT edited (rule): the findings below are for the lead to register.
Interpreter `/tmp/venv/bin/python` 3.13.14, run from the worktree root, `pytest -q -p no:cacheprovider`. The sandbox refuses an inline `HOME=` assignment, so every run used the ambient `HOME`;
tests isolate their own `ZERO_MEM_DATA_ROOT` / `XDG_*` directories (and the manual client checks below used throw-away config homes).

Scope respected: new package `src/integration/m6w/`; `src/integration/m6/mcp_server.py` only as a mount hook (the 11 M6 tools, `tools.py`, `mcp_wrapper.py` and every T6a test are untouched); `zero_mem/cli.py`,
`zero_mem/commands_mcp.py` (new), `zero_mem/commands_memory.py` (the T5 `serve` placeholder removed), `zero_mem/memory_bootstrap.py` (new), docs, tests. `zero_mem/memory.py` is untouched.

## What was built

| Piece | Files |
|---|---|
| Tool set: closed schemas, validation, structured statuses, bounded results, path allowlist | `src/integration/m6w/{__init__,contracts,pathguard,toolset}.py` |
| Mount hook: `--enable-memory`, `--enable-write`, `--allow-root`, env `ZM_M6_ENABLE_MEMORY` / `ZM_M6_ENABLE_WRITE` / `ZM_M6_ALLOW_ROOTS`, `initialize.instructions` | `src/integration/m6/mcp_server.py` (`mount_tool_set`, `unmount_tool_sets`, `main`) |
| `zero-mem serve` really execs the pinned server; `zero-mem mcp-config` prints per-agent registrations | `zero_mem/commands_mcp.py`, `zero_mem/cli.py`, `zero_mem/commands_memory.py` |
| Race-safe first-run setup (found by the cold-start test, see "Defects found") | `zero_mem/memory_bootstrap.py` |
| Runbook; quickstart and README point to it | `docs/runbooks/agent-integration.md`, `docs/runbooks/shared-memory-quickstart.md`, `README.md` |
| Tests (226 new) | `tests/unit/{t6b_helpers,test_t6b_toolset,test_t6b_mount,test_t6b_cli,test_t6b_e2e_agents,test_t6b_pathguard,test_t6b_bootstrap}.py`; `test_t5_cli.py` lost the two tests that pinned the placeholder |

Tools (all delegate to `zero_mem.memory.Memory` as the PINNED profile, one fresh `Memory` per call so a grant the operator adds or revokes applies on the next call):
read `memory_recall(query, memory_types?, limit<=8, project_id?)`, `memory_context(max_chars 200..4000, project_id?)`; write (only with `--enable-write`) `memory_add(text, memory_type, scope, name?, project_id?)`,
`memory_ingest(path, memory_type, scope, project_id?)`, `memory_forget(source_id)`. Statuses `SUCCESS`, `EMPTY` (not an error), `PARTIAL`, `DENIED`, `REJECTED_SECRET`, `REJECTED_CONTENT`, `INVALID`, `NOT_FOUND`,
`ERROR`; `isError` is true for everything except `SUCCESS` and `EMPTY`. No result ever carries a path, SQL, exception text or the text of a rejected secret.

## RED evidence

Final test files copied into a clean `git archive` of the base (`e66f0d8`), nothing else changed, so each failure is a failure of the original code:

| Test file | base (unfixed) | fixed tree |
|---|---|---|
| `test_t6b_toolset.py` | collection error (`No module named 'src.integration.m6w'`) | 108 passed |
| `test_t6b_mount.py` | collection error (same) | 23 passed |
| `test_t6b_pathguard.py` | collection error (same) | 44 passed |
| `test_t6b_cli.py` | 19 failed, 6 passed, 6 errors | 31 passed |
| `test_t6b_e2e_agents.py` (real stdio servers launched from the printed registrations) | 13 failed | 13 passed |
| `test_t6b_bootstrap.py` | 7 failed | 7 passed |
| **total** | | **226 passed** (49 s) |

The tests were written first and seen failing at each step (collection errors, then `unrecognized arguments: mcp-config`, then the cold-start race below, then the `instructions` / env-cap / startup-warning
tests: `AssertionError ... 'instructions' not in ...`, `assert 2 == 2 and 'ZM_M6_INGEST_MAX_BYTES' in 'ERROR: max_ingest_bytes must be a positive integer'`, `assert ('WARNING' in 'zero-mem-mcp: memory tools mounted ...')`).

## Requirement by requirement

1. **Tools, closed schemas, token-bounded, identity always the pin.** `additionalProperties:false` everywhere; no identity or scope-authority property exists. `requesting_profile_id`, `profile_id`, `profile`, `agent`,
   `subject_profile`, `target_profile_ids`, ... are denied with `DENY_IDENTITY_PINNED` even when equal to the pin; `knowledge_space_ids`, `grants`, `verification_ref`, `operation`, ... with
   `DENY_SCOPE_NOT_CALLER_CONTROLLED`; any other unknown field is `INVALID` `UNKNOWN_ARGUMENT` (parametrized: 7 identity fields x 5 values x 3 tools, 10 authority fields; e2e: spoofing on all four new tools and on the M6
   `corpus_search` of the same server). A schema-driven validator is checked against the advertised schemas for every property bound (`test_the_validator_enforces_exactly_what_the_schema_advertises`).
   Bounds: recall `limit` <= 8 (default 5), a hit's text <= 600 chars, all hits <= 5000 chars; context <= `max_chars` <= 4000; ingest report <= 10 entries per list; tool descriptions 365-734 chars; the five tools'
   `tools/list` entries total 6.2 KB (the two read tools 2.3 KB); the 11 M6 tools are 17.5 KB (all measured as JSON characters).
2. **`serve` and `mcp-config`.** `zero-mem serve --profile P [--enable-write] [--allow-root DIR]...` execs `python -m src.integration.m6.mcp_server --store-path <db> --profile-id P --enable-memory [--enable-write]
   [--allow-root ...]` (T5's refusal is gone). `mcp-config --agent claude-code|codex|hermes|openclaw [--profile P] [--name N] [--enable-write] [--allow-root DIR]... [--json]` prints, without touching state, the absolute interpreter
   (`os.path.abspath(sys.executable)`: a venv's python is a symlink that must stay one), the `serve` arguments, and an environment pinning `ZERO_MEM_DATA_ROOT` (+ `ZERO_MEM_CORPUS_ROOT` / `XDG_*_HOME` when set), as: Claude Code
   `claude mcp add ... -s user -e K=V -- cmd args` + `.mcp.json`; Codex `[mcp_servers.zero-mem]` TOML block + `codex mcp add`; Hermes `hermes mcp add` + the `mcp_servers` YAML block + generic JSON; OpenClaw `openclaw mcp set` /
   `mcp add` + generic JSON. Quoting is tested with a path containing spaces, quotes, `$` and backslashes through shlex, tomllib, PyYAML and JSON. `docs/runbooks/agent-integration.md` has the verification matrix.
3. **End-to-end, four real stdio server processes, ONE data root** (`test_t6b_e2e_agents.py`; every server is launched from exactly what `mcp-config --json` printed for that agent): (a) claude-code adds a shared persona after the
   operator `grant-write`, codex / hermes / openclaw recall it through their own processes, an update under the same name replaces it; (b) claude-code's private notes are not visible to the other three, a spoofed `requesting_profile_id`
   is `DENIED` on every new tool and `POLICY_DENIED` on `corpus_search`; (c) shared write without a grant is `DENIED` / `DENY_CROSS_PROFILE_WRITE` for all four agents with the `grant-write` command in `operator_hint`, nothing stored, audit
   events on the stream, and grant / revoke take effect without restarting a server; (d) secret text (token form and `password=` form, in a shared and a private add, in an md file, inside a docx; in the unit tests also hidden in a name) is `REJECTED_SECRET`
   and `grep` over the data root's bytes (sqlite db + WAL, registry, blobs, canonical stream) finds neither the token nor `hunter2`; (e) a docx + xlsx + md folder ingests under the allowlist and is recalled by other agents,
   a second ingest is `unchanged`, paths outside the roots (`/etc/passwd`, `/`, `..` traversal), symlinked files / folders / path components are refused, symlinks inside a walked folder are skipped (a canary string never reaches the store),
   a server without `--allow-root` answers `DENY_NO_ALLOWED_ROOTS`; (f) forget by `source_id` removes a shared memory from all four agents' recall (a reader without the write approval is `DENIED`, forgetting twice is
   `already_forgotten`, the raw record and a `deleted` tombstone stay in the registry); (g) 4 servers writing concurrently (private + shared adds plus a read after each pair), all statuses `SUCCESS` / `created`, registry line count exactly
   `4 x N x 2` with unique `(ref, profile, space)`, sqlite `integrity_check` ok and sources = units = FTS rows, every shared item recallable by an agent that did not write it, no private item recallable by the neighbouring agent;
   (h) the context bundle contains persona / workflow / skill description / devlog, never exceeds `max_chars` (200, 300, 700, 1200, 2000, 4000 checked) and excludes another agent's private fact.

   Concurrency stability (default N = 20 per agent and scope, two rounds per run, and larger sizes): on the final code 10 consecutive runs at N = 20 (2 rounds x 240 calls each) and 6 at N = 60 (2 x 720 calls each); 8 more runs at
   N = 40 on an earlier commit: all passed, no flake, no `database is locked`, no traceback on any server's stderr.
4. **Fresh venv.** Network was available: `uv venv --python 3.13 /tmp/venv-t6b && uv pip install -p /tmp/venv-t6b -e .` (editable) and `uv pip install -p /tmp/venv-t6b-wheel .` (non-editable build; `src/integration/m6w/*`,
   `zero_mem/commands_mcp.py` and `memory_bootstrap.py` are in site-packages). From a foreign cwd with no `PYTHONPATH`: `zero-mem setup / agents add / agents grant-write / mcp-config`, the registration's command started a pinned server
   (16 tools with writes), `memory_add` shared, `memory_ingest`, `memory_recall` worked, and the `zero-mem-mcp --profile-id codex --enable-memory` console script served 13 tools, recalled the shared persona, built the context
   bundle and refused `memory_add` (not mounted).

## Real client CLIs (2026-10-01; npm / PyPI installs in /tmp, isolated config homes, none of it in the repo)

The printed snippets were executed verbatim (through shlex) by each client's own CLI. Re-run on the final code (`verify_all_clients.py`, scratch, not committed):

```text
--- claude mcp add (printed command, verbatim): exit 0
Added stdio MCP server zero-mem with command: /tmp/venv-t6b/bin/python -m zero_mem.cli serve --profile claude-code --enable-write --allow-root /tmp/.../docs to user config
--- claude mcp list (real health check): exit 0
zero-mem: /tmp/venv-t6b/bin/python -m zero_mem.cli serve --profile claude-code ... - √ Connected
--- codex mcp get (printed TOML block): exit 0       enabled: true / transport: stdio / command: /tmp/venv-t6b/bin/python / args: -m zero_mem.cli serve --profile codex ...
--- codex mcp add (printed command, verbatim): exit 0     Added global MCP server 'zero-mem'.      (the written entry equals the printed TOML block: True)
--- hermes mcp add (printed command, verbatim): exit 0     ✓ Connected! Found 16 tool(s) from 'zero-mem'      (then saved the entry to config.yaml)
--- hermes mcp test (also with the printed YAML block): exit 0     ✓ Connected (291ms)   ✓ Tools discovered: 16
--- openclaw mcp set / mcp add (printed commands, verbatim): exit 0     Saved MCP server "zero-mem"
--- openclaw mcp doctor: zero-mem: ok       openclaw mcp probe: zero-mem: 16 tools
```

Versions: Claude Code 2.1.286, Codex 0.159.3 (`@openai/codex`), hermes-agent 0.19.0 (`hermes-agent[mcp]`), OpenClaw 2026.6.35.

**Claude Code, model in the loop** (`claude -p ... --mcp-config <the printed .mcp.json> --strict-mcp-config --allowedTools mcp__zero-mem__memory_add,...`, stream-json; the user's own MCP configuration is neither read nor changed):

```text
MCP servers: [{'name': 'zero-mem', 'status': 'connected', 'source': 'dynamic'}]      (16 mcp__zero-mem__* tools listed)
TOOL_USE   mcp__zero-mem__memory_add {"text": "The user prefers terse answers and no emojis.", "memory_type": "persona", "scope": "shared", "name": "style"}
TOOL_RESULT is_error=None {"status":"SUCCESS","tool":"memory_add","result":"created","ref":"mem://persona/style","source_id":"270dd78084da113e","memory_type":"persona","scope":"shared","units":1}
TOOL_USE   mcp__zero-mem__memory_recall {"query": "how does the user like answers"}
TOOL_RESULT is_error=None {"status":"SUCCESS","tool":"memory_recall","count":1,"hits":[{"text":"The user prefers terse answers and no emojis.","ref":"mem://persona/style","type":"persona","scope":"shared","score":0.575,"source_id":"270dd78084da113e"}]}
TOOL_USE   mcp__zero-mem__memory_add {"text": "my api key is sk-ant-...", "memory_type": "fact", "scope": "private"}
TOOL_RESULT is_error=True memory_add: REJECTED_SECRET (secret_detected) - A credential-like value was detected. Nothing was stored. Remove the secret and retry.
TOOL_USE   mcp__zero-mem__memory_context {}
TOOL_RESULT is_error=None {"status":"SUCCESS","tool":"memory_context","text":"## Persona\nThe user prefers terse answers and no emojis.","chars":56,"max_chars":3000,"truncated":false,"sections":{"Persona":1}}
RESULT: "1) memory_add ... SUCCESS, created mem://persona/style. 2) memory_recall: SUCCESS, 1 hit ... 3) memory_add (fact, private): REJECTED_SECRET (secret_detected). Nothing was stored. 4) memory_context: SUCCESS ..."
```

What this showed about Claude Code: for a successful call the model receives the compact JSON of `structuredContent`; for an `isError` call it receives `content[0].text`. The tools therefore hold the whole answer in the JSON for successes and
a complete explanation (status, `reason_code`, what to do, the operator command) in the text for failures; empty lists and per-source lists are left out of the JSON because every key costs tokens.

**Codex handshake** (a tee shim between `codex exec` and the server; the model call itself failed, there is no model access / network in the sandbox):

```text
C->S {"method":"initialize","params":{"protocolVersion":"2025-06-18", ... "clientInfo":{"name":"codex-mcp-client","version":"0.159.3"}}}
S->C {"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"zero-mem-m6","identity":"pinned"},"instructions":"Shared long-term memory. At the start of a session ..."}}
C->S {"method":"notifications/initialized"}      C->S {"method":"tools/list"}      S->C {"result":{"tools":[ ... ]}}
```

NOT exercised: a Codex, Hermes or OpenClaw model choosing and calling the tools (needs a model provider for that client), Windows, macOS, Python 3.11 / 3.12.
OpenClaw blocks a `PYTHONPATH` entry for stdio servers (its probe failed until zero-mem was installed in the interpreter; documented), and Hermes needs its `mcp` extra.

## Defects found and what was done

1. **First-run setup race (fixed here, workaround outside T5's file).** `Layout.ensure()` on a never-initialised data root fails for most of N simultaneous processes: 10 of 10 rounds of 6 processes failed
   (`LayoutError: setup failed`; through a server: `zero-mem: unable to initialize derived store`, 7 of 8 rounds of 4 servers lost at least one). That is exactly what happens when a client launches one server per agent after a
   fresh install. RED (before the fix): `test_agent_servers_launched_at_the_same_moment_on_a_new_data_root_all_start` failed 2 of 3 rounds with `RuntimeError('MCP server closed stdout; stderr=zero-mem: unable to initialize derived store')`.
   Fix: `zero_mem/memory_bootstrap.ensure_layout` = `Layout.ensure()` under an exclusive cross-process lock (`<data root>/.layout.lock`) plus a short jittered retry; `serve` and the tool set use it. After: 8 of 8 cold-start rounds
   (4 servers each) and 8 consecutive runs of the 6-process test pass; `zero-mem doctor`, `backup create/verify`, `upgrade --check` are happy with the lock file. **Root cause is in `Layout.ensure` / schema creation (T5 / T2 territory):
   `zero-mem add|ingest|agents ...` racing on a fresh root still fail the same way.** Suggested: call the lock from `Layout.ensure` itself and keep `ensure_layout` as a thin alias.
2. **`Memory.forget` ambiguity leaks other profiles' private source ids (T5 library, not changed).** Two agents saving the same text privately share one `external_ref`; `forget(<ref>)` returns `status="ambiguous"` with `candidates` =
   every matching source id, including the other agent's private one. The MCP tool never forwards `candidates` (`AMBIGUOUS_REFERENCE`: "pass the source_id from memory_recall"; test
   `test_forget_cannot_reach_another_agents_private_memory_and_leaks_no_ids`), but the library result still exposes them. Fix there: filter `_resolve` candidates to sources the caller can see.
3. **Existence oracle in `Memory.forget` (T5, minor, not changed).** For a source in a project or space the caller cannot read, a guessed full id / ref answers `denied` (needs a write grant) instead of `not_found`.
4. **`Memory.context` drops the persona for tiny budgets (T5, worked around).** With `max_chars` below about 150 the 35 % persona share cannot hold one line and the section is skipped while later sections still print; the MCP schema
   therefore enforces `max_chars >= 200`.
5. Observation, not a defect: the 11 M6 event / project tools are 17.5 KB of `tools/list` that every agent session pays for; a `--tools memory` subset would cut it by ~70 %. The M6 list is pinned by T6a tests, so it was left alone.

## Existing tests changed

- `tests/unit/test_t5_cli.py`: `test_serve_refuses_an_unpinnable_server_and_execs_a_pinned_one` and `test_serve_support_detection_reads_the_server_source` removed. They pinned T5's placeholder (`serve` refusing to start while the MCP server
  had no `--profile-id`, and the `_mcp_supports_profile_pin` helper); the placeholder is the thing this task replaces. Their intent (exec argv, refusal of a bad profile) lives on in `test_t6b_cli.py`. No other existing test changed;
  `test_pkg1_packaging.py` / `test_pkg3_setup_doctor.py` (the `--help` word gates) pass untouched.

## Full suite

`/tmp/venv/bin/python -m pytest -q -p no:cacheprovider` on the final code (the `HOME=` prefix is refused by the sandbox; plain run):

```text
FAILED tests/unit/test_m9_6_hardening.py::test_readonly_vault_is_rejected_closed
FAILED tests/unit/test_m9_6_hardening.py::test_permission_denied_managed_root_fails_closed
2 failed, 5847 passed, 13 skipped in 267.89s (0:04:27)
```

The 2 failures are the known root-only tests (chmod does not restrict root). Baseline on the same base: 5623 passed (5847 - 226 new + 2 removed). `git diff --check` clean.

## Decisions for the reviewer

- `scope` is required for `memory_add` / `memory_ingest` (the specification lists it without `?`): an agent must choose private / shared / project; the answer echoes the stored scope. Making it default to `private` is a one-line schema change.
- Identity fields are rejected even when equal to the pin (M6 tools accept an equal value): "never accept profile/scope-authority fields from the caller".
- `memory_ingest` is mounted with `--enable-write` even without any `--allow-root` and answers `DENY_NO_ALLOWED_ROOTS` (a stable tool list; the operator sees why). The recall / context tools need `--enable-memory` (not the M6 default) because the T6a tests pin the plain
  server at exactly 11 tools; `serve` always passes it.
- Extra statuses beyond the four named (`EMPTY`, `PARTIAL`, `REJECTED_CONTENT`, `NOT_FOUND`, `ERROR`) so that "nothing found" is not an error and a partly rejected ingest is not reported as success; `PARTIAL` is `isError` true.
- `serverInfo` / `protocolVersion` unchanged (`2024-11-05`); `initialize` gains a short `instructions` text only when memory tools are mounted.
- `mcp-config` states per client what was verified (version and what ran) and what was not; the claim lives in `commands_mcp._VERIFICATION_NOTES` and must be updated if a client or version is re-verified.

## Hand-offs / not done

1. Fold the setup lock into `Layout.ensure()` (defect 1) and register the defects above (first-run race, forget ambiguity leak, forget existence oracle, context small-budget quirk).
2. Model-driven verification for Codex, Hermes and OpenClaw (needs a model provider or a mock Responses API); Windows / macOS (`os.execv` semantics, shell quoting in the printed commands); Python 3.11 / 3.12.
3. Optional leaner server (`--tools memory`) to drop the 11 M6 tools from `tools/list`.
4. One server process handles one call at a time: a long `memory_ingest` blocks that agent's other calls (the caps are 200 files / 64 MiB per call). Different agents have different processes and are not blocked.
5. Audit events: every denied write and every grant-using shared write appends ~400 bytes to the canonical stream (T5 hand-off 4 still applies; the MCP surface makes it easier to reach).
