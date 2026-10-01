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

import json
import math
import unicodedata
from collections import Counter
from dataclasses import dataclass, field, replace
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
    # ADR-V170-01: source provenance read from zm_corpus_sources at query time.
    # Informational only; never an authorization input.
    external_ref: Optional[str] = None
    memory_type: Optional[str] = None

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
            "external_ref": self.external_ref,
            "memory_type": self.memory_type,
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


# DEF-055: queries are split into FTS terms on every non-word character.  FTS5's
# default tokenizer (unicode61) indexes ``blue-green`` as the tokens ``blue`` and
# ``green``, so the query side must do the same; deleting the hyphen produced
# ``bluegreen`` (0 hits) and ``C++`` degraded to the prefix ``c*``.  Every term is
# emitted as a quoted string, so caller text can never inject FTS operators.

def _is_word_char(ch: str) -> bool:
    # Letters/digits plus combining marks (a decomposed accent must stay inside
    # its word).  '_' is a separator, exactly like the FTS5 tokenizer.
    return ch.isalnum() or unicodedata.category(ch)[0] == "M"


def _split_words(text: str) -> List[str]:
    words: List[str] = []
    current: List[str] = []
    for ch in unicodedata.normalize("NFC", text):
        if _is_word_char(ch):
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def _query_groups(text: str) -> List[List[str]]:
    """Whitespace-delimited query tokens -> their word terms.

    A group with more than one term came from one punctuated token such as
    ``blue-green``; it is also scored as a phrase bonus.
    """
    groups: List[List[str]] = []
    for token in text.split():
        words = [w.lower() for w in _split_words(token)]
        if words:
            groups.append(words)
    return groups


def _fts_term(term: str) -> str:
    # Prefix match for partial words, but a single character stays exact:
    # ``C++`` must match the token ``c``, not every word starting with c.
    return f'"{term}"*' if len(term) > 1 else f'"{term}"'


def _fts_safe_query(text: str) -> str:
    """Build a safe FTS5 MATCH expression from normalized text.

    Splits on non-word characters, quotes every term and joins with implicit
    AND so the query is well-formed and deterministic.  Text with no word
    characters yields "" (caller treats it as no lexical constraint).
    """
    return " ".join(_fts_term(term) for group in _query_groups(text) for term in group)


def _fts_or_query(text: str) -> str:
    """DEF-031: OR-joined FTS MATCH expression for the precision-guarded
    fallback (parity with the M3 event FTS path, src/retrieval/search.py
    V130-01). Terms are split/quoted exactly like the AND pass, so caller text
    can never inject FTS operators; the expression is always passed as a bound
    parameter."""
    return " OR ".join(_fts_term(term) for group in _query_groups(text) for term in group)


def _fts_term_count(text: str) -> int:
    return sum(len(group) for group in _query_groups(text))


# ---------------------------------------------------------------------------
# Deterministic lexical scoring (computed over the AUTHORIZED subset only)
# ---------------------------------------------------------------------------
#
# DEF-061: BM25 (k1=1.2, b=0.75) with unit-length normalization, computed in
# Python over the authorized candidate set.  SQLite's FTS5 ``bm25()`` is NOT
# used on purpose: it derives IDF and average length from the WHOLE FTS table,
# so unauthorized rows would shift authorized scores and order, breaking the
# authorization-before-influence invariant (see module docstring).  Here the
# document frequency, N and average length come only from authorized candidates.

_BM25_K1 = 1.2
_BM25_B = 0.75
# Added once per punctuated query token (e.g. ``blue-green``) whose words occur
# adjacently in a unit; on the scale of one rare-term contribution.
_PHRASE_BONUS = 1.0


