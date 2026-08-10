"""M9.2 — safe atomic writing of rendered notes into the managed root.

Every write goes through the VERIFIED M9.1 path layer before a single byte
touches the filesystem (plan-m9.md §10.1, §25.1):

    fully-rendered note (in memory)
        -> deterministic managed target from closed vocabularies
        -> lexical component validation
        -> symlink-chain rejection
        -> realpath physical containment
        -> collision / ownership check
        -> same-directory temp -> fsync -> os.replace

Both path defenses are kept deliberately: mutation testing during M9.1 proved
the symlink-chain guard and the realpath containment backstop each independently
protect the invariant, and that removing BOTH makes escape possible. Neither is
simplified away here.

**M9.2 never overwrites an existing file.** The create/update/skip/retire
decision engine and the manifest that makes the three-signal ownership test
decidable both belong to M9.4, and human-edit quarantine to M9.5. Until a
manifest exists, no file on disk can be *proven* Zero-Mem-managed, so this
increment takes the only safe position available to it: an existing target whose
bytes already equal the rendered note is skipped as unchanged (nothing is lost),
and any other existing target is reported as a collision and left byte-identical.
Path location alone is never treated as proof of ownership.

Writes are confined to ``managed_root``. Nothing outside it — the vault root,
``.obsidian/``, or any human note — is created, opened for writing, renamed,
truncated, or removed anywhere in this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Optional, Tuple

from .contracts import (
    MANAGED_MARKER_KEY,
    ProjectedNote,
    ProjectionPathError,
    ProjectionVocabularyError,
)
from .identity import note_id_suffix
from .paths import assert_within_managed_root, safe_managed_path

#: Characters of the note-id digest used in the same-directory temp name. Short
#: enough that ``<filename>.tmp-<digest>`` stays inside the M9.1 component-length
#: bound, and unique per note because the filename prefix is already unique.
TEMP_SUFFIX_CHARS: Final[int] = 6

#: Fixed infix of a partially-written note. Same directory (so ``os.replace`` is
#: atomic and same-filesystem) and always inside the managed root.
TEMP_INFIX: Final[str] = ".tmp-"


class WriteStatus(str, Enum):
    """Closed per-note write outcome vocabulary."""

    CREATED = "created"
    SKIPPED_UNCHANGED = "skipped_unchanged"
    SKIPPED_COLLISION = "skipped_collision"
    SKIPPED_DRY_RUN = "skipped_dry_run"
    SKIPPED_UNSAFE_PATH = "skipped_unsafe_path"


@dataclass(frozen=True)
class WriteOutcome:
    """Result of one note write. Sanitized: carries no absolute path.

    ``relative_path`` is managed-root relative and therefore portable and free of
    the operator's directory layout, matching the M9.1 rule that an absolute
    operator path is never recorded in projection output.
    """

    note_id: str
    relative_path: str
    status: WriteStatus
    reason: str = ""

    @property
    def written(self) -> bool:
        return self.status is WriteStatus.CREATED


def _target_path(managed_root: Path, note: ProjectedNote) -> Path:
    """Resolve and fully validate the managed target for one note.

    The relative path was produced by the renderer from closed vocabularies and
    M9.1 identity primitives, but it is re-validated component by component here
    rather than trusted: a note value that reached this function by any other
    route still cannot address a path outside the managed root.
    """
    components = note.relative_path.split("/")
    return safe_managed_path(managed_root, *components)


def _existing_note_is_managed(path: Path, note_id: str) -> bool:
    """Best-effort managed-marker signal for an EXISTING file.

    Returns True only when the file carries both the ownership marker and this
    note's own id in its frontmatter. This is a *signal*, never a decision: the
    manifest signal of the three-signal test does not exist until M9.4, so this
    function's answer is used only to describe a collision, never to authorize
    an overwrite or a deletion.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(4096)
    except OSError:
        return False
    return f"{MANAGED_MARKER_KEY}: true" in head and note_id in head


def write_note(
    managed_root: Path,
    note: ProjectedNote,
    *,
    dry_run: bool = False,
) -> WriteOutcome:
    """Write one fully-rendered note atomically, or explain why it was skipped.

    The note must already be complete: this function renders nothing and never
    streams partially-rendered authoritative state into a final file. On any
    validation failure the temp file is removed and the target is untouched.
    """
    if not isinstance(note, ProjectedNote):
        raise ProjectionVocabularyError("note")
    if not isinstance(managed_root, Path):
        raise ProjectionPathError("managed_root_not_a_path")

    try:
        target = _target_path(managed_root, note)
    except ProjectionPathError as exc:
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_UNSAFE_PATH, exc.reason)

    payload = note.content.encode("utf-8")

    if target.exists() or target.is_symlink():
        # Never overwrite. Identical bytes are a no-op; anything else is a
        # collision the human owns, reported and left exactly as it is.
        try:
            unchanged = target.is_file() and target.read_bytes() == payload
        except OSError:
            unchanged = False
        if unchanged:
            return WriteOutcome(note.note_id, note.relative_path,
                                WriteStatus.SKIPPED_UNCHANGED, "unchanged")
        reason = (
            "existing_managed_note"
            if target.is_file() and _existing_note_is_managed(target, note.note_id)
            else "existing_unmanaged_path"
        )
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_COLLISION, reason)

    if dry_run:
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_DRY_RUN, "dry_run")

    parent = target.parent
    try:
        assert_within_managed_root(managed_root, parent) if parent != managed_root else None
        parent.mkdir(parents=True, exist_ok=True)
        # Re-validate AFTER directory creation: the chain that was safe a moment
        # ago must still be safe now, so a directory swapped for a symlink
        # between the check and the write is refused rather than followed.
        assert_within_managed_root(managed_root, target)
    except ProjectionPathError as exc:
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_UNSAFE_PATH, exc.reason)
    except OSError:
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_UNSAFE_PATH, "directory_unavailable")

    temp_name = f"{target.name}{TEMP_INFIX}{note_id_suffix(note.note_id)[:TEMP_SUFFIX_CHARS]}"
    try:
        temp_path = safe_managed_path(
            managed_root, *(note.relative_path.split("/")[:-1] + [temp_name])
        )
    except ProjectionPathError as exc:
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_UNSAFE_PATH, exc.reason)

    try:
        # O_EXCL: refuse to reuse an existing temp file rather than truncate it.
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temp_path, target)
        _fsync_directory(parent)
    except OSError:
        _remove_quietly(temp_path)
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_UNSAFE_PATH, "write_failed")

    return WriteOutcome(note.note_id, note.relative_path, WriteStatus.CREATED)


def write_notes(
    managed_root: Path,
    notes: Tuple[ProjectedNote, ...],
    *,
    dry_run: bool = False,
) -> Tuple[WriteOutcome, ...]:
    """Write notes in deterministic ``relative_path`` order.

    Ordering is explicit rather than inherited from caller iteration, a set, a
    dict, or a database row order, so the same authorized input always produces
    the same sequence of filesystem operations.
    """
    ordered = sorted(notes, key=lambda note: (note.relative_path, note.note_id))
    return tuple(
        write_note(managed_root, note, dry_run=dry_run) for note in ordered
    )


def _fsync_directory(directory: Path) -> None:
    """Fsync a directory so the rename is durable. Never fatal if unsupported."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _remove_quietly(path: Path) -> None:
    """Remove a temp file M9 itself just created inside the managed root."""
    try:
        os.unlink(path)
    except OSError:
        pass


__all__ = [
    "TEMP_INFIX",
    "TEMP_SUFFIX_CHARS",
    "WriteStatus",
    "WriteOutcome",
    "write_note",
    "write_notes",
]
