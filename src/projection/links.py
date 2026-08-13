"""M9.3 — deterministic, authorization-bounded links between projected notes.

A link is **navigation only**. Rendering one asserts nothing: not authorization,
not truth, not verification, not conflict resolution, and not supersession. The
vault confers nothing (docs/plans/plan-m9.md §5, §21).

Two invariants make that safe rather than merely stated:

1. **A link can only ever address an ALREADY-AUTHORIZED projected note.** The
   registry is populated exclusively from the authorized, eligible record set
   the current request produced. A record the request never authorized is not in
   the registry, so no link to it can be constructed — and, critically, an
   unresolvable reference renders *byte-identically* to a reference whose target
   simply does not exist. A reader therefore cannot distinguish "hidden from you"
   from "not recorded", which is the same existence-leak safety M8.3 established
   (docs/plans/plan-m9.md §7.1, §18 of the M9.3 brief).

2. **A link target is never built from hostile human text.** Targets are
   assembled from the VERIFIED M9.1 primitives only — a closed category map, a
   sanitized slug, and a generated identity filename — then re-validated
   component by component through the M9.1 path layer. Display labels are not
   escaped but *whitelisted*: a label that is not already a strictly safe token
   is replaced by the note's own machine identity. Nothing content-derived can
   synthesize ``..``, an absolute path, a second ``[[``, an ``![[`` embed, an
   ``|`` alias, a ``#`` heading reference, or a ``^`` block reference.

The registry key is ``(resource_type, resource_id)``. Carrying ``resource_type``
in the key is what preserves the permanent M6.6 isolation invariant across the
link layer: an ``artifact`` target can never satisfy a ``decision`` lookup, so a
link never becomes a back door around a resource-type-restricted grant.

This module reads no store, makes no authorization decision, touches no
filesystem, and holds no request state. Zero LLM calls, zero network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Final, Iterable, Optional, Tuple

from .contracts import (
    NOTE_TYPE_DIRECTORIES,
    NoteType,
    ProjectionVocabularyError,
    validate_note_type,
    validate_resource_type,
)
from .identity import NOTE_EXTENSION, note_filename, slug, validate_note_id
from .paths import validate_path_component

#: Scope directory used when a record carries no scope. Kept identical to the
#: VERIFIED M9.1 ``safe_note_path`` fallback so a link target and the file the
#: writer actually creates can never disagree.
UNSCOPED_FALLBACK: Final[str] = "unscoped"

#: Maximum length of a link DISPLAY label. Anything longer falls back to the
#: note id rather than being truncated, because a truncated hostile label is
#: still hostile whereas the machine identity is structurally safe.
MAX_LINK_DISPLAY_LENGTH: Final[int] = 120

#: Characters permitted in a link display label, in addition to ASCII letters
#: and digits. Deliberately excludes every character with Obsidian or Markdown
#: structural meaning — ``[ ] | # ^ ! ` * _ ~ { } $ < > &`` and all whitespace
#: other than a single interior space.
_SAFE_DISPLAY_EXTRA: Final[frozenset[str]] = frozenset({".", "_", "-", ":", "/", " "})


def _is_safe_display_character(character: str) -> bool:
    if "a" <= character <= "z" or "A" <= character <= "Z":
        return True
    if "0" <= character <= "9":
        return True
    return character in _SAFE_DISPLAY_EXTRA


def safe_link_display(value: object, *, fallback: str) -> str:
    """Return ``value`` iff it is a strictly safe display token, else ``fallback``.

    A WHITELIST, not an escaper. Escaping a hostile label would still place
    attacker-influenced bytes inside a link's alias position and rely on every
    downstream renderer honouring the escape; refusing the label entirely does
    not. The fallback is the note's own machine identity, which is generated
    from a closed vocabulary plus a hex digest and is therefore always safe.

    Rejected: non-strings, empty/blank, over-long values, leading or trailing
    whitespace, any ``..`` sequence, and any character outside
    ``[A-Za-z0-9._:/ -]`` — which structurally excludes ``[``, ``]``, ``|``,
    ``#``, ``^``, ``!``, backticks, newlines, and control characters.
    """
    if not isinstance(fallback, str) or not fallback:
        raise ProjectionVocabularyError("link_display_fallback")
    if not isinstance(value, str):
        return fallback
    if not value or value != value.strip():
        return fallback
    if len(value) > MAX_LINK_DISPLAY_LENGTH:
        return fallback
    if ".." in value:
        return fallback
    if not all(_is_safe_display_character(character) for character in value):
        return fallback
    return value


def note_relative_path(
    *,
    note_type: NoteType | str,
    note_id: str,
    display_title: Optional[str],
    scope: Optional[str],
) -> str:
    """The deterministic managed-root-relative path of one projected note.

    Single source of truth for BOTH the file the writer creates and the target a
    link addresses. Deriving them from one function is what makes "a link never
    points at a path the projector would not itself write" structural rather
    than a convention two call sites happen to share.

    ``<closed category>/<slugged scope>/<identity filename>`` — three components,
    each validated by the VERIFIED M9.1 component guard.
    """
    resolved_type = validate_note_type(note_type)
    validated_id = validate_note_id(note_id)
    category = NOTE_TYPE_DIRECTORIES[resolved_type]
    filename = note_filename(note_id=validated_id, display_title=display_title)
    scope_component = slug(scope, fallback=UNSCOPED_FALLBACK)
    components = (category, scope_component, filename)
    for component in components:
        validate_path_component(component)
    return "/".join(components)


@dataclass(frozen=True)
class LinkTarget:
    """One already-authorized projected note, addressable as a link.

    Constructing a ``LinkTarget`` is NOT an authorization decision and grants
    nothing. The engine may only build one from a record M5 already authorized
    and the eligibility filter already admitted; this type simply carries the
    deterministic identity of such a note.
    """

    resource_type: str
    resource_id: str
    note_type: NoteType
    note_id: str
    relative_path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "resource_type", validate_resource_type(self.resource_type)
        )
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ProjectionVocabularyError("resource_id")
        object.__setattr__(self, "note_type", validate_note_type(self.note_type))
        object.__setattr__(self, "note_id", validate_note_id(self.note_id))

        # Re-validate the path even though it came from `note_relative_path`.
        # A LinkTarget that reached this constructor by any other route still
        # cannot carry a traversal fragment, an absolute path, a separator, or a
        # character with wiki-link meaning.
        if not isinstance(self.relative_path, str) or not self.relative_path:
            raise ProjectionVocabularyError("relative_path")
        components = self.relative_path.split("/")
        if len(components) != 3:
            raise ProjectionVocabularyError("relative_path")
        for component in components:
            validate_path_component(component)
        if not components[-1].endswith(NOTE_EXTENSION):
            raise ProjectionVocabularyError("relative_path")
        for character in ("[", "]", "|", "#", "^"):
            if character in self.relative_path:
                raise ProjectionVocabularyError("relative_path")

    @property
    def link_target(self) -> str:
        """Vault-relative wiki-link target: the note path without ``.md``."""
        return self.relative_path[: -len(NOTE_EXTENSION)]


def wiki_link(target: LinkTarget, *, display: object = None) -> str:
    """Render one Obsidian wiki link to an already-authorized projected note.

    ``[[<generated path>|<whitelisted label>]]``. Both halves come from closed
    generators: the target from M9.1 identity/path primitives, the label from
    :func:`safe_link_display` (which falls back to the machine identity rather
    than escaping anything questionable). Content therefore never determines a
    link target, an alias, or the link's boundaries (docs/plans/plan-m9.md §22.1, §22.2).
    """
    if not isinstance(target, LinkTarget):
        raise ProjectionVocabularyError("link_target")
    label = safe_link_display(display, fallback=target.note_id)
    return f"[[{target.link_target}|{label}]]"


class LinkRegistry:
    """The authorized link universe for exactly one projection request.

    Membership is the whole safety property: only records that this request
    authorized AND the eligibility filter admitted are ever registered, so a
    link can never address, count, name, or imply the existence of anything the
    requesting profile may not see.

    The registry is a lookup table, never an authority. It performs no access
    decision, caches no grant, and widens no scope.
    """

    __slots__ = ("_targets",)

    def __init__(self, targets: Iterable[LinkTarget] = ()) -> None:
        self._targets: Dict[Tuple[str, str], LinkTarget] = {}
        for target in targets:
            self.add(target)

    def add(self, target: LinkTarget) -> None:
        """Register one authorized target. A conflicting duplicate fails closed."""
        if not isinstance(target, LinkTarget):
            raise ProjectionVocabularyError("link_target")
        key = (target.resource_type, target.resource_id)
        existing = self._targets.get(key)
        if existing is not None and existing != target:
            # Two different notes claiming one canonical identity is a projector
            # bug, not something to silently pick a winner for.
            raise ProjectionVocabularyError("duplicate_link_target")
        self._targets[key] = target

    def resolve(self, resource_type: object,
                resource_id: object) -> Optional[LinkTarget]:
        """Return the authorized target, or ``None``.

        ``None`` is returned identically for "not authorized", "not eligible",
        "not recorded", and "malformed reference". The caller cannot tell these
        apart, and neither can a reader of the rendered note.
        """
        if not isinstance(resource_type, str) or not isinstance(resource_id, str):
            return None
        return self._targets.get((resource_type, resource_id.strip()))

    def targets(self) -> Tuple[LinkTarget, ...]:
        """All registered targets in deterministic key order."""
        return tuple(self._targets[key] for key in sorted(self._targets))

    def __len__(self) -> int:
        return len(self._targets)


__all__ = [
    "UNSCOPED_FALLBACK",
    "MAX_LINK_DISPLAY_LENGTH",
    "safe_link_display",
    "note_relative_path",
    "LinkTarget",
    "LinkRegistry",
    "wiki_link",
]
