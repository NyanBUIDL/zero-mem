"""M8.1 security and non-scope tests.

Static AST/import audit plus behavioral assertions that the M8.1 foundation:

- makes zero LLM and zero external-network calls;
- never reaches GrantAdminService or any write/authorization service;
- preserves resource_type, profile, project, and knowledge-space identity;
- contains no M8.2+/M9/M10 behavior, and no vectors/embeddings;
- hard-codes no user HOME path;
- leaves M6 tools and the M7 EvidenceSet budget untouched.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
M8_DIR = SRC_ROOT / "m8"
M8_MIGRATION = SRC_ROOT / "storage" / "migrations" / "migrate_9.py"


def _m8_files() -> list[Path]:
    files = sorted(M8_DIR.glob("*.py")) + [M8_MIGRATION]
    assert files, "expected M8.1 modules to exist"
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
    return "\n".join(p.read_text(encoding="utf-8") for p in _m8_files())


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
    """Executable code only: comments and docstrings removed.

    Token scans for identifiers must not trip over documentation that merely
    NAMES a forbidden concept while asserting its absence.
    """
    chunks = []
    for path in _m8_files():
        tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8")))
        chunks.append(ast.unparse(tree))
    return "\n".join(chunks)


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
        for path in _m8_files():
            for imported in _imports(path):
                root = imported.split(".")[0]
                assert root not in self.BANNED_MODULES, f"{path.name} imports {imported}"

    def test_no_llm_or_embedding_tokens_in_source(self):
        source = _all_code().lower()
        for token in (
            "openai", "anthropic", "chat.completions", "def embed",
            "embedding(", "vectorize", "api_key", "bearer ",
        ):
            assert token not in source, token

    def test_no_network_call_expressions(self):
        source = _all_source()
        for token in (
            "http://", "https://", "requests.get", "requests.post",
            "urlopen", "socket.socket", ".connect(",
        ):
            assert token not in source, token

    def test_no_subprocess_or_eval(self):
        source = _all_code()
        for token in ("subprocess", "os.system", "eval(", "exec(", "__import__("):
            assert token not in source, token


class TestNoAuthorizationReach:
    def test_no_grant_admin_import(self):
        source = _all_code()
        for token in ("GrantAdmin", "grant_admin"):
            assert token not in source, token

    def test_no_authorized_write_service(self):
        assert "AuthorizedWriteService" not in _all_code()

    def test_no_policy_engine_import(self):
        # M8.1's own freeze must not import src.access.policy. The sanctioned
        # exceptions are M8.3's graph_access.py and M8.4's temporal_read.py:
        # the increments that CONSUME the M5 authorization authority (via the
        # AuthorizedReadService facade) as their sole authorization authority.
        _SANCTIONED_ACCESS_CONSUMERS = {"graph_access.py", "temporal_read.py"}
        for path in _m8_files():
            if path.name in _SANCTIONED_ACCESS_CONSUMERS:
                continue
            for imported in _imports(path):
                assert "policy" not in imported.lower(), f"{path.name}: {imported}"
                assert "grant" not in imported.lower(), f"{path.name}: {imported}"

    def test_no_access_decision_functions(self):
        source = _all_code()
        for token in (
            "def authorize", "def check_access", "def is_authorized",
            "def grant", "def has_permission", "def can_read",
        ):
            assert token not in source, token

    def test_m8_imports_are_local_or_stdlib(self):
        allowed_prefixes = ("src.m8", "src.capture", "src.access", "src.storage", ".")
        stdlib = {
            "__future__", "dataclasses", "typing", "enum", "hashlib", "json",
            "sqlite3", "unicodedata", "datetime", "abc", "collections",
        }
        for path in _m8_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level > 0:
                        continue  # relative intra-package import
                    root = module.split(".")[0]
                    assert module.startswith(allowed_prefixes) or root in stdlib, (
                        f"{path.name} imports {module}"
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        assert root in stdlib or alias.name.startswith("src."), (
                            f"{path.name} imports {alias.name}"
                        )

    def test_access_import_is_contract_only(self):
        # M8.1's own freeze must not import any policy/decision surface from
        # src.access. The sanctioned exceptions are M8.3's graph_access.py and
        # M8.4's temporal_read.py: the increments that CONSUME the M5
        # authorization authority as their sole authorization authority
        # (authorization-first design).
        _SANCTIONED_ACCESS_CONSUMERS = {"graph_access.py", "temporal_read.py"}
        for path in _m8_files():
            if path.name in _SANCTIONED_ACCESS_CONSUMERS:
                continue
            for imported in _imports(path):
                if imported.startswith("src.access"):
                    assert "contracts" in imported, imported


class TestNoHardcodedHome:
    def test_no_hardcoded_home_paths(self):
        source = _all_source()
        for token in ("/home/", "/Users/", "C:\\\\Users", "os.path.expanduser", "Path.home()"):
            assert token not in source, token

    def test_no_hermes_home_reference(self):
        assert ".hermes" not in _all_source()


class TestIdentityPreservation:
    def test_resource_type_columns_exist_on_both_endpoints(self):
        sql = M8_MIGRATION.read_text(encoding="utf-8")
        assert "from_resource_type" in sql
        assert "to_resource_type" in sql

    def test_scope_columns_on_every_derived_table(self):
        from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteStore(SQLiteStoreConfig(path=Path(tmp) / "m.sqlite"))
            store.ensure_schema()
            try:
                for table in ("zm_entities", "zm_graph_edges",
                              "zm_entity_mentions", "zm_temporal_index"):
                    cols = {
                        r[1] for r in store._conn.execute(f"PRAGMA table_info({table})")
                    }
                    assert {"profile_id", "project_id", "knowledge_space_id"} <= cols, table
            finally:
                store.close()

    def test_no_generic_node_table(self):
        sql = M8_MIGRATION.read_text(encoding="utf-8")
        for banned in ("CREATE TABLE zm_nodes", "CREATE TABLE zm_graph_nodes"):
            assert banned not in sql

    def test_no_cross_profile_or_cross_project_flattening(self):
        source = _all_code()
        for token in (
            "profile_id = '*'", "project_id = '*'", "DROP COLUMN profile_id",
            "ignore_profile", "flatten_scope", "all_profiles", "any_project",
        ):
            assert token not in source, token


class TestNonScope:
    def test_no_m8_3_read_service(self):
        for banned in ("graph_read_service.py", "graph_reader.py", "traversal.py"):
            assert not (M8_DIR / banned).exists(), banned

    def test_no_m8_4_temporal_query_outside_m8_4(self):
        # The temporal as-of / history query vocabulary (def as_of / query_history
        # / history_at / as_of_query) is EXPECTED in M8.4's own modules
        # (temporal_read.py, temporal_projection.py). It must NOT appear in any
        # earlier M8 module, which would mean M8.4's temporal surface leaked
        # backwards into M8.1/M8.2/M8.3.
        _M8_4_MODULES = {"temporal_read.py", "temporal_projection.py"}
        for path in _m8_files():
            if path.name in _M8_4_MODULES:
                continue
            source = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8")))
            code = ast.unparse(source)
            for token in ("def as_of", "def query_history", "def history_at", "as_of_query"):
                assert token not in code, f"{path.name}: {token}"

    def test_no_m8_5_calibration_scoring_outside_m8_5(self):
        # The calibration scoring vocabulary (def calibrate / compute_score /
        # rank_ / rerank / FACTOR_WEIGHTS) is EXPECTED in M8.5's own modules
        # (calibration.py, retrieval_metadata.py). It must NOT appear in any
        # earlier M8 module, which would mean M8.5's scoring surface leaked
        # backwards into M8.1/M8.2/M8.3/M8.4. FACTOR_WEIGHTS stays banned
        # everywhere: the approved M8.5 formula is a multiplicative product
        # with NO independent weights (plan-m8.md §22.1.2).
        _M8_5_MODULES = {"calibration.py", "retrieval_metadata.py"}
        for path in _m8_files():
            source = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8")))
            code = ast.unparse(source)
            assert "FACTOR_WEIGHTS" not in code, f"{path.name}: FACTOR_WEIGHTS"
            if path.name in _M8_5_MODULES:
                continue
            for token in (
                "def calibrate", "def compute_score", "def score(",
                "def rank_", "def rerank",
            ):
                assert token not in code, f"{path.name}: {token}"

    def test_no_m8_6_evidence_integration(self):
        source = _all_code()
        for token in ("EvidenceSet", "evidence_set", "build_evidence"):
            assert token not in source, token

    def test_no_traversal_primitives(self):
        source = _all_code()
        for token in (
            "def traverse", "def neighbors", "def neighbours", "def bfs",
            "def dfs", "def shortest_path", "def degree", "def centrality",
            "max_hops", "hop_limit",
        ):
            assert token not in source, token

    def test_no_m9_obsidian(self):
        source = _all_code().lower()
        for token in ("obsidian", "vault", "markdown_projection"):
            assert token not in source, token

    def test_no_m10_corpus_expansion(self):
        source = _all_code().lower()
        for token in ("corpus_expansion", "bulk_ingest", "full_corpus"):
            assert token not in source, token

    def test_no_vectors_or_embeddings(self):
        source = _all_code().lower()
        for token in ("embedding", "vector", "cosine", "ann_index", "knn"):
            assert token not in source, token


class TestUnchangedPriorMilestones:
    def test_m7_evidence_budget_unchanged(self):
        from src.integration.m7 import contracts as m7_contracts
        source = Path(m7_contracts.__file__).read_text(encoding="utf-8")
        assert "5" in source and "3" in source
        # M8.1 must not have touched the M7 contract module.
        assert "m8" not in source.lower()

    def test_m8_does_not_import_m6_tools(self):
        for path in _m8_files():
            for imported in _imports(path):
                assert "tools" not in imported.lower(), f"{path.name}: {imported}"

    def test_m8_does_not_import_m7_injection(self):
        for path in _m8_files():
            for imported in _imports(path):
                assert "integration.m7" not in imported, f"{path.name}: {imported}"

    def test_no_hermes_core_modification(self):
        # M8.1 lives entirely under src/m8 plus one additive migration.
        for path in _m8_files():
            rel = path.relative_to(SRC_ROOT)
            assert rel.parts[0] in ("m8", "storage"), rel


class TestAuthorityBoundaries:
    def test_graph_edge_cannot_promote_lifecycle(self):
        from src.m8.graph_contract import GraphEdge, ResourceRef, ScopeMetadata
        from src.m8.provenance import Provenance
        edge = GraphEdge(
            from_ref=ResourceRef(resource_type="event", resource_id="E1"),
            relation_type="verifies",
            to_ref=ResourceRef(resource_type="decision", resource_id="D1"),
            scope=ScopeMetadata(project_id="P1"),
            lifecycle_status="candidate",
            provenance=Provenance(
                relation_source="m4_verification",
                source_ref="v:1",
                projection_version="m8.1",
                project_id="P1",
            ),
        )
        # A 'verifies' relation does NOT make the edge verified or active.
        assert edge.lifecycle_status == "candidate"
        assert edge.verification_status is None

    def test_calibration_cannot_encode_authorization(self):
        from src.m8.calibration_contract import CalibrationResult
        result = CalibrationResult(
            candidate_resource_type="decision",
            candidate_resource_id="D1",
            score=1.0,
            lifecycle_status="candidate",
        )
        payload = result.to_dict()
        for banned in ("authorized", "allowed", "grant", "permission", "access"):
            assert banned not in payload

    def test_no_setter_can_mutate_frozen_contracts(self):
        from src.m8.graph_contract import ResourceRef
        ref = ResourceRef(resource_type="event", resource_id="E1")
        with pytest.raises(Exception):
            ref.resource_type = "artifact"  # type: ignore[misc]
