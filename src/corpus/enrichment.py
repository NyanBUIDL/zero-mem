"""M10.6 — OPTIONAL corpus enrichment boundary (in-process, derived, absent-safe).

This module implements the *optional* enrichment half of M10.6. It is a strict
boundary, NOT a mandatory pipeline:

- Enrichment is OPTIONAL. Core ingestion, normalization, versioning, derived
  storage, lexical/metadata retrieval, EvidenceSet, and the deterministic
  corpus graph all work WITHOUT any enrichment adapter.
- Enrichment output is DERIVED, NON-CANONICAL metadata. It is never written to
  the closed canonical/memory stores and never becomes verified_state, a
  decision, or a corpus-system-of-record fact. It is marked ``derived`` /
  ``inferred`` and carries provenance + adapter/version/config so stale output
  is distinguishable from current.
- Enrichment is LOCAL and ABSENCE-SAFE. No cloud API, no paid inference, no
  network. The bundled ``KeywordEnrichmentAdapter`` uses only deterministic
  string tokenization. An LLM adapter MAY be added later ONLY as a separately
  configured, explicit, optional, absence-safe implementation; it is NOT
  present here and nothing requires it.
- Source corpus text is untrusted DATA. Enrichment adapters receive bounded
  source text and CANNOT mutate canonical memory, execute instructions found in
  the source, grant authorization, or invoke tools. Prompt-injection strings
  inside source text are treated as ordinary tokens (DATA), never as commands.
- Secret-bearing text is never enriched: the fail-closed M10.2 redactor is
  applied first; a secret-shaped unit yields NO enrichment output.

The minimal stable interface is :class:`EnrichmentAdapter` + :func:`enrich_unit`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, List, Mapping, Optional, Sequence

from src.corpus.redact import CorpusRedactionError, require_safe

#: Marker so downstream consumers never mistake enrichment for canonical fact.
ENRICHMENT_PROVENANCE_KIND: Final[str] = "derived"
ENRICHMENT_RELATION_KIND: Final[str] = "inferred"

#: Stopwords — tiny closed set, deterministic only; not a linguistic claim.
_STOPWORDS: Final[frozenset] = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "was", "were", "be", "by", "as", "at", "that", "this", "it", "its",
    "from", "into", "than", "then", "they", "them", "their", "we", "you", "he",
    "she", "his", "her", "but", "not", "no", "can", "will", "use", "used",
    "using", "which", "who", "what", "when", "where", "how", "all", "any",
})


@dataclass(frozen=True)
class EnrichmentItem:
    """One derived enrichment token (keyword/keyphrase) for a unit.

    ``derived`` flag is always True — enrichment is never canonical. Provenance
    ties it to the adapter + version + config + source unit so stale output is
    distinguishable.
    """

    term: str
    weight: float
    adapter_id: str
    adapter_version: str
    config_hash: str
    source_unit_id: str
    derived: bool = True

    def as_dict(self) -> dict:
        return {
            "term": self.term,
            "weight": round(self.weight, 6),
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "config_hash": self.config_hash,
            "source_unit_id": self.source_unit_id,
            "derived": self.derived,
        }


@dataclass(frozen=True)
class UnitEnrichment:
    """Derived enrichment result for one unit (never persisted to canonical)."""

    unit_id: str
    adapter_id: str
    adapter_version: str
    config_hash: str
    items: List[EnrichmentItem] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "config_hash": self.config_hash,
            "items": [i.as_dict() for i in self.items],
        }


class EnrichmentAdapter:
    """Stable optional-enrichment interface.

    Implementations MUST be deterministic, local, and fail-closed. ``enrich``
    takes bounded source text and a unit id and returns a :class:`UnitEnrichment`
    (possibly empty). It must never raise to break core retrieval; callers wrap
    it and degrade gracefully.
    """

    adapter_id: str = "base"
    adapter_version: str = "0"

    def config_hash(self) -> str:
        from src.m8.identity import content_hash

        return content_hash({"adapter": self.adapter_id,
                             "version": self.adapter_version})

    def enrich(self, *, unit_id: str, text: str) -> UnitEnrichment:  # pragma: no cover
        raise NotImplementedError


class KeywordEnrichmentAdapter(EnrichmentAdapter):
    """Bundled deterministic keyword/keyphrase extractor (no LLM, no network).

    Extracts the top-N most frequent meaningful tokens (and bigrams) from
    bounded source text using a closed stopword list. Output is derived metadata
    only; identical input -> identical output (deterministic, rebuildable).
    """

    adapter_id: str = "keyword"
    adapter_version: str = "m10.6"

    def __init__(self, *, top_n: int = 8, min_len: int = 3) -> None:
        self.top_n = top_n
        self.min_len = min_len

    def config_hash(self) -> str:
        from src.m8.identity import content_hash

        return content_hash({"adapter": self.adapter_id,
                             "version": self.adapter_version,
                             "top_n": self.top_n,
                             "min_len": self.min_len})

    def enrich(self, *, unit_id: str, text: str) -> UnitEnrichment:
        cfg = self.config_hash()
        items: List[EnrichmentItem] = []
        try:
            # Fail-closed: secret-bearing text is rejected before enrichment.
            require_safe(text)
        except CorpusRedactionError:
            # No enrichment for secret-bearing content (safety boundary).
            return UnitEnrichment(
                unit_id=unit_id, adapter_id=self.adapter_id,
                adapter_version=self.adapter_version, config_hash=cfg, items=[],
            )
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text.lower())
        kept = [t for t in tokens if len(t) >= self.min_len and t not in _STOPWORDS]
        counts: dict = {}
        for i, t in enumerate(kept):
            counts[t] = counts.get(t, 0) + 1
            # bigram (adjacent kept tokens) — still deterministic, no semantic claim
            if i + 1 < len(kept):
                big = f"{t} {kept[i + 1]}"
                counts[big] = counts.get(big, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        top = ranked[: self.top_n]
        total = sum(c for _t, c in top) or 1
        for term, c in top:
            items.append(EnrichmentItem(
                term=term, weight=c / total, adapter_id=self.adapter_id,
                adapter_version=self.adapter_version, config_hash=cfg,
                source_unit_id=unit_id,
            ))
        return UnitEnrichment(
            unit_id=unit_id, adapter_id=self.adapter_id,
            adapter_version=self.adapter_version, config_hash=cfg, items=items,
        )


def enrich_unit(
    adapter: Optional[EnrichmentAdapter],
    *,
    unit_id: str,
    text: str,
) -> UnitEnrichment:
    """Boundary entry point: enrich one unit via an OPTIONAL adapter.

    If ``adapter`` is ``None`` (the default core path), returns an empty
    derived result — enrichment is genuinely optional and absence-safe. If the
    adapter raises, returns an empty result rather than propagating (core must
    not break when enrichment fails). Source text is treated as DATA; nothing
    here grants authority or executes instructions.
    """
    if adapter is None:
        return UnitEnrichment(
            unit_id=unit_id, adapter_id="none", adapter_version="0",
            config_hash="", items=[],
        )
    try:
        return adapter.enrich(unit_id=unit_id, text=text)
    except Exception:
        # Enrichment failure degrades safely; never expands scope or breaks core.
        return UnitEnrichment(
            unit_id=unit_id, adapter_id=getattr(adapter, "adapter_id", "unknown"),
            adapter_version=getattr(adapter, "adapter_version", "0"),
            config_hash="", items=[],
        )


__all__ = [
    "ENRICHMENT_PROVENANCE_KIND",
    "EnrichmentItem",
    "UnitEnrichment",
    "EnrichmentAdapter",
    "KeywordEnrichmentAdapter",
    "enrich_unit",
]