def _fold(word: str) -> str:
    """Case + diacritic folding for scoring (NFD, drop combining marks, đ -> d)."""
    decomposed = unicodedata.normalize("NFD", word.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("\u0111", "d")


def _score_tokens(text: str) -> List[str]:
    return [_fold(word) for word in _split_words(text)]


def _scoring_terms(text: str) -> tuple:
    """Unique folded query terms (in order) and the folded multi-word phrases."""
    terms: List[str] = []
    seen = set()
    phrases: List[tuple] = []
    for group in _query_groups(text):
        folded = tuple(_fold(word) for word in group)
        for term in folded:
            if term not in seen:
                seen.add(term)
                terms.append(term)
        if len(folded) > 1 and folded not in phrases:
            phrases.append(folded)
    return terms, phrases


def _token_matches(token: str, term: str) -> bool:
    # Mirrors the FTS query: prefix for multi-character terms, exact for one.
    return token.startswith(term) if len(term) > 1 else token == term


def _term_frequency(counts: Counter, term: str) -> int:
    if len(term) > 1:
        return sum(count for token, count in counts.items() if token.startswith(term))
    return counts.get(term, 0)


def _has_phrase(tokens: List[str], phrase: tuple) -> bool:
    width = len(phrase)
    for start in range(len(tokens) - width + 1):
        if all(_token_matches(tokens[start + i], phrase[i]) for i in range(width)):
            return True
    return False


def _bm25_scores(hits: List[CorpusHit], query_text: str) -> List[float]:
    """BM25 score per hit, using statistics of ``hits`` (the authorized set) only."""
    terms, phrases = _scoring_terms(query_text)
    if not terms or not hits:
        return [0.0] * len(hits)
    token_lists = [_score_tokens(hit.normalized_text) for hit in hits]
    counters = [Counter(tokens) for tokens in token_lists]
    n_docs = len(hits)
    avg_len = (sum(len(tokens) for tokens in token_lists) / n_docs) or 1.0
    freqs = [[_term_frequency(counts, term) for term in terms] for counts in counters]
    idf = []
    for index in range(len(terms)):
        df = sum(1 for row in freqs if row[index] > 0)
        idf.append(math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5)))
    scores: List[float] = []
    for tokens, row in zip(token_lists, freqs):
        length_norm = _BM25_K1 * (1.0 - _BM25_B + _BM25_B * len(tokens) / avg_len)
        score = 0.0
        for index, tf in enumerate(row):
            if tf > 0:
                score += idf[index] * tf * (_BM25_K1 + 1.0) / (tf + length_norm)
        score += _PHRASE_BONUS * sum(1 for phrase in phrases if _has_phrase(tokens, phrase))
        scores.append(round(min(score, _MAX_LEXICAL_SCORE), 6))
    return scores


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

