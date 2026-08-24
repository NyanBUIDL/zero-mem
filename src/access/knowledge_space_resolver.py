"""V140-02 Option B — knowledge-space resolution layer (DEF-004).

Resolution layer (NO schema change to zm_meta). Maps a set of
``knowledge_space_id`` values to the concrete ``(profile_id, project_id)``
pairs that own resources in that space, drawn from the derived corpus
projection (``zm_corpus_sources`` / ``zm_corpus_units`` both carry
``knowledge_space_id``). This lets the event-store authorization path
(``_scope_allows``) validate a space grant against row data without adding a
``knowledge_space_id`` column to ``zm_meta``.

The resolver is pure, deterministic, and rebuildable: it reads only derived
state, so it can be recomputed from canonical corpus data at any time.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

# (profile_id, project_id) — both may be NULL for unowned/default corpus rows.
SpaceMember = Tuple[Optional[str], Optional[str]]


def resolve_space_members(
    corpus_conn,
    space_ids: Iterable[str],
) -> List[SpaceMember]:
    """Return DISTINCT (profile_id, project_id) owning resources in ``space_ids``.

    Sources and units both carry ``knowledge_space_id``; a space is "owned" by
    every (profile, project) pair that has at least one corpus resource in it.
    NULL profile/project are preserved as ``None`` so unowned corpus rows map to
    the ``(None, None)`` sentinel the authorization layer already understands.

    Args:
        corpus_conn: a sqlite3 connection (or any DBAPI cursor source exposing
            ``execute``) to the corpus derived DB.
        space_ids: knowledge-space identifiers to resolve.

    Returns:
        Sorted list of distinct (profile_id, project_id) tuples. Empty when no
        corpus resource references any of ``space_ids`` (fail-closed callers
        must then deny space-scoped reads).
    """
    space_ids = list(space_ids)
    if not space_ids:
        return []

    placeholders = ", ".join("?" for _ in space_ids)
    sql = (
        f"SELECT DISTINCT profile_id, project_id FROM zm_corpus_sources "
        f"WHERE knowledge_space_id IN ({placeholders}) "
        f"UNION "
        f"SELECT DISTINCT profile_id, project_id FROM zm_corpus_units "
        f"WHERE knowledge_space_id IN ({placeholders})"
    )
    params = list(space_ids) + list(space_ids)
    rows = corpus_conn.execute(sql, params).fetchall()
    members: List[SpaceMember] = [(r[0], r[1]) for r in rows]
    # Sort for determinism (None sorts first in Python tuple comparison).
    members.sort(key=lambda t: (t[0] is None, t[0] or "", t[1] is None, t[1] or ""))
    return members


__all__ = ["SpaceMember", "resolve_space_members"]
