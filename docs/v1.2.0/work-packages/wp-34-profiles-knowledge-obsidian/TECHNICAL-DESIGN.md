# WP-34 Technical Design

**Status:** VERIFIED

## Technologies and dependencies

Reuse Python 3.11, standard-library filesystem primitives, existing SQLite read-only access, existing `AuthorizedReadService`, and existing `src/projection` modules. No dependency or schema change.

## Algorithm

`ProjectionRequest` → validate explicit vault/config/scope → construct one M5 `AccessRequest` per resource type → call the existing authorized-read facade → on denial/error produce no note/stub/count for that resource → apply closed lifecycle/sensitivity/secret eligibility → derive stable note identity and safe relative path → escape all content as DATA → reconcile desired notes against the manifest and three-signal ownership proof → atomically write only the managed subtree.

Projection never opens SQLite directly, authorizes, ranks, verifies, supersedes, resolves conflicts, or writes canonical state.

## Variables and constants

- `profile_id`, `project_id`, `knowledge_space_id`, `resource_type`: explicit scope strings; missing/unknown scope is not widened.
- `vault_root`: explicit absolute configured directory; never inferred.
- `managed_root`: `vault_root / managed_dir_name`; strict subtree boundary.
- `sensitivity_ceiling`: canonical `public < internal < private < secret`; default projection ceiling `internal`; `secret` never projects.
- `ProjectionRequest`, `ProjectedNote`, `ProjectionResult`, `ProjectionManifest`, `EditConflict`: existing typed contracts.
- `MAX_RELATIVE_DEPTH`, component/length limits, and note vocabulary: existing constants in `src/projection`, not new WP constants.

## Ordering / determinism

Stable ordering uses existing note identity, relative path, resource type, and canonical IDs. Content fingerprints use canonical serialization. No wall clock, randomness, rowid, or Python hash affects identity or output.

## Filesystem and ownership model

Validation rejects relative roots, path traversal, unsafe components, symlink chains, `.obsidian`, and paths outside the managed subtree. Writes use existing atomic same-directory temporary files and `os.replace`; collisions and human edits fail closed. Manifest entries are DATA for ownership proof only and are never authorization/truth sources.

## Concurrency / retry / timeout

No background worker, watcher, or retry loop. Projection is an explicit bounded call. Existing writer/reconcile operations are finite and atomic per file; terminal write failures are surfaced as safe statuses without canonical mutation.

## Status vocabulary

Reuse `ProjectionStatus`, `NoteStatus`, and `WriteStatus` from existing contracts. Unconfigured projection is unavailable; denial/error yields no materialized note. No new transport-specific status is introduced.

## Provenance and compatibility

Every note carries source/trace/resource/scope metadata already exposed by authorized views. Markdown is a human-facing projection only. Deleting/rebuilding the managed root is reversible from canonical/derived sources. v1.1/M9 callers and v1.2 authorization/context contracts remain unchanged.

## Prohibited approaches

Direct SQL/JSONL reads in the projector; auth-after-render; vault-as-canonical; write-back; global vault discovery; unrestricted whole-vault ownership; path concatenation from content; secret-pattern replacement; LLM/network/embedding use; new vector or graph subsystem.

## Open decision

Knowledge-space note projection remains `NOT_PRESENT_IN_CURRENT_SURFACE` unless current authorized views expose the field. Do not invent a knowledge-space database column or fallback.
