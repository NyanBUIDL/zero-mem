"""Shared fixtures for M8.3 authorization-first bounded graph read tests.

Builds a v9 store containing:

* M4 project-memory resources (artifact / decision / requirement / verification)
  for two profiles (PR1 own, PR2 other) and two projects (P1, P2).
* M5 persistent READ grants (so authorization is genuinely M5-evaluated, not
  faked): PR1 owns P1 (unrestricted); an artifact-only project grant for P1;
  a requirement grant for P2 (cross-project, via grant).
* A v9 derived graph (zm_graph_edges) exercising authorized and hidden paths.

Hidden-path construction (authorization-first guarantee):
    A (PR1/P1 artifact, authorized)
      -> B (PR2/P2 decision, NOT authorized for PR1)
      -> C (PR1/P1 requirement, authorized)
So M8.3 must NOT reveal B, nor that A and C are connected through B, nor any
degree/count influenced by B.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from src.access import authorized_read  # noqa: E402
from src.access import resolver  # noqa: E402
from src.access.grant_events import AccessGrantEvent, project_grant_event  # noqa: E402
from src.access.contracts import READ  # noqa: E402
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig  # noqa: E402


# --- low-level builders ----------------------------------------------------

_STORES: list = []


def _new_store():
    # Build a real file-backed SQLiteStore so the full M3/M4/M5 facade (which
    # expects a store object with ._conn) works end to end; the derived graph
    # and grants live on the same connection.
    d = Path(tempfile.mkdtemp(prefix="m8_3_")).resolve()
    cfg = SQLiteStoreConfig(path=Path(d) / "meta.sqlite")
    store = SQLiteStore(cfg)
    store.ensure_schema()  # applies migrate_4/7/8/9 in order
    _STORES.append(store)
    return store


def _insert(conn: sqlite3.Connection, table: str, **cols: Any) -> None:
    keys = list(cols.keys())
    ph = ",".join("?" for _ in keys)
    conn.execute(
        f"INSERT INTO {table} ({','.join(keys)}) VALUES ({ph})",
        [cols[k] for k in keys],
    )


def seed_resources(conn: sqlite3.Connection) -> None:
    # Authorized PR1 / P1 resources.
    _insert(conn, "zm_artifacts",
            artifact_id="ART-A", content_hash="hA", kind="doc",
            retention="365d", origin_event_id="E-A", stored_path="/x/A",
            created_at="2026-01-01T00:00:00+00:00")
    _insert(conn, "zm_project_artifacts",
            artifact_id="ART-A", project_id="P1", artifact_type="doc",
            version="1", safe_reference="refA",
            created_at="2026-01-01T00:00:00+00:00",
            verification_status="verified")
    _insert(conn, "zm_requirements",
            requirement_id="REQ-C", project_id="P1", statement="C",
            created_at="2026-01-01T00:00:00+00:00",
            lifecycle_status="active", verification_status="verified",
            trace_id="T-C", profile_id="PR1")
    _insert(conn, "zm_decisions",
            decision_id="DEC-D", project_id="P1", statement="D",
            lifecycle_status="active", trace_id="T-D", profile_id="PR1",
            linked_requirement_ids='["REQ-C"]')
    _insert(conn, "zm_verifications",
            verification_id="VER-V", subject_type="requirement",
            subject_id="REQ-C", project_id="P1", method="test",
            verification_status="verified", source_event_id="E-V",
            timestamp="2026-01-01T00:00:00+00:00")
    # A second authorized artifact (for fan-out / density tests).
    _insert(conn, "zm_artifacts",
            artifact_id="ART-A2", content_hash="hA2", kind="doc",
            retention="365d", origin_event_id="E-A2", stored_path="/x/A2",
            created_at="2026-01-01T00:00:00+00:00")
    _insert(conn, "zm_project_artifacts",
            artifact_id="ART-A2", project_id="P1", artifact_type="doc",
            version="1", safe_reference="refA2",
            created_at="2026-01-01T00:00:00+00:00",
            verification_status="verified")

    # Hidden PR2 / P2 resource (NOT authorized for PR1).
    _insert(conn, "zm_decisions",
            decision_id="DEC-B", project_id="P2", statement="B-hidden",
            lifecycle_status="active", trace_id="T-B", profile_id="PR2")

    # An isolated authorized PR1/P1 requirement, no edges (degree isolation).
    _insert(conn, "zm_requirements",
            requirement_id="REQ-ISO", project_id="P1", statement="iso",
            created_at="2026-01-01T00:00:00+00:00",
            lifecycle_status="active", verification_status="verified",
            trace_id="T-ISO", profile_id="PR1")


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
    # PR1 cross-project requirement grant on P2 (so a P2 resource is readable,
    # but only requirement resource_type, and only within P2).
    project_grant_event(conn, AccessGrantEvent(
        grant_id="G-P2", subject_profile="PR1", operation=READ,
        target_type="project", target_id="P2", op="create",
        resource_types=["requirement"]))
    conn.commit()


_EDGE_COLS = (
    "edge_id", "from_resource_type", "from_resource_id", "relation_type",
    "to_resource_type", "to_resource_id", "profile_id", "project_id",
    "relation_source", "source_ref", "projection_version",
    "identity_version", "provenance_hash", "content_hash",
)


def _edge(conn, eid, frt, frid, rel, trt, trid, proj, src="m4_project_link"):
    vals = (eid, frt, frid, rel, trt, trid, "PR1" if proj == "P1" else "PR2",
            proj, src, "r:" + eid, "pv", "iv", "ph", "ch")
    conn.execute(
        f"INSERT INTO zm_graph_edges ({','.join(_EDGE_COLS)}) VALUES ("
        f"{','.join('?' for _ in _EDGE_COLS)})", vals)


def seed_graph(conn: sqlite3.Connection) -> None:
    # Authorized path: ART-A (P1) --source_of--> ART-A2 (P1)
    _edge(conn, "e_aa2", "artifact", "ART-A", "source_of",
          "artifact", "ART-A2", "P1")
    # Hidden middle: ART-A (P1) --decision_for--> DEC-B (P2, NOT authorized)
    _edge(conn, "e_ab", "artifact", "ART-A", "decision_for",
          "decision", "DEC-B", "P2")
    # Hidden continuation: DEC-B (P2) --requirement_for--> REQ-C (P1 authorized)
    _edge(conn, "e_bc", "decision", "DEC-B", "requirement_for",
          "requirement", "REQ-C", "P2")
    # Authorized direct: DEC-D --requirement_for--> REQ-C
    _edge(conn, "e_dc", "decision", "DEC-D", "requirement_for",
          "requirement", "REQ-C", "P1")
    # Extra authorized edge to test degree isolation.
    _edge(conn, "e_a_extra", "artifact", "ART-A", "references",
          "artifact", "ART-A2", "P1")
    conn.commit()


# --- service factory -------------------------------------------------------

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


def make_service(store, subject: str):
    wrapped = _StoreWrapper(store)
    return authorized_read.AuthorizedReadService(
        wrapped, subject, grant_conn=wrapped.conn
    )


def build_fixture():
    store = _new_store()
    seed_resources(store._conn)
    seed_grants(store._conn)
    seed_graph(store._conn)
    return store


__all__ = ["build_fixture", "make_service", "seed_resources",
           "seed_grants", "seed_graph", "READ"]
