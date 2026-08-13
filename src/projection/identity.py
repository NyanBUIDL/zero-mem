"""M9.1 — deterministic projection identity and safe slug primitives.

Identity must be reproducible from canonical inputs alone: the same canonical
state plus the same config must yield byte-identical identifiers on every
process, machine, and ``PYTHONHASHSEED``.

Explicitly forbidden as identity inputs (docs/plans/plan-m9.md §9, §16.2):

- a display title (titles change, collide, and carry hostile characters);
- ``uuid4()``, ``random``, or ``os.urandom``;
- wall-clock time, run identity, or generation order;
- Python ``hash()`` (``PYTHONHASHSEED``-dependent);
- SQLite ``rowid`` / insertion order / result-set ordering;
- string similarity or any inferred equivalence.

Only explicit canonical field values participate, via the VERIFIED M8 hashing
discipline (``canonical_json`` + domain-separated SHA-256), so M9 introduces no
second hashing scheme that could drift from it.

**Titles are display only.** A title contributes to a slug that is normalized,
stripped, truncated, and then suffixed with the machine identity. The slug can
never select a parent directory, escape a directory, or collide two distinct
notes onto one filename.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any, Final, Mapping, Optional

from src.m8.identity import canonical_json

from .contracts import NoteType, ProjectionVocabularyError, validate_note_type

#: Identity algorithm version. Any change to canonicalization, normalization, or
#: the digest scheme MUST bump this, because it changes every derived note id.
PROJECTION_IDENTITY_VERSION: Final[str] = "v1"

#: Domain separators. A digest is always bound to exactly one logical kind, so
#: a note id can never collide with a content fingerprint.
_DOMAIN_NOTE: Final[str] = "zm9.note"
_DOMAIN_CONTENT: Final[str] = "zm9.content"

#: Stable human-readable prefix for every projected note identifier.
NOTE_ID_PREFIX: Final[str] = "zm-"

#: Length of the truncated digest carried in a note id / filename suffix.
NOTE_ID_DIGEST_CHARS: Final[int] = 16

#: Maximum slug length in the generated filename (docs/plans/plan-m9.md §9 / §10.1).
MAX_SLUG_LENGTH: Final[int] = 80

#: Separator between the display slug and the stable identity suffix.
FILENAME_SEPARATOR: Final[str] = "--"

#: Generated-note file extension.
NOTE_EXTENSION: Final[str] = ".md"

#: Unicode general categories stripped before slugging: control (Cc), format
#: (Cf — zero-width joiners, bidi overrides), surrogate (Cs), private-use (Co),
#: and unassigned (Cn). Together these remove the invisible characters that
#: would otherwise let two visually identical titles differ, or let a bidi
#: override disguise an extension.
_STRIPPED_UNICODE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {"Cc", "Cf", "Cs", "Co", "Cn"}
)

#: Windows reserved device names. Rejected for cross-platform vault portability:
#: on Windows a file named ``CON.md`` is not creatable, so a vault synced there
#: would silently lose the note.
RESERVED_FILENAMES: Final[frozenset[str]] = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in range(1, 10)}
    | {f"lpt{digit}" for digit in range(1, 10)}
)


def _digest(domain: str, payload: Mapping[str, Any]) -> str:
    material = f"{domain}|{PROJECTION_IDENTITY_VERSION}|{canonical_json(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _optional_identity_field(value: Optional[str], field_name: str) -> Optional[str]:
    """Explicit ``None`` participates in identity as ``null`` — never as ''.

    A note scoped to a project is a DIFFERENT logical note from an otherwise
    identical unscoped one, so collapsing ``None`` into an empty string would
    flatten a profile/project boundary into a single identity.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProjectionVocabularyError(field_name)
    return value


