# ADR-V170-01 - CorpusHit provenance (`external_ref`, `memory_type`) and source filters

**Status:** ACCEPTED / IMPLEMENTED (repository owner approved in chat, 2026-10-01)
**Date:** 2026-10-01 - **Defect:** DEF-056 - **Design:** `docs/design/SHARED-MEMORY-RUNTIME.md` section 3

## Context

A corpus hit identified its source only by the 64-hex `source_id`. Agents sharing one memory
(persona, workflow, skill, devlog, fact, user files) need to know *what* a hit is
(`external_ref="mem://<type>/<id>"`, `custom_meta.memory_type`) and to ask for one type. Unit rows
do not persist source `meta`/`custom_meta`, and `VALID_METADATA_KEYS` is a closed contract, so
neither was retrievable or filterable.

## Decision

1. `CorpusHit` gains two **additive, optional** fields, both defaulting to `None`:
   `external_ref` (source `external_ref`) and `memory_type` (string `custom_meta.memory_type`, else `None`).
   `as_evidence_dict()` carries both. Existing constructors and consumers are unaffected; the M6
   `_safe_view` returns them to agents with no handler change.
2. **No schema change.** Both values are read at query time with a `LEFT JOIN zm_corpus_sources s ON
   s.source_id = u.source_ref` over columns that already exist (schema v10+, schema version stays 13).
   They stay derived and rebuildable; a malformed `custom_meta` yields `memory_type=None`, never an error.
3. The closed filter contract is extended by exactly two keys, validated fail-closed
   (`CorpusQueryError`):
   - `memory_type`: string matching `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`, exact match;
   - `external_ref_prefix`: non-empty string of at most 512 characters, prefix match on `external_ref`.
4. **Authorization is unchanged.** Both filters run in `_authorize_and_filter` strictly *after*
   `AuthorizedCorpusScope.allows()`, like the existing metadata dimensions. They can only narrow the
   authorized set: the `AuthorizedReadService` decision, `reason_code` and the authorized universe are
   identical with and without them, and unauthorized rows never reach filtering, ranking or scoring.
5. The new fields are **informational labels written by the ingesting agent, never authorization
   inputs** and never instructions. Retrieval and policy must not branch on them, and a prefix filter
   is a convenience, not a security boundary.

## Alternatives rejected

- Persist columns on `zm_corpus_units` (migration v14): needless rebuild/migration cost for data that
  is one indexed join away, and a second copy of source truth.
- SQL `json_extract` on `custom_meta`: depends on the JSON1 build; Python parsing is portable.
- Derive `memory_type` from the `mem://` prefix: two sources of truth that can disagree.

## Consequences

- Hits expose provenance (`mem://persona/style` + `persona`) instead of an opaque hash.
- Forwarding these two filters from the MCP `corpus_search` tool is separate M6 work (task T6); this
  ADR only extends the retrieval contract.
- Tests: `tests/unit/test_def056_corpus_hit_provenance.py` (fields, filters, unchanged decision,
  non-vacuous narrowing, invalid values, malformed `custom_meta`, MCP surface).
