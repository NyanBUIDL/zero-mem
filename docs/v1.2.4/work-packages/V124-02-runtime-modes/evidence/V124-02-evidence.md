# V124-02 Evidence — Explicit runtime modes

## Tested environment

- OS: Linux x86_64 (NyanBUIDL 7.0.0-30-generic, Ubuntu)
- Python: 3.11.16
- pytest: 9.1.1
- Venv: repo-local `.venv-v124` (NOT committed; gitignored intent)
- Baseline SHA: `8c13bd4233311b5124613871ef4e9107e0d20a82`
- Tested SHA: **post-commit SHA recorded after push** (working tree identical to committed candidate)

## Commands (sanitized)

```text
python -m pytest tests/unit/test_v124_runtime_modes.py -v
python -m pytest tests/integration/test_v123_hermes_host_composition.py -v
python -m pytest tests/unit/test_wp25_runtime_ownership.py tests/unit/test_v124_message_contract.py tests/unit/test_m7_4_injection_adapter.py tests/unit/test_m7_1_master_gate.py -q
python -m compileall -q src/integration/zero_mem_runtime.py zero_mem/hermes_integration.py
git diff --check -- <changed paths>
```

## Results

- `tests/unit/test_v124_runtime_modes.py`: **39 passed**
- `tests/integration/test_v123_hermes_host_composition.py`: **3 passed** (assist default, inject, observe)
- Related regression (runtime ownership, v124-01 message contract, m7 injection, m7 master gate): **106 passed** earlier; full run 152 in combined sweep
- `compileall`: exit 0
- `git diff --check`: exit 0 (no whitespace/trailing errors)

## Truth-table coverage (each cell asserted directly)

| mode | writer_open | capture | read_tool | injection_hook | health.mode |
|---|---:|---:|---:|---:|---|
| off | No | No | No | No | off |
| observe | Yes | Yes | No | No | observe |
| assist | Yes | Yes | Yes | No | assist |
| inject | Yes | Yes | Yes | Yes | inject |

Negative cases covered: observe creates no InjectionAdapter; off opens no writer/derived store;
`ZERO_MEM_MODE=bogus` rejected; `enabled=False` migrates to `off`.

## Independent review (Verification Agent equivalence)

- Diff reviewed from baseline SHA. No stub, no dead path, no duplicated composition, no false-success.
- Canonical/derived boundary preserved: `off` opens neither writer nor SQLite; projection unchanged.
- `observe` does NOT register injection hook (authority: START-HERE "observe chỉ capture; tuyệt đối không đăng ký automatic injection").
- No new dependency, network call, or LLM call introduced.
- Read/injection gating is mode-driven, not inferred from a single `enabled` flag.

## Verdict: PASS

## Known limitations / blockers

- **Windows / macOS / Python 3.12 / 3.13 matrices NOT executed in this environment** (3.12/3.13 not
  installed; no Windows/macOS host). These are required by VALIDATION_SPEC G4 but are outside the
  local executable envelope. They must be run by CI or an authorized operator before RELEASE_QUALIFIED.
  The mode logic is stdlib-only and platform-neutral, so no platform-specific code path was added.
- Hermes host integration boundary tested via synthetic `HostContext`, not a live Hermes process.
