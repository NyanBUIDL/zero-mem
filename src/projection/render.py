"""M9.2 — deterministic rendering of curated Zero-Mem notes.

Pure functions only: this module reads no store, makes no authorization
decision, touches no filesystem, and holds no state. It turns an
already-authorized, already-eligible authoritative record into an immutable
:class:`~src.projection.contracts.ProjectedNote` value.

Two structural rules make the "memory is DATA" guarantee real rather than
best-effort (docs/plans/plan-m9.md §22.2):

1. **Content never chooses structure.** Every heading, label, frontmatter key,
   note category, and path component comes from a closed literal in this module
   or from the frozen M9.1 vocabularies. Record content is only ever emitted in
   a *value position* that has already been escaped for its context, and never
   at the start of a line, so it cannot open a frontmatter block, a callout, a
   heading, a code fence, a wiki link, an embed, or a tag.
2. **No wall clock, no ordering, no randomness.** The same authoritative record
   plus the same configuration always renders byte-identical output. Note
   identity comes from the verified M9.1 primitives; nothing here consults
   ``time``, ``random``, ``uuid``, ``hash()``, a rowid, or an insertion order.

M9.3 adds, on top of that: a complete deterministic provenance block on every
note, safe wiki links between already-authorized notes, explicit
supersession/history presentation, and honest unresolved-conflict presentation
(Conflict notes plus a per-resource-type Conflict Queue).

Deliberately NOT implemented here (later increments): the manifest,
incremental/unchanged-write suppression, retirement, human-edit quarantine,
Research Note and Knowledge Index bodies.

Two authority rules govern the M9.3 surface and are load-bearing:

* **Links are navigation only.** A rendered link asserts no authorization, no
  truth, no verification, no conflict resolution, and no supersession. A
  reference whose target this request did not authorize renders exactly like a
  reference to something that was never recorded (docs/plans/plan-m9.md §5, §21).
* **M4 is the only conflict/supersession authority.** This layer PRESENTS
  ``lifecycle_status='conflicted'`` and the explicit ``supersedes`` /
  ``replaced_by`` fields. It never creates, resolves, ranks, or infers them —
  not from recency, insertion order, file mtime, calibration, or graph
  structure (docs/plans/plan-m9.md §19, §20).

Zero LLM calls, zero network calls, zero embeddings.
"""

from __future__ import annotations

from typing import Any, Final, Mapping, Optional, Sequence, Tuple

from src.project_memory.contracts import is_safe_reference

from .contracts import (
    NOTE_TYPE_DIRECTORIES,
    PROJECTION_VERSION,
    MANAGED_MARKER_KEY,
    NoteType,
    ProjectedNote,
    ProjectionVocabularyError,
    validate_note_type,
    validate_resource_type,
)
from .conflicts import ConflictGroup, CONFLICTED_LIFECYCLE, conflict_resource_id
from .identity import content_fingerprint, derive_note_id, note_filename, slug
from .links import LinkRegistry, LinkTarget, note_relative_path, wiki_link

# ---------------------------------------------------------------------------
# Closed rendering constants
# ---------------------------------------------------------------------------

#: Value of the ``generated_by`` provenance field (docs/plans/plan-m9.md §8).
GENERATED_BY: Final[str] = "zero-mem/m9"

#: Per-field length cap, mirroring the verified M7 ``_MAX_FIELD_LEN`` discipline
#: (docs/plans/plan-m9.md §22.1 "Length/DoS"). A 10 MB memory field cannot bloat a note.
MAX_FIELD_LENGTH: Final[int] = 2000

#: Appended verbatim (never escaped) when a field was truncated.
TRUNCATION_MARKER: Final[str] = "…[truncated]"

#: Rendered in place of a missing optional value. A missing value is shown as
#: explicitly absent rather than invented, guessed, or silently omitted.
NONE_MARKER: Final[str] = "(none)"

#: Frontmatter keys, in the exact fixed order of docs/plans/plan-m9.md §8. The set is
#: CLOSED: rendering fails closed if a key is missing or unexpected, so record
#: content can never introduce, rename, or remove a frontmatter field.
FRONTMATTER_FIELDS: Final[Tuple[str, ...]] = (
    MANAGED_MARKER_KEY,
    "note_id",
    "note_type",
    "projection_version",
    "content_fingerprint",
    "resource_type",
    "resource_id",
    "project_id",
    "profile_id",
    "knowledge_spaces",
    "lifecycle_status",
    "verification_status",
    "conflict_status",
    "supersedes",
    "replaced_by",
    "source_trace_ids",
    "source_event_ids",
    "artifact_refs",
    "generated_by",
)

#: Closed conflict vocabulary. ``conflicted`` is derived ONLY from an
#: authoritative ``lifecycle_status`` of ``conflicted`` — never inferred from
#: two records disagreeing, from recency, or from any score.
CONFLICT_NONE: Final[str] = "none"
CONFLICT_CONFLICTED: Final[str] = "conflicted"

#: ASCII punctuation escaped in every content-derived string, so a memory value
#: can never synthesize a link, embed, tag, emphasis, fence, or math span.
_ESCAPED_PUNCTUATION: Final[Tuple[str, ...]] = (
    "[", "]", "|", "#", "`", "*", "_", "!", "$", "~", "^", "{", "}",
)


# ---------------------------------------------------------------------------
# Escaping (every content-derived string passes through exactly one of these)
# ---------------------------------------------------------------------------

