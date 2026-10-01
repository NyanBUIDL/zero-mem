# T6a closure evidence - MCP read side (DEF-052, 061 agent default, 062, 063, 064, 066 server start)

Branch: `worktree-agent-a7a2192f7837d258d` (worktree of `feat/shared-memory-runtime`, fast-forwarded to `67c6f19`
= T4 merge `3a444d2` + the T2/T3 fixture alignment). Commit: the commit that adds this file
(`git log -1 -- docs/defects/closures/T6a.md`).
Registry: `docs/defects/DEFECT-REGISTRY.md` was NOT edited (rule); the maintainer/lead closes the entries from this evidence.
Process per defect: RED-first test -> smallest fix -> focused test -> full suite. Python 3.13.14 (`/tmp/venv/bin/python`).
Scope respected: `src/integration/m6/*`, `src/access/{grants,authorized_read}.py`, `pyproject.toml`, `examples/`, tests. `zero_mem/memory.py`,
`zero_mem/cli.py`, `benchmarks/` untouched. M6 read-only invariants intact (`Operation` has only READ, `FORBIDDEN_TOOL_NAMES`, exact tool list of 11).

## How the RED evidence was produced

Each test file was run against the unfixed code before its fix was written (seen RED per defect). The numbers below are the **final** test
files run against a clean `git archive` of the base commit (`67c6f19`) with only the new/changed tests copied in, so each failure is a failure
of the original code. Tests that pass on base are guards (the section-3 matrix, authorization still fails closed, `limit` cap, ...).

| Test file | base (unfixed) | fixed tree |
|---|---|---|
| `test_def052_identity_pin.py` (real stdio subprocess) | 19 failed, 4 passed | 23 passed |
| `test_def061_agent_default_limit.py` | 2 failed, 4 passed | 6 passed |
| `test_def062_mcp_transport.py` | 13 failed, 14 passed | 27 passed |
| `test_def063_requested_ks.py` | 12 failed, 11 passed | 23 passed |
| `test_def064_console_script.py` | 4 failed, 1 passed | 5 passed |
| `test_def066_server_start.py` (real stdio subprocess) | 4 failed | 4 passed |
| `test_t6a_corpus_search_filters.py` | 10 failed, 3 passed | 13 passed |
| `test_pkg1_packaging.py` (1 test updated) | 1 failed, 7 passed | 8 passed |
| `test_v141_def012_wiring.py` (2 tests updated) | 2 failed, 8 passed | 10 passed |
| **total** | **67 failed, 52 passed** | **119 passed** |

Shared helper (not collected): `tests/unit/t6a_mcp_helpers.py` builds a real derived store (production corpus projection + persistent READ grants) with the
design-doc section-3 matrix (units A..I) and a `StdioServer` that drives the server as a real subprocess over pipes.

## DEF-052 - server-side pinned identity

Root cause: `requesting_profile_id` came from `tools/call` arguments, so any client could pass another agent's id and read its private rows.
Base behaviour, demonstrated by `test_unpinned_keeps_todays_behaviour` (passes on base AND on the fixed unpinned server): caller-asserted `codex` returns
`['B', 'D', 'E', 'G']` (D = codex private row).

Fix (`src/integration/m6/mcp_server.py`, `mcp_wrapper.py`):
- `--profile-id` / env `ZM_M6_PROFILE_ID` (flag wins; empty env = unset; blank/overlong/control-char value -> exit 2). Optional `--default-ks` / `ZM_M6_DEFAULT_KS`.
- Pinned: the value overwrites `arguments.requesting_profile_id`; a different caller value (including `""`, `"*"`, trailing-space variants) is rejected with a structured
  tool error (`isError` true, status `POLICY_DENIED`, `reason_code` `DENY_IDENTITY_PINNED`, no results); `null`/equal values are accepted; applies to all 11 tools.
- `tools/list` omits `requesting_profile_id` from every schema (`tool_schemas(include_identity=False)`).
- `--default-ks` is applied to `corpus_search` only, only when the caller OMITS `knowledge_space_ids`; an explicit list (even `[]`) wins. Not applied to event/project tools
  (their per-row space authorization would be emptied by it).
- Not pinned: today's behaviour, one stderr line (`zero-mem-mcp: WARNING identity unpinned - ... pin it with --profile-id or ZM_M6_PROFILE_ID`) and
  `serverInfo.identity = "unpinned"` (`"pinned"` otherwise).

