# V11 Durable Restart Evidence

## Identity

- Target release: `1.1.0`
- Surviving product baseline: `/home/lenovo/Hermes Workspace/zero-mem-prep-kTxwTi/repo`
- Baseline HEAD: `78c4bb46b88b8ce9987c6882b24201e08b82a7f0`
- Baseline branch: `master`
- Planning checkout: `/home/lenovo/Hermes Workspace/zero-mem-prep-kTxwTi/planning`
- Planning ref: `2f1763f1335326b83bf90f263cada5c3715f21eb`
- Canonical specification: `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`
- Canonical SHA-256: `85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a`

## Lost execution status

- `/tmp/zero-mem`: `LOST_AFTER_REBOOT_OR_TMP_CLEANUP`
- Previous Phase D/E implementation: `NOT_RECOVERED`
- Previous Phase D/E machine state: `NOT_RECOVERED`
- Previous execution reports: historical, non-authoritative for current source
- Continuity claim: none

## Durable reconstruction

- Durable worktree: `/home/lenovo/Hermes Workspace/zero-mem-v1.1`
- Local branch: `NyanBUIDL-Zero-mem`
- Remote publication: denied
- Local commits: authorized
- Current lifecycle: `V1.1_RESTART_BOOTSTRAP`
- Roadmap source: planning ref WP-00 through WP-22 DAG; no Phase A-G structure is present in surviving planning authority.

## Baseline verification

Command: `HOME=<isolated temporary HOME> .venv/bin/python -m pytest -q`

Result: `3138 passed, 5 skipped, 0 failed` in the durable worktree, Python 3.11.16, pytest 9.1.1, SQLite 3.53.1 with FTS5 enabled.

Graphify baseline corroboration was read-only and external: 253 code files, 6,811 nodes, 20,250 edges, 177 communities. Documentation semantics were excluded (`--code-only`).

## Authority and boundaries

The current maintainer instruction authorizes local implementation and local checkpoints while denying remote publication. The control plane is derived governance evidence, not Product Memory and not canonical product data. No control-plane content is ingested into Product Memory.

## Status

`PASS — DURABLE V1.1 RECONSTRUCTION ACTIVE`
