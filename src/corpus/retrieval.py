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
import re
import unicodedata
from bisect import bisect_left
from collections import Counter
from functools import lru_cache
from dataclasses import dataclass, field, replace
from typing import Any, List, Optional, Protocol, runtime_checkable

from .query_planner import (
    CorpusMetadataFilter,
    CorpusQueryError,
    CorpusQueryPlan,
    _match_metadata,
)
from .stemming import stem
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


_ASCII_WORDS = re.compile(r"[A-Za-z0-9]+")
_UNICODE_WORDS: Optional["re.Pattern[str]"] = None


def _unicode_words() -> "re.Pattern[str]":
    """``[^\\W_]`` is exactly ``str.isalnum``; the combining marks (category M*) of the BMP are added so a
    decomposed accent stays inside its word.  Built once, on the first non-ASCII text (about 20 ms)."""
    global _UNICODE_WORDS
    if _UNICODE_WORDS is None:
        ranges: List[str] = []
        start = prev = None
        for code in range(0x300, 0x10000):
            if 0xD800 <= code < 0xE000 or unicodedata.category(chr(code))[0] != "M":
                continue
            if start is None:
                start = prev = code
            elif code == prev + 1:
                prev = code
            else:
                ranges.append(f"\\u{start:04x}-\\u{prev:04x}")
                start = prev = code
        if start is not None:
            ranges.append(f"\\u{start:04x}-\\u{prev:04x}")
        _UNICODE_WORDS = re.compile("(?:[^\\W_]|[" + "".join(ranges) + "])+")
    return _UNICODE_WORDS


def _split_words(text: str) -> List[str]:
    if text.isascii():
        return _ASCII_WORDS.findall(text)
    return _unicode_words().findall(unicodedata.normalize("NFC", text))


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


# T7: English stemming.  A plain ASCII word of at least ``_STEM_MIN_LENGTH`` letters is compared by its Porter stem
# ("adopted" ~ "adopting" ~ "adoption"); everything else (short words, digits, accented or non-Latin text) keeps the
# prefix semantics above.  FTS5's tokenizer cannot stem, so discovery matches the ROOT every inflected form shares as a
# prefix ("adopt*", "stud*" for "studies"), and the stem comparison in the scorer rejects the false friends ("student").
_STEM_MIN_LENGTH = 4
_STEM_MIN_ROOT = 3
# A natural-language question rarely has more distinct content words; the bound keeps the SQL statement small.
_MAX_DISCOVERY_TERMS = 32


def _stemmable(term: str) -> bool:
    return len(term) >= _STEM_MIN_LENGTH and term.isascii() and term.isalpha()


def _discovery_root(term: str) -> str:
    """Longest prefix a word shares with its stem (``y`` -> ``i`` stems give up their last letter)."""
    word = term.lower()
    stemmed = stem(word)
    length = 0
    while length < min(len(word), len(stemmed)) and word[length] == stemmed[length]:
        length += 1
    root = word[:length]
    if root == stemmed and root.endswith("i") and len(root) - 1 >= _STEM_MIN_ROOT:
        root = root[:-1]  # studi -> stud (matches study, studies, studying)
    return root


def _fts_discovery_term(term: str) -> str:
    if _stemmable(term):
        root = _discovery_root(term)
        if len(root) >= _STEM_MIN_ROOT:
            return f'"{root}"*'
    return _fts_term(term)


def _fts_discovery_terms(text: str) -> List[str]:
    """Distinct quoted FTS terms the corpus search discovers candidates with (never caller-controlled operators;
    each is passed as its own bound parameter), at most ``_MAX_DISCOVERY_TERMS``."""
    terms: List[str] = []
    for group in _query_groups(text):
        for term in group:
            expr = _fts_discovery_term(term)
            if expr not in terms:
                terms.append(expr)
    return terms[:_MAX_DISCOVERY_TERMS]


