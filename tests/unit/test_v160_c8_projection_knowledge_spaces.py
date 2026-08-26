"""V1.6.0 C8 RED-first tests for Multi-KS projection frontmatter."""
from __future__ import annotations

from src.access import AccessRequest
from src.access.authorized_read import AuthorizedReadService
from src.access.grants import AuthorizedReadGrant
from src.project_memory import reader as m4
from src.projection.render import render_decision, render_project_state
from src.retrieval.db import ReadonlyStore
from tests.unit.test_m8_2_rebuild import _event, db


class _Record:
    def __init__(self, **values):
        for name, value in values.items():
            setattr(self, name, value)


def _decision(**extra):
    values = dict(
        decision_id="D-KS",
        project_id="P",
        profile_id="PR1",
        scope="project:P",
        statement="Multi-KS projection",
        lifecycle_status="active",
        state="accepted",
        effective_at="2026-08-27T00:00:00Z",
        rationale_ref=None,
        alternatives=None,
        supersedes_id=None,
        replaced_by=None,
        linked_requirement_ids=None,
        linked_artifact_ids=None,
        linked_verification_ids=None,
        source_event_id="E-KS",
        trace_id="T-KS",
        session_id="S1",
    )
    values.update(extra)
    return _Record(**values)


def test_decision_note_renders_full_event_knowledge_space_list():
    note = render_decision(_decision(knowledge_space_ids=("A", "B")))
    assert 'knowledge_spaces: ["A", "B"]' in note.content


def test_projection_normalizes_duplicate_or_blank_space_values():
    note = render_decision(
        _decision(knowledge_space_ids=("B", "", "A", "B", None))
    )
    assert 'knowledge_spaces: ["B", "A"]' in note.content


def test_aggregate_state_note_unions_source_event_spaces_deterministically():
    rows = (
        _Record(
            state_key="one", state_value="1", lifecycle_status="active",
            verification_status="none", effective_at=None,
            source_event_id="E1", trace_id="T1", knowledge_space_ids=("A", "B"),
        ),
        _Record(
            state_key="two", state_value="2", lifecycle_status="active",
            verification_status="none", effective_at=None,
            source_event_id="E2", trace_id="T2", knowledge_space_ids=("B", "C"),
        ),
    )
    note = render_project_state(project_id="P", state_rows=rows)
    assert 'knowledge_spaces: ["A", "B", "C"]' in note.content


def test_authorized_m4_record_is_enriched_from_source_event_junction(db):
    _event(db._conn, "E-KS", profile_id="PR1", project_id="P")
    db._conn.execute(
        "UPDATE zm_meta SET knowledge_space_id=? WHERE event_id=?", ("A", "E-KS")
    )
    db._conn.executemany(
        "INSERT INTO zm_event_spaces (event_id, knowledge_space_id) VALUES (?,?)",
        (("E-KS", "A"), ("E-KS", "B")),
    )
    db._conn.execute(
        "INSERT INTO zm_decisions "
        "(decision_id, project_id, statement, source_event_id, lifecycle_status, "
        "profile_id, trace_id) VALUES (?,?,?,?,?,?,?)",
        ("D-KS", "P", "Multi-KS projection", "E-KS", "active", "PR1", "T-KS"),
    )
    db._conn.commit()
    readonly = ReadonlyStore(db._conn, db.path)
    assert [item.decision_id for item in m4.list_decisions(readonly, "P").items] == ["D-KS"]

    service = AuthorizedReadService(readonly, "PR1")
    result = service.m4_decisions(
        AccessRequest(
            operation="READ", requesting_profile_id="PR1", project_ids=["P"]
        ),
        "P",
        grants=[AuthorizedReadGrant(
            grant_id="G-P",
            subject_profile="PR1",
            operation="READ",
            target_type="project",
            target_id="P",
        )],
    )
    assert result.allowed is True
    assert result.items[0].knowledge_space_ids == ("A", "B")
    assert 'knowledge_spaces: ["A", "B"]' in render_decision(result.items[0]).content
