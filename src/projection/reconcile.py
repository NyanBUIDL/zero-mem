"""M9.4 — deterministic incremental reconcile + safe stale retirement.

This is the engine that turns the rendered DESIRED set and the loaded PAST
manifest into a minimal, safe set of filesystem operations, then records the
resulting manifest. It is the single place where the create/update/skip/retire
decision (plan-m9.md §14.3, §14.5) is made, and the only place where
:func:`~src.projection.writer.overwrite_note` and
:func:`~src.projection.writer.retire_note` are ever called.

**Authorization always wins over the old manifest** (§22). The desired set is
produced upstream by the closed M9.2 pipeline (M5 authorization -> M6.6
resource_type -> M7 sensitivity/lifecycle eligibility -> render). The manifest
is consulted ONLY for the ownership proof required to overwrite a changed file
or to retire a stale one. Nothing in this module ever treats "present in the old
manifest" as authorization, visibility, or truth.

**Three-signal ownership (§12.1) is the ONLY gate to a destructive or
overwriting write.** All three must hold or the operation is refused:

1. *manifest* — the old manifest lists this exact ``note_id``;
2. *containment* — the resolved managed path is physically inside the managed
   root (verified by the closed M9.1 pipeline, never by string prefix);
3. *frontmatter marker* — the on-disk file carries the Zero-Mem managed marker
   plus this exact ``note_id`` in its frontmatter.

The manifest supplies at most one signal. A tampered, restored, or stale
manifest can therefore never, on its own, authorize the deletion or overwrite of
a file whose other signals disagree.

**Human content is never destroyed** (§19). A managed note whose current on-disk
bytes no longer match its fingerprint, and whose edit state cannot be proven
safe, is reported as a collision/``human_modified`` and left byte-for-byte
intact. Full human-edit quarantine is M9.5's job; M9.4 only fails safe here.

No wall-clock, no run id, no ``hash()``, no randomness, no filesystem ordering
affects any decision. The manifest is serialized through
:class:`~src.projection.manifest.ProjectionManifest`, which is byte-deterministic
on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Iterable, Mapping, Optional, Tuple

from .contracts import (
    MANAGED_MARKER_KEY,
    NoteStatus,
    ProjectedNote,
    ProjectionPathError,
    ProjectionVocabularyError,
)
from .identity import content_fingerprint
from .manifest import (
    ManifestEntry,
    ManifestError,
    ProjectionManifest,
    load_manifest,
    store_manifest,
)
from .writer import (
    WriteOutcome,
    WriteStatus,
    overwrite_note,
    retire_note,
    write_note,
)

#: Read that many bytes of the frontmatter to look for the ownership marker.
_FRONTMATTER_HEAD_LIMIT: Final[int] = 4096


def _on_disk_marked_managed(path: Path, note_id: str) -> bool:
    """Third ownership signal: the file carries the marker + this note_id.

    A defensive read of the frontmatter head only. A missing, unreadable, or
    marker-less file is simply "not proven": the caller then refuses the
    destructive action rather than assuming. The check is rejection-biased.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(_FRONTMATTER_HEAD_LIMIT)
    except OSError:
        return False
    return f"{MANAGED_MARKER_KEY}: true" in head and note_id in head


def _note_index(notes: Iterable[ProjectedNote]) -> Mapping[str, ProjectedNote]:
    indexed: dict[str, ProjectedNote] = {}
    for note in notes:
        indexed[note.note_id] = note  # note_ids are unique by construction
    return indexed


