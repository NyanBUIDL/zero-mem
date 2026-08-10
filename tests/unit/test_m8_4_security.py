"""M8.4 static security + authority-boundary audit.

Mirrors the M8.2 / M8.3 static-security pattern but scopes it to the two M8.4
modules:

* ``src/m8/temporal_projection.py`` — the ONLY writer of ``zm_temporal_index``;
  a pure deterministic projector that reaches NO authorization, grant, policy,
  LLM, or network surface.
* ``src/m8/temporal_read.py`` — the authorization-first bounded read layer. It
  is the sanctioned M8.4 consumer of the M5 facade (precedent: M8.3's
  ``graph_access.py``). It may import ``src.access.contracts`` (typed request /
  result) and ``src.access.authorized_read`` (the facade) ONLY. It must NOT
  import ``src.access.policy`` directly, nor any grant-admin / write / LLM /
  network surface.

The M8.4 read layer makes ZERO authorization decisions of its own: it routes
every seed through ``AuthorizedReadService`` and consumes the decision.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
M8_DIR = SRC_ROOT / "m8"
M8_4_MODULES = ("temporal_projection.py", "temporal_read.py")

BANNED_MODULES = {
    "openai", "anthropic", "cohere", "together", "litellm", "transformers",
    "sentence_transformers", "torch", "tiktoken", "langchain", "llama_index",
    "requests", "httpx", "aiohttp", "urllib", "urllib.request", "urllib3",
    "http", "http.client", "socket", "ftplib", "smtplib", "websockets",
    "grpc", "boto3", "faiss", "chromadb", "qdrant_client", "pinecone",
    "weaviate", "neo4j", "networkx",
}

# The ONLY sanctioned M5 access surface for M8.4 (matches M8.3 precedent).
ALLOWED_ACCESS_IMPORTS = {
    "src.access",                 # facade re-export (AuthorizedReadService)
    "src.access.contracts",       # typed request / result
    "src.access.authorized_read",  # the facade module
}


def _m8_4_files() -> list[Path]:
    files = [M8_DIR / name for name in M8_4_MODULES]
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


def _all_code() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _m8_4_files())


def _all_source() -> str:
    return _all_code()


class TestZeroLLMZeroNetwork:
    def test_no_banned_imports(self):
        for path in _m8_4_files():
            for imported in _imports(path):
                root = imported.split(".")[0]
                assert root not in BANNED_MODULES, f"{path.name}: {imported}"

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


class TestAccessSurfaceIsSanctionedOnly:
    def test_access_imports_are_sanctioned_only(self):
        # Every src.access import in an M8.4 module must be a sanctioned
        # surface: the facade (src.access / src.access.authorized_read) or its
        # typed contracts (src.access.contracts). No policy / grant-admin /
        # write surface is reachable from M8.4.
        for path in _m8_4_files():
            for imported in _imports(path):
                if not imported.startswith("src.access"):
                    continue
                sanctioned = any(
                    imported == allowed or imported.startswith(allowed + ".")
                    for allowed in ALLOWED_ACCESS_IMPORTS
                )
                assert sanctioned, (
                    f"{path.name}: unauthorized access import {imported!r}; "
                    f"allowed: {sorted(ALLOWED_ACCESS_IMPORTS)}"
                )

    def test_no_policy_module_import(self):
        for path in _m8_4_files():
            for imported in _imports(path):
                assert imported != "src.access.policy", f"{path.name}: {imported}"
                assert "policy" != imported.split(".")[-1] or not imported.startswith(
                    "src.access"
                ), f"{path.name}: {imported}"

    def test_no_grant_admin_or_write_service(self):
        source = _all_code()
        for token in ("GrantAdminService", "grant_admin", "AuthorizedWriteService"):
            assert token not in source, token

    def test_no_access_decision_functions(self):
        source = _all_code()
        for token in (
            "def authorize", "def check_access", "def is_authorized", "def grant",
            "def has_permission", "def can_read", "def filter_authorized",
        ):
            assert token not in source, token

    def test_no_hardcoded_home(self):
        source = _all_source()
        for token in ("/home/", "/Users/", "C:\\Users", "expanduser",
                      "Path.home()", ".hermes"):
            assert token not in source, token

    def test_no_schema_v10(self):
        assert not (SRC_ROOT / "storage" / "migrations" / "migrate_10.py").exists()

    def test_lives_only_under_m8(self):
        for path in _m8_4_files():
            assert path.relative_to(SRC_ROOT).parts[0] == "m8"
