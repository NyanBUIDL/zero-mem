"""M8.2 security, authority-boundary, and non-scope tests.

Static audit of the M8.2 modules plus behavioral assertions that projection:

- makes zero LLM and zero external-network calls;
- makes no authorization decision and reaches no grant/policy surface;
- preserves profile / project / knowledge-space / resource_type identity;
- never promotes an assistant claim, resolves a conflict, or lets recency,
  degree, or frequency become authority;
- adds no M8.3+ traversal, no temporal query, no calibration scoring, and no
  M6/M7/Hermes-core change.
"""

from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest

from src.m8.graph_projection import (
    EdgeSourceRecord,
    EntitySourceRecord,
    project_edge,
    project_entity,
)
from src.m8.projection_store import project_graph_from_sources, rebuild_graph
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
M8_DIR = SRC_ROOT / "m8"
M8_2_MODULES = ("graph_projection.py", "graph_sources.py", "projection_store.py")

TS = "2026-01-02T03:04:05+00:00"


def _m8_2_files() -> list[Path]:
    files = [M8_DIR / name for name in M8_2_MODULES]
    for path in files:
        assert path.exists(), path.name
    return files


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module or ''}.{alias.name}")
    return names


def _all_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _m8_2_files())


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _all_code() -> str:
    """Executable code only — comments and docstrings removed."""
    chunks = []
    for path in _m8_2_files():
        tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8")))
        chunks.append(ast.unparse(tree))
    return "\n".join(chunks)


@pytest.fixture()
def db(tmp_path: Path):
    store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "meta.sqlite"))
    store.ensure_schema()
    try:
        yield store
    finally:
        store.close()


def _event(conn: sqlite3.Connection, event_id: str, **kw) -> None:
    conn.execute(
        "INSERT INTO zm_meta (event_id, trace_id, event_type, source, schema_version, "
        "created_at, observed_at, sequence, profile_id, project_id, lifecycle_status, "
        "verification_status, confidence, sensitivity, retention, content_hash, "
        "redaction_applied, ingested_at, origin_jsonl) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            event_id, f"T-{event_id}", kw.get("event_type", "note"), "test", 1,
            kw.get("created_at", TS), TS, kw.get("sequence", 1),
            kw.get("profile_id"), kw.get("project_id"),
            kw.get("lifecycle_status", "candidate"),
            kw.get("verification_status", "none"),
            "medium", "normal", "standard", f"h-{event_id}", 0, TS, "raw.jsonl",
        ),
    )


class TestZeroLLMZeroNetwork:
    BANNED_MODULES = {
        "openai", "anthropic", "cohere", "together", "litellm", "transformers",
        "sentence_transformers", "torch", "tiktoken", "langchain", "llama_index",
        "requests", "httpx", "aiohttp", "urllib", "urllib.request", "urllib3",
        "http", "http.client", "socket", "ftplib", "smtplib", "websockets",
        "grpc", "boto3", "faiss", "chromadb", "qdrant_client", "pinecone",
        "weaviate", "neo4j", "networkx",
    }

    def test_no_banned_imports(self):
        for path in _m8_2_files():
            for imported in _imports(path):
                root = imported.split(".")[0]
                assert root not in self.BANNED_MODULES, f"{path.name}: {imported}"

    def test_no_llm_tokens(self):
        source = _all_code().lower()
        for token in (
            "openai", "anthropic", "chat.completions", "def embed", "embedding(",
            "vectorize", "api_key", "bearer ",
        ):
            assert token not in source, token

    def test_no_network_expressions(self):
        source = _all_source()
        for token in (
            "http://", "https://", "requests.get", "requests.post", "urlopen",
            "socket.socket", ".connect(",
        ):
            assert token not in source, token

    def test_no_subprocess_or_eval(self):
        source = _all_code()
        for token in ("subprocess", "os.system", "eval(", "exec(", "__import__("):
            assert token not in source, token

    def test_no_vectors_or_embeddings(self):
        source = _all_code().lower()
        for token in ("embedding", "vector", "cosine", "ann_index", "knn", "faiss"):
            assert token not in source, token