# ---------------------------------------------------------------------------
# Reconcile result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconcileResult:
    """The full deterministic outcome of one reconcile pass (plan-m9.md §14.5).

    ``written`` counts only bytes-actually-changed operations (CREATED + UPDATED
    + RETIRED). ``skipped`` counts the safe no-ops. This split is what proves the
    zero-write rerun invariant: on an unchanged second run both counters land on
    exactly the writes the prior run already produced, and any genuine rerun
    reports ``written == 0``.
    """

    writes: Tuple[WriteOutcome, ...] = ()
    manifest_stored: bool = False
    manifest: ProjectionManifest = field(default_factory=ProjectionManifest)
    notes: Tuple[ProjectedNote, ...] = ()

    @property
    def written(self) -> int:
        return sum(
            1 for outcome in self.writes
            if outcome.status in (
                WriteStatus.CREATED,
                WriteStatus.UPDATED,
                WriteStatus.RETIRED,
            )
        )

    @property
    def skipped(self) -> int:
        return sum(
            1 for outcome in self.writes
            if outcome.status is not WriteStatus.CREATED
            and outcome.status is not WriteStatus.UPDATED
            and outcome.status is not WriteStatus.RETIRED
        )

    @property
    def created(self) -> int:
        return sum(1 for outcome in self.writes if outcome.status is WriteStatus.CREATED)

    @property
    def updated(self) -> int:
        return sum(1 for outcome in self.writes if outcome.status is WriteStatus.UPDATED)

    @property
    def retired(self) -> int:
        return sum(1 for outcome in self.writes if outcome.status is WriteStatus.RETIRED)

    @property
    def note_writes(self) -> int:
        """FileSystem-changing note operations (create + update + retire)."""
        return self.written


# ---------------------------------------------------------------------------
# Core reconcile
# ---------------------------------------------------------------------------

def reconcile(
    managed_root: Path,
    desired_notes: Iterable[ProjectedNote],
    *,
    prior_manifest: Optional[ProjectionManifest] = None,
    managed_dir_name: str = "",
    dry_run: bool = False,
) -> ReconcileResult:
    """Apply the deterministic desired set against the managed tree, safely.

    Steps, each order-independent of any non-deterministic input:

    1. Load the past manifest (or empty) — DATA only, never authority.
    2. For each desired note: create if absent; overwrite if present + proven
       managed + fingerprint changed; skip if fingerprint unchanged; refuse a
       silent overwrite if ownership cannot be proven (human_modified /
       unsafe_ownership).
    3. For each previously-managed active note no longer desired: retire only
       when all three ownership signals hold; otherwise leave it untouched and
       record the safe outcome.
    4. Serialize the resulting manifest (desired entries as CURRENT/recorded
       status, still-active prior entries unchanged, retired entries as RETIRED)
       and write it LAST, atomically, only if its bytes changed.

    Authorization of *what* is desired is decided upstream in M9.2; this function
    never reintroduces a resource the current authorization rejected.
    """
    if prior_manifest is None:
        prior_manifest = load_manifest(
            managed_root, managed_dir_name=managed_dir_name
        )
    if not isinstance(prior_manifest, ProjectionManifest):
        raise ManifestError("manifest")

    outcomes: list[WriteOutcome] = []
    desired_index = _note_index(desired_notes)
    prior_by_id = prior_manifest.by_note_id()

    # -- 2. reconcile each desired note -----------------------------------
    for note in sorted(desired_notes, key=lambda item: (item.relative_path, item.note_id)):
        prior_entry = prior_by_id.get(note.note_id)
        # Signal 1 (manifest): does the old manifest list this exact note_id?
        listed = prior_entry is not None
        outcome = _reconcile_desired(
            managed_root, note, prior_entry=prior_entry, listed=listed,
            dry_run=dry_run,
        )
        outcomes.append(outcome)

    # -- 3. retire previously-managed notes no longer desired, OR moved ----
    retired_entries: list[ManifestEntry] = []
    desired_ids = set(desired_index)
    for entry in prior_manifest.active_entries():
        desired_now = desired_index.get(entry.note_id)
        if desired_now is None:
            # No longer desired at all -> retire the stale file.
            outcome = _retire_stale(managed_root, entry, dry_run=dry_run)
            _record_retire(outcome, entry, retired_entries, outcomes, dry_run)
            continue
        if desired_now.relative_path != entry.relative_path:
            # Same note_id, but its deterministic path drifted (e.g. the
            # rendered filename embeds content that changed). The OLD file is
            # now stale and must be retired so the tree stays byte-clean and the
            # old orphan does not linger. Three-signal proof uses the OLD entry;
            # the new path is created by the desired loop.
            old_entry = ManifestEntry(
                note_id=entry.note_id,
                note_type=entry.note_type,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
                project_id=entry.project_id,
                relative_path=entry.relative_path,
                content_fingerprint=entry.content_fingerprint,
                source_trace_ids=entry.source_trace_ids,
                status=NoteStatus.CURRENT,
            )
            outcome = _retire_stale(managed_root, old_entry, dry_run=dry_run)
            _record_retire(outcome, old_entry, retired_entries, outcomes, dry_run)

    # -- 4. build + write the resulting manifest (written LAST) ----------
    new_manifest = ProjectionManifest.from_notes(
        tuple(desired_notes),
        managed_dir_name=managed_dir_name,
        projection_version=prior_manifest.projection_version,
        retired=tuple(retired_entries),
    )
    manifest_stored = store_manifest(managed_root, new_manifest, dry_run=dry_run)
    return ReconcileResult(
        writes=tuple(outcomes),
        manifest_stored=manifest_stored,
        manifest=new_manifest,
        notes=tuple(desired_notes),
    )


