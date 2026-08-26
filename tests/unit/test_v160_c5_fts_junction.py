"""V1.6.0 C5 RED-first — FTS authorization parity through the Multi-KS junction.

ADR-V160-01 section 8 requires structured and FTS reads to use the same
correlated-EXISTS junction boundary.  SQL candidate filtering already receives
the C4 predicate; these tests also require the defensive post-validation step
to use the complete row Knowledge-Space set rather than PRIMARY-KS alone.
"""
from __future__ import annotations

from pathlib import Path

from src.access import AccessRequest
from src.access.authorized_read import AuthorizedReadService
from src.access import resolver
from src.retrieval.db import open_readonly
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from tests.unit.test_m3_query import _checkpoint_and_close, _make_env
from tests.unit.test_v160_c4_auth_junction import _build


def _service(db_path: str, requester: str = "PR1"):
    store = open_readonly(Path(db_path))
    grants = resolver.resolve_read_grants(store.conn, requester)
    return store, AuthorizedReadService(store, requester, grant_conn=store.conn), grants


def _fts_items():
    return [
        _make_env(
            "multi-ab",
            profile_id="PR2",
            project_id="P",
            knowledge_space_ids=["A", "B"],
            sanitized_content={"text": "multi junction needle"},
        ),
        _make_env(
            "only-b",
            profile_id="PR2",
            project_id="P",
            knowledge_space_ids=["B"],
            sanitized_content={"text": "multi junction needle"},
        ),
        _make_env(
            "only-c",
            profile_id="PR2",
            project_id="P",
            knowledge_space_ids=["C"],
            sanitized_content={"text": "multi junction needle"},
        ),
        _make_env(
            "unscoped",
            profile_id="PR2",
            project_id="P",
            sanitized_content={"text": "multi junction needle"},
        ),
    ]


def test_fts_non_primary_space_grant_uses_full_junction_set(tmp_path):
    """An event [A,B] (PRIMARY A) is readable through a grant for B."""
    db = _build(tmp_path, _fts_items(), name="c5-non-primary.sqlite",
                grants=[("GB", "PR1", "B")])
    store, service, grants = _service(db)
    try:
        result = service.search_text(
            AccessRequest(
                operation="READ",
                requesting_profile_id="PR1",
                knowledge_space_ids=["B"],
            ),
            "needle",
            grants=grants,
        )
        assert result.allowed is True
        assert {item.event_id for item in result.items} == {"multi-ab", "only-b"}
    finally:
        store.close()


def test_fts_missing_junction_row_fails_closed(tmp_path):
    """PRIMARY-KS must never substitute for a missing junction authorization row."""
    db = _build(
        tmp_path,
        [_make_env(
            "primary-b",
            profile_id="PR2",
            project_id="P",
            knowledge_space_ids=["B"],
            sanitized_content={"text": "fail closed needle"},
        )],
        name="c5-fail-closed.sqlite",
        grants=[("GB", "PR1", "B")],
    )
    writable = SQLiteStore(SQLiteStoreConfig(path=Path(db)))
    writable.ensure_schema()
    writable._conn.execute(
        "DELETE FROM zm_event_spaces WHERE event_id=?", ("primary-b",)
    )
    writable._conn.commit()
    _checkpoint_and_close(writable)

    store, service, grants = _service(db)
    try:
        result = service.search_text(
            AccessRequest(
                operation="READ",
                requesting_profile_id="PR1",
                knowledge_space_ids=["B"],
            ),
            "needle",
            grants=grants,
        )
        assert result.allowed is True
        assert result.items == []
    finally:
        store.close()


def test_fts_union_has_no_duplicates_and_paginates(tmp_path):
    items = [
        _make_env(
            f"event-{index:02d}",
            profile_id="PR2",
            project_id="P",
            knowledge_space_ids=["A", "B"],
            sanitized_content={"text": "page junction needle"},
        )
        for index in range(7)
    ]
    db = _build(
        tmp_path,
        items,
        name="c5-pagination.sqlite",
        grants=[("GA", "PR1", "A"), ("GB", "PR1", "B")],
    )
    store, service, grants = _service(db)
    try:
        seen: list[str] = []
        cursor = None
        for _ in range(5):
            result = service.search_text(
                AccessRequest(
                    operation="READ",
                    requesting_profile_id="PR1",
                    knowledge_space_ids=["B", "A"],
                ),
                "needle",
                limit=2,
                cursor=cursor,
                grants=grants,
            )
            seen.extend(item.event_id for item in result.items)
            cursor = result.next_cursor
            if cursor is None:
                break
        assert seen == [f"event-{index:02d}" for index in range(7)]
        assert len(seen) == len(set(seen))
    finally:
        store.close()
