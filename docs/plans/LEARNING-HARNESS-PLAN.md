# Learning harness - plan (phase 1)

Authorization: repository owner (chat, 2026-10-02) asked to improve the memory for what an agent needs: project context, rules,
workflow and knowledge, with settings the owner controls. Defaults chosen by the implementer and recorded here: learning mode
`suggest`, context injection OFF, agents may PROPOSE but nothing becomes active without the owner's approval.
Stacked on `feat/shared-memory-runtime` (PR #3, not merged); this branch's PR targets that branch.

## Governance (AGENTS.md)
Unverified claims must not become active facts; memory must not be injected automatically before controlled-injection gates pass;
zero LLM calls for memory operations. So: proposals are inert until approved; injection is a setting that defaults to off;
all extraction is deterministic.

## What an agent needs (priority order)
1. A short, correct briefing at session start: active rules, relevant decisions and gotchas, recent devlog, within a token budget.
2. A safe way to add knowledge: propose -> owner reviews -> active (versioned, revocable, expiring).
3. Controls the owner can set and audit.
4. A measurable check that the briefing contains what a task needs and nothing unapproved.

## Tasks
| Wave | Task | Scope |
|---|---|---|
| 1 | T14 core | settings file + CLI, new memory types `rule`/`decision`/`gotcha`, proposal store with lifecycle, `zero-mem review` |
| 2 | T15 briefing + eval | task-aware `memory_brief`, MCP `memory_propose`/`memory_brief`, `zero-mem eval` with owner-written cases |
| 2 | T16 learner + hooks | deterministic candidate extraction from corrections/transcripts/git into proposals; hook snippets |
| 3 | Review | full suite, CI on 3 OS, security review, PR |
