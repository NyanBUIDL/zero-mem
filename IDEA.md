# Hermes External Zero-Mem

## 1. Project Status

- Status: Proposed
- Project type: Local-first AI agent infrastructure
- Primary agent: Hermes Agent
- Human knowledge workspace: Obsidian
- Canonical trace storage: SQLite, JSONL, and local artifact files
- Primary specification: `docs/Hermes-External-ZeroMem-Specification.md`

This file describes the stable product idea, intended architecture, scope,
and non-negotiable principles.

It does not track implementation progress.

Implementation progress must be stored in:

- `project-state.yaml`
- `implementation-plan.yaml`
- Git history
- test results

---

## 2. Vision

Build an external memory substrate for Hermes Agent that preserves original
interaction traces, project state, decisions, tool observations, research
sources, user preferences, and knowledge systems without requiring an LLM
for routine memory operations.

The system should allow Hermes to continue long-running projects across
sessions with:

- lower repeated context-token consumption;
- stronger project consistency;
- verifiable state;
- traceable evidence;
- controlled profile-specific knowledge;
- explicit conflict handling;
- human-readable knowledge management through Obsidian.

The system is not only a PDF retrieval system.

PDF files and research documents are one category of memory source inside
a larger memory architecture for Hermes.

---

## 3. Problem

A normal long-running agent workflow can gradually lose consistency because:

- previous conversation history becomes too large;
- old tool results remain mixed with current state;
- summaries omit constraints and rejected decisions;
- assistant statements may be mistaken for verified facts;
- project state is distributed across sessions and files;
- profiles, skills, and knowledge domains become mixed;
- the model repeatedly reads the same historical context;
- decisions can silently change between sessions;
- artifacts may be duplicated or modified from outdated versions.

The project must solve these problems without depending on repeated
LLM-generated memory summaries.

---

## 4. Primary Objectives

The system must:

1. Capture relevant Hermes events and preserve their provenance.
2. Store raw traces outside the LLM context.
3. Distinguish statements, observations, decisions, inferences, and verified states.
4. Retrieve only the evidence needed for the current task.
5. Preserve temporal order and project boundaries.
6. Support profile-specific knowledge systems.
7. Allow explicit combination of multiple knowledge systems.
8. Allow global read access by default with profile-first ranking.
9. Restrict cross-profile writes unless explicitly authorized.
10. Use Obsidian as the main human-facing knowledge workspace.
11. Avoid LLM calls for ordinary memory construction, indexing, routing,
    retrieval, deduplication, and deterministic calibration.
12. Continue projects from verified project state rather than from vague
    assistant recollection.
13. Keep all important decisions and state changes auditable.
14. Reduce repeated input-token use in long-running workflows.
15. Prevent secrets and sensitive information from being persisted without
    appropriate filtering.

---

## 5. Non-Goals

The first version will not:

- replace Hermes Agent;
- replace the final reasoning LLM;
- treat Obsidian as the canonical raw event database;
- automatically convert every conversation message into permanent memory;
- use an LLM to summarize every event;
- automatically trust assistant completion claims;
- allow unrestricted writes across all knowledge spaces;
- redesign Hermes core before a sidecar prototype is validated;
- ingest the entire document library before the basic memory pipeline works;
- guarantee zero computation cost;
- guarantee zero token usage for final answers.

“Zero-Mem” in this project means that memory operations should not require
LLM input or output tokens by default. Final reasoning and final response
generation may still use an LLM.

---

## 6. Core Architecture

```text
Hermes Agent
  |
  | messages, tool events, task events, file events
  v
Zero-Mem Capture Sidecar
  |
  | redact, classify, normalize, assign provenance
  v
Canonical Storage
  |
  +-- SQLite metadata and relationships
  +-- JSONL append-only raw traces
  +-- artifact and source files
  |
  v
Local Retrieval Layer
  |
  +-- SQLite FTS5 or BM25
  +-- local dense embeddings
  +-- entity-context relationships
  +-- temporal and project hierarchy
  +-- status and provenance filtering
  +-- conflict detection
  +-- evidence closure
  |
  v
Small Evidence Set
  |
  v
Hermes Final Reasoning and Action
