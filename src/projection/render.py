"""M9.2 — deterministic rendering of curated Zero-Mem notes.

Pure functions only: this module reads no store, makes no authorization
decision, touches no filesystem, and holds no state. It turns an
already-authorized, already-eligible authoritative record into an immutable
:class:`~src.projection.contracts.ProjectedNote` value.

Two structural rules make the "memory is DATA" guarantee real rather than
best-effort (plan-m9.md §22.2):

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

Deliberately NOT implemented here (later increments): wiki links and backlinks,
conflict navigation, the manifest, incremental/unchanged-write suppression,
retirement, human-edit quarantine, Research Note and Knowledge Index bodies.
M9.2 preserves a conflicted or superseded status honestly and minimally, but the
full conflict/supersession presentation belongs to M9.3.

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
from .identity import content_fingerprint, derive_note_id, note_filename, slug

# ---------------------------------------------------------------------------
# Closed rendering constants
# ---------------------------------------------------------------------------

#: Value of the ``generated_by`` provenance field (plan-m9.md §8).
GENERATED_BY: Final[str] = "zero-mem/m9"

#: Per-field length cap, mirroring the verified M7 ``_MAX_FIELD_LEN`` discipline
#: (plan-m9.md §22.1 "Length/DoS"). A 10 MB memory field cannot bloat a note.
MAX_FIELD_LENGTH: Final[int] = 2000

#: Appended verbatim (never escaped) when a field was truncated.
TRUNCATION_MARKER: Final[str] = "…[truncated]"

#: Rendered in place of a missing optional value. A missing value is shown as
#: explicitly absent rather than invented, guessed, or silently omitted.
NONE_MARKER: Final[str] = "(none)"

#: Frontmatter keys, in the exact fixed order of plan-m9.md §8. The set is
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

    Reuses ``is_safe_reference`` (plan-m9.md §11.3.3) rather than reimplementing
    it, so an absolute path, a traversal fragment, a raw transcript, or a
    secret-shaped value never reaches the vault as a reference.
    """
    return tuple(ref for ref in _identifier_list(raw) if is_safe_reference(ref))


def _attribute(record: Any, name: str) -> Any:
    return getattr(record, name, None)


def _conflict_status(lifecycle_status: Optional[str]) -> str:
    return CONFLICT_CONFLICTED if lifecycle_status == "conflicted" else CONFLICT_NONE


def _status_callouts(lifecycle_status: Optional[str],
                     replaced_by: Optional[str]) -> Tuple[str, ...]:
    """Minimal, honest status banners (plan-m9.md §19/§20 boundary for M9.2).

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
    BODY (plan-m9.md §14.1: "hash of the rendered managed body"); it must exclude
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
) -> ProjectedNote:
    """Render the Project Home entry point from authoritative records only.

    Every section is built from structured M4 fields. Nothing is summarized,
    paraphrased, inferred, or invented: an absent optional value renders as
    ``(none)`` and an absent collection renders its section as an explicit
    empty list. No LLM is involved, and none may ever be.

    A collection argument of ``None`` means "this resource type was not part of
    the request, or its authorized read produced nothing to show", and its
    section is omitted entirely — a denial leaves no stub, no count, and no
    placeholder (plan-m9.md §7.1).

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
    provenance = "## Provenance\n\n" + "\n".join([
        _bullet("Source event", _attribute(charter, "source_event_id")),
        _bullet("Trace", _attribute(charter, "trace_id")),
        _bullet("Session", _attribute(charter, "session_id")),
        _bullet("Profile", _attribute(charter, "profile_id")),
    ])

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

    provenance_rows = [
        "- {key}: event {event}, trace {trace}, profile {profile}".format(
            key=escape_inline(_attribute(row, "state_key")),
            event=escape_inline(_attribute(row, "source_event_id")),
            trace=escape_inline(_attribute(row, "trace_id")),
            profile=escape_inline(_attribute(row, "profile_id")),
        )
        for row in state_rows
    ]
    provenance = "## Provenance\n\n" + (
        "\n".join(provenance_rows) if provenance_rows else "- " + NONE_MARKER
    )

    trace_ids = tuple(
        t for t in (_attribute(row, "trace_id") for row in state_rows) if t
    )
    event_ids = tuple(
        e for e in (_attribute(row, "source_event_id") for row in state_rows) if e
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

def render_decision(decision: Any) -> ProjectedNote:
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
        _bullet("Requirements", _attribute(decision, "linked_requirement_ids")),
        _bullet("Artifacts", _attribute(decision, "linked_artifact_ids")),
        _bullet("Verifications", _attribute(decision, "linked_verification_ids")),
    ])

    provenance = "## Provenance\n\n" + "\n".join([
        _bullet("Source event", _attribute(decision, "source_event_id")),
        _bullet("Trace", _attribute(decision, "trace_id")),
        _bullet("Session", _attribute(decision, "session_id")),
        _bullet("Profile", _attribute(decision, "profile_id")),
    ])

    body = _sections(
        f"# Decision: {escape_inline(display_title)}",
        _PROVENANCE_NOTE,
        *_status_callouts(lifecycle, _attribute(decision, "replaced_by")),
        record,
        supersession,
        linked,
        provenance,
    )

    trace_id = _attribute(decision, "trace_id")
    event_id = _attribute(decision, "source_event_id")
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

def render_requirement(requirement: Any) -> ProjectedNote:
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

    linked = "## Linked records\n\n" + "\n".join([
        _bullet("Decisions", _attribute(requirement, "linked_decision_ids")),
        _bullet("Artifacts", _attribute(requirement, "linked_artifact_ids")),
        _bullet("Verifications", _attribute(requirement, "linked_verification_ids")),
    ])

    provenance = "## Provenance\n\n" + "\n".join([
        _bullet("Source event", _attribute(requirement, "source_event_id")),
        _bullet("Trace", _attribute(requirement, "trace_id")),
        _bullet("Session", _attribute(requirement, "session_id")),
        _bullet("Profile", _attribute(requirement, "profile_id")),
    ])

    body = _sections(
        f"# Requirement: {escape_inline(display_title)}",
        _PROVENANCE_NOTE,
        *_status_callouts(lifecycle, _attribute(requirement, "replaced_by")),
        record,
        supersession,
        linked,
        provenance,
    )

    trace_id = _attribute(requirement, "trace_id")
    event_id = _attribute(requirement, "source_event_id")
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

    provenance = "## Provenance\n\n" + "\n".join([
        _bullet("Source event", _attribute(verification, "source_event_id")),
    ])

    body = _sections(
        f"# Verification: {escape_inline(verification_id)}",
        _PROVENANCE_NOTE,
        caveat,
        record,
        provenance,
    )

    event_id = _attribute(verification, "source_event_id")
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
]
