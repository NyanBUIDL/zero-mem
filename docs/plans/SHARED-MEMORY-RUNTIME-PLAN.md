# Shared Memory Runtime - work plan

Authorization: repository owner (chat, 2026-10-01) approved building this on the Hermes authorization pipeline, fixing every
defect found (DEF-049..066), optional OCR for images, and a PR to master once the integration branch is stable.
No tag, release, version bump, or force-push is authorized. Design: `docs/design/SHARED-MEMORY-RUNTIME.md`.

Branching: integration branch `feat/shared-memory-runtime` (from verified master v1.6.1). Each task works on its own
`wt/<task>` branch, merged into the integration branch with a merge commit (no rebase, no force). PR -> master at the end.

| Wave | Task | Scope (files) | Defects |
|---|---|---|---|
| 1 | T1 security | `src/redaction/*`, `src/access/authorized_write.py`, pre-register scan helper | 049, 051, 057 (secret sensitivity) |
| 1 | T2 storage | `src/corpus/{derived_store,registry,blob_store}.py`, `src/storage/coordination` use | 050, 053, 058, 059, 060 |
| 1 | T3 paths/retrieval | `zero_mem/{paths,upgrade,commands_*,backup}.py`, `src/corpus/retrieval.py`, `query_planner.py` | 054, 055, 056, 061(query side), 065, 066 |
| 1 | T4 adapters | `src/corpus/adapters/*` | md, csv, json/jsonl chat, docx, xlsx, image(OCR optional), paragraph chunking, extension->kind |
| 2 | T5 library+CLI | `zero_mem/memory.py`, `zero_mem/cli.py`, provisioning, retire `notes.py` | memory API, agents/grants provisioning |
| 2 | T6 MCP | `src/integration/m6/*`, new `src/integration/m6w/*` | 052, 062, 063, 064, write tools, memory_recall |
| 3 | T7 quality | benchmarks over the real pipeline, ranking | 061 |
| 3 | T8 e2e+docs | multi-process + real stdio MCP tests, runbook, per-agent configs | - |
| 4 | Review | full suite, code-review, security-review, registry closure, PR | all |