RED excerpt (base; the `--profile-id` flag does not exist, so a pinned server cannot even start):

```text
_ TestPinnedByFlag.test_cannot_read_another_profiles_private_rows_by_any_route _
tests/unit/test_def052_identity_pin.py:94: in test_cannot_read_another_profiles_private_rows_by_any_route
    resp = srv.call(tool, dict(args))
tests/unit/t6a_mcp_helpers.py:165: in rpc
    raise RuntimeError("server closed stdout; stderr=" + self.stderr_text())
E   RuntimeError: server closed stdout; stderr=usage: mcp_server.py [-h] [--store-path STORE_PATH] [--transport TRANSPORT]
E   mcp_server.py: error: unrecognized arguments: --profile-id claude-code
```

Fixed: the same test (and `test_other_caller_value_is_rejected_with_a_structured_error[codex|hermes||claude-code |*]`) passes; D and G never reach a `claude-code`-pinned server
by impersonation (`requesting_profile_id=codex`), by `target_profile_ids=["codex"]` (`POLICY_DENIED`), or via the shared space.

## DEF-062 - MCP transport

1. `isError`: the old tuple tested `"DENIED"`. Real envelope statuses (enum `ResponseStatus`): `SUCCESS, EMPTY, POLICY_DENIED, INVALID_REQUEST, UNSUPPORTED_OPERATION,
   UNSUPPORTED_TOOL, CAPABILITY_UNAVAILABLE, DOWNSTREAM_ERROR`. Now `isError = status not in {SUCCESS, EMPTY}` (fail closed for any future status); parametrized over the enum.
2. `arguments.tool` can no longer override the called tool: `handle_call` sets `payload["tool"] = tool_name` (a mismatching value is ignored; `{"tool":"execute_sql"}` on `corpus_search` still runs `corpus_search`).
3. `inputSchema`: `tool` stays declared (`const` = name; existing tests pin that) but is not required; `search_text` is required for `corpus_search`/`memory_search`; per-tool agent-oriented
   descriptions (when to call, which args, what comes back, read-only note; 80-900 chars each, unique; whole `tools/list` ~18.7 KB vs ~10.3 KB before (11 tools; pinned < 20 KB)); relevant arguments carry short docs
   (`limit` 1..500, `relation` enum, `filters` properties for `corpus_search`).
4. One copy of the envelope: `structuredContent` = complete envelope; `content[0].text` = short summary (`corpus_search: SUCCESS (reason) - N result(s)`, up to 5 one-line previews with
   `external_ref` / `memory_type` / text, `next_cursor` hint, <= 2000 chars). A text-only client therefore still sees the key facts.
5. Direct start from any cwd: the `sys.path` bootstrap now runs before the first project import (`zero_mem` was imported first); the script directory is removed from `sys.path`;
   `python -m src.integration.m6.mcp_server` unchanged. The stdlib POC (`examples/mcp_client_poc.py`) never read `content[0].text` (it prints the result / `structuredContent`); it gained
   `--profile-id` and a docstring on the result shape, and is exercised from a foreign cwd by `test_the_poc_client_still_parses_the_result`.

RED excerpts (base):

```text
_____________ test_policy_denied_is_an_error_through_the_real_path _____________
tests/unit/test_def062_mcp_transport.py:57: in test_policy_denied_is_an_error_through_the_real_path
    assert resp["result"]["isError"] is True
E   assert False is True
_________________ test_arguments_tool_cannot_redirect_the_call _________________
tests/unit/test_def062_mcp_transport.py:103: in test_arguments_tool_cannot_redirect_the_call
    assert env["diagnostics"]["tool"] == "corpus_search"
E   AssertionError: assert 'memory_search' == 'corpus_search'
__________ TestStartModes.test_direct_script_start_from_a_foreign_cwd __________
E   RuntimeError: server closed stdout; stderr=Traceback (most recent call last):
E     File "/tmp/t6a-base/src/integration/m6/mcp_server.py", line 32, in <module>
E       from zero_mem.version import __version__ as _zm_version
E   ModuleNotFoundError: No module named 'zero_mem'
_____ TestSchemas.test_tool_is_not_required_but_still_documented_as_const ______
E   AssertionError: corpus_search
E   assert 'tool' not in ['tool']
_ TestEnvelopeSentOnce.test_text_is_a_short_summary_and_structured_content_is_the_envelope _
E   assert '{"status": ...us_search"}}' not in '{"status": ...us_search"}}'
E     '{"status": "SUCCES...: "corpus_search"}}' is contained here:
E       {"status": "SUCCESS", "results": [{"unit_id": "u_b105dcedaa9b385c93e14d35839544f8", "source_id": "0793c0be5454051fd5ac8a7d920f4f502e5728030521eb1e2e388a60f8398701", ...
```

