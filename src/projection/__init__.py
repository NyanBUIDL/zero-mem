"""M9 — Obsidian projection layer. M9.1: contracts, config boundary, path safety.

M9.1 establishes the safe foundation every later projection write depends on.
It writes NO note, renders NO content, reads NO canonical store, and makes NO
authorization decision. Later increments add rendering (M9.2), provenance and
links (M9.3), the manifest and incremental updates (M9.4), the human-ownership
and edit-conflict policy (M9.5), and hardening plus the single controlled
real-vault smoke test (M9.6).

Architectural invariants (AGENTS.md, plan-m9.md §5, §11, §23):

- **Canonical authority is unchanged.** Append-only JSONL traces, approved
  project-state records, and the versioned artifact store remain the source of
  record; SQLite stays derived and rebuildable. The Obsidian vault is a curated,
  derived, disposable projection — deleting it destroys nothing canonical, and a
  rebuild restores it exactly.
- **Direction is one-way.** Canonical -> projection. M9 performs no write-back:
  an Obsidian edit can never mutate canonical memory (§29 Q5/Q20).
- **The vault confers nothing.** Filesystem location, folder name, wiki link,
  tag, or a shared entity name never creates authorization, verification,
  supersession, or truth. M5 remains the sole authorization authority and
  ``requesting_profile_id`` is always explicit (``None`` stays ``None``).
- **Ownership is proven, not assumed.** A generated file is claimed only under
  the three-signal test; path containment alone is never sufficient, so a
  human-owned note is never overwritten or deleted.
- **Sensitivity uses the one canonical vocabulary** (``public < internal <
  private < secret``) with a default projection ceiling of ``internal``;
  ``secret`` never projects, and an unknown sensitivity or ceiling fails closed.
- **Schema remains v9.** No migration, no SQLite projection table.
- **Zero LLM calls, zero external network calls, zero embeddings, no new
  third-party dependency, and no Hermes core change.**
"""

from __future__ import annotations

from typing import Final

from .config import (
    CONFIG_FILE_RELATIVE_PATH,
    CONFIG_FILE_VAULT_KEY,
    DEFAULT_MANAGED_DIR_NAME,
    REASON_VAULT_NOT_CONFIGURED,
    VAULT_ROOT_ENV_VAR,
    ProjectionConfig,
    load_projection_config,
    resolve_vault_root,
    unavailable_result,
    validate_vault_root,
)
from .contracts import (
    DEFAULT_PROJECTION_SENSITIVITY_CEILING,
    M9_CONTRACT_VERSION,
    MANAGED_MARKER_KEY,
    META_DIR_NAME,
    NOTE_TYPE_DIRECTORIES,
    PROJECTION_VERSION,
    NoteStatus,
    NoteType,
    OwnershipSignals,
    ProjectedNote,
    ProjectionConfigError,
    ProjectionError,
    ProjectionPathError,
    ProjectionRequest,
    ProjectionResult,
    ProjectionStatus,
    ProjectionVocabularyError,
    is_projectable_sensitivity,
    is_zero_mem_managed,
    sensitivity_rank,
    validate_sensitivity_ceiling,
)
from .identity import (
    NOTE_ID_PREFIX,
    PROJECTION_IDENTITY_VERSION,
    content_fingerprint,
    derive_note_id,
    note_filename,
    note_id_suffix,
    slug,
    validate_note_id,
)
from .paths import (
    OBSIDIAN_CONFIG_DIR,
    assert_within_managed_root,
    is_obsidian_config_path,
    is_within_managed_root,
    managed_relative_path,
    path_ownership_signal,
    resolve_managed_root,
    safe_managed_path,
    safe_meta_path,
    safe_note_path,
    validate_path_component,
)
from .writer import (
    WriteOutcome,
    WriteStatus,
    overwrite_note,
    retire_note,
    write_note,
    write_notes,
)
from .manifest import (
    MANIFEST_FILENAME,
    MANIFEST_RELATIVE_PATH,
    MANIFEST_VERSION,
    ManifestEntry,
    ManifestError,
    ProjectionManifest,
    empty_manifest,
    load_manifest,
    resolve_entry_path,
    store_manifest,
)
from .reconcile import (
    ReconcileResult,
    reconcile,
    rebuild,
)

#: Derived-schema version this projection layer runs against. M9 adds no table,
#: column, index, or migration; the manifest lives on the filesystem (§15.1/§23).
PROJECTION_SCHEMA_VERSION: Final[int] = 9

__all__ = [
    "PROJECTION_SCHEMA_VERSION",
    "PROJECTION_VERSION",
    "M9_CONTRACT_VERSION",
    "PROJECTION_IDENTITY_VERSION",
    # configuration
    "ProjectionConfig",
    "VAULT_ROOT_ENV_VAR",
    "CONFIG_FILE_RELATIVE_PATH",
    "CONFIG_FILE_VAULT_KEY",
    "DEFAULT_MANAGED_DIR_NAME",
    "REASON_VAULT_NOT_CONFIGURED",
    "load_projection_config",
    "resolve_vault_root",
    "validate_vault_root",
    "unavailable_result",
    # contracts
    "ProjectionRequest",
    "ProjectionResult",
    "ProjectedNote",
    "ProjectionStatus",
    "NoteType",
    "NoteStatus",
    "NOTE_TYPE_DIRECTORIES",
    "META_DIR_NAME",
    "MANAGED_MARKER_KEY",
    "OwnershipSignals",
    "is_zero_mem_managed",
    "ProjectionError",
    "ProjectionConfigError",
    "ProjectionPathError",
    "ProjectionVocabularyError",
    # sensitivity
    "DEFAULT_PROJECTION_SENSITIVITY_CEILING",
    "sensitivity_rank",
    "is_projectable_sensitivity",
    "validate_sensitivity_ceiling",
    # identity
    "NOTE_ID_PREFIX",
    "derive_note_id",
    "validate_note_id",
    "note_id_suffix",
    "note_filename",
    "content_fingerprint",
    "slug",
    # paths
    "OBSIDIAN_CONFIG_DIR",
    "resolve_managed_root",
    "validate_path_component",
    "assert_within_managed_root",
    "is_within_managed_root",
    "safe_managed_path",
    "safe_note_path",
    "safe_meta_path",
    "is_obsidian_config_path",
    "path_ownership_signal",
    "managed_relative_path",
    # writer (M9.2 atomic writes; M9.4 overwrite/retire gated extensions)
    "WriteStatus",
    "WriteOutcome",
    "write_note",
    "write_notes",
    "overwrite_note",
    "retire_note",
    # manifest + reconcile (M9.4)
    "MANIFEST_VERSION",
    "MANIFEST_FILENAME",
    "MANIFEST_RELATIVE_PATH",
    "ManifestEntry",
    "ManifestError",
    "ProjectionManifest",
    "empty_manifest",
    "load_manifest",
    "store_manifest",
    "resolve_entry_path",
    "ReconcileResult",
    "reconcile",
    "rebuild",
]