# ---------------------------------------------------------------------------
# Deterministic lexical scoring (computed over the AUTHORIZED subset only)
# ---------------------------------------------------------------------------
#
# DEF-061: BM25 with unit-length normalization, computed in Python over the
# authorized candidate set.  SQLite's FTS5 ``bm25()`` is NOT used on purpose: it
# derives IDF and average length from the WHOLE FTS table, so unauthorized rows
# would shift authorized scores and order, breaking the
# authorization-before-influence invariant (see module docstring).  Here the
# document frequency, N and average length come only from authorized candidates.
#
# T7 (measured in docs/benchmarks/RESULTS.md): short-text parameters (units are
# chat turns, paragraphs and notes, where long units are not noisier), a mild
# coordination factor and the neighbor propagation below.

_BM25_K1 = 0.6
_BM25_B = 0.3
# Added once per punctuated query token (e.g. ``blue-green``) whose words occur
# adjacently in a unit; on the scale of one rare-term contribution.
_PHRASE_BONUS = 1.0
# The BM25 sum is multiplied by (distinct query terms found / distinct query terms) ** exponent for queries with at
# least two terms, so a unit covering the whole question beats one that matches a single rare word.
_COORD_EXPONENT = 0.6


@lru_cache(maxsize=65536)
def _fold(word: str) -> str:
    """Case + diacritic folding for scoring (NFD, drop combining marks, đ -> d)."""
    if word.isascii():
        return word.lower()
    decomposed = unicodedata.normalize("NFD", word.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("\u0111", "d")


@lru_cache(maxsize=32768)
def _doc_terms(text: str) -> tuple:
    """``(folded tokens, Counter, Counter of stems, sorted distinct tokens)`` of one unit text.  Pure function of the
    text, so caching it across queries is safe (it never depends on which rows are authorized)."""
    tokens = tuple(_fold(word) for word in _split_words(text))
    counts = Counter(tokens)
    return tokens, counts, Counter(stem(token) for token in tokens), tuple(sorted(counts))


def _score_tokens(text: str) -> List[str]:
    return list(_doc_terms(text)[0])


@dataclass(frozen=True)
class _QueryTerm:
    key: str    # identity: the stem of a stemmable word, else the folded word
    word: str   # folded word (prefix semantics when ``stem`` is empty)
    stem: str   # Porter stem for stemmable words, "" otherwise


def _scoring_terms(text: str) -> tuple:
    """Unique query terms (in order) and the folded multi-word phrases."""
    terms: List[_QueryTerm] = []
    seen = set()
    phrases: List[tuple] = []
    for group in _query_groups(text):
        folded = tuple(_fold(word) for word in group)
        for raw, word in zip(group, folded):
            term = _QueryTerm(stem(word), word, stem(word)) if _stemmable(raw) else _QueryTerm(word, word, "")
            if term.key not in seen:
                seen.add(term.key)
                terms.append(term)
        if len(folded) > 1 and folded not in phrases:
            phrases.append(folded)
    return terms, phrases


def _token_matches(token: str, term: str) -> bool:
    # Mirrors the FTS query: prefix for multi-character terms, exact for one.
    return token.startswith(term) if len(term) > 1 else token == term


def _term_frequency(doc: tuple, term: _QueryTerm) -> int:
    _tokens, counts, stem_counts, distinct = doc
    if term.stem:
        return stem_counts.get(term.stem, 0)
    word = term.word
    if len(word) > 1:  # prefix match: the distinct tokens starting with ``word`` are one contiguous sorted run
        total = 0
        for index in range(bisect_left(distinct, word), len(distinct)):
            token = distinct[index]
            if not token.startswith(word):
                break
            total += counts[token]
        return total
    return counts.get(word, 0)


def _has_phrase(tokens: List[str], phrase: tuple) -> bool:
    width = len(phrase)
    first = phrase[0]
    prefix = len(first) > 1
    for start in range(len(tokens) - width + 1):
        token = tokens[start]
        if not (token.startswith(first) if prefix else token == first):
            continue  # one cheap comparison per position; the rest of the phrase only after the first word matched
        if all(_token_matches(tokens[start + i], phrase[i]) for i in range(1, width)):
            return True
    return False


def _bm25_scores(hits: List[CorpusHit], query_text: str) -> tuple:
    """``(scores, masks)`` per hit: the BM25 score, using statistics of ``hits`` (the authorized set) only, and the
    bit mask of the query terms the unit contains."""
    terms, phrases = _scoring_terms(query_text)
    if not terms or not hits:
        return [0.0] * len(hits), [0] * len(hits)
    docs = [_doc_terms(hit.normalized_text) for hit in hits]
    n_docs = len(hits)
    avg_len = (sum(len(doc[0]) for doc in docs) / n_docs) or 1.0
    freqs = [[_term_frequency(doc, term) for term in terms] for doc in docs]
    idf = []
    for index in range(len(terms)):
        df = sum(1 for row in freqs if row[index] > 0)
        idf.append(math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5)))
    scores: List[float] = []
    masks: List[int] = []
    for doc, row in zip(docs, freqs):
        tokens = doc[0]
        masks.append(sum(1 << index for index, tf in enumerate(row) if tf > 0))
        length_norm = _BM25_K1 * (1.0 - _BM25_B + _BM25_B * len(tokens) / avg_len)
        score = 0.0
        for index, tf in enumerate(row):
            if tf > 0:
                score += idf[index] * tf * (_BM25_K1 + 1.0) / (tf + length_norm)
        if len(terms) > 1 and _COORD_EXPONENT:
            score *= (sum(1 for tf in row if tf > 0) / len(terms)) ** _COORD_EXPONENT
        score += _PHRASE_BONUS * sum(1 for phrase in phrases if _has_phrase(tokens, phrase))
        scores.append(round(min(score, _MAX_LEXICAL_SCORE), 6))
    return scores, masks


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

