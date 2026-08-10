"""M9.5 — human ownership boundary and deterministic edit classification.

This module answers exactly one question, deterministically and without ever
touching a byte:

    for this managed-root-relative path, what is the CURRENT ownership and
    edit state of whatever is on disk right now?

It is the single place the three-signal ownership rule (plan-m9.md §12.1) is
evaluated against a live file, and it is deliberately decision-free: it
classifies, and the reconcile engine decides. Nothing here creates, opens for
writing, renames, truncates, or removes anything.

**The three signals (§12.1), unchanged and un-weakened**

1. *containment* — the path resolves, through the VERIFIED M9.1 pipeline
   (lexical component validation -> symlink-chain rejection -> realpath physical
   containment), to a strict descendant of ``managed_root``;
2. *frontmatter marker* — the file itself carries ``zero_mem_managed: true``
   together with this exact ``note_id``;
3. *manifest listing* — the prior manifest lists this exact ``note_id``.

A file is Zero-Mem-owned only when ALL THREE hold. Each alone fails in a
different direction, which is precisely why none of them is sufficient:

* path location alone would claim a human note dropped into the managed folder;
* a frontmatter marker alone is trivially spoofable — a human can copy a
  generated header, ``note_id``, ``resource_id``, and ``projection_version``
  into their own note, and that copy proves nothing;
* the manifest alone goes stale, and a tampered manifest must never be able to
  authorize the destruction of a human file.

**Human content is never destroyed.** Every classification that is not a proven,
byte-identical Zero-Mem file resolves to a preserve-only state. There is no
code path here — and, by construction, none downstream that consults these
values — in which "unprovable" degrades to "probably ours".

**Edit detection is byte/content derived only.** A human edit is detected by
comparing the file's deterministic content fingerprint with the fingerprint the
manifest recorded for the last content M9 actually wrote. ``mtime``, ``ctime``,
editor metadata, wall clock, and filesystem ordering are never consulted, never
imported, and never inferred from.

**Projection-only.** Nothing in this module reads, writes, proposes, queues, or
promotes canonical state. A human's Markdown is DATA: its bytes influence one
thing only — whether M9 refuses to touch the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, Optional

from .contracts import (
    MANAGED_MARKER_KEY,
    OwnershipSignals,
    ProjectionPathError,
    ProjectionVocabularyError,
    is_zero_mem_managed,
)
from .identity import (
    FILENAME_SEPARATOR,
    NOTE_EXTENSION,
    content_fingerprint,
    validate_note_id,
)
from .paths import MAX_COMPONENT_LENGTH, safe_managed_path

#: Bytes of the file head inspected for the ownership marker. Bounded so a
#: hostile multi-megabyte file cannot turn an ownership probe into a DoS, and
#: because a genuine generated note carries its frontmatter at byte 0.
FRONTMATTER_HEAD_LIMIT: Final[int] = 4096

#: Suffix of the non-destructive conflict copy (plan-m9.md §13.3 step 2). The
#: human's file keeps its own name and its own bytes; the newly-rendered
#: authoritative version is placed BESIDE it under this fixed suffix. There is
#: no counter, no timestamp, and no numbering: the same conflict always yields
#: exactly one sibling at exactly one deterministic path, so repeated runs can
#: never accumulate ``...-1.md``/``...-2.md`` debris.
CONFLICT_SIBLING_SUFFIX: Final[str] = ".zero-mem-new.md"


class OwnershipClass(str, Enum):
    """Closed, deterministic ownership/edit classification vocabulary.

    Closed on purpose: an unrecognized state must be impossible rather than
    handled leniently, because every destructive operation downstream is gated
    on this value.
    """

    #: Proven Zero-Mem file whose bytes still equal what M9 last wrote.
    GENERATED_UNCHANGED = "generated_unchanged"
    #: Proven Zero-Mem file whose bytes no longer equal what M9 last wrote.
    GENERATED_HUMAN_MODIFIED = "generated_human_modified"
    #: A file with no Zero-Mem marker. Human content. Never touched.
    HUMAN_OWNED = "human_owned"
    #: Marker-shaped but unprovable (e.g. spoofed header, absent from the
    #: manifest, unreadable, not a regular file, unsafe path). Never touched.
    UNKNOWN_OWNERSHIP = "unknown_ownership"
    #: Nothing is at the path. Safe to (re)create if the current authoritative
    #: state still wants it; never read as "the human wanted it deleted".
    MISSING_EXPECTED_FILE = "missing_expected_file"
    #: Proven, unmodified Zero-Mem file that the current authoritative state no
    #: longer wants. The only class that may be retired.
    STALE_GENERATED = "stale_generated"


#: Classes that permit a destructive or overwriting operation. Everything else
#: is preserve-only. Kept as an explicit closed set so that adding a new class
#: can never silently widen destructive authority.
DESTRUCTIVE_ELIGIBLE: Final[frozenset[OwnershipClass]] = frozenset(
    {OwnershipClass.GENERATED_UNCHANGED, OwnershipClass.STALE_GENERATED}
)


@dataclass(frozen=True)
class OwnershipAssessment:
    """One deterministic ownership/edit verdict. Sanitized by construction.

    Carries hashes and closed status codes only — never file content, never a
    diff, never an absolute path, and never any authoritative source text. That
    is what makes it safe to place in a report, a log line, or an exception:
    when authorization or sensitivity no longer permits the source material,
    this record still reveals nothing about it (plan-m9.md §11.3).
    """

    note_id: str
    relative_path: str
    classification: OwnershipClass
    signals: OwnershipSignals
    observed_fingerprint: Optional[str] = None
    recorded_fingerprint: Optional[str] = None
    reason: str = ""

    @property
    def is_owned(self) -> bool:
        """True only under a complete three-signal proof."""
        return is_zero_mem_managed(self.signals)

    @property
    def human_modified(self) -> bool:
        return self.classification is OwnershipClass.GENERATED_HUMAN_MODIFIED

    @property
    def may_be_destroyed(self) -> bool:
        """Destructive eligibility. Requires the full proof AND a safe class."""
        return self.is_owned and self.classification in DESTRUCTIVE_ELIGIBLE


# ---------------------------------------------------------------------------
# Read-only filesystem probes (never mutate, always rejection-biased)
# ---------------------------------------------------------------------------

def has_managed_marker(path: Path, note_id: str) -> bool:
    """Frontmatter ownership SIGNAL: marker plus this exact ``note_id``.

    One signal of three. A defensive, bounded, read-only head probe: an absent,
    unreadable, binary, or marker-less file is simply "not proven", and the
    caller then refuses the destructive action rather than assuming ownership.

    Requiring the note_id as well as the marker means a generated header copied
    from a *different* note does not authorize anything for this one.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(FRONTMATTER_HEAD_LIMIT)
    except OSError:
        return False
    return f"{MANAGED_MARKER_KEY}: true" in head and note_id in head