def _memory_type_from_custom_meta(raw: Any) -> Optional[str]:
    """``memory_type`` from a source's JSON ``custom_meta`` (None when absent/invalid)."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        meta = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(meta, dict):
        return None
    value = meta.get("memory_type")
    return value if isinstance(value, str) and value else None


def _row_to_hit(row, memory_type: Optional[str] = None) -> CorpusHit:
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
        external_ref=row["source_external_ref"],
        memory_type=memory_type,
    )


def _authorize_and_filter(
    rows: List[Any],
    scope: AuthorizedCorpusScope,
    meta: CorpusMetadataFilter,
) -> List[CorpusHit]:
    """Keep ONLY authorized rows that also satisfy the closed metadata filter.

    This is the authorization-before-influence enforcement point: unauthorized
    rows are removed here and never reach ranking/scoring/fusion.  The source
    provenance filters (memory_type / external_ref_prefix) run strictly AFTER
    the scope check, on rows that are already authorized (ADR-V170-01).
    """
    hits: List[CorpusHit] = []
    for row in rows:
        # Authorization (M5 scope) — fail closed on any unmatched row.
        if not scope.allows(row["profile_id"], row["project_id"], row["knowledge_space_id"]):
            continue
        memory_type = _memory_type_from_custom_meta(row["source_custom_meta"])
        # Closed metadata filter (no authorization of its own).
        if not _match_metadata(
            meta,
            profile_id=row["profile_id"],
            project_id=row["project_id"],
            knowledge_space_id=row["knowledge_space_id"],
            source_id=row["source_ref"],
            unit_kind=row["kind"],
            lifecycle_status=row["lifecycle_status"],
            memory_type=memory_type,
            external_ref=row["source_external_ref"],
        ):
            continue
        # deleted lifecycle is never eligible corpus evidence.
        if (row["lifecycle_status"] or "").lower() == "deleted":
            continue
        hits.append(_row_to_hit(row, memory_type))
    return hits


# ADR-V170-01: provenance is read at query time from the source table (a LEFT
# JOIN on columns that already exist in schema v10+; no migration needed).
_UNIT_COLUMNS = (
    "u.unit_id, u.source_ref, u.source_location_id, u.content_hash, u.normalized_text, "
    "u.kind, u.profile_id, u.project_id, u.knowledge_space_id, u.lifecycle_status, "
    "u.sensitivity, u.page, u.unit_order, "
    "s.external_ref AS source_external_ref, s.custom_meta AS source_custom_meta"
)
_SOURCE_JOIN = "LEFT JOIN zm_corpus_sources s ON s.source_id = u.source_ref"


# DEF-030 (DEF-C1): candidate-discovery cap. Ranking happens over the
# authorized subset of the DISCOVERED candidates; a safety factor keeps the
# top-k of a reasonable query inside the cap while bounding memory on broad
# queries ("risk", "the"). Ranking is over the capped set (documented).
_DISCOVERY_FACTOR = 50
# DEF-061: lowering the default result limit must not shrink the candidate
# window (ranking runs over the authorized subset of the discovered set), so the
# window never drops below this floor.  Both constants are module-level knobs.
_DISCOVERY_CAP_FLOOR = 5000


def _discovery_cap(plan_limit: int) -> int:
    return max(plan_limit * _DISCOVERY_FACTOR, _DISCOVERY_CAP_FLOOR, plan_limit)


# DEF-061: ``duplicate_of`` marks an exact within-source repeat of an earlier unit
# (same source => same scope, so collapsing never touches authorization identity);
# excluding it in SQL also keeps repeats from consuming the discovery cap.
_FTS_DISCOVERY_SQL = (
    f"SELECT {_UNIT_COLUMNS} "
    f"FROM zm_corpus_fts JOIN zm_corpus_units u ON u.unit_id = zm_corpus_fts.unit_id "
    f"{_SOURCE_JOIN} "
    "WHERE zm_corpus_fts MATCH ? AND u.duplicate_of IS NULL LIMIT ?"
)


def _read_all_units(cur, cap: int) -> list:
    """Read derived units (bounded candidate discovery) for the explicit
    non-FTS capability path.

    Bounded by ``cap`` (DEF-030) so a metadata-only query never materializes the
    whole table. Callers must pass the rows through ``_authorize_and_filter``
    before lexical scoring or limiting.
    """
    return cur.execute(
        f"SELECT {_UNIT_COLUMNS} FROM zm_corpus_units u {_SOURCE_JOIN} "
        "WHERE u.duplicate_of IS NULL LIMIT ?",
        (cap,),
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
      1. Discover lexical candidates via FTS MATCH (discovery only; within-source
         duplicate units are excluded in SQL).
      2. Scope-filter to the AUTHORIZED set (drop unauthorized before ranking).
      3. Apply closed metadata filter (incl. source memory_type / external_ref
         prefix, ADR-V170-01) - strictly after the scope check.
      4. Compute deterministic BM25 over the authorized subset (DEF-061).
      5. Optionally fuse a local semantic adapter (authorized set only).
      6. Return ranked ``CorpusHit[]`` (bounded by ``plan.limit``).

    Never mutates the database. Raises no exception that leaks content; query
    errors are sanitized to a typed ``CorpusQueryError``.
    """
    semantic = semantic or NO_SEMANTIC_ADAPTER
    cur = conn.cursor()
    # True only when discovery had no FTS to filter on a text query: the fallback
    # then returns every unit, so non-matching units are dropped after scoring.
    unfiltered_lexical_discovery = False

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
            unfiltered_lexical_discovery = True
            try:
                rows = _read_all_units(cur, cap)
            except Exception as exc:  # pragma: no cover - defensive
                raise CorpusQueryError(f"corpus_query_failed: {type(exc).__name__}") from None
        else:
            # FTS discovery: match unit_ids, then join units (bounded by cap).
            try:
                rows = cur.execute(_FTS_DISCOVERY_SQL, (fts_expr, cap)).fetchall()
                # DEF-031 (DEF-C2): precision-guarded OR fallback — only when
                # the implicit-AND pass returned zero rows AND the query has
                # >= 2 terms (single-term queries have nothing to fall back to).
                # Mirror of the M3 event FTS path (search.py V130-01). The OR
                # expression is FTS5-quoted and stays a bound parameter.
                if not rows and _fts_term_count(plan.text) >= 2:
                    or_expr = _fts_or_query(plan.text)
                    if or_expr:
                        rows = cur.execute(_FTS_DISCOVERY_SQL, (or_expr, cap)).fetchall()
            except Exception as exc:
                # Malformed FTS expression or missing FTS table => fail closed to
                # a typed error (never silently return everything).
                raise CorpusQueryError(f"corpus_fts_error: {type(exc).__name__}") from None

    # Steps 2-3: authorization + metadata filter BEFORE ranking.
    hits = _authorize_and_filter(rows, scope, plan.metadata)
    if not hits:
        return []

    # Step 4: deterministic BM25 over the AUTHORIZED subset only (DEF-061).
    scores = _bm25_scores(hits, plan.text)
    hits = [_scored(h, score) for h, score in zip(hits, scores)]
    if unfiltered_lexical_discovery:
        hits = [h for h in hits if h.lexical_score > 0.0]
        if not hits:
            return []

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
# ``replace`` keeps every other field (incl. provenance) untouched.
def _scored(h: CorpusHit, lexical_score: float) -> CorpusHit:
    return replace(h, lexical_score=lexical_score)


def _fused(h: CorpusHit) -> CorpusHit:
    return replace(h, retrieval_mode="semantic")


def _lexical_only(h: CorpusHit) -> CorpusHit:
    return replace(h, semantic_score=0.0, retrieval_mode="lexical")


def _with_combined(h: CorpusHit, semantic_active: bool) -> CorpusHit:
    combined = h.lexical_score + (h.semantic_score if semantic_active else 0.0)
    mode = h.retrieval_mode if semantic_active else "lexical"
    return replace(h, combined_score=combined, retrieval_mode=mode)


__all__ = [
    "AuthorizedCorpusScope",
    "CorpusHit",
    "SemanticAdapter",
    "NO_SEMANTIC_ADAPTER",
    "retrieve_corpus",
    "CorpusQueryError",
]
