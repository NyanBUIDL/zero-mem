"""T5 - provisioning + operator-approval model (ADR-V170-02).

``agents add`` registers a profile and grants READ on ks-shared; a WRITE grant exists only after the explicit
operator action ``grant-write``, which first writes a canonical ``operator_approval`` event that serves as the
grant's ``verification_ref``.  Everything is replayable from the canonical stream.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.access import AccessRequest, AuthorizedReadService
from src.access.authorized_write import authorize_write
from src.access.rebuild import iter_canonical_policy_events, rebuild_policy_state
from src.retrieval.db import open_readonly
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from zero_mem import upgrade as upgrade_mod
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import (
    OperatorApprovalLookup,
    Provisioner,
    ProvisioningError,
    append_canonical_event,
)

SHARED = "ks-shared"


@pytest.fixture
def lay(tmp_path):
    layout = Layout.resolve(tmp_path / "zm")
    layout.ensure()
    return layout


@pytest.fixture
def prov(lay):
    return Provisioner(lay)


def events(lay, event_type=None):
    out = []
    for line in lay.memory_stream.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            if event_type is None or rec.get("event_type") == event_type:
                out.append(rec)
    return out


class Db:
    """Writer connection + request helpers against the derived store of a layout."""

    def __init__(self, lay):
        self.lay = lay
        self.store = SQLiteStore(SQLiteStoreConfig(path=lay.derived_db))
        self.conn = self.store._conn
        self.lookup = OperatorApprovalLookup(lay.memory_stream)

    def write(self, profile, **scope):
        req = AccessRequest(operation="WRITE", requesting_profile_id=profile, resource_type="corpus_source", **scope)
        return authorize_write(req, self.conn, self.lookup)

    def grants(self, profile):
        rows = self.conn.execute(
            "SELECT operation, target_type, target_id, state, verification_ref FROM zm_access_grants "
            "WHERE subject_profile=? ORDER BY grant_id", (profile,)).fetchall()
        return [tuple(r) for r in rows]

    def close(self):
        self.store.close()


@pytest.fixture
def db(lay):
    d = Db(lay)
    yield d
    d.close()


# ---------------------------------------------------------------- agents add
def test_add_agent_records_the_profile_and_grants_read_on_the_shared_space(prov, lay, db):
    res = prov.add_agent("claude-code")
    assert res["status"] == "added" and res["profile"] == "claude-code"
    assert db.grants("claude-code") == [("READ", "knowledge_space", SHARED, None, None)]
    rec = events(lay, "agent_profile")
    assert len(rec) == 1 and rec[0]["m4"]["profile_id"] == "claude-code" and rec[0]["m4"]["op"] == "add"
    assert len(events(lay, "access_grant")) == 1


def test_add_agent_is_idempotent(prov, lay, db):
    prov.add_agent("claude-code")
    again = prov.add_agent("claude-code")
    assert again["status"] == "exists"
    assert len(events(lay, "agent_profile")) == 1 and len(events(lay, "access_grant")) == 1
    assert len(db.grants("claude-code")) == 1


@pytest.mark.parametrize("bad", ["", " ", "a b", "../x", "a/b", "-x", "x" * 65, "ü", "a\nb", None, 7])
def test_add_agent_rejects_invalid_profile_ids(prov, lay, bad):
    with pytest.raises(ProvisioningError) as exc:
        prov.add_agent(bad)
    assert exc.value.code == "invalid_profile"
    assert events(lay) == []


def test_new_agent_default_is_private_write_only(prov, db):
    prov.add_agent("codex")
    private = db.write("codex", target_profile_ids=["codex"])
    shared = db.write("codex", knowledge_space_ids=[SHARED])
    assert private.allow and private.reason_code == "ALLOW_LOCAL_WRITE"
    assert not shared.allow and shared.reason_code == "DENY_CROSS_PROFILE_WRITE"


def test_read_grant_makes_the_shared_space_readable_through_the_authorized_facade(prov, lay):
    prov.add_agent("codex")
    ro = open_readonly(lay.derived_db)
    try:
        svc = AuthorizedReadService(ro, "codex", grant_conn=ro.conn)
        res = svc.corpus_unit_search(
            AccessRequest(operation="READ", requesting_profile_id="codex", knowledge_space_ids=[SHARED],
                          resource_type="corpus_unit"), "anything")
        assert res.allowed and res.reason_code == "ALLOW_EXPLICIT_CROSS_PROFILE_READ"
    finally:
        ro.close()


# ---------------------------------------------------------------- grant-write
def test_grant_write_requires_a_registered_agent(prov, lay):
    with pytest.raises(ProvisioningError) as exc:
        prov.grant_write("ghost", space=SHARED)
    assert exc.value.code == "unknown_agent"
    assert events(lay) == []


def test_grant_write_requires_exactly_one_target(prov):
    prov.add_agent("codex")
    for kwargs in ({}, {"space": SHARED, "project": "p"}):
        with pytest.raises(ProvisioningError) as exc:
            prov.grant_write("codex", **kwargs)
        assert exc.value.code == "invalid_target"


def test_grant_write_writes_the_approval_event_first_then_the_grant(prov, lay, db):
    prov.add_agent("codex")
    res = prov.grant_write("codex", space=SHARED, basis="owner chat 2026-10-01")
    assert res["status"] == "granted" and res["approval_ref"].startswith("opapp-")
    stream = events(lay)
    types = [e["event_type"] for e in stream]
    assert types == ["agent_profile", "access_grant", "operator_approval", "access_grant"]
    approval = stream[2]["m4"]
    assert approval["domain"] == "operator_approval" and approval["op"] == "approve"
    assert (approval["subject_profile"], approval["operation"], approval["target_type"], approval["target_id"]) == (
        "codex", "WRITE", "knowledge_space", SHARED)
    assert approval["basis"] == "owner chat 2026-10-01" and approval["approval_ref"] == res["approval_ref"]
    grant = stream[3]["m4"]
    assert grant["operation"] == "WRITE" and grant["verification_ref"] == res["approval_ref"]
    assert grant["resource_types"] == ["corpus_source"]


def test_grant_write_makes_shared_writes_authorized_and_audit_grade(prov, db):
    prov.add_agent("codex")
    prov.grant_write("codex", space=SHARED)
    d = db.write("codex", knowledge_space_ids=[SHARED])
    assert d.allow and d.reason_code == "ALLOW_EXPLICIT_CROSS_PROFILE_WRITE" and d.grant_refs
    assert not db.write("codex", knowledge_space_ids=["ks-other"]).allow
    assert not db.write("codex", target_profile_ids=["someone-else"]).allow
    assert not db.write("claude-code", knowledge_space_ids=[SHARED]).allow  # another agent: no grant


def test_grant_write_for_a_project_target_authorizes_project_writes_only(prov, db):
    prov.add_agent("codex")
    prov.grant_write("codex", project="zero-mem")
    assert db.write("codex", project_ids=["zero-mem"]).allow
    assert not db.write("codex", project_ids=["other"]).allow
    assert not db.write("codex", knowledge_space_ids=[SHARED]).allow


def test_grant_write_is_idempotent(prov, lay):
    prov.add_agent("codex")
    first = prov.grant_write("codex", space=SHARED)
    second = prov.grant_write("codex", space=SHARED)
    assert second["status"] == "exists" and second["approval_ref"] == first["approval_ref"]
    assert len(events(lay, "operator_approval")) == 1


def test_a_forged_write_grant_without_an_operator_approval_is_not_honoured(prov, lay, db):
    """A WRITE grant event whose verification_ref names no operator approval must not authorize anything."""
    prov.add_agent("codex")
    append_canonical_event(lay.memory_stream, {
        "event_id": "forged-1", "event_type": "access_grant", "created_at": "2026-10-01T00:00:00Z",
        "m4": {"domain": "access_grant", "identity": "g-forged", "op": "create", "grant_id": "g-forged",
               "subject_profile": "codex", "operation": "WRITE", "target_type": "knowledge_space",
               "target_id": SHARED, "resource_types": ["corpus_source"], "lifecycle_status": "active",
               "verification_ref": "opapp-doesnotexist"}})
    rebuild_policy_state(db.conn, lay.memory_stream)
    db.conn.commit()
    d = db.write("codex", knowledge_space_ids=[SHARED])
    assert not d.allow and d.reason_code == "DENY_CROSS_PROFILE_WRITE"


def test_unrelated_verification_refs_are_not_verified(lay):
    lookup = OperatorApprovalLookup(lay.memory_stream)
    for ref in ("", "x", "opapp-nope", "ver-1", None):
        assert lookup(ref) is None


def test_the_lookup_plugs_into_authorized_write_service_and_authorize_then_write(prov, lay, db):
    from src.access.authorized_write import AuthorizedWriteService

    prov.add_agent("codex")
    service = AuthorizedWriteService(db.conn, db.lookup)
    request = AccessRequest(operation="WRITE", requesting_profile_id="codex", knowledge_space_ids=[SHARED],
                            resource_type="corpus_source")
    written = []
    decision, result = service.authorize_then_write(request, lambda req: written.append(req) or "wrote")
    assert not decision.allow and result is None and written == []  # denied: the writer never ran
    prov.grant_write("codex", space=SHARED)
    decision, result = service.authorize_then_write(request, lambda req: written.append(req) or "wrote")
    assert decision.allow and result == "wrote" and len(written) == 1


# ---------------------------------------------------------------- grant-read
def test_grant_read_for_a_project(prov, db):
    prov.add_agent("codex")
    res = prov.grant_read("codex", project="zero-mem")
    assert res["status"] == "granted"
    assert ("READ", "project", "zero-mem", None, None) in db.grants("codex")
    assert prov.grant_read("codex", project="zero-mem")["status"] == "exists"


# ---------------------------------------------------------------- revoke
def test_revoke_write_removes_shared_write_but_keeps_read(prov, lay, db):
    prov.add_agent("codex")
    granted = prov.grant_write("codex", space=SHARED)
    res = prov.revoke("codex", space=SHARED, operation="WRITE")
    assert res["status"] == "revoked" and len(res["revoked"]) == 1
    assert not db.write("codex", knowledge_space_ids=[SHARED]).allow
    states = {(g[0], g[3]) for g in db.grants("codex")}
    assert ("WRITE", "revoked") in states and ("READ", None) in states
    rev = [e for e in events(lay, "operator_approval") if e["m4"]["op"] == "revoke"]
    assert len(rev) == 1 and rev[0]["m4"]["approval_ref"] == granted["approval_ref"]
    assert OperatorApprovalLookup(lay.memory_stream)(granted["approval_ref"]).verification_status == "revoked"


def test_revoke_everything_for_an_agent(prov, db):
    prov.add_agent("codex")
    prov.grant_write("codex", space=SHARED)
    res = prov.revoke("codex")
    assert res["status"] == "revoked" and len(res["revoked"]) == 2
    assert all(g[3] == "revoked" for g in db.grants("codex"))


def test_revoke_nothing_to_revoke(prov):
    prov.add_agent("codex")
    assert prov.revoke("codex", space=SHARED, operation="WRITE")["status"] == "not_found"


def test_regrant_after_revoke_works_with_a_fresh_approval(prov, lay, db):
    prov.add_agent("codex")
    first = prov.grant_write("codex", space=SHARED)
    prov.revoke("codex", space=SHARED, operation="WRITE")
    second = prov.grant_write("codex", space=SHARED)
    assert second["status"] == "granted" and second["approval_ref"] != first["approval_ref"]
    assert db.write("codex", knowledge_space_ids=[SHARED]).allow


def test_a_revoked_approval_alone_defeats_an_unrevoked_grant_row(prov, lay, db):
    """Defense in depth: the WRITE verification predicate fails once the approval is revoked."""
    prov.add_agent("codex")
    granted = prov.grant_write("codex", space=SHARED)
    append_canonical_event(lay.memory_stream, {
        "event_id": "rv-1", "event_type": "operator_approval", "created_at": "2026-10-01T00:00:00Z",
        "m4": {"domain": "operator_approval", "op": "revoke", "approval_ref": granted["approval_ref"]}})
    assert not db.write("codex", knowledge_space_ids=[SHARED]).allow


# ---------------------------------------------------------------- list
def test_list_agents(prov):
    assert prov.list_agents() == []
    prov.add_agent("claude-code")
    prov.add_agent("codex")
    prov.grant_write("codex", space=SHARED)
    prov.revoke("claude-code", space=SHARED, operation="READ")
    rows = {r["profile"]: r for r in prov.list_agents()}
    assert sorted(rows) == ["claude-code", "codex"]
    assert rows["codex"]["can_write_shared"] is True and rows["codex"]["can_read_shared"] is True
    assert rows["claude-code"]["can_write_shared"] is False and rows["claude-code"]["can_read_shared"] is False
    assert {(g["operation"], g["target_type"], g["target_id"]) for g in rows["codex"]["grants"]} == {
        ("READ", "knowledge_space", SHARED), ("WRITE", "knowledge_space", SHARED)}


# ---------------------------------------------------------------- canonical replay
def test_provisioning_survives_a_full_derived_rebuild(prov, lay, db):
    prov.add_agent("codex")
    prov.grant_write("codex", space=SHARED)
    prov.add_agent("hermes")
    prov.grant_write("hermes", project="p1")
    prov.revoke("hermes", project="p1", operation="WRITE")
    before = db.grants("codex") + db.grants("hermes")
    rebuild_policy_state(db.conn, lay.memory_stream)
    db.conn.commit()
    assert db.grants("codex") + db.grants("hermes") == before
    assert db.write("codex", knowledge_space_ids=[SHARED]).allow
    assert not db.write("hermes", project_ids=["p1"]).allow


def test_stream_stays_valid_for_doctor_upgrade_and_strict_policy_replay(prov, lay):
    prov.add_agent("codex")
    prov.grant_write("codex", space=SHARED)
    prov.revoke("codex")
    upgrade_mod._validate_memory(lay.memory_stream)  # every line: JSON object with an event_id
    assert iter_canonical_policy_events(lay.memory_stream)  # strict replay accepts every policy line
    ids = [e["event_id"] for e in events(lay)]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- lookup internals
def test_lookup_ignores_malformed_approvals_and_partial_tails(lay):
    good = {"event_id": "a1", "event_type": "operator_approval", "created_at": "t",
            "m4": {"domain": "operator_approval", "op": "approve", "approval_ref": "opapp-1",
                   "subject_profile": "codex", "operation": "WRITE", "target_type": "knowledge_space",
                   "target_id": SHARED}}
    append_canonical_event(lay.memory_stream, good)
    with lay.memory_stream.open("ab") as fh:
        fh.write(b'{"event_type": "operator_approval", "m4": {"domain": "operator_approval", "op": "approve"')  # torn
    lookup = OperatorApprovalLookup(lay.memory_stream)
    assert lookup("opapp-1").verification_status == "verified"
    assert lookup("opapp-2") is None


def test_lookup_rejects_wrong_domain_and_wrong_shapes(lay):
    for i, m4 in enumerate((
        {"domain": "something_else", "op": "approve", "approval_ref": "opapp-x"},
        {"domain": "operator_approval", "op": "approve"},
        {"domain": "operator_approval", "op": "approve", "approval_ref": 5},
        {"domain": "operator_approval", "op": "maybe", "approval_ref": "opapp-y"},
        "not-a-dict",
    )):
        append_canonical_event(lay.memory_stream, {
            "event_id": f"b{i}", "event_type": "operator_approval", "created_at": "t", "m4": m4})
    append_canonical_event(lay.memory_stream, {
        "event_id": "c", "event_type": "other", "created_at": "t",
        "m4": {"domain": "operator_approval", "op": "approve", "approval_ref": "opapp-z"}})
    lookup = OperatorApprovalLookup(lay.memory_stream)
    for ref in ("opapp-x", "opapp-y", "opapp-z"):
        assert lookup(ref) is None


def test_lookup_sees_events_appended_after_it_was_created(lay):
    lookup = OperatorApprovalLookup(lay.memory_stream)
    assert lookup("opapp-late") is None
    append_canonical_event(lay.memory_stream, {
        "event_id": "late", "event_type": "operator_approval", "created_at": "t",
        "m4": {"domain": "operator_approval", "op": "approve", "approval_ref": "opapp-late",
               "subject_profile": "codex", "operation": "WRITE", "target_type": "project", "target_id": "p"}})
    assert lookup("opapp-late").verification_status == "verified"


def test_lookup_is_independent_of_stream_size_noise(lay):
    for i in range(300):
        append_canonical_event(lay.memory_stream, {"event_id": f"n{i}", "event_type": "noise", "created_at": "t"})
    append_canonical_event(lay.memory_stream, {
        "event_id": "ok", "event_type": "operator_approval", "created_at": "t",
        "m4": {"domain": "operator_approval", "op": "approve", "approval_ref": "opapp-ok",
               "subject_profile": "p", "operation": "WRITE", "target_type": "project", "target_id": "q"}})
    assert OperatorApprovalLookup(lay.memory_stream)("opapp-ok").verification_status == "verified"


# ---------------------------------------------------------------- canonical append
def test_append_canonical_event_refuses_a_torn_stream(lay):
    with lay.memory_stream.open("ab") as fh:
        fh.write(b'{"event_id": "torn"')
    with pytest.raises(ProvisioningError) as exc:
        append_canonical_event(lay.memory_stream, {"event_id": "x", "event_type": "t", "created_at": "t"})
    assert exc.value.code == "stream_not_terminated"


def test_append_canonical_event_requires_an_event_id(lay):
    with pytest.raises(ProvisioningError):
        append_canonical_event(lay.memory_stream, {"event_type": "t"})
    assert lay.memory_stream.read_bytes() == b""


def test_stream_permissions_stay_private(prov, lay):
    import os
    import stat
    prov.add_agent("codex")
    if os.name != "nt":  # POSIX permission bits only (Windows reports 0o666/0o777)
        assert stat.S_IMODE(os.stat(lay.memory_stream).st_mode) == 0o600