@lru_cache(maxsize=1024)
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
# T7: the authorized scope and the closed metadata filter are part of the SELECT, so
# the candidate window, and the decision which units are scored at all, depend on
# authorized rows only; rows of other principals can neither fill the window nor
# decide which query form the caller gets.
#
# The window holds at most ``_CANDIDATE_LIMIT`` units, chosen by how many of the
# query's terms a unit contains (most first, then registration order): one OR query
# over a store of tens of thousands of units matches thousands of units for a
# question made of common words, and scoring them all costs tens of milliseconds
# per query, while truncating by registration order dropped the best unit.  The
# coverage count of a unit does not depend on any other unit, so it cannot carry
# information from outside the authorized scope.
_CANDIDATE_LIMIT = 500


def _fts_discovery_sql(n_terms: int, scope_sql: str, meta_sql: str) -> str:
    # Two stages (measured): the window (best ``?`` units by coverage, then registration order) is chosen from narrow
    # rows (unit id + rowid), and only the units that made the window are read with their text and source columns.
    # ``CROSS JOIN`` fixes the join order (grouped matches first, units by primary key); without it SQLite scanned
    # the duplicate_of index and built an automatic index over the grouped matches on every query.
    matches = " UNION ALL ".join("SELECT unit_id FROM zm_corpus_fts WHERE zm_corpus_fts MATCH ?" for _ in range(n_terms))
    return (
        f"SELECT {_UNIT_COLUMNS} "
        f"FROM (SELECT u.rowid AS rid, m.coverage AS coverage "
        f"FROM (SELECT unit_id AS covered_id, COUNT(*) AS coverage FROM ({matches}) GROUP BY unit_id) m "
        f"CROSS JOIN zm_corpus_units u ON u.unit_id = m.covered_id "
        f"{_SOURCE_JOIN} "
        f"WHERE u.duplicate_of IS NULL AND {scope_sql} AND {meta_sql} "
        "ORDER BY m.coverage DESC, u.rowid LIMIT ?) w "
        "JOIN zm_corpus_units u ON u.rowid = w.rid "
        f"{_SOURCE_JOIN} "
        "ORDER BY w.coverage DESC, w.rid"
    )


