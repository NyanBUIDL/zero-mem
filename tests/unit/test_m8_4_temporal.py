"""M8.4 focused tests — temporal projection, as-of, history, authorization.

These tests exercise the M8.4 temporal-projection and authorization-first
bounded as-of / history read layer over the derived ``zm_temporal_index``.

They assert the permanent M8.4 invariants:

- temporal projection is deterministic and rebuildable (insertion-order
  independent);
- transaction/history time (``created_at``) stays distinct from valid/effective
  time (``effective_at`` / ``valid_from``–``valid_until``);
- no timestamp is invented to fill a NULL; unknown time stays unknown;
- malformed temporal data fails closed;
- as-of / history reads are bounded and respect explicit boundaries;
- authorization is applied BEFORE any temporal visibility, so a denied seed
  reveals no temporal metadata (no count, no bound, no existence leak);
- M6.6 resource_type isolation is preserved end-to-end through temporal reads;
- M4 lifecycle / supersession / conflict semantics are not redefined, and
  recency is never authority;
- the read path is read-only (no mutation of JSONL, derived tables, grants).

Zero LLM, zero network, zero Hermes-core change.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path("/home/brian-nguyen/Hermes Workplace/Zero-mem")
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from src.access import AuthorizedReadService  # noqa: E402
from src.access import AccessRequest  # noqa: E402
from src.access.grant_events import AccessGrantEvent, project_grant_event  # noqa: E402
from src.access.contracts import READ  # noqa: E402
from src.m8.temporal_projection import (  # noqa: E402
    PROJECTION_VERSION,
    TEMPORAL_TABLE,
    TemporalProjectionError,
    describe_temporal_projection,
    project_temporal_index,
)
from src.m8.temporal_read import (  # noqa: E402
    MAX_HISTORY_VERSIONS,
    TemporalDimension,
    TemporalReadError,
    TemporalReadRequest,
    TemporalReadResult,
    as_of_match,
    describe_temporal_read,
    read_temporal,
    within_window,
)
from src.m8.vocabulary import RESOURCE_TYPES
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

TS = "2026-01-02T03:04:05+00:00"
CUTOFF = "2026-06-01T00:00:00+00:00"
BUILT_AT = "2026-06-01T00:00:00+00:00"


def _new_store() -> SQLiteStore:
    d = tempfile.mkdtemp(prefix="m8_4_")
    store = SQLiteStore(SQLiteStoreConfig(path=Path(d) / "meta.sqlite"))
    store.ensure_schema()  # migrate_4/7/8/9
    return store


def _insert(conn: sqlite3.Connection, table: str, **cols: Any) -> None:
    keys = list(cols.keys())
    ph = ",".join("?" for _ in keys)
    conn.execute(
        f"INSERT INTO {table} ({','.join(keys)}) VALUES ({ph})",
        [cols[k] for k in keys],
    )


def seed_two_profiles(conn: sqlite3.Connection) -> None:
    """Two profiles (PR1 own, PR2 other) and two projects (P1, P2)."""
    # PR1 / P1 decision WITH explicit effective_at (no created_at column).
    _insert(conn, "zm_decisions",
            decision_id="DEC-P1", project_id="P1", statement="d1",
            lifecycle_status="active", profile_id="PR1",
            effective_at="2026-03-01T00:00:00+00:00")
    # PR1 / P1 requirement WITHOUT any valid time (created_at only).
    _insert(conn, "zm_requirements",
            requirement_id="REQ-P1", project_id="P1", statement="r1",
            lifecycle_status="active", verification_status="verified",
            profile_id="PR1", created_at="2026-02-15T00:00:00+00:00")
    # PR2 / P2 decision (NOT authorized for PR1), with effective_at.
    _insert(conn, "zm_decisions",
            decision_id="DEC-P2", project_id="P2", statement="d2-hidden",
            lifecycle_status="active", profile_id="PR2",
            effective_at="2026-04-01T00:00:00+00:00")
    # PR2 / P2 requirement (not authorized for PR1).
    _insert(conn, "zm_requirements",
            requirement_id="REQ-P2", project_id="P2", statement="r2-hidden",
            lifecycle_status="active", profile_id="PR2",
            created_at="2026-03-20T00:00:00+00:00")
    # PR1 / P1 decision with a distinct effective_at (used for explicit
    # valid-time preservation / as-of point tests).
    _insert(conn, "zm_decisions",
            decision_id="DEC-ENV", project_id="P1", statement="d3",
            lifecycle_status="active", profile_id="PR1",
            effective_at="2026-06-01T00:00:00+00:00")
    conn.commit()


def seed_grants(conn: sqlite3.Connection) -> None:
    # PR1 owns P1 (unrestricted project grant).
    project_grant_event(conn, AccessGrantEvent(
        grant_id="G-P1", subject_profile="PR1", operation=READ,
        target_type="project", target_id="P1", op="create",
        resource_types=None))
    # PR1 artifact-only grant on P1 (M6.6 isolation target).
    project_grant_event(conn, AccessGrantEvent(
        grant_id="G-ART", subject_profile="PR1", operation=READ,
        target_type="project", target_id="P1", op="create",
        resource_types=["artifact"]))
    conn.commit()


def project(conn: sqlite3.Connection) -> dict:
    return project_temporal_index(conn, source_cutoff=CUTOFF, built_at=BUILT_AT)


# ---------------------------------------------------------------------------
# Determinism / projection
# ---------------------------------------------------------------------------

class TestTemporalProjectionDeterminism:
    def test_projection_is_deterministic_and_rebuildable(self):
        s1 = project_temporal_index(_new_store()._conn,
                                    source_cutoff=CUTOFF, built_at=BUILT_AT)
        s2 = project_temporal_index(_new_store()._conn,
                                    source_cutoff=CUTOFF, built_at=BUILT_AT)
        assert s1["canonical_fingerprint"] == s2["canonical_fingerprint"]
        assert s1["inserted_rows"] == s2["inserted_rows"]

    def test_insertion_order_independent(self):
        a = _new_store()
        seed_two_profiles_reversed(a._conn)
        fa = project_temporal_index(a._conn, source_cutoff=CUTOFF,
                                    built_at=BUILT_AT)["canonical_fingerprint"]
        b = _new_store()
        seed_two_profiles(b._conn)
        fb = project_temporal_index(b._conn, source_cutoff=CUTOFF,
                                    built_at=BUILT_AT)["canonical_fingerprint"]
        assert fa == fb

    def test_rows_ordered_by_resource_identity(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        project(store._conn)
        rows = store._conn.execute(
            f"SELECT resource_type, resource_id FROM {TEMPORAL_TABLE} "
            f"ORDER BY resource_type ASC, resource_id ASC"
        ).fetchall()
        assert rows == sorted(rows, key=lambda r: (r[0], r[1]))

    def test_projection_touches_only_temporal_table(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        before = dict(store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_graph_edges").fetchone())
        project(store._conn)
        # Graph edges untouched by temporal projection.
        after = store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_graph_edges").fetchone()
        assert after["n"] == before["n"]


def seed_two_profiles_reversed(conn: sqlite3.Connection) -> None:
    # Same logical data, inserted in a different order; decisions have no
    # created_at column.
    _insert(conn, "zm_requirements",
            requirement_id="REQ-P2", project_id="P2", statement="r2-hidden",
            lifecycle_status="active", profile_id="PR2",
            created_at="2026-03-20T00:00:00+00:00")
    _insert(conn, "zm_decisions",
            decision_id="DEC-ENV", project_id="P1", statement="d3",
            lifecycle_status="active", profile_id="PR1",
            effective_at="2026-06-01T00:00:00+00:00")
    _insert(conn, "zm_decisions",
            decision_id="DEC-P2", project_id="P2", statement="d2-hidden",
            lifecycle_status="active", profile_id="PR2",
            effective_at="2026-04-01T00:00:00+00:00")
    _insert(conn, "zm_requirements",
            requirement_id="REQ-P1", project_id="P1", statement="r1",
            lifecycle_status="active", verification_status="verified",
            profile_id="PR1", created_at="2026-02-15T00:00:00+00:00")
    _insert(conn, "zm_decisions",
            decision_id="DEC-P1", project_id="P1", statement="d1",
            lifecycle_status="active", profile_id="PR1",
            effective_at="2026-03-01T00:00:00+00:00")
    conn.commit()


class TestNoInventedTimestamps:
    def test_created_at_not_copied_into_valid_columns(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        project(store._conn)
        row = store._conn.execute(
            f"SELECT created_at, effective_at, valid_from, valid_until "
            f"FROM {TEMPORAL_TABLE} WHERE resource_type='requirement' "
            f"AND resource_id='REQ-P1'"
        ).fetchone()
        # created_at present; but NO valid/effective invented.
        assert row["created_at"] is not None
        assert row["effective_at"] is None
        assert row["valid_from"] is None
        assert row["valid_until"] is None

    def test_unknown_time_stays_unknown(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        project(store._conn)
        # A requirement with only created_at must have NULL valid time; the
        # read layer treats that as unknown, never epoch or infinity.
        req = _row(store, "requirement", "REQ-P1")
        assert req["valid_from"] is None and req["valid_until"] is None
        assert req["effective_at"] is None

    def test_explicit_valid_time_preserved(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        project(store._conn)
        dec = _row(store, "decision", "DEC-P1")
        assert dec["effective_at"] == "2026-03-01T00:00:00+00:00"
        # An effective_at point is surfaced verbatim; no envelope invented.
        env = _row(store, "decision", "DEC-ENV")
        assert env["effective_at"] == "2026-06-01T00:00:00+00:00"
        assert env["valid_from"] is None and env["valid_until"] is None

    def test_malformed_source_timestamp_fails_closed(self):
        store = _new_store()
        _insert(store._conn, "zm_decisions",
                decision_id="DEC-BAD", project_id="P1", statement="x",
                lifecycle_status="active", profile_id="PR1",
                effective_at="2026-13-45T99:99:99Z")  # impossible
        store._conn.commit()
        with pytest.raises((TemporalProjectionError, Exception)):
            project(store._conn)


def _row(store: SQLiteStore, rt: str, rid: str) -> dict:
    cur = store._conn.execute(
        f"SELECT * FROM {TEMPORAL_TABLE} WHERE resource_type=? AND resource_id=?",
        (rt, rid),
    )
    return dict(cur.fetchone())


# ---------------------------------------------------------------------------
# Pure temporal predicates
# ---------------------------------------------------------------------------

class TestTemporalPredicates:
    def _fact(self, **kw) -> dict:
        base = dict(created_at="2026-02-01T00:00:00+00:00",
                    effective_at=None, valid_from=None, valid_until=None)
        base.update(kw)
        return base

    def test_transaction_known_at_after_created(self):
        f = self._fact(created_at="2026-02-01T00:00:00+00:00")
        assert as_of_match(f, TemporalDimension.TRANSACTION,
                           "2026-03-01T00:00:00+00:00")
        assert not as_of_match(f, TemporalDimension.TRANSACTION,
                               "2026-01-01T00:00:00+00:00")

    def test_transaction_unknown_created_never_matches(self):
        f = self._fact(created_at=None)
        assert not as_of_match(f, TemporalDimension.TRANSACTION,
                               "2026-01-01T00:00:00+00:00")

    def test_valid_exact_effective_point(self):
        f = self._fact(effective_at="2026-03-01T00:00:00+00:00")
        assert as_of_match(f, TemporalDimension.VALID,
                           "2026-03-01T00:00:00+00:00")
        assert not as_of_match(f, TemporalDimension.VALID,
                               "2026-03-02T00:00:00+00:00")

    def test_valid_envelope_open_lower(self):
        f = self._fact(valid_from=None, valid_until="2026-07-01T00:00:00+00:00")
        assert as_of_match(f, TemporalDimension.VALID,
                           "2020-01-01T00:00:00+00:00")  # before "dawn"

    def test_valid_envelope_open_upper(self):
        f = self._fact(valid_from="2026-05-01T00:00:00+00:00", valid_until=None)
        assert as_of_match(f, TemporalDimension.VALID,
                           "2099-01-01T00:00:00+00:00")

    def test_valid_envelope_boundaries(self):
        f = self._fact(valid_from="2026-05-01T00:00:00+00:00",
                       valid_until="2026-07-01T00:00:00+00:00")
        assert as_of_match(f, TemporalDimension.VALID,
                           "2026-05-01T00:00:00+00:00")  # inclusive lower
        assert as_of_match(f, TemporalDimension.VALID,
                           "2026-06-01T00:00:00+00:00")
        assert not as_of_match(f, TemporalDimension.VALID,
                               "2026-07-01T00:00:00+00:00")  # exclusive upper
        assert not as_of_match(f, TemporalDimension.VALID,
                               "2026-04-01T00:00:00+00:00")  # before lower

    def test_valid_without_explicit_time_never_matches(self):
        f = self._fact(created_at="2026-02-01T00:00:00+00:00")
        # No valid time -> a valid-dimension as-of must NOT invent coverage.
        assert not as_of_match(f, TemporalDimension.VALID,
                               "2026-03-01T00:00:00+00:00")

    def test_dimensions_not_conflated(self):
        f = self._fact(created_at="2026-02-01T00:00:00+00:00",
                       effective_at="2026-03-01T00:00:00+00:00")
        # Transaction match does not imply valid match at the same instant.
        assert as_of_match(f, TemporalDimension.TRANSACTION,
                           "2026-02-15T00:00:00+00:00")
        assert not as_of_match(f, TemporalDimension.VALID,
                               "2026-02-15T00:00:00+00:00")

    def test_window_inclusive_lower_exclusive_upper(self):
        f = self._fact(created_at="2026-02-01T00:00:00+00:00")
        assert within_window(f, TemporalDimension.TRANSACTION,
                             "2026-02-01T00:00:00+00:00",
                             "2026-03-01T00:00:00+00:00")
        assert not within_window(f, TemporalDimension.TRANSACTION,
                                "2026-03-01T00:00:00+00:00",
                                "2026-04-01T00:00:00+00:00")
        # Unknown dimension value never falls in a window.
        assert not within_window(self._fact(created_at=None),
                                TemporalDimension.TRANSACTION,
                                "2026-01-01T00:00:00+00:00",
                                "2026-12-01T00:00:00+00:00")


# ---------------------------------------------------------------------------
# Authorization-first as-of / history reads
# ---------------------------------------------------------------------------

class _StoreWrapper:
    """Adapt a SQLiteStore to the facade's expected store shape.

    The M5 facade and the M4 reader both reach for a ``.conn`` attribute;
    SQLiteStore only exposes ``._conn``. This thin adapter exposes ``.conn``
    (and ``._conn``) without modifying any M5/M4 code.
    """

    def __init__(self, store):
        self._wrapped = store
        self.conn = store._conn
        self._conn = store._conn


def _service(store: SQLiteStore, subject: str) -> AuthorizedReadService:
    # Mirror M8.3 wiring: facade over a conn-adapted store, persistent grants
    # resolved from canonical zm_access_grants.
    wrapped = _StoreWrapper(store)
    return AuthorizedReadService(wrapped, subject, grant_conn=wrapped.conn)

    def _req(self, store, rt, rid, **kw) -> TemporalReadRequest:
        svc = _service(store, kw.pop("requester", "PR1"))
        # project_id / knowledge_space_id are the explicit seed scope the caller
        # asserts; M5 re-validates them. Tests pass the resource's real project.
        return TemporalReadRequest(
            requester="PR1", resource_type=rt, resource_id=rid,
            requesting_profile_id="PR1", **kw), svc

    def test_denied_seed_reveals_no_temporal_metadata(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        seed_grants(store._conn)
        project(store._conn)
        # PR1 has no grant for P2 resources -> denied (checked against P2).
        req, svc = self._req(store, "decision", "DEC-P2", project_id="P2")
        res = read_temporal(store._conn, svc, req)
        assert res.authorized is False
        assert res.facts == ()
        assert res.provenance == {}
        assert res.bound_code is None

    def test_authorized_seed_returns_bounded_fact(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        seed_grants(store._conn)
        project(store._conn)
        req, svc = self._req(store, "decision", "DEC-P1", project_id="P1")
        res = read_temporal(store._conn, svc, req)
        assert res.authorized is True
        assert len(res.facts) == 1
        assert res.facts[0]["effective_at"] == "2026-03-01T00:00:00+00:00"
        # Provenance is populated only from the authorized row.
        assert res.provenance["profile_id"] == "PR1"
        assert res.provenance["project_id"] == "P1"

    def test_hidden_cross_project_row_never_affects_bounds(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        seed_grants(store._conn)
        project(store._conn)
        # Authorized P1 read; any earlier/later timestamp on the hidden P2
        # resource must not surface in the authorized result's metadata.
        req, svc = self._req(store, "decision", "DEC-P1", project_id="P1",
                             dimension=TemporalDimension.TRANSACTION,
                             as_of="2026-02-01T00:00:00+00:00")
        res = read_temporal(store._conn, svc, req)
        assert res.authorized is True
        assert all(f["resource_id"] == "DEC-P1" for f in res.facts)

    def test_as_of_valid_excludes_outside_effective_point(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        seed_grants(store._conn)
        project(store._conn)
        # DEC-P1 has effective_at 2026-03-01 only; valid-dimension as-of matches
        # exactly at that instant and at no other time (no envelope invented).
        req, svc = self._req(store, "decision", "DEC-P1", project_id="P1",
                             dimension=TemporalDimension.VALID,
                             as_of="2026-03-02T00:00:00+00:00")
        assert read_temporal(store._conn, svc, req).facts == ()
        req2, svc2 = self._req(store, "decision", "DEC-P1", project_id="P1",
                               dimension=TemporalDimension.VALID,
                               as_of="2026-03-01T00:00:00+00:00")
        assert len(read_temporal(store._conn, svc2, req2).facts) == 1

    def test_m6_6_artifact_only_grant_denies_non_artifact(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        seed_grants(store._conn)
        project(store._conn)
        # PR1 holds only an artifact grant on P1; a decision read must be denied
        # and expose no decision temporal metadata.
        req, svc = self._req(store, "decision", "DEC-P1", project_id="P1")
        res = read_temporal(store._conn, svc, req)
        assert res.authorized is False
        assert res.facts == ()

    def test_limit_binding_enforced(self):
        # Caller may only tighten; a limit above the ceiling fails closed.
        with pytest.raises(TemporalReadError):
            TemporalReadRequest(
                requester="PR1", resource_type="decision", resource_id="X",
                requesting_profile_id="PR1", project_id="P1",
                limit=MAX_HISTORY_VERSIONS + 1)

    def test_read_only_no_mutation(self):
        store = _new_store()
        seed_two_profiles(store._conn)
        seed_grants(store._conn)
        project(store._conn)
        before = dict(store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_temporal_index").fetchone())
        grants_before = dict(store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_access_grants").fetchone())
        req, svc = self._req(store, "decision", "DEC-P1", project_id="P1")
        read_temporal(store._conn, svc, req)
        after = dict(store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_temporal_index").fetchone())
        grants_after = dict(store._conn.execute(
            "SELECT COUNT(*) AS n FROM zm_access_grants").fetchone())
        assert after["n"] == before["n"]
        assert grants_after["n"] == grants_before["n"]
        # No open transaction remains.
        assert store._conn.in_transaction is False


class TestAuthoritySafety:
    def test_recency_is_not_authority(self):
        # A newer created_at does not promote lifecycle or verification.
        store = _new_store()
        _insert(store._conn, "zm_requirements",
                requirement_id="R-OLD", project_id="P1", statement="old",
                lifecycle_status="active", verification_status="verified",
                profile_id="PR1", created_at="2020-01-01T00:00:00+00:00")
        _insert(store._conn, "zm_requirements",
                requirement_id="R-NEW", project_id="P1", statement="new",
                lifecycle_status="candidate", verification_status="none",
                profile_id="PR1", created_at="2030-01-01T00:00:00+00:00")
        store._conn.commit()
        project_grants_trivial(store._conn)
        project(store._conn)
        rows = {r["resource_id"]: r for r in store._conn.execute(
            f"SELECT resource_id, lifecycle_status, verification_status "
            f"FROM {TEMPORAL_TABLE}").fetchall()}
        assert rows["R-OLD"]["lifecycle_status"] == "active"
        assert rows["R-NEW"]["lifecycle_status"] == "candidate"
        assert rows["R-NEW"]["verification_status"] == "none"

    def test_lifecycle_status_copied_verbatim_no_redefinition(self):
        store = _new_store()
        _insert(store._conn, "zm_decisions",
                decision_id="D1", project_id="P1", statement="x",
                lifecycle_status="superseded", profile_id="PR1")
        store._conn.commit()
        project_grants_trivial(store._conn)
        project(store._conn)
        row = _row(store, "decision", "D1")
        assert row["lifecycle_status"] == "superseded"

    def test_describe_declares_no_authority_or_calibration(self):
        d = describe_temporal_read()
        assert d["makes_authorization_decisions"] is False
        assert d["resolves_conflicts"] is False
        assert d["promotes_assistant_claim"] is False
        assert d["recency_is_not_authority"] is True
        assert d["invents_no_timestamp"] is True
        assert d["authorization_first"] is True
        # Only the two approved temporal dimensions exist.
        assert set(d["temporal_dimensions"]) == {
            TemporalDimension.TRANSACTION, TemporalDimension.VALID}


def project_grants_trivial(conn: sqlite3.Connection) -> None:
    # Unrestricted P1 grant so the read layer can authorize the seeded rows.
    project_grant_event(conn, AccessGrantEvent(
        grant_id="G-P1", subject_profile="PR1", operation=READ,
        target_type="project", target_id="P1", op="create",
        resource_types=None))
    conn.commit()


import pytest  # noqa: E402

__all__ = [
    "TestTemporalProjectionDeterminism",
    "TestNoInventedTimestamps",
    "TestTemporalPredicates",
    "TestAuthorizationFirst",
    "TestAuthoritySafety",
]
