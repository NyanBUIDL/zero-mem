"""M10.5 — deterministic corpus query planner (metadata + lexical normalization).

Pure, side-effect-free helpers that translate an authorized corpus query into a
deterministic plan. No DB, no LLM, no network.

Two responsibilities:

1. **Query normalization** — sanitize/normalize a free-text query for FTS
   discovery the same way the repo normalizes M3 text (lowercased, whitespace
   collapsed). Keeps determinism explicit; no stemming/tokenization surprises
   here: the planner never rewrites words. Term splitting, English stemming and
   scoring live in ``src/corpus/retrieval.py`` (T7) and see only authorized rows.

2. **Metadata filter validation** — accept only the approved, closed set of
   deterministic corpus metadata dimensions (M10.1-M10.4 contracts only):

     - profile_id
     - project_id
     - knowledge_space_id
     - source_id          (the corpus_source identity the unit belongs to)
     - unit_kind          (closed coarse structural set)
     - lifecycle_status   (closed lifecycle enum)
     - memory_type        (source ``custom_meta.memory_type``; ADR-V170-01)
     - external_ref_prefix (prefix of the source ``external_ref``; ADR-V170-01)

   Any unknown dimension is rejected (fail closed). No domain-specific metadata
   (finance/quant/medical/legal) is introduced as core architecture — M10 remains
   universal-domain.

The planner produces a validated ``CorpusQueryPlan`` consumed by
``src/corpus/retrieval.py``. It performs NO authorization; authorization is the
exclusive responsibility of ``AuthorizedReadService`` (M5), which supplies the
authorized scope the plan's metadata dimensions are checked against.
"""

from __future__ import annotations

import re
import unicodedata
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
        "memory_type",
        "external_ref_prefix",
    }
)

# ADR-V170-01: bounds for the two source-provenance filters.
_MEMORY_TYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
_MAX_EXTERNAL_REF_PREFIX = 512

# DEF-061: agent-facing default is token-friendly; the ceiling bounds internal
# callers (benchmarks, evidence building) that ask for a wider candidate window.
DEFAULT_RESULT_LIMIT: int = 20
MAX_RESULT_LIMIT: int = 500

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
    memory_type: Optional[str] = None
    external_ref_prefix: Optional[str] = None

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
        if self.memory_type is not None:
            out["memory_type"] = self.memory_type
        if self.external_ref_prefix is not None:
            out["external_ref_prefix"] = self.external_ref_prefix
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
            if key == "memory_type" and (
                not isinstance(value, str) or not _MEMORY_TYPE_RE.match(value)
            ):
                raise CorpusQueryError("invalid_corpus_memory_type")
            if key == "external_ref_prefix" and (
                not isinstance(value, str)
                or not value
                or len(value) > _MAX_EXTERNAL_REF_PREFIX
            ):
                raise CorpusQueryError("invalid_corpus_external_ref_prefix")
            cleaned[key] = value
        return cls(**cleaned)

    def items(self) -> List[Tuple[str, str]]:
        return list(self.as_dict().items())


@dataclass(frozen=True)
class CorpusQueryPlan:
    """Validated, deterministic corpus retrieval plan.

    - ``text`` is the normalized lexical query (may be empty for metadata-only).
    - ``metadata`` is the closed-set filter.
    - ``limit`` is the result cap: ``DEFAULT_RESULT_LIMIT`` unless a caller asks
      for more, never above ``MAX_RESULT_LIMIT`` (the M7 EvidenceSet budget is
      the final cap).
    """

    text: str
    metadata: CorpusMetadataFilter
    limit: int = DEFAULT_RESULT_LIMIT

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

    Unicode NFC (units are stored NFC, so a decomposed query such as macOS
    clipboard text still matches), lowercase, collapse internal whitespace;
    strip trailing/leading space. No stemming, no tokenization, no LLM.
    Empty/None input yields "".
    """
    if not text:
        return ""
    return " ".join(unicodedata.normalize("NFC", str(text)).lower().split())


def build_query_plan(
    text: Optional[str] = None,
    *,
    metadata: Optional[Mapping[str, Any]] = None,
    limit: Optional[int] = None,
) -> CorpusQueryPlan:
    """Construct a validated, deterministic corpus query plan.

    Raises ``CorpusQueryError`` on an unsupported metadata key or invalid enum
    value (fail closed). ``limit`` defaults to ``DEFAULT_RESULT_LIMIT``; an
    invalid (None / non-int / <=0 / above ``MAX_RESULT_LIMIT``) limit is treated
    as the default, so there is never an unbounded corpus scan.
    """
    norm = normalize_query_text(text)
    meta = CorpusMetadataFilter.from_dict(metadata)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
        or limit > MAX_RESULT_LIMIT
    ):
        limit = DEFAULT_RESULT_LIMIT
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
    memory_type: Optional[str] = None,
    external_ref: Optional[str] = None,
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
    if meta.memory_type is not None and meta.memory_type != memory_type:
        return False
    if meta.external_ref_prefix is not None and not (external_ref or "").startswith(
        meta.external_ref_prefix
    ):
        return False
    return True


__all__ = [
    "DEFAULT_RESULT_LIMIT",
    "MAX_RESULT_LIMIT",
    "CorpusQueryError",
    "CorpusMetadataFilter",
    "CorpusQueryPlan",
    "VALID_METADATA_KEYS",
    "normalize_query_text",
    "build_query_plan",
    "CorpusQueryPlan",
    "_match_metadata",
]