def _scope_predicate(scope: AuthorizedCorpusScope) -> tuple:
    """SQL form of :meth:`AuthorizedCorpusScope.allows` (exact: ``None`` means "any" per dimension; the
    all-``None`` sentinel means the unowned scope, i.e. every dimension NULL).  Returns ``(sql, params)``."""
    clauses: list = []
    params: list = []
    for ap, aj, ak in scope.allowed_scopes:
        if ap is None and aj is None and ak is None:
            clauses.append("(u.profile_id IS NULL AND u.project_id IS NULL AND u.knowledge_space_id IS NULL)")
            continue
        parts = []
        for column, value in (("profile_id", ap), ("project_id", aj), ("knowledge_space_id", ak)):
            if value is not None:
                parts.append(f"u.{column} = ?")
                params.append(value)
        clauses.append("(" + " AND ".join(parts) + ")")
    if not clauses:
        return "0", []
    return "(" + " OR ".join(clauses) + ")", params


def _metadata_predicate(meta: CorpusMetadataFilter) -> tuple:
    """SQL prefilter for the closed metadata filter.  Every clause is a SUPERSET of (or exactly) the Python
    predicate in ``_match_metadata``; the Python filter still runs afterwards as the final check."""
    clauses: list = []
    params: list = []
    for column, value in (
        ("profile_id", meta.profile_id), ("project_id", meta.project_id),
        ("knowledge_space_id", meta.knowledge_space_id), ("source_ref", meta.source_id),
        ("kind", meta.unit_kind), ("lifecycle_status", meta.lifecycle_status),
    ):
        if value is not None:
            clauses.append(f"u.{column} = ?")
            params.append(value)
    if meta.memory_type is not None:
        # the exact value must appear somewhere in the JSON text (a superset of "custom_meta.memory_type == value")
        clauses.append("instr(s.custom_meta, ?) > 0")
        params.append(meta.memory_type)
    if meta.external_ref_prefix is not None:
        clauses.append("substr(s.external_ref, 1, ?) = ?")
        params.extend([len(meta.external_ref_prefix), meta.external_ref_prefix])
    return (" AND ".join(clauses) or "1"), params


# T7: neighbor propagation.  Units of one source are ordered (a chat session, the paragraphs of a note); the unit
# that ANSWERS a matching unit often shares none of its words ("What do you love about camping?" / "A chance to be
# present and together").  A unit therefore also scores ``alpha`` times the best score of the units within
# ``_NEIGHBOR_RANGE`` positions of it in the same source, weighted by the fraction of that neighbor's matched query
# terms the unit itself does NOT contain (adjacency only counts as context when it completes the question: a run of
# table rows or list items that all contain the same words must not lift each other above an isolated exact match).
# The neighbors of the strongest hits that did not match at all enter the ranking with ``alpha`` times the hit's score
# (``alpha`` < 1: a neighbor never outranks the hit it comes from).  Neighbors are read with the same authorized-scope
# and metadata filter as every other candidate (a unit shares the scope of its source, so nothing outside the scope is
# reachable) and compete for the same result slots as every other unit.
_NEIGHBOR_ALPHA = 0.7
_NEIGHBOR_RANGE = 2
_NEIGHBOR_TOP = 10
_NEIGHBOR_OFFSETS = tuple(d for d in range(-_NEIGHBOR_RANGE, _NEIGHBOR_RANGE + 1) if d != 0)
_NEIGHBOR_BATCH = 100


def _neighbor_sql(n_positions: int) -> str:
    # ``+u.duplicate_of`` keeps SQLite from choosing the duplicate_of index (a scan of every unit, ~O(store)) over
    # the source index for the (source, order) lookups.
    clause = " OR ".join("(u.source_ref = ? AND u.unit_order = ?)" for _ in range(n_positions))
    return (f"SELECT {_UNIT_COLUMNS} FROM zm_corpus_units u {_SOURCE_JOIN} "
            f"WHERE +u.duplicate_of IS NULL AND ({clause})")


