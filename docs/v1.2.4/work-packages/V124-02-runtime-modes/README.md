# V124-02 — Explicit runtime modes

Status: IMPLEMENTED_VERIFIED
Owner: Lead Delivery Agent
Baseline SHA: 8c13bd4233311b5124613871ef4e9107e0d20a82
Depends on: V124-01 (IMPLEMENTED_VERIFIED @ 018407c)

## Authority and problem

- Master-spec: `docs/v1.2.4/MASTER_PLAN.md` (V124-02), `docs/v1.2.4/VALIDATION_SPEC.md` (runtime-mode truth table).
- ADR-009: JSONL canonical / SQLite derived boundary preserved.
- AGENTS.md / ARCHITECTURE.md: observe must not auto-inject; off must not open writer/DB.
- Problem: runtime gates only on a single boolean `enabled`. There is no explicit
  `off`/`observe`/`assist`/`inject` mode controlling writer-open, capture, read-tool
  registration, and injection-hook registration. `observe` must not create an
  InjectionAdapter; `off` must not open a writer/DB.

## In scope

- Production: `src/integration/zero_mem_runtime.py` (mode enum, config, health, capability matrix).
- Production: `zero_mem/hermes_integration.py` boundary (register read/injection by mode).
- Production: `zero_mem/cli.py` (status reports explicit mode + capability matrix).
- Test: `tests/unit/test_v124_runtime_modes.py` (truth-table + negative tests).
- Docs/evidence: this record + evidence manifest.

## Out of scope

- V124-03 single-topology freshness (separate package).
- V124-04 HITL (separate package).
- V124-05 cross-platform packaging (separate package).
- Changing canonical/derived storage boundary, auth model, or adding LLM/network.

## Contract

| Input/state | Output/status | Side effects | Failure semantics |
|---|---|---|---|
| mode=off | writer closed, read=false, injection=false | no writer/DB opened | health.mode=="off", no capture |
| mode=observe | writer open, capture on, read=false, injection=false | canonical append only | no InjectionAdapter created |
| mode=assist | writer open, capture on, read=true, injection=false | read tools registered | no injection hook |
| mode=inject | writer open, capture on, read=true, injection=true(controlled) | read+injection registered | controlled pre_llm_call only |

Backward compatibility: `RuntimeConfig.enabled=False` maps to mode `off`; missing mode
defaults to `assist` (matches prior enabled-by-default behavior for capture+read).

## Security and compatibility

- `off` opens no writer/DB (fail-closed; no canonical write).
- `observe` must NOT register an injection hook or construct an InjectionAdapter.
- Each truth-table cell asserted directly; not inferred from a single enabled flag.
- No new dependency, network call, or LLM call introduced.

## Acceptance commands

```text
python -m pytest tests/unit/test_v124_runtime_modes.py -q
python -m pytest tests/unit/test_wp25_runtime_ownership.py -q
python -m py_compile $(git diff --name-only --diff-filter=M)
git diff --check
```

## Required evidence

- Tested full SHA: `8c13bd4…` + V124-02 commit (see evidence/V124-02-evidence.md)
- Environment: Linux x86_64, Python 3.11.16 (3.12/3.13 not installed locally)
- Results: V124-02 unit 39 passed; host-composition 3 passed; related regression 106 passed
- Known limitations: Windows/macOS + Python 3.12/3.13 matrices not executable locally; gated by CI.
- Reviewer: independent Verification Agent pass (PASS)