def _record_retire(outcome, entry, retired_entries, outcomes, dry_run):
    """Append a retire outcome and, on success, a RETIRED manifest record.

    The dry_run branch is intentionally folded in: a dry retire still records a
    RETIRED intent so the serialized manifest reflects the planned state, while
    no bytes are touched on disk.
    """
    outcomes.append(outcome)
    if outcome.status is WriteStatus.RETIRED:
        retired_entries.append(
            ManifestEntry(
                note_id=entry.note_id,
                note_type=entry.note_type,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
                project_id=entry.project_id,
                relative_path=entry.relative_path,
                content_fingerprint=entry.content_fingerprint,
                source_trace_ids=entry.source_trace_ids,
                status=NoteStatus.RETIRED,
            )
        )


def _reconcile_desired(
    managed_root: Path,
    note: ProjectedNote,
    *,
    prior_entry: Optional[ManifestEntry],
    listed: bool,
    dry_run: bool,
) -> WriteOutcome:
    """Create, update-skip, overwrite, or refuse for one desired note.

    The decision tree (plan-m9.md §14.3):

    absent on disk
        -> CREATE (via the M9.2 writer; never overwrites anything).

    present + bytes equal rendered
        -> SKIPPED_UNCHANGED (zero bytes written).

    present + bytes differ + ALL three ownership signals hold
        -> UPDATE via the gated overwrite path.

    present + bytes differ + ownership not provable
        -> SKIPPED_HUMAN_MODIFIED / SKIPPED_UNSAFE_OWNERSHIP; the file is left
           byte-for-byte intact and M9.5 resolves the actual edit later.
    """
    path = managed_root / note.relative_path
    if not (path.exists() or path.is_symlink()):
        return write_note(managed_root, note, dry_run=dry_run)

    # Byte-equal is always a no-op, regardless of ownership. A human who
    # re-saved the exact same content still owns it, but identical bytes mean
    # there is nothing to change, so nothing is written and nothing is claimed.
    try:
        unchanged = path.is_file() and path.read_bytes() == note.content.encode("utf-8")
    except OSError:
        unchanged = False
    if unchanged:
        return WriteOutcome(note.note_id, note.relative_path,
                            WriteStatus.SKIPPED_UNCHANGED, "unchanged")

    # Bytes differ. Ownership must be proven before any overwrite.
    # Signal 2 (containment): resolved path is physically inside the root.
    # Signal 3 (frontmatter): the file carries the marker + this note_id.
    contained = True
    try:
        from .paths import assert_within_managed_root
        assert_within_managed_root(managed_root, path)
    except Exception:
        contained = False
    owned = (
        listed
        and contained
        and _on_disk_marked_managed(path, note.note_id)
    )
    if not owned:
        # Fail safe: never silently overwrite a file whose provenance is
        # uncertain. M9.5 will classify the human edit; here we only refuse.
        # The marker is present but the manifest listing is absent -> the file
        # matches the layout of a managed note yet is NOT one we can claim, so
        # it is treated as a human-owned/foreign file.
        reason = (
            "human_modified"
            if _on_disk_marked_managed(path, note.note_id)
            else "unsafe_ownership"
        )
        return WriteOutcome(
            note.note_id, note.relative_path,
            WriteStatus.SKIPPED_HUMAN_MODIFIED
            if reason == "human_modified"
            else WriteStatus.SKIPPED_UNSAFE_OWNERSHIP,
            reason,
        )

    # All three ownership signals hold. But a safe UPDATE must additionally
    # prove the human has NOT edited this file since the last projection: the
    # on-disk content fingerprint must still equal what the prior manifest
    # recorded. If it differs, the human changed a managed note; M9.4 must NOT
    # silently overwrite that edit (plan-m9.md §16.5 / §19). M9.5 owns the real
    # edit-resolution workflow. We record and leave the bytes intact.
    if prior_entry is not None:
        try:
            on_disk_fingerprint = content_fingerprint(path.read_text())
        except OSError:
            on_disk_fingerprint = None
        if on_disk_fingerprint != prior_entry.content_fingerprint:
            return WriteOutcome(
                note.note_id, note.relative_path,
                WriteStatus.SKIPPED_HUMAN_MODIFIED, "human_edited_managed_note",
            )

    return overwrite_note(
        managed_root, note, force_managed=True, dry_run=dry_run
    )


