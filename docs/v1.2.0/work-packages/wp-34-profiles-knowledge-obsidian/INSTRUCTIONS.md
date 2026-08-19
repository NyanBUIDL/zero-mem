# WP-34 Instructions

**WP:** WP-34 Profiles / Knowledge / Obsidian
**Status:** PLANNING
**Dependencies:** WP-29 VERIFIED; WP-32 VERIFIED; WP-33 VERIFIED

## Objective

Qualify the existing M9.1–M9.6 deterministic Obsidian projection for the v1.2 scope: explicit profile/project/knowledge-space scope, authorization parity, cross-scope leakage protection, deterministic human-facing projection, and path/ownership safety.

## Scope

- Reconcile the existing `src/projection` and `scripts/project_to_obsidian.py` implementation against the v1.2 contracts.
- Test authorized projection through `AuthorizedReadService` before rendering.
- Test profile, project, and knowledge-space isolation where the existing contracts expose those scopes.
- Test deterministic identity, rendering, manifest/reconcile lifecycle, human ownership, symlink/path traversal, secret withholding, and canonical immutability.
- Update WP-34 evidence and project state only after executable acceptance and independent review.

## Out of scope

- Obsidian as canonical storage, authorization source, retrieval engine, or write-back channel.
- New SQLite schema, canonical JSONL changes, embeddings, vector search, LLM/network calls, watchers, or Hermes core changes.
- Corpus/PDF projection; M10 explicitly deferred corpus Obsidian projection.
- Reimplementation of already-present M9 modules without a failing acceptance case.

## Required invariants

- M5 remains the sole authorization authority; projection receives authorized views and never discovers or filters unauthorized candidates after retrieval.
- `profile_id`, `project_id`, `knowledge_space_id`, and `resource_type` remain explicit where present; no cross-scope widening.
- Projection is one-way, derived, rebuildable, and canonical-store read-only.
- Obsidian output is DATA-only Markdown; hostile content cannot create frontmatter, links, embeds, HTML, or executable structure.
- Only the configured managed subtree may be written; `.obsidian`, vault root, outside paths, symlinks, and human-owned files are protected.
- Secret content is always withheld by the non-disableable baseline; custom patterns extend, never replace it.
- Output identity, ordering, filenames, manifests, and clean rebuilds are deterministic.

## Allowed changes

- WP-34 planning/evidence/state documentation.
- Minimal production or test correction only when a current acceptance test demonstrates a v1.2 contract violation and the correction remains within the existing M9 architecture.

## Prohibited changes

- New source of truth, schema migration, dependency, authorization implementation, retrieval pipeline, or write-back path.
- Destructive operation against canonical data or the operator's real vault.
- Hardcoded developer paths or credentials.
- Weakening a security assertion to obtain a pass.

## Required inputs / outputs

Inputs: current v1.2 authorities, WP-29/32/33 verified contracts, existing M9 modules/tests, and temporary isolated vault/store fixtures.

Outputs: executable WP-34 acceptance evidence, independent fail-closed review, updated package/state, and no real-vault mutation.

## Escalation conditions

Escalate if acceptance requires changing canonical truth, weakening authorization, adding a new architecture/dependency, changing M9 authority semantics, destructive real-vault/canonical operations, or resolving an unowned scope gap.

## Completion conditions

Planning package self-review passes; focused M9/WP-34 tests pass; relevant isolated regression passes; path/security/canonical immutability checks pass; Graphify is rerun on the final tree; independent review passes; evidence is complete; then state becomes VERIFIED.