def observed_fingerprint(path: Path) -> Optional[str]:
    """Deterministic content fingerprint of the bytes currently on disk.

    ``None`` when the file cannot be read as UTF-8 text at all. ``None`` never
    compares equal to a recorded fingerprint, so an unreadable file fails closed
    toward preservation rather than toward "unchanged".

    No ``mtime``, ``ctime``, size heuristic, editor metadata, or wall clock
    participates: the fingerprint is a pure function of the bytes.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return content_fingerprint(text)


def resolve_managed_target(managed_root: Path, relative_path: str) -> Path:
    """Resolve a managed-root-relative path through the full M9.1 pipeline.

    Both M9.1 defenses are kept deliberately and neither is simplified: the
    symlink-chain walk refuses an escape BEFORE resolution, and the realpath
    containment check proves the physical target really is inside the root.
    Mutation testing during M9.1 proved each one independently protects the
    invariant.
    """
    if not isinstance(relative_path, str) or not relative_path:
        raise ProjectionPathError("relative_path")
    return safe_managed_path(managed_root, *relative_path.split("/"))


# ---------------------------------------------------------------------------
# Conflict sibling identity (deterministic, collision-free, non-destructive)
# ---------------------------------------------------------------------------

def conflict_sibling_relative_path(relative_path: str) -> str:
    """Deterministic sibling path for the newly-rendered conflict copy.

    ``<name>.md`` -> ``<name>.zero-mem-new.md`` in the SAME managed directory
    (plan-m9.md §13.3 step 2). The human's file is never renamed, never moved,
    and never touched; the sibling is additive.

    For a title long enough that the sibling name would exceed the M9.1
    component bound, the DISPLAY half of the stem is truncated deterministically
    while the ``--<identity suffix>`` tail is preserved verbatim. Truncation
    therefore never collapses two distinct notes onto one sibling path, and the
    same input always yields the same output — no hash, no counter, no clock.
    """
    if not isinstance(relative_path, str) or not relative_path.endswith(NOTE_EXTENSION):
        raise ProjectionVocabularyError("relative_path")
    directory, _, filename = relative_path.rpartition("/")
    stem = filename[: -len(NOTE_EXTENSION)]
    if not stem:
        raise ProjectionVocabularyError("relative_path")

    budget = MAX_COMPONENT_LENGTH - len(CONFLICT_SIBLING_SUFFIX)
    if budget < 1:  # pragma: no cover - defensive, constants make this impossible
        raise ProjectionVocabularyError("relative_path")
    if len(stem) > budget:
        display, separator, identity = stem.rpartition(FILENAME_SEPARATOR)
        if separator and identity:
            keep = budget - len(identity) - len(FILENAME_SEPARATOR)
            if keep < 1:
                raise ProjectionVocabularyError("relative_path")
            stem = f"{display[:keep].rstrip('-')}{FILENAME_SEPARATOR}{identity}"
        else:
            stem = stem[:budget].rstrip("-")
        if not stem:
            raise ProjectionVocabularyError("relative_path")
    sibling = f"{stem}{CONFLICT_SIBLING_SUFFIX}"
    return f"{directory}/{sibling}" if directory else sibling


def is_conflict_sibling(relative_path: object) -> bool:
    """True when a managed-relative path names a conflict copy."""
    return (
        isinstance(relative_path, str)
        and relative_path.endswith(CONFLICT_SIBLING_SUFFIX)
    )


# ---------------------------------------------------------------------------
# The classification itself
# ---------------------------------------------------------------------------

def classify_managed_file(
    managed_root: Path,
    *,
    note_id: str,
    relative_path: str,
    listed: bool,
    recorded_fingerprint: Optional[str] = None,
    desired: bool = True,
) -> OwnershipAssessment:
    """Classify whatever is on disk at ``relative_path`` right now.

    The order of checks is load-bearing and fails closed at every step:

    1. **path safety first** — an unsafe path (traversal, absolute, symlinked
       component, escape, ``.obsidian``) is refused BEFORE the file is read, so
       a hostile symlink planted after generation can neither be read through
       nor written through;
    2. **absent** — nothing to own, nothing to protect;
    3. **not a regular file** — a symlink or special file is never claimed;
    4. **marker absent** -> ``HUMAN_OWNED`` regardless of manifest listing, so a
       stale or tampered manifest entry can never re-classify a human file;
    5. **marker present but the full proof fails** -> ``UNKNOWN_OWNERSHIP``:
       this is exactly the ownership-spoof case, and it is preserve-only;
    6. **full proof holds** -> fingerprint comparison decides
       unchanged/human-modified, and ``desired=False`` renders an unmodified
       file ``STALE_GENERATED`` (the only retirement-eligible class).

    ``listed`` is supplied by the caller from the prior manifest and is DATA:
    it contributes one signal and can never, alone, produce an owned verdict.
    """
    validate_note_id(note_id)
    listed_signal = bool(listed)

    try:
        path = resolve_managed_target(managed_root, relative_path)
    except ProjectionPathError as exc:
        # Never read, never write, never claim: an unsafe path is refused
        # outright and the reason code carries no path material.
        return OwnershipAssessment(
            note_id=note_id,
            relative_path=relative_path,
            classification=OwnershipClass.UNKNOWN_OWNERSHIP,
            signals=OwnershipSignals(
                inside_managed_root=False,
                has_managed_marker=False,
                listed_in_manifest=listed_signal,
            ),
            recorded_fingerprint=recorded_fingerprint,
            reason=exc.reason if isinstance(getattr(exc, "reason", None), str) else "unsafe_path",
        )

    if not (path.exists() or path.is_symlink()):
        return OwnershipAssessment(
            note_id=note_id,
            relative_path=relative_path,
            classification=OwnershipClass.MISSING_EXPECTED_FILE,
            signals=OwnershipSignals(
                inside_managed_root=True,
                has_managed_marker=False,
                listed_in_manifest=listed_signal,
            ),
            recorded_fingerprint=recorded_fingerprint,
            reason="absent",
        )

    if path.is_symlink() or not path.is_file():
        # Unreachable for a symlink under the M9.1 chain walk above; kept as an
        # independent backstop because ownership must never depend on a single
        # defense holding.
        return OwnershipAssessment(
            note_id=note_id,
            relative_path=relative_path,
            classification=OwnershipClass.UNKNOWN_OWNERSHIP,
            signals=OwnershipSignals(
                inside_managed_root=True,
                has_managed_marker=False,
                listed_in_manifest=listed_signal,
            ),
            recorded_fingerprint=recorded_fingerprint,
            reason="not_a_regular_file",
        )

    marker = has_managed_marker(path, note_id)
    signals = OwnershipSignals(
        inside_managed_root=True,
        has_managed_marker=marker,
        listed_in_manifest=listed_signal,
    )
    observed = observed_fingerprint(path)

    if not marker:
        return OwnershipAssessment(
            note_id=note_id,
            relative_path=relative_path,
            classification=OwnershipClass.HUMAN_OWNED,
            signals=signals,
            observed_fingerprint=observed,
            recorded_fingerprint=recorded_fingerprint,
            reason="no_managed_marker",
        )

    if not is_zero_mem_managed(signals):
        # Marker-shaped but unprovable: a human file carrying a copied header,
        # a note_id, a resource_id, and a projection_version is STILL not ours.
        return OwnershipAssessment(
            note_id=note_id,
            relative_path=relative_path,
            classification=OwnershipClass.UNKNOWN_OWNERSHIP,
            signals=signals,
            observed_fingerprint=observed,
            recorded_fingerprint=recorded_fingerprint,
            reason="ownership_unproven",
        )

    if recorded_fingerprint is None or observed is None:
        return OwnershipAssessment(
            note_id=note_id,
            relative_path=relative_path,
            classification=OwnershipClass.UNKNOWN_OWNERSHIP,
            signals=signals,
            observed_fingerprint=observed,
            recorded_fingerprint=recorded_fingerprint,
            reason="fingerprint_unavailable",
        )

    if observed == recorded_fingerprint:
        classification = (
            OwnershipClass.GENERATED_UNCHANGED if desired
            else OwnershipClass.STALE_GENERATED
        )
        return OwnershipAssessment(
            note_id=note_id,
            relative_path=relative_path,
            classification=classification,
            signals=signals,
            observed_fingerprint=observed,
            recorded_fingerprint=recorded_fingerprint,
            reason="fingerprint_match",
        )

    return OwnershipAssessment(
        note_id=note_id,
        relative_path=relative_path,
        classification=OwnershipClass.GENERATED_HUMAN_MODIFIED,
        signals=signals,
        observed_fingerprint=observed,
        recorded_fingerprint=recorded_fingerprint,
        reason="fingerprint_differs",
    )


__all__ = [
    "FRONTMATTER_HEAD_LIMIT",
    "CONFLICT_SIBLING_SUFFIX",
    "DESTRUCTIVE_ELIGIBLE",
    "OwnershipClass",
    "OwnershipAssessment",
    "has_managed_marker",
    "observed_fingerprint",
    "resolve_managed_target",
    "conflict_sibling_relative_path",
    "is_conflict_sibling",
    "classify_managed_file",
]