def _retire_stale(
    managed_root: Path,
    entry: ManifestEntry,
    *,
    dry_run: bool,
) -> WriteOutcome:
    """Retire a previously-managed note no longer in the desired set.

    The three-signal ownership rule (§12.1) is applied here exactly. All three
    must hold or the file is preserved untouched and a safe outcome recorded.

    Signal 1 (manifest): ``entry`` is itself a manifest entry — the manifest
        lists this note_id, so the projector once claimed it.
    Signal 2 (containment): the resolved target is physically inside the root.
    Signal 3 (frontmatter): the on-disk file carries the marker + this note_id.

    The manifest can supply at most signal 1; containment and the marker are
    independently re-proven here, so a tampered/restored manifest cannot by
    itself authorize a deletion.
    """
    from .manifest import resolve_entry_path
    try:
        path = resolve_entry_path(managed_root, entry)
    except (ProjectionPathError, ManifestError):
        return WriteOutcome(entry.note_id, entry.relative_path,
                            WriteStatus.SKIPPED_UNSAFE_OWNERSHIP, "bad_path")

    if not (path.exists() or path.is_symlink()):
        # File already gone (operator or prior run removed it). Nothing to do.
        return WriteOutcome(entry.note_id, entry.relative_path,
                            WriteStatus.SKIPPED_UNCHANGED, "absent")

    owned = _on_disk_marked_managed(path, entry.note_id)
    if not owned:
        # Ownership unproven: preserve the file, never delete it.
        return WriteOutcome(entry.note_id, entry.relative_path,
                            WriteStatus.SKIPPED_UNSAFE_OWNERSHIP,
                            "ownership_unproven")

    return retire_note(managed_root, path, force_managed=True, dry_run=dry_run)


def rebuild(
    managed_root: Path,
    desired_notes: Tuple[ProjectedNote, ...],
    *,
    managed_dir_name: str = "",
    dry_run: bool = False,
) -> ReconcileResult:
    """Deterministic full reconcile from an authoritative desired set.

    Equivalent to :func:`reconcile` with no prior manifest: a clean run, a
    rebuild from empty, and a re-run after manifest deletion all share this path.
    The projector never needs to know which case it is — the manifest is derived
    either way (§14.4).
    """
    return reconcile(
        managed_root,
        desired_notes,
        prior_manifest=ProjectionManifest(
            managed_dir_name=managed_dir_name,
            projection_version=_projection_version(),
            entries=(),
        ),
        managed_dir_name=managed_dir_name,
        dry_run=dry_run,
    )


def _projection_version() -> int:
    from .contracts import PROJECTION_VERSION
    return PROJECTION_VERSION


__all__ = [
    "ReconcileResult",
    "reconcile",
    "rebuild",
    "load_manifest",
    "store_manifest",
]