def _propagate_neighbors(cur, scope: AuthorizedCorpusScope, meta: CorpusMetadataFilter,
                         scored: List[tuple]) -> List[tuple]:
    """``scored`` and the result are ``(hit, lexical score, matched-term mask)`` triples (hits are copied only for
    the returned top)."""
    top = sorted((item for item in scored if item[1] > 0.0),
                 key=lambda item: (-item[1], item[0].source_id, item[0].unit_order))[:_NEIGHBOR_TOP]
    if not top:
        return scored
    known = {(h.source_id, h.unit_order) for h, _score, _mask in scored}
    wanted = sorted({(h.source_id, h.unit_order + d) for h, _score, _mask in top for d in _NEIGHBOR_OFFSETS
                     if h.unit_order + d >= 0} - known)
    fetched: List[CorpusHit] = []
    for start in range(0, len(wanted), _NEIGHBOR_BATCH):
        chunk = wanted[start:start + _NEIGHBOR_BATCH]
        rows = cur.execute(
            _neighbor_sql(len(chunk)), [value for key in chunk for value in key],
        ).fetchall()
        fetched.extend(_authorize_and_filter(rows, scope, meta))
    pool = list(scored) + [(h, 0.0, 0) for h in fetched]
    by_position = {(h.source_id, h.unit_order): (score, mask) for h, score, mask in pool}
    boosted: List[tuple] = []
    for hit, score, mask in pool:
        best = 0.0
        for d in _NEIGHBOR_OFFSETS:
            near = by_position.get((hit.source_id, hit.unit_order + d))
            if near is None or near[0] <= 0.0 or not near[1]:
                continue
            new_terms = (near[1] & ~mask).bit_count() / near[1].bit_count()
            best = max(best, near[0] * new_terms)
        boosted.append((hit, round(score + _NEIGHBOR_ALPHA * best, 6) if best > 0.0 else score, mask))
    return boosted


