"""M10.5 — deterministic corpus query planner (metadata + lexical normalization).

Pure, side-effect-free helpers that translate an authorized corpus query into a
deterministic plan. No DB, no LLM, no network.

Two responsibilities:

1. **Query normalization** — sanitize/normalize a free-text query for FTS
   discovery the same way the repo normalizes M3 text (lowercased, whitespace
   collapsed). Keeps determinism explicit; no stemming/tokenization surprises.

2. **Metadata filter validation** — accept only the approved, closed set of
   deterministic corpus metadata dimensions (M10.1-M10.4 contracts only):

     - profile_id
     - project_id
     - knowledge_space_id
     - source_id          (the corpus_source identity the unit belongs to)
     - unit_kind          (closed coarse structural set)
     - lifecycle_status   (closed lifecycle enum)

   Any unknown dimension is rejected (fail closed). No domain-specific metadata
   (finance/quant/medical/legal) is introduced as core architecture — M10 remains
   universal-domain.

The planner produces a validated ``CorpusQueryPlan`` consumed by
``src/corpus/retrieval.py``. It performs NO authorization; authorization is the
exclusive responsibility of ``AuthorizedReadService`` (M5), which supplies the
authorized scope the plan's metadata dimensions are checked against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

# Closed coarse structural unit kinds (mirrors migrate_10._UNIT_KIND_ENUM).
_VALID_UNIT_KINDS = frozenset(
    {"text", "heading", "table", "code", "figure", "metadata", "other"}
)

# Closed lifecycle enum (mirrors migrate_10._LIFECYCLE_ENUM / SourceLifecycle).
_VALID_LIFECYCLE = frozenset(
    {
        "raw",
        "observed",
        "candidate",
        "confirmed",
        "active",
        "superseded",
        "conflicted",
        "archived",
        "deleted",
    }
)

# Approved metadata dimensions for corpus retrieval (M10.1-M10.4 only).
VALID_METADATA_KEYS: FrozenSet[str] = frozenset(
    {
        "profile_id",
        "project_id",
        "knowledge_space_id",
        "source_id",
        "unit_kind",
        "lifecycle_status",
    }
)

# Dimensions that default to 'active' exclusions handling: deleted is never
# eligible corpus evidence (consistent with M7 eligibility for memory).
_EXCLUDED_LIFECYCLE = frozenset({"deleted"})


class CorpusQueryError(ValueError):
    """Closed-contract query-planning failure (fail closed)."""


@dataclass(frozen=True)
class CorpusMetadataFilter:
    """Validated, closed-set corpus metadata filter.

    Every field is optional. An empty filter means "no metadata restriction"
    (the authorized scope from M5 still bounds the result). Unknown keys are
    rejected at construction.
    """

    profile_id: Optional[str] = None
    project_id: Optional[str] = None
    knowledge_space_id: Optional[str] = None
    source_id: Optional[str] = None
    unit_kind: Optional[str] = None
    lifecycle_status: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.profile_id is not None:
            out["profile_id"] = self.profile_id
        if self.project_id is not None:
            out["project_id"] = self.project_id
        if self.knowledge_space_id is not None:
            out["knowledge_space_id"] = self.knowledge_space_id
        if self.source_id is not None:
            out["source_id"] = self.source_id
        if self.unit_kind is not None:
            out["unit_kind"] = self.unit_kind
        if self.lifecycle_status is not None:
            out["lifecycle_status"] = self.lifecycle_status
        return out

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "CorpusMetadataFilter":
        if not data:
            return cls()
        cleaned: Dict[str, Any] = {}
        for key, value in data.items():
            if key not in VALID_METADATA_KEYS:
                raise CorpusQueryError(f"unsupported_corpus_metadata_key: {key!r}")
            if value is None:
                continue
            if key == "unit_kind" and value not in _VALID_UNIT_KINDS:
                raise CorpusQueryError(f"invalid_corpus_unit_kind: {value!r}")
            if key == "lifecycle_status" and value not in _VALID_LIFECYCLE:
                raise CorpusQueryError(f"invalid_corpus_lifecycle: {value!r}")
            cleaned[key] = value
        return cls(**cleaned)

    def items(self) -> List[Tuple[str, str]]:
        return list(self.as_dict().items())


@dataclass(frozen=True)
class CorpusQueryPlan:
    """Validated, deterministic corpus retrieval plan.

    - ``text`` is the normalized lexical query (may be empty for metadata-only).
    - ``metadata`` is the closed-set filter.
    - ``limit`` is a conservative upper bound (the M7 EvidenceSet budget is the
      final cap; this only bounds the retrieval candidate discovery).
    """

    text: str
    metadata: CorpusMetadataFilter
    limit: int = 100

    @property
    def is_metadata_only(self) -> bool:
        return not self.text.strip()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "metadata": self.metadata.as_dict(),
            "limit": self.limit,
        }


def normalize_query_text(text: Optional[str]) -> str:
    """Deterministic lexical normalization (mirrors repo M3 normalization).

    Lowercase + collapse internal whitespace; strip trailing/leading space. No
    stemming, no tokenization, no LLM. Empty/None input yields "".
    """
    if not text:
        return ""
    return " ".join(str(text).lower().split())


def build_query_plan(
    text: Optional[str] = None,
    *,
    metadata: Optional[Mapping[str, Any]] = None,
    limit: int = 100,
) -> CorpusQueryPlan:
    """Construct a validated, deterministic corpus query plan.

    Raises ``CorpusQueryError`` on an unsupported metadata key or invalid enum
    value (fail closed). ``limit`` is clamped to a conservative ceiling; an
    invalid (<=0 / absurd) limit is treated as the default.
    """
    norm = normalize_query_text(text)
    meta = CorpusMetadataFilter.from_dict(metadata)
    # Conservative hard ceiling; never an unbounded corpus scan.
    if not isinstance(limit, int) or limit <= 0 or limit > 500:
        limit = 100
    return CorpusQueryPlan(text=norm, metadata=meta, limit=limit)


def _match_metadata(
    meta: CorpusMetadataFilter,
    *,
    profile_id: Optional[str],
    project_id: Optional[str],
    knowledge_space_id: Optional[str],
    source_id: Optional[str],
    unit_kind: Optional[str],
    lifecycle_status: Optional[str],
) -> bool:
    """True when a candidate row satisfies the closed-set metadata filter.

    Pure predicate; performs NO authorization. Authorization is supplied
    separately by the M5 authorized scope check in retrieval.py.
    """
    if meta.profile_id is not None and meta.profile_id != profile_id:
        return False
    if meta.project_id is not None and meta.project_id != project_id:
        return False
    if meta.knowledge_space_id is not None and meta.knowledge_space_id != knowledge_space_id:
        return False
    if meta.source_id is not None and meta.source_id != source_id:
        return False
    if meta.unit_kind is not None and meta.unit_kind != unit_kind:
        return False
    if meta.lifecycle_status is not None and meta.lifecycle_status != lifecycle_status:
        return False
    return True


__all__ = [
    "CorpusQueryError",
    "CorpusMetadataFilter",
    "CorpusQueryPlan",
    "VALID_METADATA_KEYS",
    "normalize_query_text",
    "build_query_plan",
    "CorpusQueryPlan",
    "_match_metadata",
]
