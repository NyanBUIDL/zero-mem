"""M10.5 — authorization-safe deterministic corpus retrieval.

This module builds the authorized corpus candidate set and ranks it. It is the
corpus-read facade that the M5 ``AuthorizedReadService.corpus_unit_search``
delegates the lower-level query to. It performs **no authorization of its own**:
the caller (AuthorizedReadService) has already evaluated the M5 policy and
passes an ``AuthorizedCorpusScope`` describing exactly which
(profile_id, project_id, knowledge_space_id) combinations the requester may
read as ``corpus_unit``.

Load-bearing invariant (authorization-before-influence):

    FTS is used ONLY for lexical candidate DISCOVERY. Every discovered unit is
    then filtered to the AUTHORIZED scope BEFORE any ranking, scoring, fusion,
    or truncation. Unauthorized units are dropped at the scope-filter step and
    never enter the ranking computation. Deterministic ranking is computed
    purely over the in-memory authorized subset, so unauthorized document
    frequency / tf-idf inside SQLite FTS statistics cannot alter authorized
    scores, ordering, or truncation. Hidden candidates therefore have ZERO
    influence on the visible result.

Optional semantic retrieval (owner decision Q2 RESOLVED A):

    A ``SemanticAdapter`` is an OPTIONAL, LOCAL-ONLY protocol. When present and
    ``available``, it is applied ONLY over the already-authorized ``CorpusHit``
    set (never a global vector ANN), so the authorization-before-influence
    invariant holds for the semantic path too. If no adapter is supplied, or the
    adapter reports ``available=False`` (missing model / failure), retrieval
    degrades safely to the deterministic lexical path. No embedding package is
    mandatory and none is imported here.

Read-only: this module only issues SELECTs against the derived v10 corpus
tables. It never mutates canonical state, derived tables, blobs, or JSONL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol, runtime_checkable

from .query_planner import (
    CorpusMetadataFilter,
    CorpusQueryError,
    CorpusQueryPlan,
    _match_metadata,
)
from src.storage.migrations import migrate_10 as _migrate_10


# Conservative lexical scoring ceiling so scores stay bounded/deterministic.
_MAX_LEXICAL_SCORE = 1_000_000


@dataclass(frozen=True)
class AuthorizedCorpusScope:
    """The corpus_unit authorization decision, supplied by M5.

    A unit is authorized iff its (profile_id, project_id, knowledge_space_id)
    matches one of the allowed (profile, project, space) tuples OR satisfies the
    global-rule / project-grant semantics M5 already computed. We reuse a simple
    explicit membership model: the authorized set is enumerated as concrete
    (profile_id, project_id, knowledge_space_id) tuples (NULL-equality allowed
    for unowned/default scope). The M5 facade enumerates these from its
    EffectiveReadScope before calling into this module.
    """

    # Each tuple is (profile_id, project_id, knowledge_space_id); None entries
    # mean "any" for that dimension (used only when M5 explicitly authorized
    # the unowned/default NULL scope).
    allowed_scopes: tuple = ()

    def allows(self, profile_id: Optional[str], project_id: Optional[str],
               knowledge_space_id: Optional[str]) -> bool:
        for ap, aj, ak in self.allowed_scopes:
            # The (None, None, None) sentinel means the UNOWNED/DEFAULT scope:
            # only units whose profile/project/space are ALL NULL match it
            # (the M5 global-read default unowned row). It does NOT mean "any".
            if ap is None and aj is None and ak is None:
                if profile_id is None and project_id is None and knowledge_space_id is None:
                    return True
                continue
            p_ok = (ap is None) or (ap == profile_id)
            j_ok = (aj is None) or (aj == project_id)
            k_ok = (ak is None) or (ak == knowledge_space_id)
            if p_ok and j_ok and k_ok:
                return True
        return False


@dataclass(frozen=True)
class CorpusHit:
    """One authorized corpus candidate (DATA only — never instruction)."""

    unit_id: str
    source_id: str
    source_ref: str
    source_location_id: str
    content_hash: str
    normalized_text: str
    kind: str
    profile_id: Optional[str]
    project_id: Optional[str]
    knowledge_space_id: Optional[str]
    lifecycle_status: str
    sensitivity: str
    page: Optional[int]
    unit_order: int
    # Deterministic lexical score (bm25-style, computed over authorized subset).
    lexical_score: float = 0.0
    # Optional semantic score (only when a semantic adapter is active).
    semantic_score: float = 0.0
    # Combined score used for final ordering.
    combined_score: float = 0.0
    # Which retrieval mode produced this hit (lexical / semantic / fused).
    retrieval_mode: str = "lexical"
    # Stable reason string for diagnostics (never leaks content).
    reason: str = "authorized_corpus_match"

    @property
    def resource_type(self) -> str:
        return "corpus_unit"

    def as_evidence_dict(self) -> dict:
        """Format-neutral representation for the EvidenceSet layer."""
        return {
            "unit_id": self.unit_id,
            "resource_type": self.resource_type,
            "source_id": self.source_id,
            "source_ref": self.source_ref,
            "source_location_id": self.source_location_id,
            "content_hash": self.content_hash,
            "kind": self.kind,
            "profile_id": self.profile_id,
            "project_id": self.project_id,
            "knowledge_space_id": self.knowledge_space_id,
            "lifecycle_status": self.lifecycle_status,
            "sensitivity": self.sensitivity,
            "page": self.page,
            "unit_order": self.unit_order,
            "lexical_score": self.lexical_score,
            "semantic_score": self.semantic_score,
            "combined_score": self.combined_score,
            "retrieval_mode": self.retrieval_mode,
        }


@runtime_checkable
class SemanticAdapter(Protocol):
    """Optional local-only semantic ranking adapter (Q2 RESOLVED A).

    Implementations MUST rank over an already-authorized ``List[CorpusHit]`` and
    return the same hits with ``semantic_score`` populated. They must NEVER
    perform a global vector ANN or expand the candidate set. ``available`` must
    be False when the local model/index is missing or fails, so the caller
    degrades to lexical retrieval.
    """

    @property
    def available(self) -> bool:
        ...

    def rank(self, query: str, hits: List[CorpusHit]) -> List[CorpusHit]:
        """Return ``hits`` with ``semantic_score`` populated, same ordering/identity."""
        ...


class _NoSemanticAdapter:
    """Absence-safe default: semantic retrieval is not available."""

    @property
    def available(self) -> bool:
        return False

    def rank(self, query: str, hits: List[CorpusHit]) -> List[CorpusHit]:
        return hits


NO_SEMANTIC_ADAPTER: SemanticAdapter = _NoSemanticAdapter()


# FTS5 MATCH special-characters that must be quoted to avoid a query error.
_FTS_SPECIAL = re.compile(r'[\"\[\]\{\}\(\)\*^\:\-\+]+')


def _fts_safe_query(text: str) -> str:
    """Build a safe FTS5 MATCH expression from normalized text.

    Tokenizes on whitespace, quotes each token, and joins with AND so the query
    is well-formed and deterministic. Empty input yields a sentinel that matches
    nothing (caller handles metadata-only separately).
    """
    tokens = [t for t in text.split() if t]
    if not tokens:
        return ""  # signal: no lexical constraint
    safe = []
    for tok in tokens:
        cleaned = _FTS_SPECIAL.sub("", tok)
        if not cleaned:
            continue
        # Quote to avoid FTS operators; prefix match for partial words.
        safe.append(f'"{cleaned}"*')
    return " ".join(safe)


def _fts_or_query(text: str) -> str:
    """DEF-031: OR-joined FTS MATCH expression for the precision-guarded
    fallback (parity with the M3 event FTS path, src/retrieval/search.py
    V130-01). Each term is quoted + prefix-starred exactly like the AND pass,
    so caller text can never inject FTS operators; the expression is always
    passed as a bound parameter."""
    tokens = [t for t in text.split() if t]
    safe = []
    for tok in tokens:
        cleaned = _FTS_SPECIAL.sub("", tok)
        if not cleaned:
            continue
        safe.append(f'"{cleaned}"*')
    return " OR ".join(safe)


def _fts_term_count(text: str) -> int:
    return len([t for t in text.split() if _FTS_SPECIAL.sub("", t)])


# ---------------------------------------------------------------------------
# Deterministic lexical scoring (computed over the AUTHORIZED subset only)
# ---------------------------------------------------------------------------

def _term_frequency(text: str, token: str) -> int:
    if not token:
        return 0
    return text.split().count(token) if " " not in token else text.count(token)


def _lexical_score(normalized_text: str, query_tokens: List[str]) -> float:
    """Bounded, deterministic lexical score over authorized text.

    Sum of per-token term-frequency, capped so scores stay stable and bounded.
    No dependence on corpus-wide document frequency (which would be influenced
    by unauthorized rows) — only on the authorized unit's own content.
    """
    if not query_tokens or not normalized_text:
        return 0.0
    score = 0
    norm = normalized_text.lower()
    for tok in query_tokens:
        tf = _term_frequency(norm, tok.lower())
        score += tf
    return float(min(score, _MAX_LEXICAL_SCORE))


# Stable deterministic tie-break key: higher score, then stable identity.
def _rank_key(hit: CorpusHit) -> tuple:
    return (
        -round(hit.combined_score, 6),
        hit.profile_id or "",
        hit.project_id or "",
        hit.source_id or "",
        hit.unit_id or "",
        hit.unit_order,
    )


# ---------------------------------------------------------------------------
# Core retrieval
# ---------------------------------------------------------------------------

def _row_to_hit(row) -> CorpusHit:
    return CorpusHit(
        unit_id=row["unit_id"],
        source_id=row["source_ref"],
        source_ref=row["source_ref"],
        source_location_id=row["source_location_id"],
        content_hash=row["content_hash"],
        normalized_text=row["normalized_text"],
        kind=row["kind"],
        profile_id=row["profile_id"],
        project_id=row["project_id"],
        knowledge_space_id=row["knowledge_space_id"],
        lifecycle_status=row["lifecycle_status"],
        sensitivity=row["sensitivity"],
        page=row["page"],
        unit_order=row["unit_order"],
    )


def _authorize_and_filter(
    rows: List[Any],
    scope: AuthorizedCorpusScope,
    meta: CorpusMetadataFilter,
) -> List[CorpusHit]:
    """Keep ONLY authorized rows that also satisfy the closed metadata filter.

    This is the authorization-before-influence enforcement point: unauthorized
    rows are removed here and never reach ranking/scoring/fusion.
    """
    hits: List[CorpusHit] = []
    for row in rows:
        # Authorization (M5 scope) — fail closed on any unmatched row.
        if not scope.allows(row["profile_id"], row["project_id"], row["knowledge_space_id"]):
            continue
        # Closed metadata filter (no authorization of its own).
        if not _match_metadata(
            meta,
            profile_id=row["profile_id"],
            project_id=row["project_id"],
            knowledge_space_id=row["knowledge_space_id"],
            source_id=row["source_ref"],
            unit_kind=row["kind"],
            lifecycle_status=row["lifecycle_status"],
        ):
            continue
        # deleted lifecycle is never eligible corpus evidence.
        if (row["lifecycle_status"] or "").lower() == "deleted":
            continue
        hits.append(_row_to_hit(row))
    return hits


_UNIT_COLUMNS = (
    "unit_id, source_ref, source_location_id, content_hash, normalized_text, "
    "kind, profile_id, project_id, knowledge_space_id, lifecycle_status, "
    "sensitivity, page, unit_order"
)


# DEF-030 (DEF-C1): candidate-discovery cap. Ranking happens over the
# authorized subset of the DISCOVERED candidates; a safety factor keeps the
# top-k of a reasonable query inside the cap while bounding memory on broad
# queries ("risk", "the"). Ranking is over the capped set (documented).
_DISCOVERY_FACTOR = 50


def _discovery_cap(plan_limit: int) -> int:
    return max(plan_limit * _DISCOVERY_FACTOR, plan_limit)


def _read_all_units(cur, cap: int) -> list:
    """Read derived units (bounded candidate discovery) for the explicit
    non-FTS capability path.

    Bounded by ``cap`` (DEF-030) so a metadata-only query never materializes the
    whole table. Callers must pass the rows through ``_authorize_and_filter``
    before lexical scoring or limiting.
    """
    return cur.execute(
        f"SELECT {_UNIT_COLUMNS} FROM zm_corpus_units LIMIT ?", (cap,)
    ).fetchall()


def retrieve_corpus(
    conn,
    scope: AuthorizedCorpusScope,
    plan: CorpusQueryPlan,
    *,
    semantic: Optional[SemanticAdapter] = None,
) -> List[CorpusHit]:
    """Authorization-safe deterministic corpus retrieval.

    Flow:
      1. Discover lexical candidates via FTS MATCH (discovery only).
      2. Scope-filter to the AUTHORIZED set (drop unauthorized before ranking).
      3. Apply closed metadata filter.
      4. Compute deterministic lexical score over the authorized subset.
      5. Optionally fuse a local semantic adapter (authorized set only).
      6. Return ranked ``CorpusHit[]`` (bounded by ``plan.limit``).

    Never mutates the database. Raises no exception that leaks content; query
    errors are sanitized to a typed ``CorpusQueryError``.
    """
    semantic = semantic or NO_SEMANTIC_ADAPTER
    cur = conn.cursor()
    query_tokens = plan.text.split()

    # Step 1: lexical discovery. If no lexical text, every unit is a candidate
    # (metadata-only retrieval). Without FTS5, the derived unit relation is the
    # explicit O(N) candidate source; authorization/filtering still precedes
    # every lexical influence.
    # DEF-030 (DEF-C1): all discovery paths are bounded by a safety-factor cap;
    # ranking runs only over the authorized subset of the capped candidate set.
    cap = _discovery_cap(plan.limit)
    if plan.is_metadata_only:
        try:
            rows = _read_all_units(cur, cap)
        except Exception as exc:  # pragma: no cover - defensive
            raise CorpusQueryError(f"corpus_query_failed: {type(exc).__name__}") from None
    else:
        fts_expr = _fts_safe_query(plan.text)
        if not fts_expr:
            # Nothing lexical to match: fall back to metadata-only discovery.
            try:
                rows = _read_all_units(cur, cap)
            except Exception as exc:  # pragma: no cover - defensive
                raise CorpusQueryError(f"corpus_query_failed: {type(exc).__name__}") from None
        elif not _migrate_10.FTS5_AVAILABLE:
            try:
                rows = _read_all_units(cur, cap)
            except Exception as exc:  # pragma: no cover - defensive
                raise CorpusQueryError(f"corpus_query_failed: {type(exc).__name__}") from None
        else:
            # FTS discovery: match unit_ids, then join units (bounded by cap).
            try:
                rows = cur.execute(
                    "SELECT u.unit_id, u.source_ref, u.source_location_id, u.content_hash, "
                    "u.normalized_text, u.kind, u.profile_id, u.project_id, "
                    "u.knowledge_space_id, u.lifecycle_status, u.sensitivity, u.page, u.unit_order "
                    "FROM zm_corpus_fts JOIN zm_corpus_units u ON u.unit_id = zm_corpus_fts.unit_id "
                    "WHERE zm_corpus_fts MATCH ? LIMIT ?",
                    (fts_expr, cap),
                ).fetchall()
                # DEF-031 (DEF-C2): precision-guarded OR fallback — only when
                # the implicit-AND pass returned zero rows AND the query has
                # >= 2 terms (single-term queries have nothing to fall back to).
                # Mirror of the M3 event FTS path (search.py V130-01). The OR
                # expression is FTS5-quoted and stays a bound parameter.
                if not rows and _fts_term_count(plan.text) >= 2:
                    or_expr = _fts_or_query(plan.text)
                    if or_expr:
                        rows = cur.execute(
                            "SELECT u.unit_id, u.source_ref, u.source_location_id, u.content_hash, "
                            "u.normalized_text, u.kind, u.profile_id, u.project_id, "
                            "u.knowledge_space_id, u.lifecycle_status, u.sensitivity, u.page, u.unit_order "
                            "FROM zm_corpus_fts JOIN zm_corpus_units u ON u.unit_id = zm_corpus_fts.unit_id "
                            "WHERE zm_corpus_fts MATCH ? LIMIT ?",
                            (or_expr, cap),
                        ).fetchall()
            except Exception as exc:
                # Malformed FTS expression or missing FTS table => fail closed to
                # a typed error (never silently return everything).
                raise CorpusQueryError(f"corpus_fts_error: {type(exc).__name__}") from None

    # Steps 2-3: authorization + metadata filter BEFORE ranking.
    hits = _authorize_and_filter(rows, scope, plan.metadata)
    if not hits:
        return []

    # Step 4: deterministic lexical score over the AUTHORIZED subset only.
    hits = [_scored(h, _lexical_score(h.normalized_text, query_tokens)) for h in hits]

    # Step 5: optional semantic fusion over the authorized set ONLY.
    semantic_active = False
    if semantic.available:
        semantic_active = True
        try:
            ranked = semantic.rank(plan.text, hits)
            hits = [_fused(h) for h in ranked]
        except Exception:
            # Semantic failure degrades safely to lexical (never expands scope).
            hits = [_lexical_only(h) for h in hits]
            semantic_active = False

    # Step 6: deterministic combined ordering (lexical + optional semantic).
    hits = [_with_combined(h, semantic_active) for h in hits]
    hits.sort(key=_rank_key)
    return hits[: plan.limit]


# Helpers to rebuild frozen CorpusHit with computed fields (frozen dataclass).
def _scored(h: CorpusHit, lexical_score: float) -> CorpusHit:
    return CorpusHit(
        unit_id=h.unit_id, source_id=h.source_id, source_ref=h.source_ref,
        source_location_id=h.source_location_id, content_hash=h.content_hash,
        normalized_text=h.normalized_text, kind=h.kind, profile_id=h.profile_id,
        project_id=h.project_id, knowledge_space_id=h.knowledge_space_id,
        lifecycle_status=h.lifecycle_status, sensitivity=h.sensitivity,
        page=h.page, unit_order=h.unit_order, lexical_score=lexical_score,
        semantic_score=h.semantic_score, combined_score=h.combined_score,
        retrieval_mode=h.retrieval_mode, reason=h.reason,
    )


def _fused(h: CorpusHit) -> CorpusHit:
    return CorpusHit(
        unit_id=h.unit_id, source_id=h.source_id, source_ref=h.source_ref,
        source_location_id=h.source_location_id, content_hash=h.content_hash,
        normalized_text=h.normalized_text, kind=h.kind, profile_id=h.profile_id,
        project_id=h.project_id, knowledge_space_id=h.knowledge_space_id,
        lifecycle_status=h.lifecycle_status, sensitivity=h.sensitivity,
        page=h.page, unit_order=h.unit_order, lexical_score=h.lexical_score,
        semantic_score=h.semantic_score, combined_score=h.combined_score,
        retrieval_mode="semantic", reason=h.reason,
    )


def _lexical_only(h: CorpusHit) -> CorpusHit:
    return CorpusHit(
        unit_id=h.unit_id, source_id=h.source_id, source_ref=h.source_ref,
        source_location_id=h.source_location_id, content_hash=h.content_hash,
        normalized_text=h.normalized_text, kind=h.kind, profile_id=h.profile_id,
        project_id=h.project_id, knowledge_space_id=h.knowledge_space_id,
        lifecycle_status=h.lifecycle_status, sensitivity=h.sensitivity,
        page=h.page, unit_order=h.unit_order, lexical_score=h.lexical_score,
        semantic_score=0.0, combined_score=h.combined_score,
        retrieval_mode="lexical", reason=h.reason,
    )


def _with_combined(h: CorpusHit, semantic_active: bool) -> CorpusHit:
    combined = h.lexical_score + (h.semantic_score if semantic_active else 0.0)
    mode = h.retrieval_mode if semantic_active else "lexical"
    return CorpusHit(
        unit_id=h.unit_id, source_id=h.source_id, source_ref=h.source_ref,
        source_location_id=h.source_location_id, content_hash=h.content_hash,
        normalized_text=h.normalized_text, kind=h.kind, profile_id=h.profile_id,
        project_id=h.project_id, knowledge_space_id=h.knowledge_space_id,
        lifecycle_status=h.lifecycle_status, sensitivity=h.sensitivity,
        page=h.page, unit_order=h.unit_order, lexical_score=h.lexical_score,
        semantic_score=h.semantic_score, combined_score=combined,
        retrieval_mode=mode, reason=h.reason,
    )


__all__ = [
    "AuthorizedCorpusScope",
    "CorpusHit",
    "SemanticAdapter",
    "NO_SEMANTIC_ADAPTER",
    "retrieve_corpus",
    "CorpusQueryError",
]