def _read_all_units(cur, cap: int, scope: Optional[AuthorizedCorpusScope] = None,
                    meta: Optional[CorpusMetadataFilter] = None) -> list:
    """Read derived units (bounded candidate discovery) for the explicit
    non-FTS capability path.

    Bounded by ``cap`` (DEF-030) so a metadata-only query never materializes the
    whole table. The authorized scope and the closed metadata filter are applied
    in SQL BEFORE the cap (T5: otherwise other profiles' rows, or rows of other
    source types, that were registered earlier crowd the caller's rows out of the
    window); both predicates are exact, and callers still pass the rows through
    ``_authorize_and_filter`` before lexical scoring or limiting.
    """
    where = ["u.duplicate_of IS NULL"]
    params: list = []
    if scope is not None:
        sql, extra = _scope_predicate(scope)
        where.append(sql)
        params.extend(extra)
    if meta is not None:
        sql, extra = _metadata_predicate(meta)
        where.append(sql)
        params.extend(extra)
    params.append(cap)
    return cur.execute(
        f"SELECT {_UNIT_COLUMNS} FROM zm_corpus_units u {_SOURCE_JOIN} "
        f"WHERE {' AND '.join(where)} ORDER BY u.rowid LIMIT ?",
        params,
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
      1. Discover lexical candidates via one FTS OR MATCH (discovery only;
         within-source duplicate units are excluded in SQL; the authorized scope
         and the closed metadata filter are part of the SELECT, so the discovery
         cap only ever counts authorized rows).
      2. Scope-filter to the AUTHORIZED set (drop unauthorized before ranking).
      3. Apply closed metadata filter (incl. source memory_type / external_ref
         prefix, ADR-V170-01) - strictly after the scope check.
      4. Compute deterministic BM25 (stemmed terms, coordination factor) over the
         authorized subset (DEF-061), then propagate score to the ordered
         neighbors of the best units (same source, authorized rows only; T7).
      5. Optionally fuse a local semantic adapter (authorized set only).
      6. Return ranked ``CorpusHit[]`` (bounded by ``plan.limit``).

    Never mutates the database. Raises no exception that leaks content; query
    errors are sanitized to a typed ``CorpusQueryError``.
    """
    semantic = semantic or NO_SEMANTIC_ADAPTER
    cur = conn.cursor()
    # True when the query has lexical terms: units that score 0 are not matches (the no-FTS fallback returns every
    # unit, and a shared stem root can discover units the stem comparison then rejects) and are dropped after scoring.
    lexical_query = False

    # Step 1: lexical discovery. If no lexical text, every unit is a candidate
    # (metadata-only retrieval). Without FTS5, the derived unit relation is the
    # explicit O(N) candidate source; authorization/filtering still precedes
    # every lexical influence.
    # DEF-030 (DEF-C1): all discovery paths are bounded by a safety-factor cap;
    # ranking runs only over the authorized subset of the capped candidate set.
    cap = _discovery_cap(plan.limit)
    if plan.is_metadata_only:
        try:
            rows = _read_all_units(cur, cap, scope, plan.metadata)
        except Exception as exc:  # pragma: no cover - defensive
            raise CorpusQueryError(f"corpus_query_failed: {type(exc).__name__}") from None
    else:
        fts_expr = _fts_safe_query(plan.text)
        if not fts_expr:
            # T11: a NON-empty lexical query that yields no terms ("_", "---") matches nothing; only an
            # explicitly empty query is metadata-only.
            return []
        elif not _migrate_10.FTS5_AVAILABLE:
            lexical_query = True
            try:
                rows = _read_all_units(cur, cap, scope, plan.metadata)
            except Exception as exc:  # pragma: no cover - defensive
                raise CorpusQueryError(f"corpus_query_failed: {type(exc).__name__}") from None
        else:
            # FTS discovery: match unit_ids, then join units (bounded by cap).
            lexical_query = True
            # T7: ONE OR query over the (stem-rooted) terms replaces the AND-first pass with OR fallback.  Candidates
            # are every authorized unit sharing a term; BM25 + the coordination factor rank full matches first.
            # Measured (docs/benchmarks/RESULTS.md): AND-first returned only the few units containing EVERY word of
            # a natural-language question and hid the answer unit.
            try:
                scope_sql, scope_params = _scope_predicate(scope)
                meta_sql, meta_params = _metadata_predicate(plan.metadata)
                terms = _fts_discovery_terms(plan.text)
                rows = cur.execute(
                    _fts_discovery_sql(len(terms), scope_sql, meta_sql),
                    [*terms, *scope_params, *meta_params, min(cap, _CANDIDATE_LIMIT)]).fetchall()
            except Exception as exc:
                # Malformed FTS expression or missing FTS table => fail closed to
                # a typed error (never silently return everything).
                raise CorpusQueryError(f"corpus_fts_error: {type(exc).__name__}") from None

    # Steps 2-3: authorization + metadata filter BEFORE ranking.
    hits = _authorize_and_filter(rows, scope, plan.metadata)
    if not hits:
        return []

    # Step 4: deterministic BM25 over the AUTHORIZED subset only (DEF-061).  Hits are carried as (hit, score, matched
    # terms) triples and copied only once, for the units that are returned (copying a 22-field frozen dataclass per
    # candidate was half of the query time).
    scores, masks = _bm25_scores(hits, plan.text)
    scored = list(zip(hits, scores, masks))
    if lexical_query:
        scored = [item for item in scored if item[1] > 0.0]
        if not scored:
            return []
    if not plan.is_metadata_only:
        # Neighbor propagation (T7), over the authorized scope only.
        scored = _propagate_neighbors(cur, scope, plan.metadata, scored)

    if not semantic.available:
        # Steps 5-6 without a semantic adapter: deterministic ordering, then the bounded result.
        scored.sort(key=_scored_rank_key)
        return [_lexical_final(h, score) for h, score, _mask in scored[: plan.limit]]

    hits = [_scored(h, score) for h, score, _mask in scored]

    # Step 5: optional semantic fusion over the authorized set ONLY.
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


def _lexical_final(h: CorpusHit, score: float) -> CorpusHit:
    return replace(h, lexical_score=score, combined_score=score, retrieval_mode="lexical")


def _scored_rank_key(item: tuple) -> tuple:
    """``_rank_key`` of a (hit, lexical score, mask) triple when the combined score equals the lexical one."""
    hit, score, _mask = item
    return (
        -round(score, 6),
        hit.profile_id or "",
        hit.project_id or "",
        hit.source_id or "",
        hit.unit_id or "",
        hit.unit_order,
    )


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