def _flatten(value: Any) -> Optional[str]:
    """Fold arbitrary record content to a single safe line, or ``None``.

    NUL and control characters are dropped, newlines/tabs become spaces, and
    whitespace runs collapse. Folding to one line is what structurally prevents
    a value from ever reaching the start of a line, which in turn prevents
    ``---`` frontmatter escape, heading injection, and callout injection.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    characters = []
    for character in text:
        code = ord(character)
        if character in ("\n", "\r", "\t"):
            characters.append(" ")
        elif code < 0x20 or code == 0x7F:
            continue
        else:
            characters.append(character)
    collapsed = " ".join("".join(characters).split())
    return collapsed or None


def escape_inline(value: Any) -> str:
    """Render one content-derived value as inert inline Markdown DATA.

    Order matters: the backslash is escaped first so later escapes stay
    unambiguous, then HTML-special characters (killing ``<script>`` and raw
    HTML), then the Markdown/Obsidian punctuation that could otherwise create a
    wiki link, an embed, a tag, a code fence, emphasis, or a math span.

    Truncation happens on the RAW value and the marker is appended afterwards,
    so the marker cannot be corrupted by escaping and an over-long hostile field
    can never smuggle a half-escaped sequence past the cap.
    """
    flattened = _flatten(value)
    if flattened is None:
        return NONE_MARKER

    truncated = len(flattened) > MAX_FIELD_LENGTH
    if truncated:
        flattened = flattened[:MAX_FIELD_LENGTH]

    escaped = flattened.replace("\\", "\\\\")
    escaped = escaped.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for character in _ESCAPED_PUNCTUATION:
        escaped = escaped.replace(character, "\\" + character)

    return escaped + TRUNCATION_MARKER if truncated else escaped


def _yaml_scalar(value: Any) -> str:
    """Serialize one frontmatter scalar. Strings are ALWAYS quoted and escaped.

    Because every string is emitted as a double-quoted YAML scalar with escaped
    quotes, backslashes, newlines, and control characters, a value containing
    ``---``, ``: ``, or a newline is inert: it cannot close the frontmatter
    block, introduce a key, or break the document structure.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not isinstance(value, str):
        raise ProjectionVocabularyError("frontmatter_value")

    text = value
    if len(text) > MAX_FIELD_LENGTH:
        text = text[:MAX_FIELD_LENGTH]
    characters = ['"']
    for character in text:
        code = ord(character)
        if character == "\\":
            characters.append("\\\\")
        elif character == '"':
            characters.append('\\"')
        elif character == "\n":
            characters.append("\\n")
        elif character == "\r":
            characters.append("\\r")
        elif character == "\t":
            characters.append("\\t")
        elif code < 0x20 or code == 0x7F:
            characters.append(f"\\x{code:02x}")
        else:
            characters.append(character)
    characters.append('"')
    return "".join(characters)


def _yaml_value(value: Any) -> str:
    """Serialize a frontmatter value: scalar, or a deterministic inline list."""
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(item) for item in value) + "]"
    return _yaml_scalar(value)


