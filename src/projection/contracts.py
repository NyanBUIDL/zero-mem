"""M9.1 — frozen projection contracts (vocabularies, request/result, ownership).

This module freezes the SHAPE of the Obsidian projection layer. It deliberately
implements no rendering, no writing, no manifest behaviour, and no
authorization. There is intentionally no ``project()``, ``render()``,
``write()``, ``retire()``, or ``authorize()`` anywhere in this package at M9.1.

Authority boundaries baked into these contracts (docs/plans/plan-m9.md §5, §7.1, §11):

- **Obsidian is a curated derived projection.** Canonical authority remains the
  append-only JSONL traces, the approved project-state records, and the
  versioned artifact store. SQLite stays derived/rebuildable. Nothing here is a
  source of truth, and deleting an entire projection loses nothing canonical.
- **M5 is the sole authorization authority.** These contracts CARRY an explicit
  ``requesting_profile_id`` (``None`` stays ``None``, meaning an unbound
  caller); they never infer identity and never make, cache, or widen an access
  decision. Filesystem co-location, folder membership, a wiki link, or a shared
  tag grants nothing.
- **Sensitivity uses the ONE canonical vocabulary** from
  ``src/capture/event_types.py::Sensitivity`` (``public < internal < private <
  secret``). M9 introduces no second ladder. The projection ceiling defaults to
  ``internal`` — deliberately stricter than the M7 retrieval default
  (``private``) because a projected note is plaintext at rest in a vault the
  operator may sync. Projection may narrow visibility; it must never widen it.
- **Ownership is proven, never assumed.** A file is Zero-Mem-managed only under
  the three-signal test (§12.1). Path containment ALONE is explicitly
  insufficient, so a human note dropped into the managed subtree is never
  claimed, overwritten, or deleted.

Zero LLM calls, zero network calls, zero embeddings. Pure data + pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, FrozenSet, Iterable, Mapping, Optional, Sequence, Tuple

from src.capture.event_types import Sensitivity
from src.m8.vocabulary import RESOURCE_TYPES

# ---------------------------------------------------------------------------
# Contract versions
# ---------------------------------------------------------------------------

#: Renderer-contract version (docs/plans/plan-m9.md §14.1). Bumped ONLY when the generated
#: note layout / frontmatter field set / section structure changes. It never
#: changes per run and carries no truth semantics.
PROJECTION_VERSION: Final[int] = 1

#: Frozen M9.1 contract version, mirroring the ``M8_CONTRACT_VERSION`` discipline.
M9_CONTRACT_VERSION: Final[str] = "m9.1"


# ---------------------------------------------------------------------------
# Errors (sanitized: never echo secrets, offending payloads, or absolute paths)
# ---------------------------------------------------------------------------

class ProjectionError(Exception):
    """Base sanitized projection failure.

    Messages name a stable machine-readable reason code only. They never carry
    raw memory content, environment values, secrets, or the offending absolute
    filesystem path — a rejected traversal payload must not be leaked into logs.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"projection_error: {reason}")
        self.reason = reason


class ProjectionConfigError(ProjectionError):
    """Vault/managed-root configuration is invalid. Fails closed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class ProjectionPathError(ProjectionError):
    """A requested path violates the §10 safe-path invariant. Fails closed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)


class ProjectionVocabularyError(ProjectionError):
    """A value fell outside a closed projection vocabulary. Fails closed."""

    def __init__(self, field_name: str) -> None:
        super().__init__(f"invalid_{field_name}")
        self.field_name = field_name


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------

class NoteType(str, Enum):
    """Closed curated note-type vocabulary approved in docs/plans/plan-m9.md §29 Q1.

    Exactly the owner-approved M9 curated types, one member each. M9.1 defines
    the vocabulary and the directory mapping only; it renders none of them.

    ``RESEARCH_NOTE`` projects research material ALREADY held by Zero-Mem. It
    does not authorize, imply, or begin M10 corpus ingestion.
    """

    PROJECT = "project"                # Project Home
    DECISION = "decision"              # Decision
    REQUIREMENT = "requirement"        # Requirement
    VERIFICATION = "verification"      # Verification
    CONFLICT = "conflict"              # Conflict (incl. the per-type unresolved-conflict index)
    ARTIFACT = "artifact"              # Artifact Reference
    RESEARCH_NOTE = "research_note"    # Research Note
    KNOWLEDGE_INDEX = "knowledge_index"  # Knowledge Index


