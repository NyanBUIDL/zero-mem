"""M9.1 — the projection path-safety layer (security boundary, not formatting).

The projector eventually writes into a real Obsidian vault the operator uses
daily, so every rule here is treated as a security boundary. The load-bearing
invariant (docs/plans/plan-m9.md §10.1) is:

    the PHYSICAL target must be inside the approved managed root

not the far weaker

    the path STRING begins with the managed root

A lexical ``Path.is_relative_to`` check is explicitly insufficient, because a
symlink component defeats it while the string still looks contained. Every
target is therefore validated against ``os.path.realpath`` — which resolves
symlinks for the existing prefix and leaves a not-yet-created tail intact — AND
against an explicit symlink walk of the whole chain.

**Memory-controlled text never determines a filesystem path.** A path is
CONSTRUCTED from a closed category enum plus a sanitized slug plus a generated
filename; no caller-supplied fragment is ever joined raw. That is what makes
"a malicious title cannot select a parent directory" structural.

Nothing in this module creates, opens, writes, renames, or deletes anything.
Validation is read-only: it stats and reads link metadata, never mutates.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Final, Iterable, Optional

from .contracts import (
    MANAGED_CATEGORY_DIRECTORIES,
    META_DIR_NAME,
    NOTE_TYPE_DIRECTORIES,
    NoteType,
    ProjectionPathError,
    validate_note_type,
)
from .identity import (
    MAX_SLUG_LENGTH,
    RESERVED_FILENAMES,
    note_filename,
    slug,
)

#: Maximum length of any single path component after slugging, excluding the
#: ``--<suffix>.md`` identity tail that ``note_filename`` appends.
MAX_COMPONENT_LENGTH: Final[int] = MAX_SLUG_LENGTH + 32

#: Maximum length in bytes of a managed-root-relative path (docs/plans/plan-m9.md §10.1.6).
#: Bounded well inside the common 255-byte per-component and 4096-byte total
#: filesystem limits so a deep vault path can never fail mid-write.
MAX_RELATIVE_PATH_BYTES: Final[int] = 240

#: Maximum managed-root-relative depth: ``<category>/<scope>/<note>.md``.
MAX_RELATIVE_DEPTH: Final[int] = 3

#: Characters that may never appear inside a single path component.
_FORBIDDEN_COMPONENT_CHARACTERS: Final[tuple[str, ...]] = ("/", "\\", "\x00")

#: Vault-relative directory that belongs exclusively to the operator's Obsidian
#: application configuration. It is NEVER read, written, enumerated, or owned.
OBSIDIAN_CONFIG_DIR: Final[str] = ".obsidian"


# ---------------------------------------------------------------------------
# Component-level validation
# ---------------------------------------------------------------------------

def validate_path_component(component: str) -> str:
    """Validate one final path component, or fail closed.

    Rejects: non-strings, empty, ``.``, ``..``, separators (``/`` and ``\\``),
    NUL and other control characters, drive-letter prefixes (``C:``), any colon,
    leading/trailing whitespace, leading/trailing dots, over-long names, and
    Windows reserved device names.

    The error carries a stable reason code only — never the offending value, so
    a hostile title cannot inject itself into a log line.
    """
    if not isinstance(component, str):
        raise ProjectionPathError("component_not_a_string")
    if not component:
        raise ProjectionPathError("empty_component")
    if component in (".", ".."):
        raise ProjectionPathError("relative_component")
    for character in _FORBIDDEN_COMPONENT_CHARACTERS:
        if character in component:
            raise ProjectionPathError("separator_or_nul_in_component")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in component):
        raise ProjectionPathError("control_character_in_component")
    if ":" in component:
        # Covers drive-letter injection (``C:``) and NTFS alternate data streams.
        raise ProjectionPathError("drive_or_stream_in_component")
    if component != component.strip():
        raise ProjectionPathError("outer_whitespace_in_component")
    if component.startswith(".") and component != META_DIR_NAME:
        raise ProjectionPathError("leading_dot_component")
    if component.endswith(".") or component.endswith(" "):
        raise ProjectionPathError("trailing_dot_or_space_component")
    if len(component) > MAX_COMPONENT_LENGTH:
        raise ProjectionPathError("component_too_long")
    stem = component.split(".", 1)[0].casefold()
    if stem in RESERVED_FILENAMES:
        raise ProjectionPathError("reserved_filename")
    return component


def _validate_relative_components(components: Iterable[str]) -> tuple[str, ...]:
    validated = tuple(validate_path_component(component) for component in components)
    if not validated:
        raise ProjectionPathError("empty_relative_path")
    if len(validated) > MAX_RELATIVE_DEPTH:
        raise ProjectionPathError("relative_path_too_deep")
    relative = "/".join(validated)
    if len(relative.encode("utf-8")) > MAX_RELATIVE_PATH_BYTES:
        raise ProjectionPathError("relative_path_too_long")
    return validated


# ---------------------------------------------------------------------------
# Managed-root resolution
# ---------------------------------------------------------------------------

def resolve_managed_root(vault_root: Path, managed_dir_name: str) -> Path:
    """Resolve the dedicated managed subtree beneath a configured vault root.

    SUBTREE ownership (docs/plans/plan-m9.md §6.1 / §29 Q2-Q3): M9 owns
    ``<vault_root>/<managed_dir_name>`` and nothing else. The vault root itself,
    ``.obsidian/``, and every other human path stay outside M9's write universe.

    The managed root is validated to be a real, non-symlinked, strict descendant
    of the vault root. It is NOT created here — M9.1 writes nothing.
    """
    if not isinstance(vault_root, Path):
        raise ProjectionPathError("vault_root_not_a_path")
    if not vault_root.is_absolute():
        raise ProjectionPathError("vault_root_not_absolute")
    name = validate_path_component(managed_dir_name)
    if name == OBSIDIAN_CONFIG_DIR or name.casefold() == OBSIDIAN_CONFIG_DIR:
        raise ProjectionPathError("managed_dir_is_obsidian_config")

    candidate = vault_root / name
    real_vault = Path(os.path.realpath(vault_root))
    real_candidate = Path(os.path.realpath(candidate))

    # The managed root may not itself be a symlink: resolving through it would
    # let an attacker (or a careless human) relocate M9's entire write domain
    # outside the vault while every containment check still looked satisfied.
    if candidate.is_symlink():
        raise ProjectionPathError("managed_root_is_symlink")
    if real_candidate == real_vault or real_vault not in real_candidate.parents:
        raise ProjectionPathError("managed_root_escapes_vault")
    if candidate.exists() and not candidate.is_dir():
        raise ProjectionPathError("managed_root_not_a_directory")
    return candidate


# ---------------------------------------------------------------------------
# Containment (physical, symlink-aware, works for not-yet-existing paths)
# ---------------------------------------------------------------------------

def _assert_no_symlink_on_chain(managed_root: Path, target: Path) -> None:
    """Reject if ANY component from the managed root down to the final parent
    is a symlink (docs/plans/plan-m9.md §10.1.4).

    Prevents ``managed_root/Decisions -> /etc`` style escapes, and also refuses
    a symlink that happens to point back inside the managed root: a symlinked
    chain makes "may M9 delete this?" undecidable, so it fails closed.
    """
    if managed_root.is_symlink():
        raise ProjectionPathError("managed_root_is_symlink")
    try:
        relative = target.relative_to(managed_root)
    except ValueError:
        raise ProjectionPathError("target_outside_managed_root") from None
    current = managed_root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ProjectionPathError("symlink_on_path_chain")


def assert_within_managed_root(managed_root: Path, target: Path) -> Path:
    """Return ``target`` iff its PHYSICAL location is inside ``managed_root``.

    Order of checks (each one fails closed):

    1. both paths are absolute;
    2. no symlink anywhere on the chain from the managed root to the final
       parent — checked BEFORE any resolution, so an escape is refused rather
       than followed;
    3. physical containment via ``os.path.realpath``, which resolves symlinks in
       the existing prefix and leaves a not-yet-created tail alone, so the check
       is valid for a file M9 has not written yet;
    4. the target is a strict descendant — the managed root itself is never a
       write target.

    This is deliberately stricter than ``Path.is_relative_to``, which a symlink
    defeats. Rejection always happens BEFORE any destructive operation is
    attempted, because nothing in this module performs one.
    """
    if not isinstance(managed_root, Path) or not isinstance(target, Path):
        raise ProjectionPathError("path_not_a_path")
    if not managed_root.is_absolute():
        raise ProjectionPathError("managed_root_not_absolute")
    if not target.is_absolute():
        raise ProjectionPathError("target_not_absolute")

    _assert_no_symlink_on_chain(managed_root, target)

    real_root = Path(os.path.realpath(managed_root))
    real_target = Path(os.path.realpath(target))
    if real_target == real_root:
        raise ProjectionPathError("target_is_managed_root")
    if real_root not in real_target.parents:
        raise ProjectionPathError("target_outside_managed_root")
    return target


def is_within_managed_root(managed_root: Path, target: Path) -> bool:
    """Boolean form of :func:`assert_within_managed_root` (never raises)."""
    try:
        assert_within_managed_root(managed_root, target)
    except ProjectionPathError:
        return False
    return True


# ---------------------------------------------------------------------------
# Constructive safe-path builders
# ---------------------------------------------------------------------------

def safe_managed_path(managed_root: Path, *components: str) -> Path:
    """Join validated components beneath the managed root and prove containment.

    Every component is validated individually, so an absolute path, a traversal
    fragment, a separator, a drive letter, or a NUL can never enter the join.
    ``managed_root / "../x"`` is impossible by construction rather than by luck.
    """
    validated = _validate_relative_components(components)
    target = managed_root
    for component in validated:
        target = target / component
    return assert_within_managed_root(managed_root, target)


def safe_note_path(
    managed_root: Path,
    *,
    note_type: NoteType | str,
    note_id: str,
    display_title: Optional[str],
    scope: Optional[str] = None,
) -> Path:
    """Build the deterministic, contained path for one projected note.

    ``managed_root / <closed-enum category> / <slugged scope> / <filename>``.

    The category comes from the closed :data:`NOTE_TYPE_DIRECTORIES` map, the
    scope from :func:`slug`, and the filename from the note's stable identity.
    Content-controlled text therefore contributes to the DISPLAY half of a leaf
    filename only: it can never choose the category, escape the scope
    directory, or address a path outside the managed root.

    The path is validated but NOT created — M9.1 writes nothing.
    """
    resolved_type = validate_note_type(note_type)
    category = NOTE_TYPE_DIRECTORIES[resolved_type]
    if category not in MANAGED_CATEGORY_DIRECTORIES:  # pragma: no cover - defensive
        raise ProjectionPathError("unknown_category")
    filename = note_filename(note_id=note_id, display_title=display_title)
    scope_component = slug(scope, fallback="unscoped")
    return safe_managed_path(managed_root, category, scope_component, filename)


def safe_meta_path(managed_root: Path, filename: str) -> Path:
    """Build a contained path inside the reserved ``_meta/`` directory.

    M9.1 defines the location only. Manifest content, incremental behaviour, and
    the projection report belong to M9.4/M9.5 and are not implemented here.
    """
    return safe_managed_path(managed_root, META_DIR_NAME, filename)


# ---------------------------------------------------------------------------
# Ownership-adjacent path predicates (path is NEVER sufficient for ownership)
# ---------------------------------------------------------------------------

def is_obsidian_config_path(vault_root: Path, target: Path) -> bool:
    """True when ``target`` is the operator's ``.obsidian/`` directory or inside it.

    Used to prove M9 stays out of it. ``.obsidian/`` is outside every managed
    root by construction, so this is defense in depth, not the primary guard.
    """
    if not isinstance(vault_root, Path) or not isinstance(target, Path):
        raise ProjectionPathError("path_not_a_path")
    config_dir = Path(os.path.realpath(vault_root / OBSIDIAN_CONFIG_DIR))
    real_target = Path(os.path.realpath(target))
    return real_target == config_dir or config_dir in real_target.parents


def path_ownership_signal(managed_root: Path, target: Path) -> bool:
    """Return ONLY the containment signal of the three-signal ownership test.

    Deliberately named a *signal*, not a decision. Containment alone must never
    authorize an overwrite or a delete: a human note dropped into the managed
    subtree is contained yet human-owned. The frontmatter marker and manifest
    signals (``OwnershipSignals`` in ``contracts``) are equally required.
    """
    return is_within_managed_root(managed_root, target)


def managed_relative_path(managed_root: Path, target: Path) -> str:
    """Return the POSIX-style managed-root-relative path for a contained target.

    Manifest and report entries must be portable and vault-relative; an absolute
    operator path is never recorded in projection output.
    """
    assert_within_managed_root(managed_root, target)
    relative = Path(os.path.realpath(target)).relative_to(
        Path(os.path.realpath(managed_root))
    )
    return str(PurePosixPath(*relative.parts))


__all__ = [
    "MAX_COMPONENT_LENGTH",
    "MAX_RELATIVE_PATH_BYTES",
    "MAX_RELATIVE_DEPTH",
    "OBSIDIAN_CONFIG_DIR",
    "validate_path_component",
    "resolve_managed_root",
    "assert_within_managed_root",
    "is_within_managed_root",
    "safe_managed_path",
    "safe_note_path",
    "safe_meta_path",
    "is_obsidian_config_path",
    "path_ownership_signal",
    "managed_relative_path",
]