## DEF-063 - requested knowledge space narrows the grants

Root cause (reproduced, design doc section 3 quirk): the MCP handlers resolve ALL of the caller's READ grants (`handlers._resolve_grants`, `target_type=None`) and pass them as explicit
`grants`; `compose_effective_scope` (`grants.py`) then added one grant scope per granted space regardless of which spaces the request named
(`policy.py` echoes every requested space as allowed, so a requested space was never denied or checked against the grants). Unknown/ungranted/unrequested spaces therefore
returned every granted space. (The facade's own single-target resolution already narrowed; the explicit-grants path did not.)

Fix (`src/access/grants.py`, 9 lines): knowledge-space grants whose target is not one of the request's `knowledge_space_ids` are dropped before composition; if none remain the
base policy decision and its reason code are preserved. Plus `contracts._validated_space_ids`: each requested space id must be non-blank, <= 256 chars, no control characters
(`INVALID_REQUEST` otherwise). `policy.py` needed no change (base scope is requester-scoped by DEF-028; own rows in a requested space still surface, pinned by `test_v151_audit_a1_base_ks_scope`).

Matrix through the real MCP path (claude-code has a READ grant on `ks-shared`; A=cc/ks-shared, B=codex/ks-shared, C=cc private, D=codex private, E=all-NULL, F=profile-NULL/ks-shared, G=codex/ks-other, H=cc/ks-other):

| Request | Result (fixed) | Base |
|---|---|---|
| cc implicit | A C E H | same |
| cc `KS=[ks-shared]` | A B E F | same |
| hermes (no grant) `KS=[ks-shared]` | E | same |
| cc `target_profile_ids=[codex]` / isolated / unbound+KS | `POLICY_DENIED` | same |
| cc `KS=[ks-does-not-exist]` | **E** | A B E F (every granted space) |
| cc `KS=[ks-hermes-only]` (no grant) | E | A B E F |
| cc (grants ks-shared + ks-other) `KS=[ks-shared]` | **A B E F** | A B E F G H |
| cc (same grants) `KS=[ks-other]` / both | E G H / A B E F G H | all of them |

RED excerpts (base):

```text
_ TestRequestedSpaceNarrowsGrants.test_unknown_space_does_not_return_other_granted_spaces _
E   AssertionError: unknown space returned granted ks-shared rows: ['A', 'B', 'E', 'F']
_ TestRequestedSpaceNarrowsGrants.test_unrequested_granted_space_does_not_ride_along _
E   AssertionError: ['A', 'B', 'E', 'F', 'G', 'H']
E   assert ['A', 'B', 'E', 'F', 'G', 'H'] == ['A', 'B', 'E', 'F']
```

Observed, NOT changed (separate semantic decision, hand-off): the same "unrequested dimension rides along" exists for profile and project grants
(`compose_effective_scope(KS-only request, [profile grant on codex])` still yields a `codex` profile scope). DEF-063 is about knowledge spaces and the section-3 matrix has no such grant,
so the smallest fix was kept to spaces.

## DEF-061 (agent-facing default)

Root cause: `authorized_read.py` called `build_query_plan(..., limit=limit or 100)`, overriding T3's planner default (20) for every MCP caller that sends no `limit`.
Fix: `limit=limit` (planner default `DEFAULT_RESULT_LIMIT = 20`; explicit `limit` honoured; M6 contract `MAX_LIMIT = 500` still rejects larger, `MAX_RESULT_LIMIT` ceiling unchanged).
Tests that pinned 100: none (grep + full suite; the T3 note found the same). No existing test changed for DEF-061.

```text
test_mcp_corpus_search_without_limit_is_bounded
E   AssertionError: assert 45 == 20     # base: 45 matching units, all returned
```

## DEF-064 - console script

`pyproject.toml`: `zero-mem-mcp = "src.integration.m6.mcp_server:main"` (version NOT bumped: `1.6.1`, asserted). Verified in a fresh venv:

```text
$ uv venv --python 3.13 /tmp/venv-t6a && uv pip install -p /tmp/venv-t6a -e .
 + zero-mem==1.6.1 (from file:///.../agent-a7a2192f7837d258d)
$ /tmp/venv-t6a/bin/python -c "import importlib.metadata as m; print([e for e in m.entry_points(group='console_scripts') if e.name.startswith('zero-mem')])"
[EntryPoint(name='zero-mem', value='zero_mem.cli:main', group='console_scripts'), EntryPoint(name='zero-mem-mcp', value='src.integration.m6.mcp_server:main', group='console_scripts')]
$ cd /tmp/t6a-scratch   # a foreign cwd; initialize, tools/list and two tools/call over stdio:
$ ... | /tmp/venv-t6a/bin/zero-mem-mcp --store-path <matrix.sqlite> --profile-id claude-code
initialize -> {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "zero-mem-m6", "version": "1.6.1", "identity": "pinned"}}
tools/list -> 11 tools; has requesting_profile_id: False
tools/call 3 -> isError False | corpus_search: SUCCESS - 1 result(s) // 1. external_ref=mem://persona/a; memory_type=persona; normalized_text=zebra marker-A // Full records are in structuredContent.
tools/call 4 -> isError True | corpus_search: POLICY_DENIED (DENY_IDENTITY_PINNED)
```

Also from the base venv with nothing installed, from a foreign cwd (DEF-062 item 5):
`python <repo>/src/integration/m6/mcp_server.py --store-path <db>` answers `initialize` (`identity: unpinned` + the one-line stderr warning), and with
`ZM_M6_CORPUS_STORE_PATH=/nope/missing.sqlite` still answers (stderr: `ignoring configured corpus-store-path (missing_corpus_store); corpus search uses the main derived store`).
The repo-root `build/` and `zero_mem.egg-info/` created by that editable install are git-ignored and were removed afterwards.
Not done (out of scope, listed in DEF-064): top-level package still named `src`; `scripts*` still excluded from the wheel.

## DEF-066 - bad corpus-store-path no longer aborts server start

`M6Runtime.__init__` caught nothing from `_validate_corpus_store_path`; now `CorpusStoreConfigError` is caught, the path is dropped (no corpus connection = fail-closed as when unconfigured),
`runtime.corpus_store_config_error` holds the stable code (never the path) and one `logging` warning goes to stderr. `_validate_corpus_store_path` itself is unchanged (still raises when called directly).
Server tests run a real subprocess with `ZM_M6_CORPUS_STORE_PATH` = missing / relative / not-a-corpus-store: `initialize` and a `corpus_search` (A C E H) succeed; stderr has the warning, no path, no traceback.

```text
E   src.integration.m6.runtime.CorpusStoreConfigError: missing_corpus_store: /tmp/pytest-of-root/pytest-220/test_server_starts_and_searche0/no-such-corpus.sqlite   # base: server dies in configure()
```

## Item 6 - `corpus_search` forwards `memory_type` / `external_ref_prefix`

`handlers.handle_corpus_search` now passes `metadata=` (validated through `CorpusMetadataFilter`) to `corpus_unit_search`; filters live in the existing `filters` object
(`filters.memory_type`, `filters.external_ref_prefix`; documented in the tool schema). Any other filter key or a malformed value is `INVALID_REQUEST` (`UNSUPPORTED_FILTER` / `INVALID_FILTER`) instead of being silently
ignored (previously every `filters` object was ignored for this tool). Results already carried `external_ref` / `memory_type` (T3 `_safe_view`); now asserted through MCP. Filters are post-authorization:
`memory_type=persona` as claude-code returns A C, never codex's private D.

```text
tests/unit/test_t6a_corpus_search_filters.py:39: in test_memory_type_filter_is_forwarded
    assert markers(env["results"]) == ["B"]
E   AssertionError: assert ['A', 'B', 'E', 'F'] == ['B']      # base: filter ignored
```

## Existing tests changed (3, justified)

- `tests/unit/test_v141_def012_wiring.py::test_configure_with_bad_corpus_path_fails_loudly` -> `..._degrades_without_aborting` and `::test_relative_path_rejected` -> `..._degrades_without_aborting`:
  they pinned the raise that DEF-066 removes (the T3 hand-off named them). They now assert the new contract (path dropped, `corpus_store_path is None`, `open_corpus_conn() is None`, stable error code recorded). Module docstring line 2 updated.
- `tests/unit/test_pkg1_packaging.py::test_console_entry_point_is_declared_exactly_once`: pinned `scripts == {"zero-mem": ...}`; DEF-064 adds the second console script, so the expected mapping now lists both (each still declared exactly once).
- No test changed for DEF-061 (none pinned 100), DEF-062 (the existing schema tests still hold: `tool` const, `operation` const, `additionalProperties: false` are kept) or DEF-063.

## Full suite (fixed tree)

`/tmp/venv/bin/python -m pytest -q -p no:cacheprovider` (the mandated `HOME=` prefix is refused by the sandbox; plain run, as in T3):

```text
FAILED tests/unit/test_m9_6_hardening.py::test_readonly_vault_is_rejected_closed
FAILED tests/unit/test_m9_6_hardening.py::test_permission_denied_managed_root_fails_closed
2 failed, 5356 passed, 13 skipped in 133.01s (0:02:13)
```

The 2 failures are the known root-only ones. Baseline on the same base before any change: `2 failed, 5255 passed, 13 skipped` -> +101 passed (the 101 new tests: 119 above minus the 18 that already existed in `test_pkg1_packaging.py`/`test_v141_def012_wiring.py`).
`git diff --check` clean.

## Decisions for the reviewer

- `content` is a bounded summary (not JSON) because the envelope must not be sent twice; `protocolVersion` stays `2024-11-05`, a version whose spec has no `structuredContent`. Clients that ignore
  `structuredContent` see status, reason, count and up to 5 one-line previews; whether Claude Code / Codex / Hermes / OpenClaw surface `structuredContent` to the model is [U] (not testable here).
  If a client turns out to need the full JSON in `content`, revert only `_tool_result` (one function).
- `arguments.tool` is ignored when it differs (not rejected): the called tool name is authoritative, which is what a per-tool client allowlist checks.
- A pinned server rejects (does not silently rewrite) a different `requesting_profile_id`, so a confused or hostile client gets an `isError` it can see.
- `--default-ks` is `corpus_search`-only and loses private rows by design (one request cannot return private + shared rows, design doc section 3); T6b `memory_recall` is the composite.
- Agent default limit is 20 (task statement), not the 8 floated in the design doc; one constant (`DEFAULT_RESULT_LIMIT`) to change.

## Files changed

- `src/integration/m6/mcp_server.py` (identity pin, isError, summary, bootstrap, flags), `mcp_wrapper.py` (schemas/descriptions, tool-name forcing), `handlers.py` (corpus filters), `runtime.py` (DEF-066), `contracts.py` (space-id validation)
- `src/access/grants.py` (DEF-063), `src/access/authorized_read.py` (DEF-061), `pyproject.toml` (DEF-064), `examples/mcp_client_poc.py`
- tests: `tests/unit/t6a_mcp_helpers.py`, `test_def052_identity_pin.py`, `test_def061_agent_default_limit.py`, `test_def062_mcp_transport.py`, `test_def063_requested_ks.py`, `test_def064_console_script.py`, `test_def066_server_start.py`, `test_t6a_corpus_search_filters.py`; edited `test_v141_def012_wiring.py`, `test_pkg1_packaging.py`
- `docs/defects/closures/T6a.md`

## Hand-offs / not done

1. T6b `memory_recall`: use `mcp_server.get_identity()` for the pinned profile; compose private (implicit) + shared (`knowledge_space_ids=[ks]`) requests and merge; `corpus_search` hits still carry about 20 fields each (hashes, scores, `reason`) - consider a compact projection for agents.
2. Profile/project-grant analog of DEF-063 (see above) needs a maintainer decision on request-vs-grant intersection semantics.
3. Not verified with real clients: Claude Code, Codex, Hermes, OpenClaw sessions (summary-vs-structuredContent behaviour, `required` handling); Windows/macOS; the console script was verified with the editable install only (no wheel build).
4. Registry text: DEF-064 remainder (package name `src`, `scripts*` excluded from the wheel) stays open.