#: Deterministic category directory for each curated note type (docs/plans/plan-m9.md §6.2).
#: Categories come from THIS closed map — never from caller- or content-supplied
#: text — which is what makes "content can never choose a parent directory"
#: structural rather than best-effort. ``Research/`` is the smallest consistent
#: extension of the §6.2 table for the owner-approved Q1 Research Note type.
NOTE_TYPE_DIRECTORIES: Final[Mapping[NoteType, str]] = {
    NoteType.PROJECT: "Projects",
    NoteType.DECISION: "Decisions",
    NoteType.REQUIREMENT: "Requirements",
    NoteType.VERIFICATION: "Verification",
    NoteType.CONFLICT: "Conflicts",
    NoteType.ARTIFACT: "Artifacts",
    NoteType.RESEARCH_NOTE: "Research",
    NoteType.KNOWLEDGE_INDEX: "Knowledge",
}

#: Reserved directory name for projection metadata (manifest, report, README).
#: M9.1 defines the name only; manifest behaviour belongs to M9.4.
META_DIR_NAME: Final[str] = "_meta"

#: Every directory name M9 may own directly beneath the managed root.
MANAGED_CATEGORY_DIRECTORIES: Final[FrozenSet[str]] = frozenset(
    set(NOTE_TYPE_DIRECTORIES.values()) | {META_DIR_NAME}
)


class NoteStatus(str, Enum):
    """Closed per-note manifest status vocabulary (docs/plans/plan-m9.md §15.1)."""

    CURRENT = "current"
    RETIRED = "retired"
    EDIT_CONFLICT = "edit_conflict"
    HUMAN_MODIFIED = "human_modified"


class ProjectionStatus(str, Enum):
    """Closed run-status vocabulary.

    ``UNAVAILABLE`` is a NORMAL, safe, silent state (docs/plans/plan-m9.md §2.4): no vault
    configured means nothing is written anywhere and no exception escapes.
    """

    OK = "ok"
    UNAVAILABLE = "unavailable"
    BUSY = "busy"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Sensitivity policy (ONE canonical vocabulary; never a second ladder)
# ---------------------------------------------------------------------------

#: Canonical ordering derived programmatically from the authoritative M1
#: ``Sensitivity`` enum declaration order (public < internal < private < secret).
#: Deriving it — rather than hand-writing a second table — is what makes a
#: vocabulary drift like the corrected M7.3 defect structurally impossible here.
SENSITIVITY_ORDER: Final[Mapping[str, int]] = {
    member.value: index for index, member in enumerate(Sensitivity)
}

#: Unknown/malformed values rank above every real class, so they always fail closed.
UNKNOWN_SENSITIVITY_RANK: Final[int] = 99

#: M9 default projection ceiling (docs/plans/plan-m9.md §11.2 / §29 Q18). Deliberately
#: STRICTER than the M7 retrieval default (``private``): a projected note is
#: plaintext at rest in a vault the operator may sync, whereas M7 evidence is
#: transient and in-process. M9 may narrow visibility; it must never widen it.
DEFAULT_PROJECTION_SENSITIVITY_CEILING: Final[str] = Sensitivity.INTERNAL.value


def sensitivity_rank(level: Optional[str]) -> int:
    """Rank a canonical sensitivity value. Unknown/malformed => fail closed."""
    if not isinstance(level, str):
        return UNKNOWN_SENSITIVITY_RANK
    return SENSITIVITY_ORDER.get(level.strip().lower(), UNKNOWN_SENSITIVITY_RANK)