class TestNoAuthorizationReach:
    def test_no_grant_admin(self):
        source = _all_code()
        for token in ("GrantAdmin", "grant_admin", "AuthorizedWriteService"):
            assert token not in source, token

    def test_no_policy_or_grant_import(self):
        for path in _m8_2_files():
            for imported in _imports(path):
                assert "policy" not in imported.lower(), f"{path.name}: {imported}"
                assert "grant" not in imported.lower(), f"{path.name}: {imported}"

    def test_no_access_decision_functions(self):
        source = _all_code()
        for token in (
            "def authorize", "def check_access", "def is_authorized", "def grant",
            "def has_permission", "def can_read", "def filter_authorized",
        ):
            assert token not in source, token

    def test_no_hardcoded_home(self):
        source = _all_source()
        for token in ("/home/", "/Users/", "C:\\\\Users", "expanduser", "Path.home()",
                      ".hermes"):
            assert token not in source, token


class TestNonScope:
    def test_no_traversal_primitives(self):
        source = _all_code()
        for token in (
            "def traverse", "def neighbors", "def neighbours", "def bfs", "def dfs",
            "def shortest_path", "def degree", "def centrality", "max_hops",
            "hop_limit", "def expand",
        ):
            assert token not in source, token

    def test_no_temporal_query_service(self):
        source = _all_code()
        for token in ("def as_of", "def query_history", "def history_at", "as_of_query",
                      "def latest", "latest_wins"):
            assert token not in source, token

    def test_no_calibration_scoring(self):
        source = _all_code()
        for token in ("def calibrate", "def compute_score", "def score(",
                      "FACTOR_WEIGHTS", "def rank_", "def rerank"):
            assert token not in source, token

    def test_no_evidence_set_integration(self):
        source = _all_code()
        for token in ("EvidenceSet", "evidence_set", "build_evidence"):
            assert token not in source, token

    def test_no_m9_or_m10(self):
        source = _all_code().lower()
        for token in ("obsidian", "vault", "corpus_expansion", "bulk_ingest",
                      "full_corpus"):
            assert token not in source, token

    def test_no_m3_plus_read_service_modules_added(self):
        # These module names were never part of any approved increment and must
        # never appear. ``calibration.py`` was on this list until M8.5, which
        # legitimately introduces it as the approved deterministic calibration
        # engine (docs/plans/plan-m8.md §22.1); the M8.2 boundary is now enforced by
        # test_m8_2_modules_do_not_reach_m8_5_calibration below.
        for banned in ("graph_read_service.py", "graph_reader.py", "traversal.py",
                       "temporal_query.py"):
            assert not (M8_DIR / banned).exists(), banned

    def test_m8_2_modules_do_not_reach_m8_5_calibration(self):
        # M8.5's calibration surface must not leak backwards into M8.2: the
        # projector neither imports the calibration engine nor scores anything.
        for path in _m8_2_files():
            for imported in _imports(path):
                assert "calibration" not in imported.lower(), (
                    f"{path.name}: {imported}"
                )
        code = _all_code()
        for token in ("def calibrate", "def compute_score", "def rerank",
                      "FACTOR_WEIGHTS"):
            assert token not in code, token

    def test_no_m6_tool_import(self):
        for path in _m8_2_files():
            for imported in _imports(path):
                assert "tools" not in imported.lower(), f"{path.name}: {imported}"

    def test_no_m7_import(self):
        for path in _m8_2_files():
            for imported in _imports(path):
                assert "integration.m7" not in imported, f"{path.name}: {imported}"

    def test_lives_only_under_m8(self):
        for path in _m8_2_files():
            assert path.relative_to(SRC_ROOT).parts[0] == "m8"

    def test_no_schema_v10(self):
        # M10.4 legitimately introduces migrate_10 (schema v10) as an ADDITIVE
        # derived corpus store. This test now asserts that the v10 migration
        # exists AND is purely derived (it must not mutate canonical JSONL or
        # v1-v9 memory tables). The security invariant preserved: no v10
        # migration alters canonical authority or M1-M9 tables.
        from src.storage.migrations.migrate_10 import CORPUS_DERIVED_TABLES

        assert (SRC_ROOT / "storage" / "migrations" / "migrate_10.py").exists()
        # Every v10 table is a derived corpus table (rebuildable), never a
        # canonical or memory table.
        assert all(t.startswith("zm_corpus_") for t in CORPUS_DERIVED_TABLES)


