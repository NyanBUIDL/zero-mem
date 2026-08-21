# V124-04 Evidence — Hermes pillars, HITL and Agent Skills

## Tested environment

- OS: Linux x86_64 (Ubuntu 7.0.0-30-generic)
- Python: 3.11.16
- pytest: 9.1.1
- Baseline SHA: `eaa0e7a3567de7644ec3d28ff1bda0c8158b39ef`
- Tested SHA: post-commit candidate (working tree identical to committed)

## Commands (sanitized)

```text
python -m pytest tests/unit/test_v124_hitl_correction.py -q
python -m pytest tests/unit/test_v124_runtime_modes.py tests/unit/test_v124_storage_topology.py tests/unit/test_v124_hitl_correction.py tests/unit/test_wp25_runtime_ownership.py tests/unit/test_v124_message_contract.py tests/integration/test_v123_hermes_host_composition.py -q
python -m compileall -q zero_mem/correction.py
git diff --check -- zero_mem/correction.py tests/unit/test_v124_hitl_correction.py
```

## Results

- `tests/unit/test_v124_hitl_correction.py`: **6 passed**
  - propose returns preview without mutation (no canonical write)
  - confirm preserves original canonical line byte-for-byte; appends linked control event (no silent overwrite)
  - delete-request tombstones without removing the canonical record
  - denial (unknown target) returns None/DENIED and appends nothing; no candidate leak
  - supersession links original trace via `supersedes` key at canonical top level
  - skill lifecycle capture emits no .md (sidecar never owns/rewrites SKILL.md)
- Regression (V124-02 + V124-03 + wp25 + v124-01 + v123 host composition): **69 passed**
- `compileall`: exit 0
- `git diff --check`: exit 0

## Independent review (Verification Agent equivalence)

- Diff reviewed from baseline SHA. No stub, no dead path, no duplicated composition, no false-success.
- HITL gate: `propose()` side-effect-free; `confirm()` appends a LINKED control event to canonical
  JSONL; original record retained (ADR-009: append-only, no silent overwrite, no delete).
- Derived projection advanced incrementally via the bounded projection worker; no full rebuild path
  that triggered a migration edge case was used.
- Skills pillar: controller never touches Hermes SKILL.md; capture root scan confirms no .md written.
- No new dependency / LLM / network; stdlib + existing src only.

## Verdict: PASS

## Known limitations / blockers

- Windows / macOS / Python 3.12 / 3.13 matrices NOT executed locally (not installed). The logic is
  stdlib + platform-neutral storage; must be run by CI before RELEASE_QUALIFIED.
