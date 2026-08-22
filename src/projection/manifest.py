"""M9.4 — the deterministic projection manifest.

``managed_root/_meta/manifest.json`` (docs/plans/plan-m9.md §15.1, §29 Q7) is the ONLY
place projection lifecycle state lives. It is a plain file inside the vault, not
a SQLite table, because it must live and die with the vault: a table would
describe a filesystem that no longer matches the moment the vault is moved,
deleted, or restored from the operator's backup. Schema stays at v9 — no
migration, no ``projection_links``/``projection_manifest``/``projection_state``
table (docs/plans/plan-m9.md §23).

**The manifest is derived, rebuildable, and NOT authority** (§15.2). It records
what was projected. It never establishes truth, authorization, verification,
lifecycle, supersession, or project state. Deleting it destroys nothing
canonical: re-running the projector reproduces it byte-for-byte from
authoritative state plus the deterministic renderer. A note absent from the
manifest is *unmanaged* — never "unauthorized".

Two rules make that safe rather than merely stated:

1. **Manifest content is DATA, never a capability.** Every entry is re-validated
   through the closed M9.1 vocabularies on load, and every path it names is
   re-validated through the VERIFIED M9.1 safety pipeline (lexical containment ->
   symlink-chain rejection -> realpath containment) before any filesystem
   operation. A manifest path never reaches ``unlink`` directly.
2. **The manifest supplies exactly ONE of three ownership signals** (§12.1). It
   can never authorize a delete on its own, so a stale, tampered, or restored
   manifest cannot make M9 destroy a human file.

Determinism (§16.2): sorted keys, notes ordered by ``note_id``, ASCII-safe JSON,
LF newlines, one trailing newline, no wall clock, no run id, no absolute path,
no randomness, no ``hash()``. Equivalent input in any insertion order serializes
to identical bytes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Final, Iterable, Mapping, Optional, Tuple

from .contracts import (
    META_DIR_NAME,
    PROJECTION_VERSION,
    NoteStatus,
    NoteType,
    ProjectedNote,
    ProjectionPathError,
    ProjectionVocabularyError,
    validate_note_status,
    validate_note_type,
    validate_resource_type,
)
from .identity import validate_note_id
from .paths import (
    assert_within_managed_root,
    safe_managed_path,
    safe_meta_path,
    validate_path_component,
)

#: Manifest envelope-format version (docs/plans/plan-m9.md §15.1). Distinct from
#: ``PROJECTION_VERSION``: this versions the JSON container, that versions the
#: rendered-note contract. Neither is derived from a clock or a run counter.
MANIFEST_VERSION: Final[int] = 1

#: Manifest filename inside the reserved ``_meta/`` directory.
MANIFEST_FILENAME: Final[str] = "manifest.json"

#: Managed-root-relative manifest location, for reports and tests.
MANIFEST_RELATIVE_PATH: Final[str] = f"{META_DIR_NAME}/{MANIFEST_FILENAME}"

#: Required envelope keys. These MUST be present in every valid manifest,
#: including every manifest M9.4 produced before M9.5 existed. They alone drive
#: the ``missing`` check in :meth:`ProjectionManifest.from_json`.
REQUIRED_ENVELOPE_KEYS: Final[Tuple[str, ...]] = (
    "manifest_version",
    "projection_version",
    "managed_dir_name",
    "notes",
)

#: Complete set of KNOWN envelope keys. Used only to REJECT unknown keys (a
#: tampered manifest smuggling state past the validator fails closed); it is
#: NOT used to require presence. ``edit_conflicts`` is an optional M9.5 channel:
#: a manifest written before M9.5 simply omits it and loads unchanged
#: (backward-safe), and a freshly written one emits an empty list so the
#: conflict record travels WITH the manifest (one file to trust, one proof to
#: verify) rather than as a separate sidecar.
ENVELOPE_KEYS: Final[Tuple[str, ...]] = REQUIRED_ENVELOPE_KEYS + ("edit_conflicts",)

#: Closed per-entry key set, in the fixed serialization order of §15.1.
ENTRY_KEYS: Final[Tuple[str, ...]] = (
    "note_id",
    "note_type",
    "resource_type",
    "resource_id",
    "project_id",
    "relative_path",
    "content_fingerprint",
    "source_trace_ids",
    "status",
)

#: OPTIONAL per-entry keys (M9.5). An optional key is emitted ONLY when it
#: carries a value, so a manifest written before M9.5 still loads unchanged and
#: a ``current``/``retired`` entry serializes byte-identically to M9.4. The set
#: stays closed: anything outside ``ENTRY_KEYS | OPTIONAL_ENTRY_KEYS`` is still
#: rejected, so a tampered manifest cannot smuggle state past the validator.
#:
#: ``observed_fingerprint`` records the fingerprint of the bytes a human left on
#: disk for an ``edit_conflict``/``human_modified`` note (docs/plans/plan-m9.md §13.3 step
#: 3, "with both fingerprints"). It is a hash, never content: it explains that
#: the file diverged without revealing a single byte of either version.
OPTIONAL_ENTRY_KEYS: Final[Tuple[str, ...]] = ("observed_fingerprint",)


#: Exact expected shape of a ``sha256:<64 lowercase hex>`` fingerprint.
_FINGERPRINT_PREFIX: Final[str] = "sha256:"
_FINGERPRINT_HEX_CHARS: Final[int] = 64
_HEX_ALPHABET: Final[frozenset[str]] = frozenset("0123456789abcdef")


class ManifestError(ProjectionVocabularyError):
    """A manifest failed validation. Sanitized: names the failed field only.

    Subclasses :class:`ProjectionVocabularyError` so existing fail-closed
    handlers catch it without change; the offending value, path, or content is
    never echoed.
    """


def validate_fingerprint(value: Any) -> str:
    """Return ``value`` iff it is a well-formed content fingerprint.

    Shape is checked structurally rather than trusted: a malformed fingerprint
    from a tampered manifest must never be comparable to a real one, and must
    never be accepted as proof that an on-disk file is unchanged.
    """
    if not isinstance(value, str) or not value.startswith(_FINGERPRINT_PREFIX):
        raise ManifestError("content_fingerprint")
    digest = value[len(_FINGERPRINT_PREFIX):]
    if len(digest) != _FINGERPRINT_HEX_CHARS:
        raise ManifestError("content_fingerprint")
    if any(character not in _HEX_ALPHABET for character in digest):
        raise ManifestError("content_fingerprint")
    return value


def validate_manifest_relative_path(value: Any) -> str:
    """Validate a managed-root-relative path loaded FROM a manifest.

    Runs the same closed lexical rules the writer uses (M9.1
    ``validate_path_component``), so a traversal fragment, an absolute path, a
    backslash, a NUL, a drive letter, a reserved device name, or an over-deep
    path is rejected before it can ever be joined to the managed root. This is
    the LEXICAL stage only; physical containment is re-proved separately at the
    moment of use by :func:`resolve_entry_path`.
    """
    if not isinstance(value, str) or not value:
        raise ManifestError("relative_path")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise ManifestError("relative_path")
    components = value.split("/")
    if not components:
        raise ManifestError("relative_path")
    try:
        for component in components:
            validate_path_component(component)
    except ProjectionPathError:
        raise ManifestError("relative_path") from None
    return value


# ---------------------------------------------------------------------------
# Manifest entry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ManifestEntry:
    """One managed note as recorded in the manifest (docs/plans/plan-m9.md §15.1).

    Carries the minimum needed to make the create/update/skip/retire decision
    and to satisfy the manifest signal of the three-signal ownership test:
    identity, managed-relative location, content fingerprint, authoritative
    source identity, and projection status. Deliberately absent: any mutable
    runtime metadata (mtime, run id, generation timestamp, write counter),
    which would break determinism without informing a single decision.
    """

    note_id: str
    note_type: NoteType
    resource_type: str
    resource_id: str
    project_id: Optional[str]
    relative_path: str
    content_fingerprint: str
    source_trace_ids: Tuple[str, ...] = ()
    status: NoteStatus = NoteStatus.CURRENT
    observed_fingerprint: Optional[str] = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "note_id", validate_note_id(self.note_id))
            object.__setattr__(self, "note_type", validate_note_type(self.note_type))
            object.__setattr__(
                self, "resource_type", validate_resource_type(self.resource_type)
            )
            object.__setattr__(self, "status", validate_note_status(self.status))
        except ProjectionVocabularyError as exc:
            raise ManifestError(getattr(exc, "field_name", "entry")) from None
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ManifestError("resource_id")
        if self.project_id is not None and (
            not isinstance(self.project_id, str) or not self.project_id.strip()
        ):
            raise ManifestError("project_id")
        object.__setattr__(
            self, "relative_path", validate_manifest_relative_path(self.relative_path)
        )
        object.__setattr__(
            self, "content_fingerprint", validate_fingerprint(self.content_fingerprint)
        )
        trace_ids = tuple(self.source_trace_ids or ())
        for trace_id in trace_ids:
            if not isinstance(trace_id, str) or not trace_id.strip():
                raise ManifestError("source_trace_ids")
        object.__setattr__(self, "source_trace_ids", trace_ids)
        if self.observed_fingerprint is not None:
            object.__setattr__(
                self,
                "observed_fingerprint",
                validate_fingerprint(self.observed_fingerprint),
            )

    @property
    def is_active(self) -> bool:
        """True when this entry describes a file that should exist on disk.

        ``retired`` is the only status whose file is expected absent. The
        human-boundary statuses (``human_modified``, ``edit_conflict``) still
        describe a present file, and the human's bytes are authoritative for it.
        """
        return self.status is not NoteStatus.RETIRED

    @property
    def casefolded_path(self) -> str:
        """Path key for case-collision detection (docs/plans/plan-m9.md §10.1 item 7)."""
        return self.relative_path.casefold()

    def to_json(self) -> Dict[str, Any]:
        """Serialize in the fixed §15.1 key order. No absolute path, no clock.

        Optional M9.5 keys are emitted only when populated, so a ``current``
        entry is byte-identical to what M9.4 produced and the deterministic
        rebuild/zero-write invariants are untouched.
        """
        payload = {
            "note_id": self.note_id,
            "note_type": self.note_type.value,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "project_id": self.project_id,
            "relative_path": self.relative_path,
            "content_fingerprint": self.content_fingerprint,
            "source_trace_ids": list(self.source_trace_ids),
            "status": self.status.value,
        }
        if self.observed_fingerprint is not None:
            payload["observed_fingerprint"] = self.observed_fingerprint
        return payload

    @classmethod
    def from_json(cls, payload: Any) -> "ManifestEntry":
        """Rebuild one entry from untrusted JSON, failing closed on any surprise.

        A missing key, an unexpected key, or a wrong type is a hard failure: an
        entry that cannot be fully validated must never participate in an
        ownership decision, because a partially-understood entry is exactly how
        a tampered manifest would try to authorize a deletion. Optional M9.5
        keys are permitted but still closed-set: an unknown key is refused.
        """
        if not isinstance(payload, dict):
            raise ManifestError("entry")
        unexpected = set(payload) - set(ENTRY_KEYS) - set(OPTIONAL_ENTRY_KEYS)
        if unexpected:
            raise ManifestError("entry_key")
        missing = set(ENTRY_KEYS) - set(payload)
        if missing:
            raise ManifestError("entry_key")
        trace_ids = payload["source_trace_ids"]
        if not isinstance(trace_ids, list):
            raise ManifestError("source_trace_ids")
        return cls(
            note_id=payload["note_id"],
            note_type=payload["note_type"],
            resource_type=payload["resource_type"],
            resource_id=payload["resource_id"],
            project_id=payload["project_id"],
            relative_path=payload["relative_path"],
            content_fingerprint=payload["content_fingerprint"],
            source_trace_ids=tuple(trace_ids),
            status=payload["status"],
            observed_fingerprint=payload.get("observed_fingerprint"),
        )

    @classmethod
    def from_note(cls, note: ProjectedNote,
                  *, status: NoteStatus = NoteStatus.CURRENT,
                  observed_fingerprint: Optional[str] = None,
                  content_fingerprint: Optional[str] = None) -> "ManifestEntry":

        """Build an entry from a rendered note.

        The note already carries the authoritative identity the renderer used to
        derive its ``note_id``, so the entry cannot disagree with the file. A
        note lacking that identity is refused rather than back-filled by parsing
        generated Markdown — inferring source identity from rendered text is
        exactly the "projection becomes its own source" inversion M9 forbids.

        ``content_fingerprint`` (M9.5) overrides the fingerprint recorded for the
        entry. For a human-divergent note this MUST stay the last fingerprint M9
        actually wrote to the human's file (NOT the newly-desired content), so a
        later run still detects the divergence. The default (note's own
        fingerprint) is correct for every unchanged/created/updated note.
        """
        if not isinstance(note, ProjectedNote):
            raise ManifestError("note")
        if note.resource_type is None or note.resource_id is None:
            raise ManifestError("note_source_identity")
        return cls(
            note_id=note.note_id,
            note_type=note.note_type,
            resource_type=note.resource_type,
            resource_id=note.resource_id,
            project_id=note.project_id,
            relative_path=note.relative_path,
            content_fingerprint=content_fingerprint
            if content_fingerprint is not None
            else note.content_fingerprint,
            source_trace_ids=note.source_trace_ids,
            status=status,
            observed_fingerprint=observed_fingerprint,
        )



# ---------------------------------------------------------------------------
# Edit conflict record (M9.5)
# ---------------------------------------------------------------------------

#: Closed key set for a single M9.5 edit-conflict record (docs/plans/plan-m9.md §13.3).
#: ``resolved`` is the only optional key; everything else is required, so a
#: tampered or partially-understood conflict record is refused rather than
#: trusted to authorize anything.
EDIT_CONFLICT_KEYS: Final[Tuple[str, ...]] = (
    "note_id",
    "note_type",
    "relative_path",
    "human_fingerprint",
    "recorded_fingerprint",
    "desired_fingerprint",
    "human_modified",
    "desired_changed",
    "resolved",
)

#: Keys that MUST be present in an edit-conflict record. ``resolved`` is omitted
#: above so a pre-M9.5-shaped record (there were none) or a minimal one still
#: loads; it always defaults to ``False``.
EDIT_CONFLICT_REQUIRED_KEYS: Final[Tuple[str, ...]] = (
    "note_id",
    "note_type",
    "relative_path",
    "human_fingerprint",
    "recorded_fingerprint",
    "desired_fingerprint",
    "human_modified",
    "desired_changed",
)


@dataclass(frozen=True)
class EditConflict:
    """One deterministic, unresolved human-edit/projection conflict.

    The record carries ONLY closed status codes and deterministic content
    FINGERPRINTS (hashes of bytes, never the bytes themselves). That is what
    makes it safe to store in the manifest, surface in a projection report, or
    carry in an exception: when authorization or sensitivity no longer permits
    the source material, this record still reveals nothing about it
    (docs/plans/plan-m9.md §11.3, §13.3 step 3 "with both fingerprints").

    **Resolution is always a human action.** M9.5 never resolves a conflict: it
    records that one exists and, when the desired source also changed, writes
    the new generated content to a deterministic sibling file while leaving the
    human's file byte-for-byte intact. Exactly one conflict exists per
    ``note_id`` (``conflict_id`` is the ``note_id``), so repeated runs can never
    accumulate numbered duplicates.
    """

    note_id: str
    note_type: NoteType
    relative_path: str
    human_fingerprint: str
    recorded_fingerprint: str
    desired_fingerprint: str
    human_modified: bool = False
    desired_changed: bool = False
    resolved: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "note_id", validate_note_id(self.note_id))
        object.__setattr__(self, "note_type", validate_note_type(self.note_type))
        object.__setattr__(
            self, "relative_path", validate_manifest_relative_path(self.relative_path)
        )
        object.__setattr__(
            self, "human_fingerprint", validate_fingerprint(self.human_fingerprint)
        )
        object.__setattr__(
            self, "recorded_fingerprint", validate_fingerprint(self.recorded_fingerprint)
        )
        object.__setattr__(
            self, "desired_fingerprint", validate_fingerprint(self.desired_fingerprint)
        )
        if not isinstance(self.human_modified, bool):
            raise ManifestError("human_modified")
        if not isinstance(self.desired_changed, bool):
            raise ManifestError("desired_changed")
        if not isinstance(self.resolved, bool):
            raise ManifestError("resolved")

    @property
    def conflict_id(self) -> str:
        """Stable deterministic identity (no clock, no uuid, no run id)."""
        return self.note_id

    def to_json(self) -> Dict[str, Any]:
        return {
            "note_id": self.note_id,
            "note_type": self.note_type.value,
            "relative_path": self.relative_path,
            "human_fingerprint": self.human_fingerprint,
            "recorded_fingerprint": self.recorded_fingerprint,
            "desired_fingerprint": self.desired_fingerprint,
            "human_modified": self.human_modified,
            "desired_changed": self.desired_changed,
            "resolved": self.resolved,
        }

    @classmethod
    def from_json(cls, payload: Any) -> "EditConflict":
        if not isinstance(payload, dict):
            raise ManifestError("edit_conflict")
        unexpected = set(payload) - set(EDIT_CONFLICT_KEYS)
        if unexpected:
            raise ManifestError("edit_conflict_key")
        missing = set(EDIT_CONFLICT_REQUIRED_KEYS) - set(payload)
        if missing:
            raise ManifestError("edit_conflict_key")
        return cls(
            note_id=payload["note_id"],
            note_type=payload["note_type"],
            relative_path=payload["relative_path"],
            human_fingerprint=payload["human_fingerprint"],
            recorded_fingerprint=payload["recorded_fingerprint"],
            desired_fingerprint=payload["desired_fingerprint"],
            human_modified=payload["human_modified"],
            desired_changed=payload["desired_changed"],
            resolved=payload.get("resolved", False),
        )


# ---------------------------------------------------------------------------
# Manifest envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProjectionManifest:
    """The whole deterministic manifest (docs/plans/plan-m9.md §15.1).

    Entries are stored in a canonical order derived from ``note_id`` alone, so
    two runs that discovered the same notes in opposite orders serialize to
    identical bytes. Duplicate identities and duplicate (casefolded) paths are
    rejected at construction: two notes claiming one identity or one file is a
    projector bug, and silently picking a winner would be exactly the kind of
    invisible resolution this system forbids everywhere else.
    """

    projection_version: int = PROJECTION_VERSION
    managed_dir_name: str = ""
    entries: Tuple[ManifestEntry, ...] = ()
    manifest_version: int = MANIFEST_VERSION
    edit_conflicts: Tuple["EditConflict", ...] = ()

    def __post_init__(self) -> None:
        for name in ("manifest_version", "projection_version"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ManifestError(name)
        if not isinstance(self.managed_dir_name, str):
            raise ManifestError("managed_dir_name")
        if self.managed_dir_name:
            try:
                validate_path_component(self.managed_dir_name)
            except ProjectionPathError:
                raise ManifestError("managed_dir_name") from None

        entries = tuple(self.entries or ())
        for entry in entries:
            if not isinstance(entry, ManifestEntry):
                raise ManifestError("entry")
        seen_active_ids: set[str] = set()
        seen_active_paths: set[str] = set()
        for entry in entries:
            # A RETIRED entry is historical state and may legitimately share a
            # note_id with a CURRENT one (the path-drift / safe-retirement case:
            # the old file is retired, the new file carries the same identity).
            # Only ACTIVE (non-retired) entries are constrained to be unique in
            # id and managed path; two active notes claiming one id or one file
            # is a projector bug and is rejected rather than silently resolved.
            if not entry.is_active:
                continue
            if entry.note_id in seen_active_ids:
                raise ManifestError("duplicate_note_id")
            seen_active_ids.add(entry.note_id)
            # Casefolded, because macOS/Windows would collapse two paths that
            # differ only by case onto one file and silently overwrite one note.
            if entry.casefolded_path in seen_active_paths:
                raise ManifestError("duplicate_relative_path")
            seen_active_paths.add(entry.casefolded_path)
        # Canonical order: note_id alone is unique and stable, so ordering never
        # depends on insertion, a set, a dict, or a database row order.
        object.__setattr__(
            self, "entries", tuple(sorted(entries, key=lambda item: item.note_id))
        )

        # Edit conflicts: validated closed records, deduped by note_id (every
        # conflict is keyed on exactly one note_id, so two records for the same
        # note are a projector bug and are rejected rather than silently merged).
        raw_conflicts = tuple(self.edit_conflicts or ())
        for conflict in raw_conflicts:
            if not isinstance(conflict, EditConflict):
                raise ManifestError("edit_conflict")
        seen_conflict_ids: set[str] = set()
        for conflict in raw_conflicts:
            if conflict.conflict_id in seen_conflict_ids:
                raise ManifestError("duplicate_edit_conflict")
            seen_conflict_ids.add(conflict.conflict_id)
        # Deterministic order by note_id — never run order, a dict, or a list.
        object.__setattr__(
            self,
            "edit_conflicts",
            tuple(sorted(raw_conflicts, key=lambda item: item.note_id)),
        )

    # -- lookups (pure; never a decision) ----------------------------------

    def by_note_id(self) -> Dict[str, ManifestEntry]:
        return {entry.note_id: entry for entry in self.entries}

    def by_relative_path(self) -> Dict[str, ManifestEntry]:
        return {entry.relative_path: entry for entry in self.entries}

    def get(self, note_id: object) -> Optional[ManifestEntry]:
        """Return the entry for ``note_id``, or ``None``. Never raises on a miss."""
        if not isinstance(note_id, str):
            return None
        for entry in self.entries:
            if entry.note_id == note_id:
                return entry
        return None

    def active_entries(self) -> Tuple[ManifestEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_active)

    def lists_note_id(self, note_id: object) -> bool:
        """The MANIFEST SIGNAL of the three-signal ownership test (§12.1).

        One signal of three. On its own it authorizes nothing — containment and
        the frontmatter marker are equally required before any file is written
        over or deleted.
        """
        entry = self.get(note_id)
        return entry is not None

    # -- serialization ------------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        # ``edit_conflicts`` is emitted unconditionally (even when empty) so a
        # manifest produced BY M9.5 round-trips through a parser that still
        # treats the key as known. A pre-M9.5 manifest (no such key) is handled
        # by from_json's backward-safe key handling.
        return {
            "manifest_version": self.manifest_version,
            "projection_version": self.projection_version,
            "managed_dir_name": self.managed_dir_name,
            "notes": [entry.to_json() for entry in self.entries],
            "edit_conflicts": [conflict.to_json() for conflict in self.edit_conflicts],
        }

    def serialize(self) -> bytes:
        """Deterministic UTF-8 bytes: sorted keys, LF, one trailing newline.

        ``ensure_ascii=True`` keeps the file byte-identical regardless of the
        platform's default encoding, and the fixed separators remove the
        whitespace variability that would otherwise make two equal manifests
        compare unequal.
        """
        text = json.dumps(
            self.to_json(),
            sort_keys=True,
            ensure_ascii=True,
            indent=2,
            separators=(",", ": "),
        )
        return (text + "\n").encode("utf-8")

    @classmethod
    def from_json(cls, payload: Any) -> "ProjectionManifest":
        """Rebuild from untrusted JSON, failing closed on any deviation.

        ``edit_conflicts`` is OPTIONAL in the wire form: a manifest written by
        M9.4 (before M9.5 existed) carries no such key and must still load
        byte-for-byte safely. Any UNKNOWN key is still refused (tamper defense).
        """
        if not isinstance(payload, dict):
            raise ManifestError("manifest")
        unexpected = set(payload) - set(ENVELOPE_KEYS)
        if unexpected:
            raise ManifestError("manifest_key")
        # Only the keys that MUST always be present are required; edit_conflicts
        # is tolerated when absent (backward-safe load).
        missing = set(REQUIRED_ENVELOPE_KEYS) - set(payload)
        if missing:
            raise ManifestError("manifest_key")
        manifest_version = payload["manifest_version"]
        if manifest_version != MANIFEST_VERSION:
            # An unsupported envelope version is refused rather than
            # best-effort parsed: a format we do not understand must never be
            # used to decide that a file may be deleted.
            raise ManifestError("manifest_version")
        projection_version = payload["projection_version"]
        if (
            not isinstance(projection_version, int)
            or isinstance(projection_version, bool)
            or projection_version < 1
            or projection_version > PROJECTION_VERSION
        ):
            # A manifest from a FUTURE renderer contract is unsupported; a past
            # one is legitimate and triggers a full re-render (§14.4).
            raise ManifestError("projection_version")
        notes = payload["notes"]
        if not isinstance(notes, list):
            raise ManifestError("notes")
        raw_conflicts = payload.get("edit_conflicts", [])
        if not isinstance(raw_conflicts, list):
            raise ManifestError("edit_conflicts")
        return cls(
            manifest_version=manifest_version,
            projection_version=projection_version,
            managed_dir_name=payload["managed_dir_name"],
            entries=tuple(ManifestEntry.from_json(item) for item in notes),
            edit_conflicts=tuple(EditConflict.from_json(item) for item in raw_conflicts),
        )

    @classmethod
    def deserialize(cls, raw: bytes) -> "ProjectionManifest":
        """Parse manifest bytes. Invalid JSON fails closed, never silently empty."""
        if not isinstance(raw, (bytes, bytearray)):
            raise ManifestError("manifest")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ManifestError("manifest_json") from None
        return cls.from_json(payload)

    @classmethod
    def from_notes(cls, notes: Iterable[ProjectedNote], *,
                   managed_dir_name: str = "",
                   projection_version: int = PROJECTION_VERSION,
                   statuses: Optional[Mapping[str, NoteStatus]] = None,
                   retired: Iterable[ManifestEntry] = (),
                   edit_conflicts: Iterable["EditConflict"] = (),
                   observed_fingerprints: Mapping[str, str] = {},
                   content_fingerprints: Mapping[str, str] = {}) -> "ProjectionManifest":
        """Build a manifest from the rendered desired set plus retired entries.

        ``statuses`` optionally overrides a note's recorded status (used for the
        human-boundary outcomes M9.4 must record without acting on). ``retired``
        carries forward entries whose files were retired in this run.
        ``edit_conflicts`` (M9.5) carries the deterministic record of any
        explored human-edit/projection boundary conflicts discovered in this run.
        ``observed_fingerprints`` (M9.5) carries the fingerprint of a human's
        current on-disk bytes for a note whose file diverged, recorded as a hash
        only (never content) so a later run can prove divergence without reading
        the file again. ``content_fingerprints`` (M9.5) overrides the recorded
        content fingerprint — used to keep a human-divergent note's recorded
        fingerprint equal to the LAST bytes M9 actually wrote, so the divergence
        stays detectable on later runs.
        """
        overrides = dict(statuses or {})
        observed = dict(observed_fingerprints or {})
        content_overrides = dict(content_fingerprints or {})
        entries = [
            ManifestEntry.from_note(
                note, status=overrides.get(note.note_id, NoteStatus.CURRENT),
                observed_fingerprint=observed.get(note.note_id),
                content_fingerprint=content_overrides.get(note.note_id),
            )
            for note in notes
        ]
        entries.extend(retired)
        return cls(
            manifest_version=MANIFEST_VERSION,
            projection_version=projection_version,
            managed_dir_name=managed_dir_name,
            entries=tuple(entries),
            edit_conflicts=tuple(edit_conflicts),
        )


#: An empty manifest. Returned when none exists yet — a first run and a deleted
#: manifest are the same, safe, non-exceptional state.
def empty_manifest(*, managed_dir_name: str = "") -> ProjectionManifest:
    return ProjectionManifest(
        managed_dir_name=managed_dir_name,
        projection_version=PROJECTION_VERSION,
        entries=(),
    )


# ---------------------------------------------------------------------------
# Safe path resolution for manifest-supplied paths
# ---------------------------------------------------------------------------

def resolve_entry_path(managed_root: Path, entry: ManifestEntry) -> Path:
    """Resolve one manifest entry to an absolute path, or fail closed.

    The REQUIRED pipeline (never shortened): contract validation (already done
    by :class:`ManifestEntry`) -> lexical containment -> symlink-chain rejection
    -> realpath physical containment. ``safe_managed_path`` performs the last
    three, and both M9.1 defenses are kept: mutation testing proved each one
    independently protects the invariant.

    A manifest path therefore never reaches an ``unlink``/``open`` call as a raw
    string, and a manifest that names ``../../etc/passwd``, an absolute path, or
    a symlinked directory cannot address anything outside the managed root.
    """
    if not isinstance(managed_root, Path):
        raise ProjectionPathError("managed_root_not_a_path")
    if not isinstance(entry, ManifestEntry):
        raise ManifestError("entry")
    components = entry.relative_path.split("/")
    return safe_managed_path(managed_root, *components)


def manifest_path(managed_root: Path) -> Path:
    """Absolute, contained path of ``_meta/manifest.json``."""
    return safe_meta_path(managed_root, MANIFEST_FILENAME)


# ---------------------------------------------------------------------------
# Load / store
# ---------------------------------------------------------------------------

def load_manifest(managed_root: Path, *,
                  managed_dir_name: str = "") -> ProjectionManifest:
    """Load the manifest, or return an empty one when none exists.

    An ABSENT manifest is a normal state (first run, or the operator deleted the
    derived projection metadata) and yields an empty manifest, never an error:
    the projection is rebuildable from authoritative state by definition.

    A PRESENT but malformed, tampered, or unsupported manifest is a hard
    failure. It must not be silently treated as empty, because "empty" means
    "nothing is managed", which would strip the manifest ownership signal from
    every file and could convert a corrupt manifest into a mass overwrite.
    """
    path = manifest_path(managed_root)
    if path.is_symlink():
        # A symlinked manifest could redirect reads outside the managed root.
        raise ManifestError("manifest_is_symlink")
    if not path.exists():
        return empty_manifest(managed_dir_name=managed_dir_name)
    if not path.is_file():
        raise ManifestError("manifest_not_a_file")
    try:
        raw = path.read_bytes()
    except OSError:
        raise ManifestError("manifest_unreadable") from None
    return ProjectionManifest.deserialize(raw)


def store_manifest(managed_root: Path, manifest: ProjectionManifest,
                   *, dry_run: bool = False) -> bool:
    """Write the manifest atomically. Returns True only if bytes were written.

    Unchanged-byte suppression is load-bearing for the zero-write invariant
    (§16.3): when the serialized manifest equals what is already on disk, this
    performs NO write at all, so ``mtime`` stays stable and Obsidian's file
    watcher does not fire on an unchanged run.

    Written last in a run (§25.2) and via same-directory temp + fsync +
    ``os.replace``, so a crash can never leave a half-written manifest claiming
    state that does not exist on disk.
    """
    if not isinstance(manifest, ProjectionManifest):
        raise ManifestError("manifest")
    payload = manifest.serialize()
    path = manifest_path(managed_root)

    if path.is_symlink():
        raise ManifestError("manifest_is_symlink")
    if path.is_file():
        try:
            if path.read_bytes() == payload:
                return False  # already current: zero writes
        except OSError:
            raise ManifestError("manifest_unreadable") from None
    if dry_run:
        return False

    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        # Re-prove containment AFTER creating the directory: a directory swapped
        # for a symlink between check and write is refused, not followed.
        assert_within_managed_root(managed_root, path)
    except ProjectionPathError:
        raise
    except OSError:
        # Fail CLOSED on an unavailable manifest directory (permission denied,
        # read-only managed root, disk-full). The manifest is DERIVED and fully
        # rebuildable from canonical traces + on-disk notes, so a failed store is
        # a soft condition: the run completes with manifest_stored=False and the
        # next reconcile re-derives it. Raising here would abort the whole run
        # and risk leaving the vault in a half-written state (docs/plans/plan-m9.md §28
        # failure-isolation: every failure fails closed and leaves the vault
        # consistent).
        return False

    temp_path = safe_managed_path(
        managed_root, META_DIR_NAME, f"{MANIFEST_FILENAME}.tmp-manifest"
    )
    try:
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), 0o644)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temp_path, path)
    except OSError:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise ManifestError("manifest_write_failed") from None
    _fsync_directory(parent)
    return True


def _fsync_directory(directory: Path) -> None:
    """Fsync a managed directory so a rename is durable. Never fatal."""
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


__all__ = [
    "MANIFEST_VERSION",
    "MANIFEST_FILENAME",
    "MANIFEST_RELATIVE_PATH",
    "ENVELOPE_KEYS",
    "REQUIRED_ENVELOPE_KEYS",
    "EDIT_CONFLICT_KEYS",
    "EDIT_CONFLICT_REQUIRED_KEYS",
    "ManifestError",
    "ManifestEntry",
    "EditConflict",
    "ProjectionManifest",
    "empty_manifest",
    "validate_fingerprint",
    "validate_manifest_relative_path",
    "resolve_entry_path",
    "manifest_path",
    "load_manifest",
    "store_manifest",
]
