"""M9.2 — deterministic projection engine.

This is the only product module that knows the full M9.2 pipeline, and it does
so by *orchestrating* verified pieces — it invents no projection semantics of
its own:

    request + config
        -> M5 AuthorizedReadService (authorization BEFORE any read)     [§2, §3]
        -> per-record sensitivity/lifecycle eligibility (eligibility.py) [§4, §15]
        -> render.* (pure, no store, no auth, no fs)                    [§1, §21]
        -> writer.write_note (verified M9.1 path + atomic write)        [§10, §25]

Hard invariants enforced here (each maps to a STOP condition in the prompt):

* **Authorization before rendering.** ``AuthorizedReadService`` is the sole
  authorization authority and is consulted before a single record is read or
  rendered. Never: read hidden material, then render it, then "authorize"
  (prompt §2, §3).
* **Unauthorized zero-influence.** The visible projection depends only on the
  authorized result set; withheld material cannot change any byte.
* **M6.6 resource_type preserved.** Each record is rendered for exactly its own
  resource_type; a grant for ``artifact`` does not silently admit or co-mingle
  ``decision``/``requirement``/``verification``/``state`` (prompt §3).
* **Sensitivity ceiling.** Default ``internal``; ``private`` and ``secret`` are
  excluded, malformed sensitivity/ceiling fail closed (prompt §4).
* **Lifecycle eligibility.** ``raw``/``observed``/``candidate`` are excluded from
  the projection; M9 never changes lifecycle state (prompt §15).
* **Canonical immutability.** The engine reads only through the authorized read
  service and the read-only store it wraps; it never writes, mutates, or deletes
  canonical JSONL, SQLite, project state, decisions, requirements, verifications,
  or authorization grants. No write-back of any kind (prompt §24).

The engine touches no filesystem itself except by delegating to
``writer.write_note`` (every disk write stays inside ``managed_root``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, List, Optional, Set, Tuple

from src.access.authorized_read import AuthorizedReadService, AuthorizedResult
from src.access.contracts import AccessRequest
from src.project_memory import reader as m4

from .config import ProjectionConfig
from .contracts import (
    NoteType,
    ProjectedNote,
    ProjectionVocabularyError,
)
from .eligibility import (
    RESOURCE_TYPES,
    default_ceiling,
    is_authorized_resource_type,
    is_eligible,
)
from .conflicts import group_conflicts
from .identity import derive_note_id
from .links import LinkRegistry, LinkTarget, note_relative_path
from .render import (
    render_conflict,
    render_conflict_queue,
    render_decision,
    render_project_home,
    render_project_state,
    render_requirement,
    render_verification,
)
from .writer import WriteOutcome, write_notes


class _ResourceType(str, Enum):
    """Mirrors the M6.6 closed resource-type vocabulary (single source of truth

    is ``eligibility.RESOURCE_TYPES``; this is a local alias only for clarity).
    """

    ARTIFACT = "artifact"
    EVENT = "event"
    DECISION = "decision"
    REQUIREMENT = "requirement"
    VERIFICATION = "verification"
    RELATION = "relation"
    STATE = "state"
    CHARTER = "charter"


#: Resource types this engine projects (the five authoritative note types of
#: M9.2). ``artifact``/``event``/``relation`` are deliberately absent: this
#: increment does not render Artifact or any Research-Note-surface resource, and
#: M9.2 must not flatten resource types that share project_id/profile_id/title.
PROJECTABLE_RESOURCE_TYPES: Final[Set[str]] = {
    _ResourceType.STATE.value,
    _ResourceType.CHARTER.value,
    _ResourceType.DECISION.value,
    _ResourceType.REQUIREMENT.value,
    _ResourceType.VERIFICATION.value,
}


@dataclass(frozen=True)
class ProjectionReport:
    """Outcome of one authorized projection run (sanitized; no secrets)."""

    notes: Tuple[ProjectedNote, ...]
    writes: Tuple[WriteOutcome, ...]
    authorized_sources: int
    projected_sources: int
    ceiling: str

    @property
    def created(self) -> int:
        return sum(1 for w in self.writes if w.written)


def _read_authorized(service: AuthorizedReadService,
                     request: AccessRequest,
                     project_id: str,
                     resource_type: str,
                     grants=None) -> Tuple[AuthorizedResult, Tuple[object, ...]]:
    """Consult M5 for exactly one resource_type. Authorization BEFORE read.

    Cross-resource-type isolation is structural: each resource type is a distinct
    M5 call with its own resource-type allow check, so a grant for ``artifact``
    cannot project a ``decision`` (prompt §3, §6).
    """
    if resource_type == _ResourceType.CHARTER.value:
        result = service.m4_charter(request, project_id, grants=grants)
    elif resource_type == _ResourceType.STATE.value:
        result = service.m4_current_state(request, project_id, grants=grants)
    elif resource_type == _ResourceType.DECISION.value:
        result = service.m4_decisions(request, project_id, grants=grants)
    elif resource_type == _ResourceType.REQUIREMENT.value:
        result = service.m4_requirements(request, project_id, grants=grants)
    elif resource_type == _ResourceType.VERIFICATION.value:
        result = service.m4_verifications(request, project_id, grants=grants)
    else:
        # Unknown resource type is refused, never silently dropped or rendered.
        raise ProjectionVocabularyError("resource_type")
    items = tuple(result.items) if (result.allowed and result.items) else ()
    return result, items


def _eligible_records(items: Tuple[object, ...],
                      ceiling: str,
                      resource_type: str) -> Tuple[object, ...]:
    """Filter authorized records by sensitivity + lifecycle eligibility only.

    Eligibility is a pure predicate over the record's own fields. It does not
    consult neighboring records, recency, scores, or any request/memory text, so
    it cannot be steered by hidden data or hostile prompt content.
    """
    kept = []
    for record in items:
        if is_eligible(record, ceiling=ceiling, resource_type=resource_type):
            kept.append(record)
    return tuple(kept)


def _build_link_registry(*,
                          decisions: Tuple[object, ...] = (),
                          requirements: Tuple[object, ...] = (),
                          verifications: Tuple[object, ...] = (),
                          state_rows: Tuple[object, ...] = (),
                          charter=None) -> LinkRegistry:
    """Build the authorized link universe from the SAME authorized+eligible set.

    The registry is populated ONLY from records this request already authorized
    and the eligibility filter already admitted. A record absent here is simply
    unaddressable as a link — it cannot be named, counted, or implied (plan-m9.md
    §5, §21). Targets are assembled from the verified M9.1 primitives and
    re-validated by the link layer, so a target can never escape ``managed_root``
    or embed hostile path/link syntax.
    """
    targets: List[LinkTarget] = []

    def _add(resource_type: str, resource_id: object, note_type, record) -> None:
        if not resource_id:
            return
        rid = str(resource_id)
        # The link's note_id is the VERIFIED M9.1 deterministic identity, never
        # the raw resource id. This keeps the link target identical to the file
        # the writer actually creates (single source of truth).
        note_id = derive_note_id(
            note_type=note_type,
            resource_type=resource_type,
            resource_id=rid,
            project_id=getattr(record, "project_id", None),
            profile_id=getattr(record, "profile_id", None),
        )
        relative = note_relative_path(
            note_type=note_type,
            note_id=note_id,
            display_title=getattr(record, "statement", None)
            or getattr(record, "verification_id", None)
            or getattr(record, "state_key", None)
            or rid,
            scope=getattr(record, "project_id", None),
        )
        targets.append(LinkTarget(
            resource_type=resource_type,
            resource_id=rid,
            note_type=note_type,
            note_id=note_id,
            relative_path=relative,
        ))

    for record in decisions:
        _add("decision", getattr(record, "decision_id", None), NoteType.DECISION, record)
    for record in requirements:
        _add("requirement", getattr(record, "requirement_id", None), NoteType.REQUIREMENT, record)
    for record in verifications:
        _add("verification", getattr(record, "verification_id", None), NoteType.VERIFICATION, record)
    for record in state_rows:
        _add("state", getattr(record, "state_key", None), NoteType.PROJECT, record)
    if charter is not None:
        pid = getattr(charter, "project_id", None) or getattr(charter, "charter_id", None)
        if pid:
            note_id = derive_note_id(
                note_type=NoteType.PROJECT,
                resource_type="charter",
                resource_id=pid,
                project_id=pid,
                profile_id=None,
            )
            relative = note_relative_path(
                note_type=NoteType.PROJECT,
                note_id=note_id,
                display_title=f"{pid} — Project Home",
                scope=pid,
            )
            targets.append(LinkTarget(
                resource_type="charter",
                resource_id=pid,
                note_type=NoteType.PROJECT,
                note_id=note_id,
                relative_path=relative,
            ))
    return LinkRegistry(targets)


def project_project_home(
    service: AuthorizedReadService,
    request: AccessRequest,
    config: ProjectionConfig,
    project_id: str,
    *,
    grants=None,
) -> Tuple[ProjectedNote, ...]:
    """Project the Project Home plus its authorized sub-collections.

    Project Home is the human-facing entry point. Each sub-collection is an
    independent authorized read at its own resource_type, so a missing grant for
    one type leaves that section entirely absent — a denial produces no stub, no
    count, and no placeholder (prompt §7.1).
    """
    ceiling = config.sensitivity_ceiling
    charter_result, charters = _read_authorized(
        service, request, project_id, _ResourceType.CHARTER.value, grants=grants
    )
    if not charters:
        # No authorized charter -> no Project Home. We never synthesize a Home
        # from decisions/requirements alone, and we never invent a project.
        return ()

    charter = charters[0]
    decisions_result, decisions = _read_authorized(
        service, request, project_id, _ResourceType.DECISION.value, grants=grants
    )
    requirements_result, requirements = _read_authorized(
        service, request, project_id, _ResourceType.REQUIREMENT.value, grants=grants
    )
    verifications_result, verifications = _read_authorized(
        service, request, project_id, _ResourceType.VERIFICATION.value, grants=grants
    )
    state_result, state_rows = _read_authorized(
        service, request, project_id, _ResourceType.STATE.value, grants=grants
    )

    eligible_decisions = _eligible_records(decisions, ceiling, _ResourceType.DECISION.value)
    eligible_requirements = _eligible_records(requirements, ceiling, _ResourceType.REQUIREMENT.value)
    eligible_verifications = _eligible_records(verifications, ceiling, _ResourceType.VERIFICATION.value)
    eligible_state = _eligible_records(state_rows, ceiling, _ResourceType.STATE.value)

    # M9.3 — the link universe is built from the SAME authorized+eligible set
    # the notes are rendered from, so a link can never address a withheld record.
    registry = _build_link_registry(
        decisions=eligible_decisions,
        requirements=eligible_requirements,
        verifications=eligible_verifications,
        state_rows=eligible_state,
        charter=charter,
    )

    # Each sub-collection is emitted only when its authorized read succeeded
    # AND produced authorized items. A denied/absent type contributes None,
    # which render_project_home omits entirely (no stub, no placeholder).
    home = render_project_home(
        project_id=project_id,
        charter=charter,
        state_rows=eligible_state if (state_result.allowed and state_rows) else None,
        decisions=eligible_decisions if (decisions_result.allowed and decisions) else None,
        requirements=eligible_requirements if (requirements_result.allowed and requirements) else None,
        verifications=eligible_verifications if (verifications_result.allowed and verifications) else None,
        registry=registry,
    )
    return (home,)


def project_source_records(
    service: AuthorizedReadService,
    request: AccessRequest,
    config: ProjectionConfig,
    project_id: str,
    *,
    grants=None,
) -> Tuple[ProjectedNote, ...]:
    """Project the per-record notes (decisions, requirements, verifications).

    Project State is projected separately by :func:`project_project_state`
    because it aggregates the project's active state slot rather than emitting
    one note per row.

    M9.3: the link universe is built from the SAME authorized+eligible decision/
    requirement/verification records this call renders, so cross-note links can
    never address a withheld record. Conflicts are grouped from the eligible
    decision/state set M4 already marked ``conflicted`` and presented verbatim;
    nothing here resolves, ranks, or infers them.
    """
    ceiling = config.sensitivity_ceiling
    notes: List[ProjectedNote] = []

    _, decisions = _read_authorized(
        service, request, project_id, _ResourceType.DECISION.value, grants=grants
    )
    eligible_decisions = _eligible_records(
        decisions, ceiling, _ResourceType.DECISION.value)
    _, requirements = _read_authorized(
        service, request, project_id, _ResourceType.REQUIREMENT.value, grants=grants
    )
    eligible_requirements = _eligible_records(
        requirements, ceiling, _ResourceType.REQUIREMENT.value)
    _, verifications = _read_authorized(
        service, request, project_id, _ResourceType.VERIFICATION.value, grants=grants
    )
    eligible_verifications = _eligible_records(
        verifications, ceiling, _ResourceType.VERIFICATION.value)

    # Build the link universe from exactly the records about to be rendered.
    registry = _build_link_registry(
        decisions=eligible_decisions,
        requirements=eligible_requirements,
        verifications=eligible_verifications,
    )

    for record in eligible_decisions:
        notes.append(render_decision(record, registry=registry))
    for record in eligible_requirements:
        notes.append(render_requirement(record, registry=registry))
    for record in eligible_verifications:
        notes.append(render_verification(record))

    # M9.3 — conflict presentation from AUTHORIZED, M4-marked-conflicted records
    # only. Grouping is a join on M4's explicit conflict key, never an inference.
    conflict_groups = group_conflicts(eligible_decisions, resource_type="decision")
    if conflict_groups:
        notes.append(render_conflict_queue(resource_type="decision", groups=conflict_groups))
        for group in conflict_groups:
            notes.append(render_conflict(group))

    return tuple(notes)


def project_project_state(
    service: AuthorizedReadService,
    request: AccessRequest,
    config: ProjectionConfig,
    project_id: str,
    *,
    grants=None,
) -> Tuple[ProjectedNote, ...]:
    """Project the current project state note.

    The current state is the authoritative active project-state slot returned by
    M4 (``lifecycle_status='active'``), NOT the newest timestamp, mtime, trace,
    assistant claim, or calibration score (prompt §9, §13).
    """
    ceiling = config.sensitivity_ceiling
    _, state_rows = _read_authorized(
        service, request, project_id, _ResourceType.STATE.value, grants=grants
    )
    eligible = _eligible_records(state_rows, ceiling, _ResourceType.STATE.value)
    if not eligible:
        return ()
    return (render_project_state(project_id=project_id, state_rows=eligible),)


def run_projection(
    service: AuthorizedReadService,
    request: AccessRequest,
    config: ProjectionConfig,
    project_id: str,
    *,
    grants=None,
    managed_root=None,
    dry_run: bool = False,
    secret_patterns: Tuple[str, ...] = (),
) -> ProjectionReport:
    """One authorized M9.2 projection pass for a single project.

    Authorization is performed once per resource type at the top of the
    sub-projection helpers (before any record is read or rendered). Eligibility
    is applied per record before rendering. Notes are rendered in memory, then
    delegated to the verified writer for physically-contained atomic writes.

    ``managed_root`` is optional: if ``None``, notes are rendered and returned
    but not written (a pure read/render pass, useful for verification harnesses
    that assert on in-memory content). When provided, it must be a
    :class:`pathlib.Path` inside the operator-configured vault.

    ``secret_patterns`` is the content-level backstop required by the prompt:
    any rendered note whose body matches a secret pattern is withheld (never
    written). This catches secret-shaped material that reached the
    sensitivity-agnostic derived substrate (e.g. a verification observed_result).
    It complements, and never replaces, the sensitivity ceiling.
    """
    ceiling = config.sensitivity_ceiling
    if ceiling != default_ceiling():
        # Defense: the engine refuses to run under any ceiling the eligibility
        # layer does not recognize. A malformed/unknown ceiling fails closed.
        if not is_authorized_resource_type("state", ceiling):
            raise ProjectionVocabularyError("ceiling_unknown")

    home_notes = project_project_home(service, request, config, project_id, grants=grants)
    state_notes = project_project_state(service, request, config, project_id, grants=grants)
    source_notes = project_source_records(service, request, config, project_id, grants=grants)

    notes = home_notes + state_notes + source_notes
    return _commit(service, request, config, project_id, notes,
                   managed_root=managed_root, dry_run=dry_run, ceiling=ceiling,
                   secret_patterns=secret_patterns)


def _commit(service, request, config, project_id, notes, *,
            managed_root, dry_run, ceiling, secret_patterns=()) -> ProjectionReport:
    """Sort, optionally write, and assemble a sanitized report.

    Deterministic ordering: notes are sorted by (relative_path, note_id) so the
    produced set and the write sequence are independent of source insertion
    order or any database row order (prompt §16).

    Secret backstop: any note whose rendered content matches a secret pattern is
    withheld entirely (never written). It is excluded from the returned ``notes``
    too, so it never leaks back to a caller.
    """
    ordered = tuple(sorted(set(notes), key=lambda n: (n.relative_path, n.note_id)))
    kept = []
    for note in ordered:
        if secret_patterns and any(pat in note.content for pat in secret_patterns):
            continue
        kept.append(note)
    writes: Tuple[WriteOutcome, ...] = ()
    if managed_root is not None:
        if not hasattr(managed_root, "is_absolute"):
            raise ProjectionVocabularyError("managed_root_not_a_path")
        writes = write_notes(managed_root, tuple(kept), dry_run=dry_run)
    return ProjectionReport(
        notes=tuple(kept),
        writes=writes,
        authorized_sources=len(ordered),
        projected_sources=len(kept),
        ceiling=ceiling,
    )


__all__ = [
    "PROJECTABLE_RESOURCE_TYPES",
    "ProjectionReport",
    "project_project_home",
    "project_project_state",
    "project_source_records",
    "run_projection",
]