def render_frontmatter(fields: Mapping[str, Any]) -> str:
    """Serialize the CLOSED frontmatter field set in its fixed §8 order.

    A missing or unexpected key fails closed. The delimiters are emitted by this
    serializer, never by content.
    """
    unexpected = set(fields) - set(FRONTMATTER_FIELDS)
    if unexpected:
        raise ProjectionVocabularyError("frontmatter_field")
    lines = ["---"]
    for key in FRONTMATTER_FIELDS:
        if key not in fields:
            raise ProjectionVocabularyError("frontmatter_field")
        lines.append(f"{key}: {_yaml_value(fields[key])}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Small deterministic body helpers
# ---------------------------------------------------------------------------

def _bullet(label: str, value: Any) -> str:
    """One ``- **Label:** value`` line. The label is a closed literal."""
    return f"- **{label}:** {escape_inline(value)}"


def _identifier_list(raw: Any) -> Tuple[str, ...]:
    """Split a comma-joined M4 identifier string into a deterministic tuple.

    Order is preserved verbatim as recorded (it is authoritative data, not a
    presentation choice); blanks are dropped and duplicates are kept, because
    rewriting authoritative content is not this layer's job.
    """
    flattened = _flatten(raw)
    if flattened is None:
        return ()
    return tuple(part.strip() for part in flattened.split(",") if part.strip())


def _safe_artifact_refs(raw: Any) -> Tuple[str, ...]:
    """Artifact references that pass the VERIFIED M4 safe-reference guard.

    Reuses ``is_safe_reference`` (docs/plans/plan-m9.md §11.3.3) rather than reimplementing
    it, so an absolute path, a traversal fragment, a raw transcript, or a
    secret-shaped value never reaches the vault as a reference.
    """
    return tuple(ref for ref in _identifier_list(raw) if is_safe_reference(ref))


def _attribute(record: Any, name: str) -> Any:
    return getattr(record, name, None)


def _conflict_status(lifecycle_status: Optional[str]) -> str:
    return CONFLICT_CONFLICTED if lifecycle_status == "conflicted" else CONFLICT_NONE


def _join_field(records: Optional[Sequence[Any]], field: str) -> Optional[str]:
    """Comma-join one authoritative id field across records, or ``None``.

    A ``None`` record sequence means "this resource type was not in scope" and
    is kept distinguished from an empty sequence ("in scope, nothing recorded")
    by returning ``None`` rather than ``""`` (docs/plans/plan-m9.md §7.1).
    """
    if records is None:
        return None
    ids = [str(_attribute(item, field)) for item in records
           if _attribute(item, field)]
    return ", ".join(ids) if ids else None


def _extract_session_id(record: Any) -> Optional[str]:
    return _attribute(record, "session_id")


def _needs_rebuild(record: Any) -> bool:
    """True iff M4 explicitly recorded a supersession/replacement relation.

    The relation must be EXPLICIT in canonical data — never inferred from
    recency, mtime, note version, calibration score, insertion order, or graph
    structure (docs/plans/plan-m9.md §20).
    """
    for name in ("replaced_by", "superseded_by", "supersedes", "supersedes_id"):
        if _attribute(record, name):
            return True
    return False


# ---------------------------------------------------------------------------
# M9.3 — links (navigation only; never authorization, truth, or resolution)
# ---------------------------------------------------------------------------

#: Rendered in a link position when the reference resolves to nothing this
#: request authorized. It is byte-identical for "withheld", "not recorded", and
#: "malformed", so no reader can infer that something exists but is hidden.
UNRESOLVED_LINK_MARKER: Final[str] = "(not available)"


def _link_or_marker(registry: Optional[LinkRegistry],
                    resource_type: str,
                    resource_id: Any,
                    *,
                    display: Any = None) -> str:
    """Render a wiki link when the target is authorized, else a neutral marker.

    This is the single choke point for every link in the projection, and it is
    where the existence-leak guarantee lives: the ``None`` branch is taken
    identically whether the target was withheld, never recorded, or malformed,
    and it emits no identifier, count, path, or relation metadata.
    """
    if registry is None:
        return UNRESOLVED_LINK_MARKER
    target = registry.resolve(resource_type, resource_id)
    if target is None:
        return UNRESOLVED_LINK_MARKER
    return wiki_link(target, display=display)


def _link_list(registry: Optional[LinkRegistry],
               resource_type: str,
               raw: Any) -> str:
    """Render a comma-joined M4 identifier field as authorized links.

    Unauthorized entries collapse to the same neutral marker as any other
    unresolvable reference. The rendered item COUNT therefore equals the number
    of recorded references, not the number of authorized ones — the visible
    output never reveals which subset was authorized, and never publishes a
    hidden count.
    """
    references = _identifier_list(raw)
    if not references:
        return NONE_MARKER
    return ", ".join(
        _link_or_marker(registry, resource_type, reference, display=reference)
        for reference in references
    )


# ---------------------------------------------------------------------------
# M9.3 — provenance (authorized source data only)
# ---------------------------------------------------------------------------

def _provenance_block(*,
                      note_id: str,
                      resource_type: str,
                      resource_id: Any,
                      project_id: Any,
                      profile_id: Any,
                      lifecycle_status: Any,
                      verification_status: Any,
                      conflict_status: str,
                      supersedes: Any,
                      replaced_by: Any,
                      source_event_ids: Sequence[str],
                      source_trace_ids: Sequence[str],
                      session_id: Any = None,
                      artifact_refs: Sequence[str] = ()) -> str:
    """The audit block carried by EVERY projected note (docs/plans/plan-m9.md §M9.3).

    Contains only fields the request already authorized and the record itself
    carries. Deterministic: fixed label order from a closed literal list, and
    list values rendered in their recorded order. A field the record does not
    carry renders as ``(none)`` rather than being omitted (which would make two
    different records' provenance blocks structurally indistinguishable) or
    invented.

    Deliberately absent: absolute paths, grant identifiers, rowids, cursors,
    hidden sibling counts, and any wall-clock generation timestamp.
    """
    lines = [
        _bullet("Note ID", note_id),
        _bullet("Resource type", resource_type),
        _bullet("Resource ID", resource_id),
        _bullet("Project", project_id),
        _bullet("Profile", profile_id),
        _bullet("Lifecycle", lifecycle_status),
        _bullet("Verification status", verification_status),
        _bullet("Conflict status", conflict_status),
        _bullet("Supersedes", supersedes),
        _bullet("Replaced by", replaced_by),
        _bullet("Session", session_id),
        _bullet("Source events", ", ".join(source_event_ids) if source_event_ids else None),
        _bullet("Source traces", ", ".join(source_trace_ids) if source_trace_ids else None),
        _bullet("Artifact references", ", ".join(artifact_refs) if artifact_refs else None),
        _bullet("Projection version", PROJECTION_VERSION),
    ]
    return "## Provenance\n\n" + "\n".join(lines)



def _status_callouts(lifecycle_status: Optional[str],
                     replaced_by: Optional[str]) -> Tuple[str, ...]:
    """Minimal, honest status banners (docs/plans/plan-m9.md §19/§20 boundary for M9.2).

    A conflicted record must never read as a clean current fact, and a
    superseded record must never read as current. M9.2 states the recorded
    status and stops there: it picks no winner, resolves nothing, links no
    chain, and infers no supersession. Full presentation is M9.3.
    """
    callouts = []
    if lifecycle_status == "conflicted":
        callouts.append(
            "> [!warning] Unresolved conflict\n"
            "> This record is recorded as conflicted in Zero-Mem. It is NOT a "
            "settled current fact, and this projection does not choose a winner."
        )
    if lifecycle_status == "superseded":
        callouts.append(
            "> [!info] Superseded\n"
            f"> This record is recorded as superseded. Replaced by: "
            f"{escape_inline(replaced_by)}."
        )
    if lifecycle_status == "archived":
        callouts.append(
            "> [!info] Archived\n"
            "> This record is archived and is not current project truth."
        )
    return tuple(callouts)


_PROVENANCE_NOTE: Final[str] = (
    "> [!note] Generated projection\n"
    "> This note is a derived, rebuildable projection of Zero-Mem canonical "
    "memory. Canonical JSONL traces and the approved project-memory records "
    "remain authoritative; editing this file changes nothing upstream."
)


def _sections(*blocks: Optional[str]) -> str:
    """Join non-empty blocks with exactly one blank line, one trailing newline."""
    present = [block.rstrip("\n") for block in blocks if block]
    return "\n\n".join(present) + "\n"


def _build_note(
    *,
    note_type: NoteType,
    resource_type: str,
    resource_id: str,
    project_id: Optional[str],
    profile_id: Optional[str],
    display_title: Optional[str],
    scope: Optional[str],
    lifecycle_status: Optional[str],
    verification_status: Optional[str],
    supersedes: Optional[str],
    replaced_by: Optional[str],
    source_trace_ids: Sequence[str],
    source_event_ids: Sequence[str],
    artifact_refs: Sequence[str],
    body: str,
) -> ProjectedNote:
    """Assemble one note: identity, path, frontmatter, body, fingerprint.

    ``content_fingerprint`` in the FRONTMATTER is the fingerprint of the rendered
    BODY (docs/plans/plan-m9.md §14.1: "hash of the rendered managed body"); it must exclude
    the frontmatter because it lives inside it. The fingerprint carried on the
    :class:`ProjectedNote` value is the M9.1 contract's whole-file fingerprint.
    Both are deterministic and neither carries truth semantics.
    """
    resolved_type = validate_note_type(note_type)
    validated_resource_type = validate_resource_type(resource_type)
    note_id = derive_note_id(
        note_type=resolved_type,
        resource_type=validated_resource_type,
        resource_id=resource_id,
        project_id=project_id,
        profile_id=profile_id,
    )
    filename = note_filename(note_id=note_id, display_title=display_title)
    category = NOTE_TYPE_DIRECTORIES[resolved_type]
    relative_path = f"{category}/{slug(scope, fallback='unscoped')}/{filename}"

    body_text = body if body.endswith("\n") else body + "\n"
    frontmatter = render_frontmatter({
        MANAGED_MARKER_KEY: True,
        "note_id": note_id,
        "note_type": resolved_type.value,
        "projection_version": PROJECTION_VERSION,
        "content_fingerprint": content_fingerprint(body_text),
        "resource_type": validated_resource_type,
        "resource_id": resource_id,
        "project_id": project_id,
        "profile_id": profile_id,
        # M4 project-memory records carry no knowledge-space dimension at v9.
        # An empty list is emitted verbatim rather than inferring membership
        # from the request scope, the vault folder, or a co-located note.
        "knowledge_spaces": [],
        "lifecycle_status": lifecycle_status,
        "verification_status": verification_status,
        "conflict_status": _conflict_status(lifecycle_status),
        "supersedes": supersedes,
        "replaced_by": replaced_by,
        "source_trace_ids": list(source_trace_ids),
        "source_event_ids": list(source_event_ids),
        "artifact_refs": list(artifact_refs),
        "generated_by": GENERATED_BY,
    })

    content = frontmatter + "\n" + body_text
    return ProjectedNote(
        note_id=note_id,
        note_type=resolved_type,
        relative_path=relative_path,
        content=content,
        content_fingerprint=content_fingerprint(content),
        # Source identity for the M9.4 manifest. These are the SAME values the
        # identity derivation above consumed, so the manifest can never disagree
        # with the note_id, and resource_type is carried verbatim (M6.6).
        resource_type=validated_resource_type,
        resource_id=resource_id,
        project_id=project_id,
        source_trace_ids=tuple(source_trace_ids),
    )


# ---------------------------------------------------------------------------
# Project Home
# ---------------------------------------------------------------------------

def render_project_home(
    *,
    project_id: str,
    charter: Any,
    state_rows: Optional[Sequence[Any]] = None,
    decisions: Optional[Sequence[Any]] = None,
    requirements: Optional[Sequence[Any]] = None,
    verifications: Optional[Sequence[Any]] = None,
    registry: Optional[LinkRegistry] = None,
) -> ProjectedNote:
    """Render the Project Home entry point from authoritative records only.

    Every section is built from structured M4 fields. Nothing is summarized,
    paraphrased, inferred, or invented: an absent optional value renders as
    ``(none)`` and an absent collection renders its section as an explicit
    empty list. No LLM is involved, and none may ever be.

    A collection argument of ``None`` means "this resource type was not part of
    the request, or its authorized read produced nothing to show", and its
    section is omitted entirely — a denial leaves no stub, no count, and no
    placeholder (docs/plans/plan-m9.md §7.1).

    Identity is bound to the PROJECT (``resource_id=project_id``), not to the
    versioned charter row: a Home note must stay stable across charter versions,
    and M9.2 has no retirement mechanism to clean up an orphaned predecessor
    (retirement is M9.4). The charter's own identity is carried in the body and
    in the provenance fields.
    """
    charter_lifecycle = _attribute(charter, "lifecycle_status")
    title = f"{project_id} — Project Home"

    identity_lines = [
        _bullet("Project ID", project_id),
        _bullet("Charter ID", _attribute(charter, "charter_id")),
        _bullet("Name", _attribute(charter, "name")),
        _bullet("Goal", _attribute(charter, "goal")),
        _bullet("Scope", _attribute(charter, "scope")),
        _bullet("Non-goals", _attribute(charter, "non_goals")),
        _bullet("Constraints", _attribute(charter, "constraints")),
        _bullet("Architecture principles",
                _attribute(charter, "architecture_principles")),
        _bullet("Success criteria", _attribute(charter, "success_criteria")),
        _bullet("Charter version", _attribute(charter, "version")),
        _bullet("Charter lifecycle", charter_lifecycle),
        _bullet("Charter state", _attribute(charter, "state")),
    ]
    identity = "## Project\n\n" + "\n".join(identity_lines)

    state_block = None
    if state_rows is not None:
        rows = [
            f"- **{escape_inline(_attribute(row, 'state_key'))}:** "
            f"{escape_inline(_attribute(row, 'state_value'))} "
            f"(verification: {escape_inline(_attribute(row, 'verification_status'))})"
            for row in state_rows
        ]
        state_block = "## Current state\n\n" + (
            "\n".join(rows) if rows else "- " + NONE_MARKER
        )

    decision_block = None
    if decisions is not None:
        rows = [
            f"- {escape_inline(_attribute(item, 'decision_id'))} — "
            f"{escape_inline(_attribute(item, 'statement'))} "
            f"(lifecycle: {escape_inline(_attribute(item, 'lifecycle_status'))})"
            for item in decisions
        ]
        decision_block = f"## Decisions ({len(rows)})\n\n" + (
            "\n".join(rows) if rows else "- " + NONE_MARKER
        )

    requirement_block = None
    if requirements is not None:
        rows = [
            f"- {escape_inline(_attribute(item, 'requirement_id'))} — "
            f"{escape_inline(_attribute(item, 'statement'))} "
            f"(lifecycle: {escape_inline(_attribute(item, 'lifecycle_status'))})"
            for item in requirements
        ]
        requirement_block = f"## Requirements ({len(rows)})\n\n" + (
            "\n".join(rows) if rows else "- " + NONE_MARKER
        )

    verification_block = None
    if verifications is not None:
        counts: dict[str, int] = {}
        for item in verifications:
            key = _attribute(item, "verification_status") or "none"
            counts[key] = counts.get(key, 0) + 1
        rows = [
            f"- **{escape_inline(status)}:** {counts[status]}"
            for status in sorted(counts)
        ]
        verification_block = f"## Verification records ({len(list(verifications))})\n\n" + (
            "\n".join(rows) if rows else "- " + NONE_MARKER
        )

    trace_ids = tuple(t for t in (_attribute(charter, "trace_id"),) if t)
    event_ids = tuple(e for e in (_attribute(charter, "source_event_id"),) if e)
    provenance = _provenance_block(
        note_id=derive_note_id(
            note_type=NoteType.PROJECT, resource_type="charter",
            resource_id=project_id, project_id=project_id, profile_id=None,
        ),
        resource_type="charter",
        resource_id=project_id,
        project_id=project_id,
        profile_id=_attribute(charter, "profile_id"),
        lifecycle_status=charter_lifecycle,
        verification_status=None,
        conflict_status=_conflict_status(charter_lifecycle),
        supersedes=_attribute(charter, "supersedes"),
        replaced_by=None,
        source_event_ids=event_ids,
        source_trace_ids=trace_ids,
        session_id=_attribute(charter, "session_id"),
        artifact_refs=(),
    )

    # M9.3 — optional deterministic cross-note links (navigation only).
    if registry is not None:
        link_rows = []
        if decisions is not None:
            link_rows.append(_bullet(
                "Decisions", _link_list(registry, "decision",
                                       _join_field(decisions, "decision_id"))))
        if requirements is not None:
            link_rows.append(_bullet(
                "Requirements", _link_list(registry, "requirement",
                                           _join_field(requirements, "requirement_id"))))
        if verifications is not None:
            link_rows.append(_bullet(
                "Verifications", _link_list(registry, "verification",
                                            _join_field(verifications, "verification_id"))))
        links = "## Links\n\n" + (
            "\n".join(link_rows) if link_rows else f"- {NONE_MARKER}")
        body = _sections(
            f"# {escape_inline(title)}",
            _PROVENANCE_NOTE,
            *_status_callouts(charter_lifecycle, _attribute(charter, "supersedes")),
            identity,
            state_block,
            decision_block,
            requirement_block,
            verification_block,
            links,
            provenance,
        )
    else:
        body = _sections(
            f"# {escape_inline(title)}",
            _PROVENANCE_NOTE,
            *_status_callouts(charter_lifecycle, _attribute(charter, "supersedes")),
            identity,
            state_block,
            decision_block,
            requirement_block,
            verification_block,
            provenance,
        )

    return _build_note(
        note_type=NoteType.PROJECT,
        resource_type="charter",
        resource_id=project_id,
        project_id=project_id,
        profile_id=_attribute(charter, "profile_id"),
        display_title=title,
        scope=project_id,
        lifecycle_status=charter_lifecycle,
        verification_status=None,
        supersedes=_attribute(charter, "supersedes"),
        replaced_by=None,
        source_trace_ids=trace_ids,
        source_event_ids=event_ids,
        artifact_refs=(),
        body=body,
    )


# ---------------------------------------------------------------------------
# Project State
# ---------------------------------------------------------------------------

def render_project_state(*, project_id: str,
                         state_rows: Sequence[Any]) -> ProjectedNote:
    """Render the authoritative current project state.

    The rows come from the authoritative project-state substrate via the M5
    authorized read (``m4_current_state``), which selects on the stored
    ``lifecycle_status='active'`` slot. Current state is NEVER derived here from
    a newer timestamp, a file mtime, insertion order, a calibration score, graph
    centrality, the latest trace, or the most recent assistant claim.

    Like Project Home, identity is bound to the project rather than to any one
    state row, because this note is the project's aggregate current-state view.
    """
    title = f"{project_id} — Project State"

    header = (
        "| Key | Value | Lifecycle | Verification | Effective at |\n"
        "| --- | --- | --- | --- | --- |"
    )
    rows = [
        "| {key} | {value} | {lifecycle} | {verification} | {effective} |".format(
            key=escape_inline(_attribute(row, "state_key")),
            value=escape_inline(_attribute(row, "state_value")),
            lifecycle=escape_inline(_attribute(row, "lifecycle_status")),
            verification=escape_inline(_attribute(row, "verification_status")),
            effective=escape_inline(_attribute(row, "effective_at")),
        )
        for row in state_rows
    ]
    table = "## Current state\n\n" + (
        header + "\n" + "\n".join(rows) if rows else "- " + NONE_MARKER
    )

    trace_ids = tuple(
        t for t in (_attribute(row, "trace_id") for row in state_rows) if t
    )
    event_ids = tuple(
        e for e in (_attribute(row, "source_event_id") for row in state_rows) if e
    )
    provenance = _provenance_block(
        note_id=derive_note_id(
            note_type=NoteType.PROJECT, resource_type="state",
            resource_id=project_id, project_id=project_id, profile_id=None,
        ),
        resource_type="state",
        resource_id=project_id,
        project_id=project_id,
        profile_id=None,
        lifecycle_status="active",
        verification_status=None,
        conflict_status=CONFLICT_NONE,
        supersedes=None,
        replaced_by=None,
        source_event_ids=event_ids,
        source_trace_ids=trace_ids,
        artifact_refs=(),
    )

    body = _sections(
        f"# {escape_inline(title)}",
        _PROVENANCE_NOTE,
        table,
        provenance,
    )

    return _build_note(
        note_type=NoteType.PROJECT,
        resource_type="state",
        resource_id=project_id,
        project_id=project_id,
        # An aggregate project view is not owned by a single profile, and a
        # profile is never inferred from the rows it happens to contain.
        profile_id=None,
        display_title=title,
        scope=project_id,
        lifecycle_status="active",
        verification_status=None,
        supersedes=None,
        replaced_by=None,
        source_trace_ids=trace_ids,
        source_event_ids=event_ids,
        artifact_refs=(),
        body=body,
    )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def render_decision(decision: Any,
                     registry: Optional[LinkRegistry] = None) -> ProjectedNote:
    """Render one authoritative Decision record.

    Supersession is rendered from the explicit ``supersedes_id`` /
    ``replaced_by`` fields ONLY. It is never inferred from effective_at
    ordering, note ordering, file mtime, or M8 temporal recency, and a
    conflicted decision is never presented as resolved.
    """
    decision_id = _attribute(decision, "decision_id")
    lifecycle = _attribute(decision, "lifecycle_status")
    statement = _attribute(decision, "statement")
    display_title = statement or decision_id

    record = "## Record\n\n" + "\n".join([
        _bullet("Decision ID", decision_id),
        _bullet("Statement", statement),
        _bullet("Project", _attribute(decision, "project_id")),
        _bullet("Scope", _attribute(decision, "scope")),
        _bullet("Decision key", _attribute(decision, "decision_key")),
        _bullet("Lifecycle", lifecycle),
        _bullet("State", _attribute(decision, "state")),
        _bullet("Effective at", _attribute(decision, "effective_at")),
        _bullet("Rationale reference", _attribute(decision, "rationale_ref")),
        _bullet("Alternatives", _attribute(decision, "alternatives")),
    ])

    supersession = "## Supersession\n\n" + "\n".join([
        _bullet("Supersedes", _attribute(decision, "supersedes_id")),
        _bullet("Replaced by", _attribute(decision, "replaced_by")),
    ])

    linked = "## Linked records\n\n" + "\n".join([
        _bullet("Requirements", _link_list(
            registry, "requirement", _attribute(decision, "linked_requirement_ids"))),
        _bullet("Artifacts", _link_list(
            registry, "artifact", _attribute(decision, "linked_artifact_ids"))),
        _bullet("Verifications", _link_list(
            registry, "verification", _attribute(decision, "linked_verification_ids"))),
    ])

    trace_id = _attribute(decision, "trace_id")
    event_id = _attribute(decision, "source_event_id")
    provenance = _provenance_block(
        note_id=derive_note_id(
            note_type=NoteType.DECISION, resource_type="decision",
            resource_id=decision_id,
            project_id=_attribute(decision, "project_id"),
            profile_id=_attribute(decision, "profile_id"),
        ),
        resource_type="decision",
        resource_id=decision_id,
        project_id=_attribute(decision, "project_id"),
        profile_id=_attribute(decision, "profile_id"),
        lifecycle_status=lifecycle,
        verification_status=None,
        conflict_status=_conflict_status(lifecycle),
        supersedes=_attribute(decision, "supersedes_id"),
        replaced_by=_attribute(decision, "replaced_by"),
        source_event_ids=(event_id,) if event_id else (),
        source_trace_ids=(trace_id,) if trace_id else (),
        session_id=_attribute(decision, "session_id"),
        artifact_refs=_safe_artifact_refs(_attribute(decision, "linked_artifact_ids")),
    )

    body = _sections(
        f"# Decision: {escape_inline(display_title)}",
        _PROVENANCE_NOTE,
        *_status_callouts(lifecycle, _attribute(decision, "replaced_by")),
        record,
        supersession,
        linked,
        provenance,
    )

    return _build_note(
        note_type=NoteType.DECISION,
        resource_type="decision",
        resource_id=decision_id,
        project_id=_attribute(decision, "project_id"),
        profile_id=_attribute(decision, "profile_id"),
        display_title=display_title,
        scope=_attribute(decision, "project_id"),
        lifecycle_status=lifecycle,
        # A Decision record carries no verification dimension at v9. Emitting
        # null is honest; inventing "verified" from a linked verification would
        # be exactly the claim-to-verification promotion M9 forbids.
        verification_status=None,
        supersedes=_attribute(decision, "supersedes_id"),
        replaced_by=_attribute(decision, "replaced_by"),
        source_trace_ids=(trace_id,) if trace_id else (),
        source_event_ids=(event_id,) if event_id else (),
        artifact_refs=_safe_artifact_refs(_attribute(decision, "linked_artifact_ids")),
        body=body,
    )


# ---------------------------------------------------------------------------
# Requirement
# ---------------------------------------------------------------------------

def render_requirement(requirement: Any,
                       registry: Optional[LinkRegistry] = None) -> ProjectedNote:
    """Render one authoritative Requirement record.

    A requirement exists here only because an authoritative requirement record
    exists upstream. Prose containing "must", "should", "requirement", or "TODO"
    never becomes a requirement in this layer — there is no text rule, no
    extractor, and no classifier anywhere in it.
    """
    requirement_id = _attribute(requirement, "requirement_id")
    lifecycle = _attribute(requirement, "lifecycle_status")
    statement = _attribute(requirement, "statement")
    display_title = statement or requirement_id

    record = "## Record\n\n" + "\n".join([
        _bullet("Requirement ID", requirement_id),
        _bullet("Statement", statement),
        _bullet("Project", _attribute(requirement, "project_id")),
        _bullet("Lifecycle", lifecycle),
        _bullet("State", _attribute(requirement, "state")),
        _bullet("Verification status", _attribute(requirement, "verification_status")),
        _bullet("Created at", _attribute(requirement, "created_at")),
    ])

    supersession = "## Supersession\n\n" + "\n".join([
        _bullet("Supersedes", _attribute(requirement, "supersedes")),
        _bullet("Replaced by", _attribute(requirement, "replaced_by")),
    ])

    trace_id = _attribute(requirement, "trace_id")
    event_id = _attribute(requirement, "source_event_id")
    linked = "## Linked records\n\n" + "\n".join([
        _bullet("Decisions", _link_list(
            registry, "decision", _attribute(requirement, "linked_decision_ids"))),
        _bullet("Artifacts", _link_list(
            registry, "artifact", _attribute(requirement, "linked_artifact_ids"))),
        _bullet("Verifications", _link_list(
            registry, "verification", _attribute(requirement, "linked_verification_ids"))),
    ])

    provenance = _provenance_block(
        note_id=derive_note_id(
            note_type=NoteType.REQUIREMENT, resource_type="requirement",
            resource_id=requirement_id,
            project_id=_attribute(requirement, "project_id"),
            profile_id=_attribute(requirement, "profile_id"),
        ),
        resource_type="requirement",
        resource_id=requirement_id,
        project_id=_attribute(requirement, "project_id"),
        profile_id=_attribute(requirement, "profile_id"),
        lifecycle_status=lifecycle,
        verification_status=_attribute(requirement, "verification_status"),
        conflict_status=_conflict_status(lifecycle),
        supersedes=_attribute(requirement, "supersedes"),
        replaced_by=_attribute(requirement, "replaced_by"),
        source_event_ids=(event_id,) if event_id else (),
        source_trace_ids=(trace_id,) if trace_id else (),
        session_id=_attribute(requirement, "session_id"),
        artifact_refs=_safe_artifact_refs(
            _attribute(requirement, "linked_artifact_ids")),
    )

    body = _sections(
        f"# Requirement: {escape_inline(display_title)}",
        _PROVENANCE_NOTE,
        *_status_callouts(lifecycle, _attribute(requirement, "replaced_by")),
        record,
        supersession,
        linked,
        provenance,
    )

    return _build_note(
        note_type=NoteType.REQUIREMENT,
        resource_type="requirement",
        resource_id=requirement_id,
        project_id=_attribute(requirement, "project_id"),
        profile_id=_attribute(requirement, "profile_id"),
        display_title=display_title,
        scope=_attribute(requirement, "project_id"),
        lifecycle_status=lifecycle,
        verification_status=_attribute(requirement, "verification_status"),
        supersedes=_attribute(requirement, "supersedes"),
        replaced_by=_attribute(requirement, "replaced_by"),
        source_trace_ids=(trace_id,) if trace_id else (),
        source_event_ids=(event_id,) if event_id else (),
        artifact_refs=_safe_artifact_refs(
            _attribute(requirement, "linked_artifact_ids")
        ),
        body=body,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def render_verification(verification: Any) -> ProjectedNote:
    """Render one authoritative Verification record.

    A Verification note is a record of a check that was performed, rendered
    verbatim. Projection never upgrades anything into one: an assistant claim,
    an inference, a user statement, a high calibration score, and a newer
    timestamp all remain exactly what they were. ``verification_status`` is
    copied, never computed.
    """
    verification_id = _attribute(verification, "verification_id")

    record = "## Record\n\n" + "\n".join([
        _bullet("Verification ID", verification_id),
        _bullet("Project", _attribute(verification, "project_id")),
        _bullet("Subject type", _attribute(verification, "subject_type")),
        _bullet("Subject ID", _attribute(verification, "subject_id")),
        _bullet("Method", _attribute(verification, "method")),
        _bullet("Command reference", _attribute(verification, "command_ref")),
        _bullet("Observed result", _attribute(verification, "observed_result")),
        _bullet("Tested commit", _attribute(verification, "tested_commit")),
        _bullet("Verification status", _attribute(verification, "verification_status")),
        _bullet("Recorded at", _attribute(verification, "timestamp")),
        _bullet("Artifact references", _attribute(verification, "artifact_references")),
    ])

    caveat = (
        "> [!note] Verification record\n"
        "> This records a check that was performed and its recorded status. It "
        "is not a truth score, and it does not verify anything beyond its own "
        "recorded subject."
    )

    event_id = _attribute(verification, "source_event_id")
    provenance = _provenance_block(
        note_id=derive_note_id(
            note_type=NoteType.VERIFICATION, resource_type="verification",
            resource_id=verification_id,
            project_id=_attribute(verification, "project_id"),
            profile_id=None,
        ),
        resource_type="verification",
        resource_id=verification_id,
        project_id=_attribute(verification, "project_id"),
        profile_id=None,
        lifecycle_status=None,
        verification_status=_attribute(verification, "verification_status"),
        conflict_status=CONFLICT_NONE,
        supersedes=None,
        replaced_by=None,
        source_event_ids=(event_id,) if event_id else (),
        source_trace_ids=(),
        session_id=_attribute(verification, "session_id"),
        artifact_refs=_safe_artifact_refs(
            _attribute(verification, "artifact_references")
        ),
    )

    body = _sections(
        f"# Verification: {escape_inline(verification_id)}",
        _PROVENANCE_NOTE,
        caveat,
        record,
        provenance,
    )

    return _build_note(
        note_type=NoteType.VERIFICATION,
        resource_type="verification",
        resource_id=verification_id,
        project_id=_attribute(verification, "project_id"),
        # A verification record carries no profile dimension at v9; a profile is
        # never inferred from its subject, its project, or its source event.
        profile_id=None,
        display_title=verification_id,
        scope=_attribute(verification, "project_id"),
        # Nor a lifecycle dimension: emitting null is honest, whereas defaulting
        # to "active" would invent a state the canonical record never recorded.
        lifecycle_status=None,
        verification_status=_attribute(verification, "verification_status"),
        supersedes=None,
        replaced_by=None,
        source_trace_ids=(),
        source_event_ids=(event_id,) if event_id else (),
        artifact_refs=_safe_artifact_refs(
            _attribute(verification, "artifact_references")
        ),
        body=body,
    )


# ---------------------------------------------------------------------------
# M9.3 — conflict presentation (AUTHORIZED positions only; no winner, no leak)
# ---------------------------------------------------------------------------

#: Fixed, deterministic ordering of the position fields. No item here ranks the
#: positions; the order is a presentation convention and is stated as such in
#: the rendered note so a reader cannot mistake it for precedence.
_POSITION_FIELDS: Final[Tuple[Tuple[str, str], ...]] = (
    ("Decision ID", "decision_id"),
    ("Statement", "statement"),
    ("Project", "project_id"),
    ("Scope", "scope"),
    ("Decision key", "decision_key"),
    ("Lifecycle", "lifecycle_status"),
    ("State", "state"),
    ("Effective at", "effective_at"),
    ("Rationale reference", "rationale_ref"),
    ("Alternatives", "alternatives"),
    ("Source event", "source_event_id"),
    ("Trace", "trace_id"),
)

_UNRESOLVED_NOTE: Final[str] = (
    "> [!warning] Unresolved conflict\n"
    "> These positions are recorded as conflicted in Zero-Mem. No position is "
    "selected as the winner; this projection does not resolve, rank, score, or "
    "choose among them. Resolve through the authoritative process."
)


def _position_block(record: Any) -> str:
    """One authorized position, verbatim. No derived ordering, no winner flag."""
    lines = [_bullet(label, _attribute(record, field))
             for label, field in _POSITION_FIELDS]
    return "\n".join(lines)


def render_conflict(group: ConflictGroup) -> ProjectedNote:
    """Render one Conflict note for an AUTHORIZED conflict group (docs/plans/plan-m9.md §19).

    Every position present is from the already-authorized record set, so a
    hidden position cannot appear, change the count, change the key, or imply a
    hidden sibling through wording. The note states verbatim that the conflict
    is UNRESOLVED and that no winner is chosen. It never promotes the highest-
    scoring, newest, or most-calibrated item, and it never collapses the
    conflict into a supersession.
    """
    group_id = conflict_resource_id(group)
    title = f"Conflict: {group.display_key or group.conflict_key}"

    position_blocks = [
        f"### Position {idx + 1} (ID: {escape_inline(_attribute(p, 'decision_id'))})\n\n"
        f"{_position_block(p)}"
        for idx, p in enumerate(group.positions)
    ]
    body = _sections(
        f"# {escape_inline(title)}",
        _PROVENANCE_NOTE,
        _UNRESOLVED_NOTE,
        f"> [!note] Positions\n"
        f"> {group.position_count} authorized position(s) are shown. "
        f"Position order is a fixed presentation convention and implies "
        f"no precedence, ranking, or resolution.",
        "## Positions\n\n" + "\n\n".join(position_blocks),
        _provenance_block(
            note_id=group_id,
            resource_type=group.resource_type,
            resource_id=group_id,
            project_id=group.project_id,
            profile_id=None,
            lifecycle_status=CONFLICTED_LIFECYCLE,
            verification_status=None,
            conflict_status=CONFLICT_CONFLICTED,
            supersedes=None,
            replaced_by=None,
            source_event_ids=tuple(
                e for e in (_attribute(p, "source_event_id") for p in group.positions)
                if e),
            source_trace_ids=tuple(
                t for t in (_attribute(p, "trace_id") for p in group.positions) if t),
            artifact_refs=(),
        ),
    )
    return _build_note(
        note_type=NoteType.CONFLICT,
        resource_type=group.resource_type,
        resource_id=group_id,
        project_id=group.project_id,
        profile_id=None,
        display_title=title,
        scope=group.project_id,
        lifecycle_status=CONFLICTED_LIFECYCLE,
        verification_status=None,
        supersedes=None,
        replaced_by=None,
        source_trace_ids=(),
        source_event_ids=(),
        artifact_refs=(),
        body=body,
    )


def render_conflict_index(*, resource_type: str,
                          groups: Sequence[ConflictGroup]) -> ProjectedNote:
    """Render the per-resource-type UNRESOLVED Conflict index (docs/plans/plan-m9.md §19).

    This is the M9.3 "Conflict Queue" deliverable, represented WITHOUT a new
    public note type: it is an aggregate Conflict note (NoteType.CONFLICT), the
    only owner-approved conflict projection type (docs/plans/plan-m9.md §29 Q1). Its
    note_id is a stable aggregate identity, so M9.1 identity/filename contracts
    still apply and M9.4's manifest will treat it as a single managed note.

    An index of conflicts this request is authorized to see. It links each
    conflict to its note (navigation only) and states the position count per
    conflict. A conflict the request may not see is absent, and the index never
    publishes a total-of-all-conflicts count that would leak hidden conflicts.
    """
    validated_type = validate_resource_type(resource_type)
    title = f"Unresolved Conflicts — {validated_type}"
    rows = []
    for group in sorted(groups, key=lambda g: conflict_resource_id(g)):
        link = _link_or_marker(
            None, validated_type, group.conflict_key, display=group.display_key)
        rows.append(
            f"- {escape_inline(group.display_key or group.conflict_key)}: "
            f"{group.position_count} position(s) — {link}")
    queue = "## Unresolved conflicts\n\n" + (
        "\n".join(rows) if rows else f"- {NONE_MARKER}")
    body = _sections(
        f"# {escape_inline(title)}",
        _PROVENANCE_NOTE,
        _UNRESOLVED_NOTE,
        "> [!note] Scope\n"
        "> Each entry lists only the conflicts this request is authorized to "
        "see. The absence of an entry means no authorized conflict of this "
        "type is present; it does not imply the absence of conflicts "
        "elsewhere or outside this request's scope.",
        queue,
        _provenance_block(
            note_id=f"conflict-index:{validated_type}",
            resource_type=validated_type,
            resource_id=f"conflict-index:{validated_type}",
            project_id=None,
            profile_id=None,
            lifecycle_status=CONFLICTED_LIFECYCLE,
            verification_status=None,
            conflict_status=CONFLICT_CONFLICTED,
            supersedes=None,
            replaced_by=None,
            source_event_ids=(),
            source_trace_ids=(),
            artifact_refs=(),
        ),
    )
    return _build_note(
        note_type=NoteType.CONFLICT,
        resource_type=validated_type,
        resource_id=f"conflict-index:{validated_type}",
        project_id=None,
        profile_id=None,
        display_title=title,
        scope="global",
        lifecycle_status=CONFLICTED_LIFECYCLE,
        verification_status=None,
        supersedes=None,
        replaced_by=None,
        source_trace_ids=(),
        source_event_ids=(),
        artifact_refs=(),
        body=body,
    )


__all__ = [
    "GENERATED_BY",
    "MAX_FIELD_LENGTH",
    "TRUNCATION_MARKER",
    "NONE_MARKER",
    "FRONTMATTER_FIELDS",
    "CONFLICT_NONE",
    "CONFLICT_CONFLICTED",
    "escape_inline",
    "render_frontmatter",
    "render_project_home",
    "render_project_state",
    "render_decision",
    "render_requirement",
    "render_verification",
    "render_conflict",
    "render_conflict_index",
    "UNRESOLVED_LINK_MARKER",
    "note_relative_path",
    "safe_link_display",
    "wiki_link",
]
