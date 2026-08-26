"""V1.6.0 C10 end-to-end Multi-KS acceptance gate."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.access import AccessRequest, grant_events, resolver
from src.access.authorized_read import AuthorizedReadService
from src.integration.capture_adapter import _envelope
from src.integration.payload_mapping import MappingResult
from src.retrieval import list_knowledge_space, open_readonly
from src.storage.ingest import ingest_file
from src.storage.jsonl_capture import CaptureStoreConfig, JsonlCaptureStore
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig


def _mapped() -> MappingResult:
    return MappingResult(
        status="mapped",
        hook="public_user_message",
        event_class="message_observation",
        event_type="user_statement",
        source="hermes",
        payload=None,
        diagnostic_code=None,
    )


def _capture_envelope(event_id: str, text: str, **scope) -> dict:
    return _envelope(
        _mapped(),
        {
            "event_id": event_id,
            "trace_id": f"trace:{event_id}",
            "text": text,
            "profile_id": "owner",
            "project_id": "project-c10",
            "redaction_audit": [{"rule": "c10", "fields": []}],
            **scope,
        },
    )


def _add_grant(conn: sqlite3.Connection, grant_id: str, space: str) -> None:
    grant_events.project_grant_event(
        conn,
        grant_events.AccessGrantEvent(
            grant_id=grant_id,
            subject_profile="reader",
            operation="READ",
            target_type="knowledge_space",
            target_id=space,
            op="create",
        ),
    )


def test_capture_to_granted_reads_and_legacy_compatibility(tmp_path: Path) -> None:
    """One [A,B] event is visible through A and B, never C; legacy still reads."""
    canonical_root = tmp_path / "canonical"
    capture = JsonlCaptureStore(CaptureStoreConfig(canonical_root))

    multi = _capture_envelope(
        "multi-ab", "c10 acceptance needle", knowledge_space_ids=["A", "B"]
    )
    capture.append(multi)

    # Simulate an envelope written by a pre-v1.6 producer. The legacy singular
    # field remains accepted and migration/ingest maps it into the junction.
    legacy = _capture_envelope("legacy", "c10 legacy needle")
    legacy["knowledge_space_id"] = "legacy-space"
    capture.append(legacy)

    canonical_path = canonical_root / "events-v1.jsonl"
    lines = [json.loads(line) for line in canonical_path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["knowledge_space_ids"] == ["A", "B"]
    assert lines[1]["knowledge_space_id"] == "legacy-space"

    db_path = tmp_path / "derived.sqlite"
    writable = SQLiteStore(SQLiteStoreConfig(path=db_path))
    writable.ensure_schema()
    ingest_file(writable, canonical_path)
    for grant_id, space in (("GA", "A"), ("GB", "B"), ("GL", "legacy-space")):
        _add_grant(writable._conn, grant_id, space)
    writable._conn.commit()
    writable.close()

    raw = sqlite3.connect(db_path)
    try:
        assert raw.execute(
            "SELECT COUNT(*) FROM zm_meta WHERE event_id='multi-ab'"
        ).fetchone()[0] == 1
        assert raw.execute(
            "SELECT knowledge_space_id FROM zm_meta WHERE event_id='multi-ab'"
        ).fetchone()[0] == "A"
        assert raw.execute(
            "SELECT knowledge_space_id FROM zm_event_spaces "
            "WHERE event_id='multi-ab' ORDER BY knowledge_space_id"
        ).fetchall() == [("A",), ("B",)]
        assert raw.execute(
            "SELECT knowledge_space_id FROM zm_event_spaces WHERE event_id='legacy'"
        ).fetchall() == [("legacy-space",)]
    finally:
        raw.close()

    readonly = open_readonly(db_path)
    service = AuthorizedReadService(readonly, "reader", grant_conn=readonly.conn)
    try:
        for space in ("A", "B"):
            grants = resolver.resolve_read_grants(
                readonly.conn,
                "reader",
                target_type="knowledge_space",
                target_id=space,
            )
            request = AccessRequest(
                operation="READ",
                requesting_profile_id="reader",
                knowledge_space_ids=[space],
            )
            structured = service.query_events(request, grants=grants)
            fts = service.search_text(request, "acceptance needle", grants=grants)
            assert [item.event_id for item in structured.items] == ["multi-ab"]
            assert [item.event_id for item in fts.items] == ["multi-ab"]

        denied = AccessRequest(
            operation="READ",
            requesting_profile_id="reader",
            knowledge_space_ids=["C"],
        )
        assert service.query_events(denied, grants=[]).items == []
        assert service.search_text(denied, "acceptance needle", grants=[]).items == []

        legacy_request = AccessRequest(
            operation="READ",
            requesting_profile_id="reader",
            knowledge_space_ids=["legacy-space"],
        )
        legacy_grants = resolver.resolve_read_grants(
            readonly.conn,
            "reader",
            target_type="knowledge_space",
            target_id="legacy-space",
        )
        assert [
            item.event_id
            for item in service.query_events(legacy_request, grants=legacy_grants).items
        ] == ["legacy"]
        assert [
            item.event_id for item in list_knowledge_space(readonly, "B").items
        ] == ["multi-ab"]
    finally:
        service.close()
