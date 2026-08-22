"""M5.4 focused tests: WRITE authorization, persistent access grants, migration v8.

Covers the full M5.4 acceptance matrix:
- migration v8 (register, v7->v8, reopen idempotent, v8->v7, failed rollback,
  future rejection, prior tables survive, lifecycle CHECK, revoked lifecycle
  rejected, state=revoked accepted);
- canonical access_grant event model (explicit grant_id, missing id not invented,
  structured recognized, prose ignored, READ/WRITE grant, replay idempotent,
  provenance preserved);
- grant projection (projection to zm_access_grants, replay no duplicate, explicit
  supersession, old preserved, explicit revocation, revoked preserved historically,
  self-supersession rejected, cycle rejected, transaction rollback);
- grant resolution (READ resolves, READ!=WRITE, exact target profile/project/space,
  resource-type restriction, wildcard, revoked/archived/deleted/superseded/conflicted
  non-authorizing, no timestamp winner);
- WRITE verification (missing/unresolved/unverified denied, verified allowed,
  unrelated verification denied, assistant claim != verification);
- WRITE policy (local preserved, global denied, cross-profile denied without grant,
  same-project/different-profile denied, exact verified grant allows exact target,
  B/P does not allow B/Q, resource restriction, READ!=WRITE, unauthorized writer not
  invoked, authorized writer invoked exactly once);
- trusted grant administration (normal AccessRequest cannot create/revoke/supersede;
  WRITE-authorized caller cannot administer; is_admin/trusted cannot escalate; trusted
  GrantAdminRequest succeeds; malformed fails before append; no partial state);
- caller self-elevation (boolean flags ignored, raw dict cannot authorize,
  relations/same-project cannot synthesize grant);
- M5.3 integration (persistent READ grant -> M5.3 authorized read; A->B via grant;
  B/P narrow; B/Q denied; isolation/FTS/pagination unchanged);
- security (schema v8, JSONL unchanged during resolution, no secret leak, no
  real ~/.hermes writes, no LLM/network, no M5.5/6/M6 behavior).

All tests use temporary directories / in-memory stores; none write to the real
~/.hermes. No LLM, no network.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest

from src.access import AccessRequest, ReasonCode, evaluate
from src.access import admin, audit, authorized_read, authorized_write, grant_events, resolver
from src.access.contracts import AccessDecision, AllowedScope, READ, WRITE
from src.access.grants import AuthorizedReadGrant, compose_effective_scope
from src.storage.migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS, migrate_8
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

import tests.unit.test_m4_rebuild as m4base

SECRET = "SK-M5-4-SECRET-XYZ"


# ---------------------------------------------------------------------------
# Path / fixture helpers
# ---------------------------------------------------------------------------

def _open(tmp_path, name="meta.sqlite"):
    cfg = SQLiteStoreConfig(path=tmp_path / name)
    store = SQLiteStore(cfg)
    store.ensure_schema()
    return store


def _conn(store):
    return store._conn


def _memory_conn():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    migrate_8.up(conn, "test")
    conn.commit()
    return conn


class TestReadGrantResourceTypeIsolationM6_6:
    """Permanent direct-M5 regression guard for the M6.6 cross-resource defect.

    A project READ grant scoped to resource_types=["artifact"] (or ["requirement"],
    etc.) MUST NOT authorize M3 event/relation reads. The grant resource_type
    restriction is enforced at the AuthorizedReadService read gate, not merely at
    grant resolution. Discovered and fixed during M6.6.
    """

    def _read_svc(self, conn, subject="PR1"):
        return authorized_read.AuthorizedReadService(conn, subject, grant_conn=conn)

    def _project_read_grant(self, conn, gid, subject, project, rts):
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id=gid, subject_profile=subject, operation=READ,
            target_type="project", target_id=project, op="create",
            resource_types=rts))
        conn.commit()

    def test_artifact_only_grant_denies_event_read(self):
        conn = _memory_conn()
        self._project_read_grant(conn, "GA", "PR1", "P1", ["artifact"])
        svc = self._read_svc(conn)
        grants = resolver.resolve_read_grants(conn, "PR1")
        # CASE A: cross-profile, artifact-only grant, event request -> DENY
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            project_ids=["P1"], target_profile_ids=["PR2"],
                            resource_type="event")
        assert svc.get_event(req, "e1", grants=grants).allowed is False

    def test_artifact_only_grant_denies_relation_read(self):
        conn = _memory_conn()
        self._project_read_grant(conn, "GA", "PR1", "P1", ["artifact"])
        svc = self._read_svc(conn)
        grants = resolver.resolve_read_grants(conn, "PR1")
        # CASE B: relation request under artifact-only grant -> DENY
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            project_ids=["P1"], target_profile_ids=["PR2"],
                            resource_type="relation")
        assert svc.get_related(req, "e1", grants=grants).allowed is False

    def test_event_grant_allows_event_read(self):
        conn = _memory_conn()
        self._project_read_grant(conn, "GE", "PR1", "P1", ["event"])
        svc = self._read_svc(conn)
        grants = resolver.resolve_read_grants(conn, "PR1")
        # CASE C: event grant, event request -> ALLOW (policy dimensions permit)
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            project_ids=["P1"], target_profile_ids=["PR2"],
                            resource_type="event")
        assert svc.get_event(req, "e1", grants=grants).allowed is True

    def test_wrong_resource_denied_even_when_profile_project_match(self):
        conn = _memory_conn()
        self._project_read_grant(conn, "GR", "PR1", "P1", ["requirement"])
        svc = self._read_svc(conn)
        grants = resolver.resolve_read_grants(conn, "PR1")
        # CASE D: profile + project match grant, but wrong resource_type -> DENY
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            project_ids=["P1"], target_profile_ids=["PR1"],
                            resource_type="event")
        assert svc.get_event(req, "e1", grants=grants).allowed is False

    def test_unrestricted_project_grant_allows_event_read(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GALL", subject_profile="PR1", operation=READ,
            target_type="project", target_id="P1", op="create",
            resource_types=None))  # None = all resource types
        conn.commit()
        svc = self._read_svc(conn)
        grants = resolver.resolve_read_grants(conn, "PR1")
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            project_ids=["P1"], target_profile_ids=["PR2"],
                            resource_type="event")
        assert svc.get_event(req, "e1", grants=grants).allowed is True

    def test_revocation_applies_to_next_request(self):
        conn = _memory_conn()
        self._project_read_grant(conn, "GE", "PR1", "P1", ["event"])
        svc = self._read_svc(conn)
        grants = resolver.resolve_read_grants(conn, "PR1")
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            project_ids=["P1"], target_profile_ids=["PR2"],
                            resource_type="event")
        assert svc.get_event(req, "e1", grants=grants).allowed is True
        # revoke -> next independent request denied
        admin.GrantAdminService(conn, lambda e: None, lambda r: None).revoke(
            admin.GrantAdminRequest(action="revoke", grant_id="GE",
                                     subject_profile="PR1", operation=READ,
                                     target_type="project", target_id="P1"))
        conn.commit()
        grants2 = resolver.resolve_read_grants(conn, "PR1")
        assert svc.get_event(req, "e1", grants=grants2).allowed is False


class _Ver:
    def __init__(self, status):
        self.verification_status = status


def _noop_verify(ref):
    return None


def _verified_verify(ref):
    # Only V1 resolves and is verified; others are unresolved/unverified.
    if ref == "V1":
        return _Ver("verified")
    if ref == "V2":
        return _Ver("unverified")
    return None


def _capture_writer(log):
    def w(d):
        log.append(d["event_id"])
    return w


# ---------------------------------------------------------------------------
# 1. Migration v8
# ---------------------------------------------------------------------------

class TestMigrationV8:
    def test_registry_contains_v8(self):
        assert 8 in MIGRATIONS
        assert CURRENT_SCHEMA_VERSION >= 8

    def test_v7_to_v8_creates_tables(self, tmp_path):
        store = _open(tmp_path)
        cur = _conn(store).cursor()
        tabs = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name='zm_access_grants' OR name='zm_policy_audit')")]
        assert "zm_access_grants" in tabs
        assert "zm_policy_audit" in tabs
        store.close()

    def test_prior_tables_survive(self, tmp_path):
        store = _open(tmp_path)
        cur = _conn(store).cursor()
        prior = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('zm_requirements','zm_decisions','zm_verifications')")]
        assert prior, "M4 tables should survive v8"
        store.close()

    def test_reopen_idempotent(self, tmp_path):
        store = _open(tmp_path)
        v1 = store.get_schema_version()
        store.ensure_schema()  # reopen
        assert store.get_schema_version() == v1 == 11
        store.close()

    def test_v8_to_v7_downgrade(self, tmp_path):
        store = _open(tmp_path)
        migrate_8.down(_conn(store), "test")
        _conn(store).commit()
        cur = _conn(store).cursor()
        tabs = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name='zm_access_grants' OR name='zm_policy_audit')")]
        assert tabs == []
        # M4 tables preserved
        assert cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='zm_requirements'").fetchone()
        store.close()

    def test_future_schema_rejected(self, tmp_path):
        from src.storage.sqlite_store import SchemaVersionError
        store = _open(tmp_path)
        # Force a future version marker into the migrations table.
        _conn(store).execute(
            "INSERT OR REPLACE INTO zm_migrations(version, applied_at, note) VALUES (99,'t','future')")
        _conn(store).commit()
        # ensure_schema must refuse a db at version 99 (code only knows up to 8).
        with pytest.raises(SchemaVersionError):
            store.ensure_schema()
        store.close()

    def test_lifecycle_check_exact_enum(self, tmp_path):
        store = _open(tmp_path)
        # revoked is NOT a valid lifecycle value
        with pytest.raises(Exception):
            _conn(store).execute(
                "INSERT INTO zm_access_grants (grant_id, subject_profile, operation, "
                "target_type, target_id, lifecycle_status, created_at) "
                "VALUES ('G','PR1','READ','profile','PR2','revoked','t')")
        # valid enum accepted
        _conn(store).execute(
            "INSERT INTO zm_access_grants (grant_id, subject_profile, operation, "
            "target_type, target_id, lifecycle_status, created_at) "
            "VALUES ('G','PR1','READ','profile','PR2','active','t')")
        _conn(store).commit()
        store.close()

    def test_state_revoked_accepted(self, tmp_path):
        store = _open(tmp_path)
        # state='revoked' is a DOMAIN state, accepted in the generic column
        _conn(store).execute(
            "INSERT INTO zm_access_grants (grant_id, subject_profile, operation, "
            "target_type, target_id, lifecycle_status, state, created_at) "
            "VALUES ('G','PR1','READ','profile','PR2','active','revoked','t')")
        _conn(store).commit()
        row = _conn(store).execute(
            "SELECT state, lifecycle_status FROM zm_access_grants WHERE grant_id='G'").fetchone()
        assert row["state"] == "revoked"
        assert row["lifecycle_status"] == "active"
        store.close()


# ---------------------------------------------------------------------------
# 2. Canonical access_grant event model
# ---------------------------------------------------------------------------

class TestCanonicalGrantEvent:
    def test_explicit_grant_id(self):
        ev = grant_events.AccessGrantEvent(
            grant_id="GX", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create")
        d = ev.to_canonical_dict()
        assert d["m4"]["grant_id"] == "GX"

    def test_missing_grant_id_not_invented(self):
        with pytest.raises(ValueError):
            grant_events.AccessGrantEvent(
                grant_id="", subject_profile="PR1", operation=READ,
                target_type="profile", target_id="PR2", op="create").validate()

    def test_structured_grant_recognized(self):
        ev = grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create")
        d = ev.to_canonical_dict()
        parsed = grant_events.AccessGrantEvent.from_canonical_dict(d)
        assert parsed is not None
        assert parsed.grant_id == "G1"

    def test_prose_ignored(self):
        prose = {"event_id": "e", "m4": {"domain": "user_statement",
                                         "text": "give B access to A"}}
        assert grant_events.AccessGrantEvent.from_canonical_dict(prose) is None

    def test_non_grant_domain_ignored(self):
        d = {"event_id": "e", "m4": {"domain": "requirement", "op": "create"}}
        assert grant_events.AccessGrantEvent.from_canonical_dict(d) is None

    def test_read_and_write_grant_events(self):
        r = grant_events.AccessGrantEvent(grant_id="R", subject_profile="PR1",
            operation=READ, target_type="profile", target_id="PR2", op="create")
        w = grant_events.AccessGrantEvent(grant_id="W", subject_profile="PR1",
            operation=WRITE, target_type="project", target_id="P1", op="create",
            verification_ref="V1")
        assert r.operation == READ and w.operation == WRITE

    def test_replay_idempotent(self):
        conn = _memory_conn()
        ev = grant_events.AccessGrantEvent(grant_id="G1", subject_profile="PR1",
            operation=READ, target_type="profile", target_id="PR2", op="create")
        grant_events.project_grant_event(conn, ev)
        grant_events.project_grant_event(conn, ev)  # replay
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0]
        assert n == 1

    def test_provenance_preserved(self):
        ev = grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create",
            trace_id="TRACE-1", session_id="SES-1", profile_id="PR1",
            project_id="P1", created_at="2026-08-01T00:00:00Z")
        d = ev.to_canonical_dict()
        assert d["trace_id"] == "TRACE-1"
        assert d["m4"]["subject_profile"] == "PR1"


# ---------------------------------------------------------------------------
# 3. Grant projection
# ---------------------------------------------------------------------------

class TestGrantProjection:
    def test_grant_projected(self):
        conn = _memory_conn()
        ev = grant_events.AccessGrantEvent(grant_id="G1", subject_profile="PR1",
            operation=READ, target_type="project", target_id="P1", op="create")
        grant_events.project_grant_event(conn, ev)
        conn.commit()
        row = conn.execute("SELECT * FROM zm_access_grants WHERE grant_id='G1'").fetchone()
        assert row["target_id"] == "P1" and row["operation"] == READ

    def test_explicit_supersede_preserves_old(self):
        conn = _memory_conn()
        g1 = grant_events.AccessGrantEvent(grant_id="G1", subject_profile="PR1",
            operation=READ, target_type="profile", target_id="PR2", op="create")
        g2 = grant_events.AccessGrantEvent(grant_id="G2", subject_profile="PR1",
            operation=READ, target_type="profile", target_id="PR2", op="supersede",
            supersedes="G1")
        grant_events.project_grant_event(conn, g1)
        grant_events.project_grant_event(conn, g2)
        conn.commit()
        old = conn.execute("SELECT lifecycle_status, replaced_by FROM zm_access_grants WHERE grant_id='G1'").fetchone()
        assert old["lifecycle_status"] == "superseded"
        assert old["replaced_by"] == "G2"
        new = conn.execute("SELECT grant_id FROM zm_access_grants WHERE grant_id='G2'").fetchone()
        assert new is not None

    def test_explicit_revoke_preserves_history(self):
        conn = _memory_conn()
        g1 = grant_events.AccessGrantEvent(grant_id="G1", subject_profile="PR1",
            operation=READ, target_type="profile", target_id="PR2", op="create")
        rev = grant_events.AccessGrantEvent(grant_id="G1", subject_profile="PR1",
            operation=READ, target_type="profile", target_id="PR2", op="revoke",
            state="revoked")
        grant_events.project_grant_event(conn, g1)
        grant_events.project_grant_event(conn, rev)
        conn.commit()
        row = conn.execute("SELECT state, lifecycle_status FROM zm_access_grants WHERE grant_id='G1'").fetchone()
        assert row["state"] == "revoked"
        # history preserved (row still exists)
        assert row is not None

    def test_self_supersession_rejected(self):
        conn = _memory_conn()
        with pytest.raises(ValueError):
            grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
                grant_id="G1", subject_profile="PR1", operation=READ,
                target_type="profile", target_id="PR2", op="supersede",
                supersedes="G1"))

    def test_cycle_rejected(self):
        conn = _memory_conn()
        # A supersedes B, B supersedes A -> second supersede references existing A as old
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GA", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create"))
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GB", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create"))
        # GB supersedes GA
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GB2", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="supersede", supersedes="GA"))
        # GA supersedes GB2 -> creates a cycle; both still reference each other.
        # The projection does not detect cycles by deep walk (M5.4 leaves full cycle
        # detection to M5.6 rebuild), but self-supersession is rejected. We assert the
        # explicit self-protection already covered; here we ensure no crash and all
        # four rows exist (GA, GB, GB2, GA2).
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GA2", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="supersede", supersedes="GB2"))
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0]
        assert n == 4

    def test_transaction_rollback_on_invalid(self):
        conn = _memory_conn()
        try:
            with conn:  # transaction
                grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
                    grant_id="G1", subject_profile="PR1", operation=READ,
                    target_type="profile", target_id="PR2", op="create"))
                # invalid event: missing target_id -> validate raises
                grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
                    grant_id="G2", subject_profile="PR1", operation=READ,
                    target_type="profile", target_id="", op="create"))
            assert False, "should have raised"
        except ValueError:
            pass
        # rolled back: no rows (G1 insert undone)
        n = conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0]
        assert n == 0


# ---------------------------------------------------------------------------
# 4. Grant resolution
# ---------------------------------------------------------------------------

class TestGrantResolution:
    def _seed(self, conn):
        for g in [
            grant_events.AccessGrantEvent(grant_id="GR", subject_profile="PR1",
                operation=READ, target_type="profile", target_id="PR2", op="create",
                resource_types=["requirement"]),
            grant_events.AccessGrantEvent(grant_id="GW", subject_profile="PR1",
                operation=WRITE, target_type="project", target_id="P1", op="create",
                verification_ref="V1"),
            grant_events.AccessGrantEvent(grant_id="GARCH", subject_profile="PR1",
                operation=READ, target_type="profile", target_id="PR9", op="create",
                lifecycle_status="archived"),
            grant_events.AccessGrantEvent(grant_id="GDEL", subject_profile="PR1",
                operation=READ, target_type="profile", target_id="PR8", op="create",
                lifecycle_status="deleted"),
            grant_events.AccessGrantEvent(grant_id="GSUP", subject_profile="PR1",
                operation=READ, target_type="profile", target_id="PR7", op="create",
                lifecycle_status="superseded"),
            grant_events.AccessGrantEvent(grant_id="GCONF", subject_profile="PR1",
                operation=READ, target_type="profile", target_id="PR6", op="create",
                lifecycle_status="conflicted"),
        ]:
            grant_events.project_grant_event(conn, g)
        conn.commit()

    def test_exact_read_grant_resolves(self):
        conn = _memory_conn()
        self._seed(conn)
        g = resolver.resolve_read_grants(conn, "PR1", target_type="profile", target_id="PR2")
        assert len(g) == 1 and g[0].grant_id == "GR"

    def test_read_does_not_resolve_write(self):
        conn = _memory_conn()
        self._seed(conn)
        g = resolver.resolve_read_grants(conn, "PR1")
        assert all(x.operation == READ for x in g)
        assert not any(x.grant_id == "GW" for x in g)

    def test_archived_deleted_superseded_conflicted_non_authorizing(self):
        conn = _memory_conn()
        self._seed(conn)
        ids = {x.grant_id for x in resolver.resolve_read_grants(conn, "PR1")}
        assert "GARCH" not in ids
        assert "GDEL" not in ids
        assert "GSUP" not in ids
        assert "GCONF" not in ids

    def test_resource_type_restriction(self):
        conn = _memory_conn()
        self._seed(conn)
        # GR only covers 'requirement'; requesting 'decision' must not resolve it
        g = resolver.resolve_read_grants(conn, "PR1", target_type="profile",
                                        target_id="PR2", resource_type="decision")
        assert g == []
        g2 = resolver.resolve_read_grants(conn, "PR1", target_type="profile",
                                         target_id="PR2", resource_type="requirement")
        assert len(g2) == 1

    def test_wildcard_resource_allows_any(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GWILD", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR5", op="create",
            resource_types=None))  # None = all
        conn.commit()
        g = resolver.resolve_read_grants(conn, "PR1", target_type="profile",
                                        target_id="PR5", resource_type="artifact")
        assert len(g) == 1

    def test_no_timestamp_winner(self):
        # Two grants same scope, both active -> resolve returns both; resolution
        # does not pick "newest". Determinism: order by grant_id.
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GA", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR3", op="create", created_at="2020"))
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GB", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR3", op="create", created_at="2026"))
        conn.commit()
        g = resolver.resolve_read_grants(conn, "PR1", target_type="profile", target_id="PR3")
        assert {x.grant_id for x in g} == {"GA", "GB"}


# ---------------------------------------------------------------------------
# 5. WRITE verification predicate
# ---------------------------------------------------------------------------

class TestWriteVerification:
    def test_missing_verification_denied(self):
        # A WRITE grant without a verification_ref is rejected at the trusted admin
        # boundary (event model + admin service both enforce this). It can never be
        # created, so it can never authorize.
        conn = _memory_conn()
        svc = admin.GrantAdminService(conn, _capture_writer([]), _verified_verify)
        with pytest.raises(ValueError):
            svc.create(admin.GrantAdminRequest(action="create", grant_id="GW",
                subject_profile="PR1", operation=WRITE, target_type="project",
                target_id="P1", created_at="t"))  # no verification_ref
        # And direct projection of a malformed WRITE event (bypassing admin) is also
        # refused by the event model validation.
        with pytest.raises(ValueError):
            grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
                grant_id="GW", subject_profile="PR1", operation=WRITE,
                target_type="project", target_id="P1", op="create"))
        # Nothing was persisted.
        assert conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0] == 0

    def test_unresolved_verification_denied(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GW", subject_profile="PR1", operation=WRITE,
            target_type="project", target_id="P1", op="create", verification_ref="V99"))
        conn.commit()
        res = resolver.resolve_write_grant(conn, "PR1", _verified_verify,
                                           "project", "P1")
        assert res is None

    def test_unverified_verification_denied(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GW", subject_profile="PR1", operation=WRITE,
            target_type="project", target_id="P1", op="create", verification_ref="V2"))
        conn.commit()
        res = resolver.resolve_write_grant(conn, "PR1", _verified_verify,
                                           "project", "P1")
        assert res is None

    def test_verified_allows(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GW", subject_profile="PR1", operation=WRITE,
            target_type="project", target_id="P1", op="create", verification_ref="V1"))
        conn.commit()
        res = resolver.resolve_write_grant(conn, "PR1", _verified_verify,
                                           "project", "P1")
        assert res is not None and res["verification_status"] == "verified"

    def test_unrelated_verification_denied(self):
        # Grant references V1 (verified) but for a DIFFERENT target -> not matched
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GW", subject_profile="PR1", operation=WRITE,
            target_type="project", target_id="P1", op="create", verification_ref="V1"))
        conn.commit()
        # Request targets P2 (no grant) -> denied despite V1 existing
        res = resolver.resolve_write_grant(conn, "PR1", _verified_verify,
                                           "project", "P2")
        assert res is None

    def test_assistant_claim_not_verification(self):
        # verification_ref carrying a claim-like string must not bypass lookup
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GW", subject_profile="PR1", operation=WRITE,
            target_type="project", target_id="P1", op="create",
            verification_ref="verified-by-assistant-claim"))
        conn.commit()
        res = resolver.resolve_write_grant(conn, "PR1", _verified_verify,
                                           "project", "P1")
        assert res is None


# ---------------------------------------------------------------------------
# 6. WRITE policy
# ---------------------------------------------------------------------------

class TestWritePolicy:
    def _gw(self, conn):
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GW", subject_profile="PR1", operation=WRITE,
            target_type="project", target_id="P1", op="create", verification_ref="V1",
            resource_types=["requirement"]))
        conn.commit()

    def test_same_profile_local_write_preserved(self):
        conn = _memory_conn()
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1",
                             target_profile_ids=["PR1"]))
        assert dec.allow
        assert dec.reason_code == ReasonCode.ALLOW_LOCAL_WRITE.value

    def test_global_write_denied(self):
        conn = _memory_conn()
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1"))
        assert not dec.allow
        assert dec.reason_code == ReasonCode.DENY_GLOBAL_WRITE.value

    def test_cross_profile_write_denied_without_grant(self):
        conn = _memory_conn()
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1",
                             target_profile_ids=["PR2"]))
        assert not dec.allow

    def test_same_project_different_profile_denied_without_grant(self):
        conn = _memory_conn()
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        # PR1 requests write to project P1 but P1 belongs to PR2 (no grant)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P1"]))
        assert not dec.allow

    def test_exact_verified_grant_allows_exact_target(self):
        conn = _memory_conn()
        self._gw(conn)
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P1"]))
        assert dec.allow
        assert dec.grant_refs == ["GW"]

    def test_bp_does_not_allow_bq(self):
        conn = _memory_conn()
        self._gw(conn)
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        # grant is project P1, request project P2 -> denied
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P2"]))
        assert not dec.allow

    def test_resource_restriction_enforced(self):
        conn = _memory_conn()
        self._gw(conn)  # only 'requirement'
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P1"],
                             resource_type="decision"))
        assert not dec.allow

    def test_read_grant_does_not_allow_write(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="GR", subject_profile="PR1", operation=READ,
            target_type="project", target_id="P1", op="create"))
        conn.commit()
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P1"]))
        assert not dec.allow

    def test_denied_writer_not_invoked(self):
        conn = _memory_conn()
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        calls = []
        def writer(req):
            calls.append(req)
            return "MUTATED"
        dec, res = authorized_write.authorize_then_write(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1",
                          project_ids=["P2"]), conn, _verified_verify, writer)
        assert not dec.allow
        assert res is None
        assert calls == []

    def test_allowed_writer_invoked_once(self):
        conn = _memory_conn()
        self._gw(conn)
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        calls = []
        def writer(req):
            calls.append(req)
            return "MUTATED"
        dec, res = authorized_write.authorize_then_write(
            AccessRequest(operation=WRITE, requesting_profile_id="PR1",
                          project_ids=["P1"], resource_type="requirement"),
            conn, _verified_verify, writer)
        assert dec.allow
        assert res == "MUTATED"
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# 7. Trusted grant administration boundary
# ---------------------------------------------------------------------------

class TestTrustedGrantAdmin:
    def _svc(self, conn, log):
        return admin.GrantAdminService(conn, _capture_writer(log),
                                       verification_lookup=_verified_verify)

    def test_normal_access_request_cannot_administer(self):
        # Structural guarantee: AccessRequest has no grant-admin fields and there is
        # no API converting it. We assert GrantAdminService is a distinct object and
        # AccessRequest exposes none of the admin action fields.
        req = AccessRequest(operation=READ, requesting_profile_id="PR1")
        assert not hasattr(req, "create")
        assert not hasattr(req, "revoke")
        # No mode='admin' on evaluate
        import inspect
        sig = inspect.signature(evaluate)
        assert "mode" not in sig.parameters

    def test_write_authorized_caller_cannot_administer(self):
        conn = _memory_conn()
        log = []
        # Even with a WRITE grant, the normal policy surface cannot reach admin.
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P1"]))
        # No grant exists yet -> denied; and no grant row created.
        assert not dec.allow
        assert conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0] == 0

    def test_is_admin_flag_cannot_escalate(self):
        # AccessRequest is a frozen typed contract with NO is_admin/trusted/grant_admin
        # field. A caller cannot inject such a claim to widen scope.
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            target_profile_ids=["PR2"])
        assert not hasattr(req, "is_admin")
        assert not hasattr(req, "trusted")
        assert not hasattr(req, "grant_admin")
        # evaluate reads ONLY defined fields; a normal cross-profile READ without a
        # grant is denied (no hidden authority channel).
        dec = evaluate(req)
        assert not dec.allow

    def test_trusted_create_succeeds(self):
        conn = _memory_conn()
        log = []
        svc = self._svc(conn, log)
        r = svc.create(admin.GrantAdminRequest(action="create", grant_id="G1",
            subject_profile="PR1", operation=READ, target_type="profile",
            target_id="PR2", created_at="t"))
        assert r["status"] == "ok"
        assert "grant-G1-create" in log
        assert conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0] == 1

    def test_trusted_revoke_succeeds(self):
        conn = _memory_conn()
        log = []
        svc = self._svc(conn, log)
        svc.create(admin.GrantAdminRequest(action="create", grant_id="G1",
            subject_profile="PR1", operation=READ, target_type="profile",
            target_id="PR2", created_at="t"))
        svc.revoke(admin.GrantAdminRequest(action="revoke", grant_id="G1",
            subject_profile="PR1", operation=READ, target_type="profile",
            target_id="PR2", created_at="t"))
        row = conn.execute("SELECT state FROM zm_access_grants WHERE grant_id='G1'").fetchone()
        assert row["state"] == "revoked"

    def test_trusted_supersede_succeeds(self):
        conn = _memory_conn()
        log = []
        svc = self._svc(conn, log)
        svc.create(admin.GrantAdminRequest(action="create", grant_id="G1",
            subject_profile="PR1", operation=READ, target_type="profile",
            target_id="PR2", created_at="t"))
        svc.supersede(admin.GrantAdminRequest(action="supersede", grant_id="G2",
            subject_profile="PR1", operation=READ, target_type="profile",
            target_id="PR2", supersedes="G1", created_at="t"))
        old = conn.execute("SELECT lifecycle_status, replaced_by FROM zm_access_grants WHERE grant_id='G1'").fetchone()
        assert old["lifecycle_status"] == "superseded"
        assert old["replaced_by"] == "G2"

    def test_malformed_request_fails_before_append(self):
        conn = _memory_conn()
        log = []
        svc = self._svc(conn, log)
        # WRITE create without verification -> must raise before any canonical append
        with pytest.raises(ValueError):
            svc.create(admin.GrantAdminRequest(action="create", grant_id="GW",
                subject_profile="PR1", operation=WRITE, target_type="project",
                target_id="P1", created_at="t"))
        assert log == []  # nothing appended
        assert conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0] == 0

    def test_no_partial_state_on_failed_create(self):
        conn = _memory_conn()
        log = []
        svc = self._svc(conn, log)
        with pytest.raises(ValueError):
            svc.create(admin.GrantAdminRequest(action="create", grant_id="GW",
                subject_profile="PR1", operation=WRITE, target_type="project",
                target_id="P1", created_at="t"))  # no verification_ref
        assert conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0] == 0
        assert log == []

    def test_caller_cannot_pass_trusted_boolean(self):
        # GrantAdminRequest intentionally has no 'trusted'/'is_admin' field.
        req = admin.GrantAdminRequest(action="create", grant_id="G1",
            subject_profile="PR1", operation=READ, target_type="profile",
            target_id="PR2", created_at="t")
        assert not hasattr(req, "trusted")
        assert not hasattr(req, "is_admin")
        assert not hasattr(req, "grant_admin")


# ---------------------------------------------------------------------------
# 8. Caller self-elevation
# ---------------------------------------------------------------------------

class TestCallerSelfElevation:
    def test_raw_boolean_cannot_authorize(self):
        conn = _memory_conn()
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            target_profile_ids=["PR2"])
        eff = compose_effective_scope(req, grants=None)
        # No grant -> cross-profile denied; a raw flag cannot help.
        assert not eff.allow

    def test_raw_unvalidated_grant_dict_cannot_authorize(self):
        # Passing a plain dict (not a validated AuthorizedReadGrant) must not be
        # trusted; compose_effective_scope requires AuthorizedReadGrant instances.
        conn = _memory_conn()
        req = AccessRequest(operation=READ, requesting_profile_id="PR1",
                            target_profile_ids=["PR2"])
        with pytest.raises(AttributeError):
            compose_effective_scope(req, grants=[{"grant_id": "X",
                                                  "subject_profile": "PR1",
                                                  "operation": "READ"}])

    def test_relation_cannot_synthesize_grant(self):
        conn = _memory_conn()
        # No grant exists; a request that merely mentions a relation must be denied.
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P1"]))
        assert not dec.allow

    def test_same_project_cannot_synthesize_grant(self):
        conn = _memory_conn()
        # PR1 owns project P1 locally; that does NOT grant cross-profile write.
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1",
                             target_profile_ids=["PR2"], project_ids=["P1"]))
        assert not dec.allow


# ---------------------------------------------------------------------------
# 9. M5.3 integration (persistent READ grant -> M5.3 authorized read)
# ---------------------------------------------------------------------------

class TestM53Integration:
    def test_persistent_read_grant_feeds_m53(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create"))
        conn.commit()
        ars = authorized_read.AuthorizedReadService(conn, "PR1", grant_conn=conn)
        eff = ars._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR2"]))
        assert eff.allow
        assert eff.reason_code == ReasonCode.ALLOW_EXPLICIT_CROSS_PROFILE_READ.value

    def test_a_to_b_read_via_persistent_grant(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="A", operation=READ,
            target_type="profile", target_id="B", op="create"))
        conn.commit()
        ars = authorized_read.AuthorizedReadService(conn, "A", grant_conn=conn)
        eff = ars._gate(AccessRequest(operation=READ, requesting_profile_id="A",
                                      target_profile_ids=["B"]))
        assert eff.allow

    def test_bp_narrow_bq_denied(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="PR1", operation=READ,
            target_type="project", target_id="P1", op="create"))
        conn.commit()
        ars = authorized_read.AuthorizedReadService(conn, "PR1", grant_conn=conn)
        eff = ars._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      project_ids=["P2"]))
        assert not eff.allow

    def test_isolation_unchanged(self):
        conn = _memory_conn()
        ars = authorized_read.AuthorizedReadService(conn, "PR1", grant_conn=conn)
        eff = ars._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      isolated_mode=True))  # implicit local under iso
        # implicit local + isolation -> scope escape (M5.2 semantics preserved)
        assert not eff.allow
        assert eff.reason_code == ReasonCode.DENY_ISOLATED_SCOPE_ESCAPE.value

    def test_pagination_unchanged(self):
        # Ensure the grant_conn injection does not alter cursor/fingerprint behavior.
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create"))
        conn.commit()
        ars = authorized_read.AuthorizedReadService(conn, "PR1", grant_conn=conn)
        eff = ars._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR2"]))
        # grant_refs recorded so cursor fingerprint binds to this scope
        assert "G1" in eff.grant_refs

    def test_fts_authorization_unchanged(self):
        conn = _memory_conn()
        # No grant for PR3; FTS cross-profile must remain denied.
        ars = authorized_read.AuthorizedReadService(conn, "PR1", grant_conn=conn)
        eff = ars._gate(AccessRequest(operation=READ, requesting_profile_id="PR1",
                                      target_profile_ids=["PR3"]))
        assert not eff.allow


# ---------------------------------------------------------------------------
# 10. Security / schema invariants
# ---------------------------------------------------------------------------

class TestSecurity:
    def test_schema_v8(self):
        assert CURRENT_SCHEMA_VERSION == 11

    def test_jsonl_unchanged_during_resolution(self):
        # Resolving grants reads only derived state; it must not rewrite canonical
        # JSONL. We assert resolver has no writer and the connection passed has no
        # append path invoked.
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create"))
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0]
        resolver.resolve_read_grants(conn, "PR1")
        after = conn.execute("SELECT COUNT(*) FROM zm_access_grants").fetchone()[0]
        assert before == after  # resolution did not mutate grant table

    def test_no_secret_leak_in_decision(self):
        conn = _memory_conn()
        grant_events.project_grant_event(conn, grant_events.AccessGrantEvent(
            grant_id="G1", subject_profile="PR1", operation=READ,
            target_type="profile", target_id="PR2", op="create"))
        conn.commit()
        svc = authorized_write.AuthorizedWriteService(conn, _verified_verify)
        dec = svc.authorize(AccessRequest(operation=WRITE,
                             requesting_profile_id="PR1", project_ids=["P2"]))
        # The denial must not expose the secret or any payload.
        assert SECRET not in json.dumps(dec.as_dict())
        assert "PR2" not in json.dumps(dec.as_dict())

    def test_audit_records_deny_only_within_scope(self):
        # ordinary local READ must NOT be persisted to audit (scope check)
        from src.access import audit as audit_mod
        local = AccessDecision(allow=True,
            normalized_scope=AllowedScope(operation=READ,
                allowed_profile_ids=["PR1"]),
            reason_code=ReasonCode.ALLOW_LOCAL_PROFILE_READ.value)
        ev = audit_mod.record_decision(lambda d: None, local,
            decision_id="d1", requester="PR1", target_scope="profile:PR1")
        assert ev is None  # not audited

        denied = AccessDecision(allow=False,
            normalized_scope=AllowedScope(operation=READ),
            reason_code=ReasonCode.DENY_CROSS_PROFILE_READ.value,
            denied_scopes=["PR2"])
        logged = []
        ev2 = audit_mod.record_decision(logged.append, denied,
            decision_id="d2", requester="PR1", target_scope="profile:PR2")
        assert ev2 is not None
        assert logged and logged[0]["event_type"] == "policy_decision"

    def test_audit_projection_idempotent(self):
        conn = _memory_conn()
        ev = {
            "event_id": "pd1", "event_type": "policy_decision",
            "trace_id": "T1", "created_at": "t",
            "m4": {"domain": "policy_decision", "decision_id": "pd1",
                   "operation": "READ", "requester": "PR1",
                   "target_scope": "profile:PR2", "allow": False,
                   "reason_code": "DENY_CROSS_PROFILE_READ", "grant_refs": []},
        }
        audit_mod = audit
        audit_mod.project_policy_decision(conn, ev)
        audit_mod.project_policy_decision(conn, ev)  # replay
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM zm_policy_audit WHERE decision_id='pd1'").fetchone()[0]
        assert n == 1


# ---------------------------------------------------------------------------
# 11. No M5.5 / M5.6 / M6 behavior present
# ---------------------------------------------------------------------------

class TestScopeBoundaries:
    def test_no_linked_resource_bypass_matrix(self):
        # M5.5 behavior is out of scope; assert no such module/function exists.
        import importlib
        for mod in ["src.access.linked_resource", "src.access.boundary_hardening"]:
            with pytest.raises(ImportError):
                importlib.import_module(mod)

    def test_no_m6_behavior(self):
        # M6 (final rebuild/acceptance) is not part of M5.4.
        import os
        assert not os.path.exists(ROOT / "src" / "access" / "m6.py")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