def _required_identity_field(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProjectionVocabularyError(field_name)
    return value


def derive_note_id(
    *,
    note_type: NoteType | str,
    resource_type: str,
    resource_id: str,
    project_id: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> str:
    """Derive the authoritative machine identity for one projected note.

    Identity = (note_type, resource_type, resource_id, project_id, profile_id).
    ``resource_type`` participates on purpose: an artifact reference and an event
    carrying the same raw identifier are different resources (permanent M6.6
    isolation), so they must never share a note id.

    Deterministic across processes and ``PYTHONHASHSEED`` values; a rebuild from
    the same canonical state reproduces it exactly.
    """
    from .contracts import validate_resource_type

    resolved_type = validate_note_type(note_type)
    payload = {
        "note_type": resolved_type.value,
        "resource_type": validate_resource_type(resource_type),
        "resource_id": _required_identity_field(resource_id, "resource_id"),
        "project_id": _optional_identity_field(project_id, "project_id"),
        "profile_id": _optional_identity_field(profile_id, "profile_id"),
    }
    digest = _digest(_DOMAIN_NOTE, payload)[:NOTE_ID_DIGEST_CHARS]
    return f"{NOTE_ID_PREFIX}{resolved_type.value}-{digest}"


def note_id_suffix(note_id: str) -> str:
    """Return the stable digest suffix carried in a generated filename."""
    validated = validate_note_id(note_id)
    return validated.rsplit("-", 1)[1]


def validate_note_id(value: str) -> str:
    """Return ``value`` if it is a well-formed note id, else fail closed.

    Shape is checked structurally (prefix, closed note type, lowercase hex
    suffix of the exact expected length) so a caller-supplied string can never
    masquerade as an identity or smuggle path characters into a filename.
    """
    if not isinstance(value, str) or not value.startswith(NOTE_ID_PREFIX):
        raise ProjectionVocabularyError("note_id")
    remainder = value[len(NOTE_ID_PREFIX):]
    head, separator, suffix = remainder.rpartition("-")
    if not separator or not head:
        raise ProjectionVocabularyError("note_id")
    try:
        NoteType(head)
    except ValueError:
        raise ProjectionVocabularyError("note_id") from None
    if len(suffix) != NOTE_ID_DIGEST_CHARS:
        raise ProjectionVocabularyError("note_id")
    if any(character not in "0123456789abcdef" for character in suffix):
        raise ProjectionVocabularyError("note_id")
    return value


def content_fingerprint(content: str) -> str:
    """Deterministic ``sha256:<hex>`` fingerprint over a rendered note body.

    A content identity marker only. It carries no truth, verification, or
    authorization semantics, and no wall clock participates, so an unchanged
    note fingerprints identically forever.
    """
    if not isinstance(content, str):
        raise ProjectionVocabularyError("content")
    digest = _digest(_DOMAIN_CONTENT, {"content": content})
    return f"sha256:{digest}"


def slug(value: Optional[str], *, fallback: str = "note") -> str:
    """Deterministic, total, path-safe slug for DISPLAY purposes only.

    Pipeline: Unicode NFC normalize -> strip invisible/control categories ->
    casefold -> map every character outside ``[a-z0-9]`` to ``-`` -> collapse
    runs -> strip outer dashes -> truncate -> re-strip -> reserved-name guard.

    The output is structurally incapable of containing ``/``, ``\\``, NUL, a
    leading or trailing dot, whitespace, ``.``, or ``..``, so hostile title text
    can never traverse, escape, select a directory, or produce a name that is
    unwritable on a case-insensitive or Windows filesystem.

    Total by construction: an empty, whitespace-only, punctuation-only, or
    fully-stripped input yields ``fallback`` rather than raising or producing an
    empty component. Uniqueness never depends on this value — the note id
    suffix does — so a fallback collision is harmless.
    """
    if not isinstance(fallback, str) or not fallback:
        raise ProjectionVocabularyError("fallback")
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    else:
        raise ProjectionVocabularyError("slug_input")

    normalized = unicodedata.normalize("NFC", text)
    visible = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in _STRIPPED_UNICODE_CATEGORIES
    )
    folded = visible.casefold()
    # Re-normalize: casefold can denormalize (e.g. some ligatures/sigmas), and a
    # stable slug must not depend on which normal form the caller supplied.
    folded = unicodedata.normalize("NFC", folded)

    characters = []
    for character in folded:
        if "a" <= character <= "z" or "0" <= character <= "9":
            characters.append(character)
        else:
            characters.append("-")
    collapsed = "".join(characters)
    while "--" in collapsed:
        collapsed = collapsed.replace("--", "-")
    stripped = collapsed.strip("-")

    if len(stripped) > MAX_SLUG_LENGTH:
        # Deterministic truncation. Never a hash, never a random suffix: the
        # same over-long title must always truncate to the same slug.
        stripped = stripped[:MAX_SLUG_LENGTH].strip("-")

    if not stripped:
        stripped = fallback

    if stripped in RESERVED_FILENAMES:
        # A reserved device name is prefixed rather than rejected: the display
        # slug is decorative, and the stable suffix still guarantees identity.
        stripped = f"{stripped}-note"

    return stripped


def note_filename(*, note_id: str, display_title: Optional[str]) -> str:
    """Build the deterministic generated filename for a note.

    ``slug(display_title)[:80] + "--" + <stable suffix> + ".md"`` (docs/plans/plan-m9.md
    §9 / §29 Q13). Two notes with identical or empty titles can never collide,
    because the suffix comes from canonical identity; and renaming a note's
    title changes only the display half, never its identity.
    """
    validated = validate_note_id(note_id)
    note_type = validated[len(NOTE_ID_PREFIX):].rsplit("-", 1)[0]
    display = slug(display_title, fallback=note_type)
    return f"{display}{FILENAME_SEPARATOR}{note_id_suffix(validated)}{NOTE_EXTENSION}"


__all__ = [
    "PROJECTION_IDENTITY_VERSION",
    "NOTE_ID_PREFIX",
    "NOTE_ID_DIGEST_CHARS",
    "MAX_SLUG_LENGTH",
    "FILENAME_SEPARATOR",
    "NOTE_EXTENSION",
    "RESERVED_FILENAMES",
    "derive_note_id",
    "validate_note_id",
    "note_id_suffix",
    "content_fingerprint",
    "slug",
    "note_filename",
]