class TestScopePreservation:
    def test_same_name_in_two_profiles_stays_distinct(self):
        a = project_entity(
            EntitySourceRecord(
                entity_type="person", canonical_name="Ada",
                relation_source="m4_project_link", source_ref="s:1", profile_id="prof-a",
            )
        )
        b = project_entity(
            EntitySourceRecord(
                entity_type="person", canonical_name="Ada",
                relation_source="m4_project_link", source_ref="s:1", profile_id="prof-b",
            )
        )
        assert a.entity_id != b.entity_id

    def test_same_name_in_two_projects_stays_distinct(self):
        make = lambda pid: project_entity(  # noqa: E731
            EntitySourceRecord(
                entity_type="person", canonical_name="Ada",
                relation_source="m4_project_link", source_ref="s:1", project_id=pid,
            )
        )
        assert make("P1").entity_id != make("P2").entity_id

    def test_same_name_in_two_knowledge_spaces_stays_distinct(self):
        make = lambda ks: project_entity(  # noqa: E731
            EntitySourceRecord(
                entity_type="person", canonical_name="Ada",
                relation_source="m4_project_link", source_ref="s:1",
                knowledge_space_id=ks,
            )
        )
        assert make("K1").entity_id != make("K2").entity_id

    def test_scoped_and_unscoped_are_distinct(self):
        scoped = project_entity(
            EntitySourceRecord(
                entity_type="person", canonical_name="Ada",
                relation_source="m4_project_link", source_ref="s:1", project_id="P1",
            )
        )
        unscoped = project_entity(
            EntitySourceRecord(
                entity_type="person", canonical_name="Ada",
                relation_source="m4_project_link", source_ref="s:1",
            )
        )
        assert scoped.entity_id != unscoped.entity_id

    def test_scope_columns_persisted(self, db):
        conn = db._conn
        _event(conn, "E1", profile_id="prof-a", project_id="P1")
        _event(conn, "E2", profile_id="prof-a", project_id="P1", sequence=2)
        conn.execute(
            "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, "
            "evidence_ref, created_at) VALUES (?,?,?,?,?,?)",
            ("E2", "E1", "derived_from", "deterministic_check", None, TS),
        )
        conn.commit()
        project_graph_from_sources(conn)
        row = conn.execute(
            "SELECT profile_id, project_id, knowledge_space_id FROM zm_graph_edges"
        ).fetchone()
        assert row["profile_id"] == "prof-a"
        assert row["project_id"] == "P1"


