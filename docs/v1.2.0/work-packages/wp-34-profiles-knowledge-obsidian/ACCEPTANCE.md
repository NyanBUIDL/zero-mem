# WP-34 Acceptance

**Status:** VERIFIED

## Functional acceptance

- Existing M9 projection is runnable from the current tree without new architecture.
- Explicit profile/project scope is preserved in identity, authorization request, provenance, and output paths.
- Authorized project/knowledge data projects only through existing M5 authorized-read surfaces.
- Output is deterministic, byte-stable on clean rebuild, and idempotent on unchanged rerun.
- Manifest/reconcile handles stale generated files and human edits without unsafe deletion or overwrite.
- Obsidian is optional and projection remains a disposable human-facing view.

## Negative / security acceptance

- Unauthorized profile/project/knowledge data cannot affect candidate sets, counts, scores, notes, links, paths, or errors.
- Cross-profile, cross-project, and cross-knowledge-space leakage tests pass where the current contracts expose those dimensions; absent knowledge-space field is recorded as a limitation, not silently widened.
- Relative paths, traversal, absolute injection, symlink chains, `.obsidian`, managed-root collisions, and unsafe ownership fail closed.
- Hostile Markdown/frontmatter/wiki-link/embed/HTML content remains inert DATA.
- Secret baseline is non-disableable; custom patterns extend it.
- Canonical JSONL and derived SQLite are unchanged by projection.

## Failure / recovery / restart acceptance

- Unconfigured or invalid vault returns safe unavailable/error without creating paths.
- Read-only/permission failures do not partially mutate canonical or human-owned files.
- Missing/corrupt/stale manifest rebuilds safely from authorized source state.
- Repeated projection is idempotent; interrupted/partial managed-root state is reconciled without deleting human-owned content.

## Required commands

- Focused M9.1–M9.6 suites and WP-29/WP-32 related authorization/context suites.
- Isolated full regression excluding the known historical baseline artifact mismatch.
- `compileall`, `git diff --check`, static secret/path audit, final Graphify, and independent fail-closed review.

## Exit gate

All executable functional, negative, security, canonical-immutability, deterministic, ownership, and relevant regression tests pass; evidence records exact commands/results and limitations; independent review has no blocking findings; package/state are synchronized. No real-vault apply, release, tag, push, or publication is performed.