def is_projectable_sensitivity(
    sensitivity: Optional[str],
    ceiling: Optional[str] = DEFAULT_PROJECTION_SENSITIVITY_CEILING,
) -> bool:
    """Return True iff an item at ``sensitivity`` may be projected at ``ceiling``.

    Fails closed in every ambiguous direction:

    * unknown/missing/malformed sensitivity is always excluded;
    * unknown/malformed ceiling excludes EVERYTHING (a broken ceiling must never
      widen visibility — the same fail-open hole corrected in M7.3);
    * ``secret`` is excluded unconditionally at any ceiling, forever.

    Eligibility here is NECESSARY, never sufficient: an item still requires M5
    authorization and the full §7.2 eligibility filter before any note exists.
    """
    item_rank = sensitivity_rank(sensitivity)
    if item_rank == UNKNOWN_SENSITIVITY_RANK:
        return False
    if item_rank >= SENSITIVITY_ORDER[Sensitivity.SECRET.value]:
        return False
    ceiling_rank = sensitivity_rank(ceiling)
    if ceiling_rank == UNKNOWN_SENSITIVITY_RANK:
        return False
    if ceiling_rank >= SENSITIVITY_ORDER[Sensitivity.SECRET.value]:
        # A `secret` ceiling would mean "project everything"; refuse it outright
        # rather than honour a ceiling that can only ever widen visibility.
        return False
    return item_rank <= ceiling_rank


def validate_sensitivity_ceiling(value: Optional[str]) -> str:
    """Return a validated projection ceiling, or fail closed.

    ``secret`` is not an acceptable ceiling: it cannot widen anything (``secret``
    never projects), and accepting it would advertise a ceiling that reads as
    "project everything".
    """
    if not isinstance(value, str):
        raise ProjectionVocabularyError("sensitivity_ceiling")
    candidate = value.strip().lower()
    if candidate not in SENSITIVITY_ORDER:
        raise ProjectionVocabularyError("sensitivity_ceiling")
    if candidate == Sensitivity.SECRET.value:
        raise ProjectionVocabularyError("sensitivity_ceiling")
    return candidate


# ---------------------------------------------------------------------------
# Small validation helpers (pure)
# ---------------------------------------------------------------------------

def validate_note_type(value: Any) -> NoteType:
    """Return the closed ``NoteType`` member, or fail closed."""
    if isinstance(value, NoteType):
        return value
    try:
        return NoteType(value)
    except (ValueError, TypeError):
        raise ProjectionVocabularyError("note_type") from None


def validate_note_status(value: Any) -> NoteStatus:
    if isinstance(value, NoteStatus):
        return value
    try:
        return NoteStatus(value)
    except (ValueError, TypeError):
        raise ProjectionVocabularyError("note_status") from None


def validate_resource_type(value: Any) -> str:
    """Return ``value`` if it is an authoritative M5 resource-type literal.

    Resource-type identity is preserved verbatim and never flattened: the
    permanent M6.6 isolation invariant means an artifact reference is not an
    event reference even when the raw identifier matches.
    """
    if not isinstance(value, str) or value not in RESOURCE_TYPES:
        raise ProjectionVocabularyError("resource_type")
    return value