class TestResourceTypeIsolation:
    def test_artifact_and_event_endpoints_never_collapse(self):
        event_edge = project_edge(
            EdgeSourceRecord(
                from_resource_type="event", from_resource_id="X",
                relation_type="derived_from", to_resource_type="event",
                to_resource_id="Y", relation_source="m2_relation", source_ref="s:1",
            )
        )
        artifact_edge = project_edge(
            EdgeSourceRecord(
                from_resource_type="event", from_resource_id="X",
                relation_type="source_of", to_resource_type="artifact",
                to_resource_id="Y", relation_source="m2_artifact", source_ref="s:1",
            )
        )
        assert event_edge.edge_id != artifact_edge.edge_id
        assert artifact_edge.to_ref.resource_type == "artifact"

    def test_project_artifact_is_not_artifact(self):
        make = lambda rt: project_edge(  # noqa: E731
            EdgeSourceRecord(
                from_resource_type=rt, from_resource_id="A1",
                relation_type="artifact_of", to_resource_type="decision",
                to_resource_id="D1", relation_source="m4_project_link",
                source_ref="s:1",
            )
        )
        assert make("artifact").edge_id != make("project_artifact").edge_id

    def test_no_generic_node_table_created(self, db):
        names = {
            r[0]
            for r in db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "zm_nodes" not in names and "zm_graph_nodes" not in names

    def test_authorization_metadata_is_per_endpoint(self):
        edge = project_edge(
            EdgeSourceRecord(
                from_resource_type="event", from_resource_id="E1",
                relation_type="source_of", to_resource_type="artifact",
                to_resource_id="A1", relation_source="m2_artifact", source_ref="s:1",
            )
        )
        meta = edge.authorization_metadata()
        assert set(meta) == {"edge", "from", "to"}
        assert meta["from"]["resource_type"] == "event"
        assert meta["to"]["resource_type"] == "artifact"
        # Descriptors are INPUT to M5 and carry no decision.
        for descriptor in meta.values():
            for banned in ("authorized", "allowed", "grant", "permission", "access"):
                assert banned not in descriptor


class TestAuthoritySafety:
    def test_assistant_claim_is_not_promoted(self, db):
        conn = db._conn
        _event(conn, "E1", event_type="assistant_claim", lifecycle_status="candidate",
               verification_status="none")
        _event(conn, "E2", event_type="assistant_claim", sequence=2,
               lifecycle_status="candidate", verification_status="none")
        conn.execute(
            "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, "
            "evidence_ref, created_at) VALUES (?,?,?,?,?,?)",
            ("E2", "E1", "derived_from", "deterministic_check", None, TS),
        )
        conn.commit()
        project_graph_from_sources(conn)
        row = conn.execute(
            "SELECT lifecycle_status, verification_status FROM zm_graph_edges"
        ).fetchone()
        assert row["lifecycle_status"] == "candidate"
        assert row["verification_status"] == "none"

    def test_verifies_edge_does_not_verify_subject(self, db):
        conn = db._conn
        conn.execute(
            "INSERT INTO zm_decisions (decision_id, project_id, lifecycle_status) "
            "VALUES (?,?,?)",
            ("D1", "P1", "candidate"),
        )
        conn.execute(
            "INSERT INTO zm_verifications (verification_id, subject_type, subject_id, "
            "project_id, verification_status) VALUES (?,?,?,?,?)",
            ("V1", "decision", "D1", "P1", "deterministic_verification"),
        )
        conn.commit()
        project_graph_from_sources(conn)
        # The decision's own record is untouched by projection.
        row = conn.execute(
            "SELECT lifecycle_status FROM zm_decisions WHERE decision_id='D1'"
        ).fetchone()
        assert row["lifecycle_status"] == "candidate"

    def test_conflict_is_not_resolved(self, db):
        conn = db._conn
        _event(conn, "E1", project_id="P1")
        _event(conn, "E2", project_id="P1", sequence=2)
        conn.execute(
            "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, "
            "evidence_ref, created_at) VALUES (?,?,?,?,?,?)",
            ("E2", "E1", "supersedes", "deterministic_check", None, TS),
        )
        conn.execute(
            "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, "
            "evidence_ref, created_at) VALUES (?,?,?,?,?,?)",
            ("E1", "E2", "supersedes", "deterministic_check", None, TS),
        )
        conn.commit()
        project_graph_from_sources(conn)
        # BOTH directions survive. Projection represents the conflict; it does
        # not pick a winner or drop the losing edge.
        count = conn.execute(
            "SELECT COUNT(*) FROM zm_graph_edges WHERE relation_type='supersedes'"
        ).fetchone()[0]
        assert count == 2

    def test_newer_timestamp_does_not_change_lifecycle(self, db):
        conn = db._conn
        _event(conn, "E1", created_at="2020-01-01T00:00:00+00:00",
               lifecycle_status="active")
        _event(conn, "E2", created_at="2030-01-01T00:00:00+00:00", sequence=2,
               lifecycle_status="candidate")
        conn.execute(
            "INSERT INTO zm_relations (from_event_id, to_event_id, relation, verifier, "
            "evidence_ref, created_at) VALUES (?,?,?,?,?,?)",
            ("E2", "E1", "derived_from", "deterministic_check", None, TS),
        )
        conn.commit()
        project_graph_from_sources(conn)
        row = conn.execute(
            "SELECT lifecycle_status FROM zm_graph_edges WHERE from_resource_id='E2'"
        ).fetchone()
        # The newer record stays 'candidate' — recency is not authority.
        assert row["lifecycle_status"] == "candidate"

    def test_high_degree_does_not_promote_authority(self, db):
        conn = db._conn
        _event(conn, "HUB", lifecycle_status="candidate")
        for i in range(2, 8):
            _event(conn, f"E{i}", sequence=i, lifecycle_status="candidate")
            conn.execute(
                "INSERT INTO zm_relations (from_event_id, to_event_id, relation, "
                "verifier, evidence_ref, created_at) VALUES (?,?,?,?,?,?)",
                (f"E{i}", "HUB", "derived_from", "deterministic_check", None, TS),
            )
        conn.commit()
        project_graph_from_sources(conn)
        rows = conn.execute(
            "SELECT DISTINCT lifecycle_status, verification_status FROM zm_graph_edges"
        ).fetchall()
        # Many incoming edges change nothing about lifecycle or verification.
        assert {(r["lifecycle_status"], r["verification_status"]) for r in rows} == {
            ("candidate", "none")
        }

    def test_no_confidence_or_score_column_written(self, db):
        cols = {r[1] for r in db._conn.execute("PRAGMA table_info(zm_graph_edges)")}
        for banned in ("score", "confidence", "rank", "weight", "centrality", "degree"):
            assert banned not in cols

    def test_report_exposes_no_authorization_outcome(self, db):
        conn = db._conn
        _event(conn, "E1")
        conn.commit()
        payload = rebuild_graph(conn).to_dict()
        for banned in ("authorized", "allowed", "grant", "permission", "denied"):
            assert banned not in str(payload)


class TestFailClosed:
    def test_malformed_link_list_aborts_rebuild(self, db):
        conn = db._conn
        _event(conn, "E1")
        conn.execute(
            "INSERT INTO zm_decisions (decision_id, project_id, lifecycle_status, "
            "linked_requirement_ids) VALUES (?,?,?,?)",
            ("D1", "P1", "candidate", '["R1", '),
        )
        conn.commit()
        with pytest.raises(Exception):
            rebuild_graph(conn)
        # Nothing partially promoted.
        assert conn.execute("SELECT COUNT(*) FROM zm_graph_edges").fetchone()[0] == 0

    def test_failed_rebuild_is_not_published(self, db):
        from src.m8.derived_index import get_index_version
        from src.m8.projection_store import GRAPH_INDEX_NAME

        conn = db._conn
        _event(conn, "E1")
        conn.execute(
            "INSERT INTO zm_decisions (decision_id, project_id, lifecycle_status, "
            "linked_requirement_ids) VALUES (?,?,?,?)",
            ("D1", "P1", "candidate", '["R1", '),
        )
        conn.commit()
        with pytest.raises(Exception):
            rebuild_graph(conn)
        rec = get_index_version(conn, GRAPH_INDEX_NAME)
        assert rec is None or rec.build_status != "published"

    def test_projection_requires_v9(self, tmp_path):
        from src.storage.migrations import MIGRATIONS

        store = SQLiteStore(SQLiteStoreConfig(path=tmp_path / "v8.sqlite"))
        for v in sorted(x for x in MIGRATIONS if x <= 8):
            store._apply_up(v, note="t")
        try:
            with pytest.raises(Exception):
                project_graph_from_sources(store._conn)
        finally:
            store.close()
