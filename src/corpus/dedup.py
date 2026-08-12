"""M10.3 — unit/source identity + exact deterministic deduplication.

Identity is split into two orthogonal axes so dedup never conflates "same
content" with "same authorization object":

- CONTENT IDENTITY (``content_hash``): what the normalized text *says*,
  determined by ``normalized_text`` (+ ``kind``) only. Format-neutral and
  scope-independent. Two identical paragraphs in different documents share a
  content hash — this is what makes physical/content dedup possible.

- SOURCE LOCATION IDENTITY (``source_location_id``): where a unit sits inside
  its own source (the M10.2 ``unit_id``). Two identical paragraphs in different
  documents have DIFFERENT source location ids, so their logical provenance /
  authorization objects stay distinct.

Authorization scope (profile/project/knowledge-space) participates in the
logical unit identity but is EXPRESSLY excluded from the content hash: physical
content may be shared by content hash across scopes, but logical
source/version/unit authorization identities remain distinct. This is the
cross-scope dedup rule from plan §14: "physical/content dedup MAY share
underlying immutable bytes by content hash BUT logical source/version/unit
authorization identities remain distinct."

Deduplication layers implemented (exact only; NO fuzzy/semantic/embedding dedup,
no LLM):
  A. Exact logical source duplicate -> same source_id / content_hash when the
                                    stable source descriptor and bytes match.
  B. Renamed copy                -> different external_ref, same content_hash,
                                    different source_id.
  C. Exact normalized unit dup   -> same content_hash, same scope -> one retained,
                                    others carry ``duplicate_of`` (provenance kept,
                                    located in their own source — no grant bleed).
  D. Revised source/version      -> same source_id, changed content -> NEW version
                                    (handled by versioning.py), not a dedup collapse.
  E. Cross-format equivalent     -> identical normalized content from different
                                    formats -> same content_hash (collapses physically),
                                    but each source/unit keeps its own logical identity.

Only class C is "within-corpus unit dedup". A/B are at the source registry level
(M10.1 derives logical source identity from the stable descriptor, not content
hash). D/E are handled by identity + versioning, not by collapsing authorization
objects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Iterable, Mapping, Optional

from src.m8.identity import content_hash

from .normalize import NormalizationResult, NormalizedUnit

#: Domain separators (domain-separated SHA-256, mirrors src/m8/identity).
_DOMAIN_UNIT_CONTENT = "zm10.unit_content"
_DOMAIN_UNIT_LOCATION = "zm10.unit_location"
_ID_DIGEST_CHARS = 32


def unit_content_hash(unit: NormalizedUnit) -> str:
    """CONTENT identity: hash over (normalized_text, kind).

    Scope is deliberately NOT part of this hash. Identical content across
    different authorization scopes shares the same content hash (physical dedup
    is allowed), while logical identity stays distinct via
    :func:`unit_source_location_id` + scope carried on the source record.
    """
    payload = {"text": unit.normalized_text, "kind": unit.kind}
    return "c_" + content_hash(payload)[:_ID_DIGEST_CHARS]


def unit_source_location_id(unit: NormalizedUnit) -> str:
    """SOURCE LOCATION identity: where the unit sits in its own source.

    Reuses the M10.2 ``unit_id`` (already structural-locator-stable), so two
    identical paragraphs in two documents resolve to two distinct location ids.
    This is what prevents "same text => same logical unit" collapse.
    """
    return unit.source_location_id


def unit_logical_id(unit: NormalizedUnit) -> str:
    """Logical unit identity = (source_ref, source_location_id).

    Scope/provenance is bound through ``source_ref`` which carries the source's
    authorization scope. Distinct documents with identical text have distinct
    logical ids => no cross-scope authorization collapse.
    """
    payload = {"source_ref": unit.source_ref, "location_id": unit.source_location_id}
    return "u_" + content_hash(payload)[:_ID_DIGEST_CHARS]


def corpus_content_hash(text: str, kind: str) -> str:
    """Standalone content hash for arbitrary (text, kind) — used by tests and
    by callers that build units outside the dataclass path."""
    payload = {"text": text, "kind": kind}
    return "c_" + content_hash(payload)[:_ID_DIGEST_CHARS]


@dataclass(frozen=True)
class DedupOutcome:
    """Result of deduping one normalized unit against a seen-content index.

    ``is_duplicate`` is True only for class C (same content hash AND same
    logical source scope already seen). The retained ``duplicate_of`` points at
    the first logical unit id that introduced the shared content; it is a
    provenance link, NOT a merge of authorization identity.
    """

    content_hash: str
    logical_id: str
    source_location_id: str
    is_duplicate: bool
    duplicate_of: Optional[str] = None


class UnitDedupIndex:
    """Deterministic in-memory exact-unit dedup index (class C).

    Tracks, per logical scope, which content hashes have been seen and which
    logical unit id first introduced each. A unit is a duplicate only when the
    SAME content hash has already appeared in the SAME logical source scope
    (same ``source_ref``). Different ``source_ref`` values (different documents,
    different authorization scopes) never collapse — even if the text is
    identical — preserving M5/M6.6 isolation.

    The index is DERIVED and rebuildable from canonical normalized units; it is
    not a corpus system of record.
    """

    def __init__(self) -> None:
        # content_hash -> (source_ref -> first logical unit id)
        self._seen: dict[str, dict[str, str]] = {}
        # content_hash -> how many logical units share it (any scope)
        self._count: dict[str, int] = {}
        self._duplicates: list[DedupOutcome] = []

    @property
    def duplicate_count(self) -> int:
        return len(self._duplicates)

    def seen_content_hashes(self) -> frozenset[str]:
        return frozenset(self._seen.keys())

    def process(self, unit: NormalizedUnit) -> DedupOutcome:
        ch = unit_content_hash(unit)
        loc = unit_source_location_id(unit)
        lid = unit_logical_id(unit)
        per_source = self._seen.setdefault(ch, {})
        if unit.source_ref in per_source:
            # Same content already seen within this exact logical source scope.
            first_lid = per_source[unit.source_ref]
            outcome = DedupOutcome(
                content_hash=ch,
                logical_id=lid,
                source_location_id=loc,
                is_duplicate=(first_lid != lid),
                duplicate_of=first_lid if first_lid != lid else None,
            )
        else:
            per_source[unit.source_ref] = lid
            outcome = DedupOutcome(
                content_hash=ch,
                logical_id=lid,
                source_location_id=loc,
                is_duplicate=False,
                duplicate_of=None,
            )
        self._count[ch] = self._count.get(ch, 0) + 1
        if outcome.is_duplicate:
            self._duplicates.append(outcome)
        return outcome

    def process_many(self, units: Iterable[NormalizedUnit]) -> list[DedupOutcome]:
        return [self.process(u) for u in units]

    def content_shared_across_scopes(self) -> bool:
        """True if any content hash appears under more than one source_ref.

        Used by tests to prove cross-scope content sharing is allowed WITHOUT
        collapsing logical identity (the two logical units still exist).
        """
        return any(len(v) > 1 for v in self._seen.values())


def dedup_normalization_result(result: NormalizationResult) -> list[DedupOutcome]:
    """Convenience: dedup every normalized unit of one source against a fresh
    in-memory index. Returns outcomes for that source's units only."""
    index = UnitDedupIndex()
    return index.process_many(u for u in result.units)


def dedup_units(units: Iterable[NormalizedUnit]) -> list[DedupOutcome]:
    index = UnitDedupIndex()
    return index.process_many(units)


# Type aliases kept explicit for clarity at call sites.
SourceId = str
ContentHash = str


__all__ = [
    "unit_content_hash",
    "unit_source_location_id",
    "unit_logical_id",
    "corpus_content_hash",
    "DedupOutcome",
    "UnitDedupIndex",
    "dedup_normalization_result",
    "dedup_units",
]