def _optional_identifier(value: Any, field_name: str) -> Optional[str]:
    """Explicit ``None`` is preserved as ``None`` — never inferred, never '*'."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProjectionVocabularyError(field_name)
    return value


def _identifier_tuple(values: Optional[Iterable[Any]], field_name: str) -> Tuple[str, ...]:
    """Normalize an identifier collection deterministically.

    De-duplicated and code-point sorted so the same logical request always
    produces the same output regardless of caller iteration order. Values
    themselves are preserved verbatim — normalization is ordering only, never
    rewriting, widening, or inferring an identifier.
    """
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ProjectionVocabularyError(field_name)
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ProjectionVocabularyError(field_name)
        seen.add(value)
    return tuple(sorted(seen))


# ---------------------------------------------------------------------------
# Ownership (three-signal test; path containment alone is NEVER enough)
# ---------------------------------------------------------------------------

#: Frontmatter key that marks a note as Zero-Mem generated (docs/plans/plan-m9.md §12.1).
MANAGED_MARKER_KEY: Final[str] = "zero_mem_managed"


@dataclass(frozen=True)
class OwnershipSignals:
    """The three independent ownership signals (docs/plans/plan-m9.md §12.1).

    A file is Zero-Mem-managed only when ALL THREE hold. Each alone fails in a
    different direction, which is exactly why one is never sufficient:

    * containment alone would claim a human note dropped into the managed folder;
    * the frontmatter marker alone is spoofable anywhere in the vault;
    * the manifest alone goes stale when the vault is edited or restored.

    M9.1 supplies the primitives and the decision rule. The manifest signal is
    materialized by M9.4 and consumed for deletion by M9.5; M9.1 deletes nothing.
    """

    inside_managed_root: bool = False
    has_managed_marker: bool = False
    listed_in_manifest: bool = False

    def __post_init__(self) -> None:
        for name in ("inside_managed_root", "has_managed_marker", "listed_in_manifest"):
            if not isinstance(getattr(self, name), bool):
                raise ProjectionVocabularyError(name)

    @property
    def is_managed(self) -> bool:
        """True only when every signal holds. Fails safe in every direction."""
        return (
            self.inside_managed_root
            and self.has_managed_marker
            and self.listed_in_manifest
        )

    @property
    def missing_signals(self) -> Tuple[str, ...]:
        """Deterministically ordered names of the signals that did not hold."""
        missing = []
        if not self.inside_managed_root:
            missing.append("inside_managed_root")
        if not self.has_managed_marker:
            missing.append("has_managed_marker")
        if not self.listed_in_manifest:
            missing.append("listed_in_manifest")
        return tuple(missing)


def is_zero_mem_managed(signals: OwnershipSignals) -> bool:
    """Three-signal ownership decision. Anything less is human-owned."""
    if not isinstance(signals, OwnershipSignals):
        raise ProjectionVocabularyError("ownership_signals")
    return signals.is_managed


# ---------------------------------------------------------------------------
# Request / note / result contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProjectionRequest:
    """Explicit projection request. Carries identity; never infers it.

    ``requesting_profile_id=None`` means an UNBOUND caller and stays ``None``.
    Authentication is out of scope here exactly as it is for M5: the caller
    supplies the identity, and no path, cwd, environment variable, session text,
    vault folder, or note content may ever be read as an identity signal.

    ``grants`` is an opaque passthrough for the M5 read surface consumed by a
    later increment. M9.1 never inspects, interprets, evaluates, or persists it.
    """

    requesting_profile_id: Optional[str] = None
    project_ids: Tuple[str, ...] = ()
    knowledge_space_ids: Tuple[str, ...] = ()
    resource_types: Tuple[str, ...] = ()
    grants: Tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requesting_profile_id",
            _optional_identifier(self.requesting_profile_id, "requesting_profile_id"),
        )
        object.__setattr__(
            self, "project_ids", _identifier_tuple(self.project_ids, "project_ids")
        )
        object.__setattr__(
            self,
            "knowledge_space_ids",
            _identifier_tuple(self.knowledge_space_ids, "knowledge_space_ids"),
        )
        resource_types = _identifier_tuple(self.resource_types, "resource_types")
        for resource_type in resource_types:
            validate_resource_type(resource_type)
        object.__setattr__(self, "resource_types", resource_types)
        if isinstance(self.grants, (str, bytes)):
            raise ProjectionVocabularyError("grants")
        object.__setattr__(self, "grants", tuple(self.grants or ()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "requesting_profile_id": self.requesting_profile_id,
            "project_ids": list(self.project_ids),
            "knowledge_space_ids": list(self.knowledge_space_ids),
            "resource_types": list(self.resource_types),
            "grant_count": len(self.grants),
        }


@dataclass(frozen=True)
class ProjectedNote:
    """One fully-rendered note, as a value. M9.1 renders none of these.

    The contract binds ``content_fingerprint`` to ``content`` so a note whose
    body was mutated can never travel with a stale fingerprint. ``relative_path``
    is always managed-root relative — an absolute path is never carried in a
    note contract, so a note value cannot smuggle a write target.

    The optional source-identity fields (``resource_type``, ``resource_id``,
    ``project_id``, ``source_trace_ids``) carry the AUTHORITATIVE identity the
    renderer already used to derive ``note_id``. They exist so the M9.4 manifest
    can record which authoritative record a managed file projects without
    re-parsing generated Markdown. They are descriptive only: they confer no
    authorization, no truth, and no ownership, and ``resource_type`` is
    preserved verbatim so the permanent M6.6 isolation invariant survives into
    the manifest (an ``artifact`` entry can never satisfy a ``decision`` lookup).
    """

    note_id: str
    note_type: NoteType
    relative_path: str
    content: str
    content_fingerprint: str
    links: Tuple[str, ...] = ()
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    project_id: Optional[str] = None
    source_trace_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        from .identity import content_fingerprint as _fingerprint, validate_note_id

        object.__setattr__(self, "note_id", validate_note_id(self.note_id))
        note_type = validate_note_type(self.note_type)
        object.__setattr__(self, "note_type", note_type)
        if not isinstance(self.relative_path, str) or not self.relative_path:
            raise ProjectionVocabularyError("relative_path")
        if self.relative_path.startswith("/") or "\\" in self.relative_path:
            raise ProjectionVocabularyError("relative_path")
        if "\x00" in self.relative_path or ".." in self.relative_path.split("/"):
            raise ProjectionVocabularyError("relative_path")
        if not isinstance(self.content, str):
            raise ProjectionVocabularyError("content")
        if "\x00" in self.content:
            raise ProjectionVocabularyError("content")
        if self.content_fingerprint != _fingerprint(self.content):
            raise ProjectionVocabularyError("content_fingerprint")
        links = _identifier_tuple(self.links, "links")
        object.__setattr__(self, "links", links)

        # Optional source identity. Absent stays absent (None), never inferred
        # and never widened into a wildcard.
        if self.resource_type is not None:
            object.__setattr__(
                self, "resource_type", validate_resource_type(self.resource_type)
            )
        object.__setattr__(
            self, "resource_id", _optional_identifier(self.resource_id, "resource_id")
        )
        object.__setattr__(
            self, "project_id", _optional_identifier(self.project_id, "project_id")
        )
        # Trace ids are preserved VERBATIM and in recorded order: they are
        # authoritative provenance data, not a presentation choice.
        trace_ids = tuple(self.source_trace_ids or ())
        for trace_id in trace_ids:
            if not isinstance(trace_id, str) or not trace_id.strip():
                raise ProjectionVocabularyError("source_trace_ids")
        object.__setattr__(self, "source_trace_ids", trace_ids)


@dataclass(frozen=True)
class ProjectionResult:
    """Outcome of a projection run. M9.1 produces only UNAVAILABLE/FAILED forms.

    Counts and reasons are sanitized machine-readable values. A denial or an
    unsafe path is reported as a reason code and a count — never as a note, a
    placeholder, or an existence signal for content the caller may not see.
    """

    status: ProjectionStatus
    reason: str = ""
    created: int = 0
    updated: int = 0
    skipped: int = 0
    retired: int = 0
    conflicted: int = 0
    notes: Tuple[ProjectedNote, ...] = ()
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProjectionStatus):
            raise ProjectionVocabularyError("status")
        if not isinstance(self.reason, str):
            raise ProjectionVocabularyError("reason")
        for name in ("created", "updated", "skipped", "retired", "conflicted"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ProjectionVocabularyError(name)
        object.__setattr__(self, "notes", tuple(self.notes or ()))
        warnings = tuple(self.warnings or ())
        for warning in warnings:
            if not isinstance(warning, str):
                raise ProjectionVocabularyError("warnings")
        object.__setattr__(self, "warnings", warnings)

    @property
    def notes_written(self) -> int:
        return self.created + self.updated

    @classmethod
    def unavailable(cls, reason: str) -> "ProjectionResult":
        """The safe silent state: nothing configured, nothing written, no error.

        Nothing is created in cwd, HOME, the repository, a temp directory, or a
        guessed ``~/Obsidian``; no exception propagates to the caller.
        """
        return cls(status=ProjectionStatus.UNAVAILABLE, reason=reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "retired": self.retired,
            "conflicted": self.conflicted,
            "note_count": len(self.notes),
            "warnings": list(self.warnings),
        }


__all__ = [
    "PROJECTION_VERSION",
    "M9_CONTRACT_VERSION",
    "ProjectionError",
    "ProjectionConfigError",
    "ProjectionPathError",
    "ProjectionVocabularyError",
    "NoteType",
    "NOTE_TYPE_DIRECTORIES",
    "META_DIR_NAME",
    "MANAGED_CATEGORY_DIRECTORIES",
    "NoteStatus",
    "ProjectionStatus",
    "SENSITIVITY_ORDER",
    "UNKNOWN_SENSITIVITY_RANK",
    "DEFAULT_PROJECTION_SENSITIVITY_CEILING",
    "sensitivity_rank",
    "is_projectable_sensitivity",
    "validate_sensitivity_ceiling",
    "validate_note_type",
    "validate_note_status",
    "validate_resource_type",
    "MANAGED_MARKER_KEY",
    "OwnershipSignals",
    "is_zero_mem_managed",
    "ProjectionRequest",
    "ProjectedNote",
    "ProjectionResult",
]
