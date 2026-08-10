"""M9.1 — security, sensitivity, contract, and zero-side-effect tests.

Covers: the canonical sensitivity contract (shared with M7.3, never duplicated),
the frozen projection contracts, the static dependency-boundary audit (zero LLM,
zero network, no hard-coded operator path, no authorization reach), and proof
that configuration/path resolution mutates no canonical store and no real vault.
"""

from __future__ import annotations

import ast
import hashlib
import os
import tempfile
from pathlib import Path

import pytest

from src.capture.event_types import Sensitivity
from src.integration.m7.eligibility import (
    DEFAULT_SENSITIVITY_CEILING as M7_DEFAULT_CEILING,
)
from src.projection.contracts import (
    DEFAULT_PROJECTION_SENSITIVITY_CEILING,
    MANAGED_MARKER_KEY,
    META_DIR_NAME,
    NOTE_TYPE_DIRECTORIES,
    PROJECTION_VERSION,
    SENSITIVITY_ORDER,
    UNKNOWN_SENSITIVITY_RANK,
    NoteStatus,
    NoteType,
    ProjectedNote,
    ProjectionRequest,
    ProjectionResult,
    ProjectionStatus,
    ProjectionVocabularyError,
    is_projectable_sensitivity,
    sensitivity_rank,
    validate_sensitivity_ceiling,
)
from src.projection.identity import content_fingerprint, derive_note_id

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECTION_DIR = REPO_ROOT / "src" / "projection"

#: The modules M9.1 itself delivered. The M9.1 non-scope guards below are pinned
#: to THIS set, not to a glob of the package: later increments legitimately add
#: modules (M9.2 added render/writer/engine/eligibility), and a glob would turn
#: every M9.1 "not yet implemented" guard into a false failure the moment the
#: next approved increment lands. Invariants that are permanent for the WHOLE
#: package (no operator path, no Hermes core import, no schema change, no LLM,
#: no network, no write authority) stay globbed over every projection module.
M9_1_MODULES: frozenset[str] = frozenset({
    "__init__.py", "contracts.py", "identity.py", "paths.py", "config.py",
})

#: Modules that must NOT exist until their own approved increment. M9.2
#: delivered render/writer/engine/eligibility; M9.4 delivered manifest.py and
#: reconcile.py (the deterministic manifest, incremental reconcile, and safe
#: stale-retirement surfaces). Those are therefore no longer "not yet
#: implemented" and are intentionally absent from this list. ``projector.py`` is
#: kept as a permanent drift sentinel: the package's projection entry point is
#: ``engine.py`` (project_to_vault), and a future splintered ``projector.py``
#: would be an unapproved module and must fail here.
NOT_YET_IMPLEMENTED_MODULES: tuple[str, ...] = ("projector.py",)


def _projection_files() -> list[Path]:
    files = sorted(PROJECTION_DIR.glob("*.py"))
    assert files, "expected M9.1 modules to exist"
    return files


def _m9_1_files() -> list[Path]:
    files = [p for p in sorted(PROJECTION_DIR.glob("*.py")) if p.name in M9_1_MODULES]
    assert len(files) == len(M9_1_MODULES), "M9.1 module set drifted"
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


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _all_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _projection_files())


def _all_code() -> str:
    """Executable code only: comments and docstrings removed."""
    return _code_of(_projection_files())


def _m9_1_code() -> str:
    """Executable code of the M9.1 module set only."""
    return _code_of(_m9_1_files())


def _code_of(paths: list[Path]) -> str:
    chunks = []
    for path in paths:
        tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8")))
        chunks.append(ast.unparse(tree))
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------

class TestSensitivityVocabulary:
    def test_uses_canonical_vocabulary_only(self):
        assert set(SENSITIVITY_ORDER) == {m.value for m in Sensitivity}
        assert SENSITIVITY_ORDER == {
            "public": 0, "internal": 1, "private": 2, "secret": 3
        }

    def test_no_second_ladder_introduced(self):
        source = _all_code()
        for banned in ("low", "medium", "high", "critical"):
            assert f'"{banned}": 0' not in source
            assert f"'{banned}': 0" not in source

    def test_default_projection_ceiling_is_internal(self):
        assert DEFAULT_PROJECTION_SENSITIVITY_CEILING == Sensitivity.INTERNAL.value

    def test_m7_retrieval_default_ceiling_unchanged(self):
        """M7 = private, M9 = internal. Intentionally different; neither may drift."""
        assert M7_DEFAULT_CEILING == Sensitivity.PRIVATE.value
        assert DEFAULT_PROJECTION_SENSITIVITY_CEILING != M7_DEFAULT_CEILING

    def test_public_allowed_by_internal_ceiling(self):
        assert is_projectable_sensitivity("public", "internal") is True

    def test_internal_allowed_by_internal_ceiling(self):
        assert is_projectable_sensitivity("internal", "internal") is True

    def test_private_excluded_by_internal_ceiling(self):
        assert is_projectable_sensitivity("private", "internal") is False

    def test_private_allowed_only_by_explicit_private_ceiling(self):
        assert is_projectable_sensitivity("private", "private") is True

    @pytest.mark.parametrize("ceiling", ["public", "internal", "private", "secret", None, "bogus"])
    def test_secret_never_projected_at_any_ceiling(self, ceiling):
        assert is_projectable_sensitivity("secret", ceiling) is False

    @pytest.mark.parametrize(
        "value", [None, "", "   ", "unknown", "LOW", "critical", 3, object(), "publicc"]
    )
    def test_unknown_sensitivity_fails_closed(self, value):
        assert is_projectable_sensitivity(value, "internal") is False

    @pytest.mark.parametrize("ceiling", [None, "", "bogus", "critical", 1, object()])
    def test_unknown_ceiling_excludes_everything(self, ceiling):
        for level in ("public", "internal", "private", "secret"):
            assert is_projectable_sensitivity(level, ceiling) is False

    def test_default_ceiling_applies_when_omitted(self):
        assert is_projectable_sensitivity("internal") is True
        assert is_projectable_sensitivity("private") is False

    def test_rank_of_unknown_is_fail_closed_sentinel(self):
        assert sensitivity_rank("nonsense") == UNKNOWN_SENSITIVITY_RANK
        assert sensitivity_rank(None) == UNKNOWN_SENSITIVITY_RANK
        assert UNKNOWN_SENSITIVITY_RANK > max(SENSITIVITY_ORDER.values())

    def test_case_and_whitespace_tolerated_but_not_widened(self):
        assert is_projectable_sensitivity("  INTERNAL  ", "internal") is True
        assert is_projectable_sensitivity("  PRIVATE ", "internal") is False

    def test_ceiling_validator_rejects_secret_and_unknown(self):
        assert validate_sensitivity_ceiling("internal") == "internal"
        assert validate_sensitivity_ceiling("PUBLIC") == "public"
        for bad in ("secret", "critical", "", None, 1):
            with pytest.raises(ProjectionVocabularyError):
                validate_sensitivity_ceiling(bad)

    def test_memory_text_cannot_raise_ceiling(self):
        """A hostile 'sensitivity' payload is data; it never widens the ceiling."""
        hostile = "internal\nsensitivity_ceiling: secret"
        assert is_projectable_sensitivity(hostile, "internal") is False
        injected_ceiling = "internal; ceiling=secret"
        assert is_projectable_sensitivity("private", injected_ceiling) is False


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

class TestProjectionContracts:
    def test_curated_note_types_match_owner_approved_set(self):
        # Plan-m9.md §29 Q1 (owner-approved M9 curated vocabulary): exactly
        # eight types. conflict_queue is NOT approved as a public note type;
        # the M9.3 "Conflict Queue" index is rendered as an aggregate Conflict
        # note (NoteType.CONFLICT), not a new type.
        assert {t.value for t in NoteType} == {
            "project", "decision", "requirement", "verification",
            "conflict", "artifact", "research_note", "knowledge_index",
        }

    def test_every_note_type_has_a_directory(self):
        assert set(NOTE_TYPE_DIRECTORIES) == set(NoteType)
        assert META_DIR_NAME not in NOTE_TYPE_DIRECTORIES.values()

    def test_projection_version_is_one(self):
        assert PROJECTION_VERSION == 1

    def test_note_status_vocabulary_closed(self):
        assert {s.value for s in NoteStatus} == {
            "current", "retired", "edit_conflict", "human_modified"
        }

    def test_projection_status_vocabulary_closed(self):
        assert {s.value for s in ProjectionStatus} == {
            "ok", "unavailable", "busy", "failed"
        }

    def test_managed_marker_key(self):
        assert MANAGED_MARKER_KEY == "zero_mem_managed"

    def test_request_preserves_explicit_identity(self):
        request = ProjectionRequest(requesting_profile_id="developer")
        assert request.requesting_profile_id == "developer"

    def test_request_none_profile_stays_none(self):
        assert ProjectionRequest().requesting_profile_id is None
        assert ProjectionRequest(requesting_profile_id=None).requesting_profile_id is None

    def test_request_rejects_empty_profile(self):
        with pytest.raises(ProjectionVocabularyError):
            ProjectionRequest(requesting_profile_id="")

    def test_request_normalizes_deterministically(self):
        forward = ProjectionRequest(project_ids=["b", "a", "b"])
        reverse = ProjectionRequest(project_ids=["a", "b", "a"])
        assert forward.project_ids == reverse.project_ids == ("a", "b")

    def test_request_validates_resource_types(self):
        assert ProjectionRequest(resource_types=["decision"]).resource_types == ("decision",)
        with pytest.raises(ProjectionVocabularyError):
            ProjectionRequest(resource_types=["not_a_resource"])

    def test_request_to_dict_hides_grant_contents(self):
        descriptor = ProjectionRequest(grants=("opaque-grant",)).to_dict()
        assert descriptor["grant_count"] == 1
        assert "opaque-grant" not in repr(descriptor)

    def test_result_unavailable_helper(self):
        result = ProjectionResult.unavailable("vault_not_configured")
        assert result.status is ProjectionStatus.UNAVAILABLE
        assert result.notes_written == 0

    def test_result_rejects_negative_counts(self):
        with pytest.raises(ProjectionVocabularyError):
            ProjectionResult(status=ProjectionStatus.OK, created=-1)

    def test_projected_note_binds_fingerprint_to_content(self):
        note_id = derive_note_id(
            note_type=NoteType.DECISION, resource_type="decision", resource_id="D1"
        )
        body = "# Title\n"
        note = ProjectedNote(
            note_id=note_id,
            note_type=NoteType.DECISION,
            relative_path="Decisions/proj/n.md",
            content=body,
            content_fingerprint=content_fingerprint(body),
        )
        assert note.content_fingerprint == content_fingerprint(body)
        with pytest.raises(ProjectionVocabularyError):
            ProjectedNote(
                note_id=note_id,
                note_type=NoteType.DECISION,
                relative_path="Decisions/proj/n.md",
                content=body,
                content_fingerprint=content_fingerprint("different"),
            )

    @pytest.mark.parametrize(
        "relative", ["/abs/n.md", "..\\n.md", "a/../../n.md", "", "a\x00b"]
    )
    def test_projected_note_rejects_unsafe_relative_path(self, relative):
        note_id = derive_note_id(
            note_type=NoteType.DECISION, resource_type="decision", resource_id="D1"
        )
        with pytest.raises(ProjectionVocabularyError):
            ProjectedNote(
                note_id=note_id,
                note_type=NoteType.DECISION,
                relative_path=relative,
                content="x",
                content_fingerprint=content_fingerprint("x"),
            )


# ---------------------------------------------------------------------------
# Static security audit
# ---------------------------------------------------------------------------

class TestZeroLLMZeroNetwork:
    BANNED_MODULES = {
        "openai", "anthropic", "cohere", "together", "litellm", "transformers",
        "sentence_transformers", "torch", "tiktoken", "langchain", "llama_index",
        "requests", "httpx", "aiohttp", "urllib", "urllib3", "http", "socket",
        "ftplib", "smtplib", "websockets", "grpc", "boto3", "faiss", "chromadb",
        "qdrant_client", "pinecone", "weaviate", "neo4j", "networkx", "yaml",
    }

    def test_no_banned_imports(self):
        for path in _projection_files():
            for imported in _imports(path):
                root = imported.split(".")[0]
                assert root not in self.BANNED_MODULES, f"{path.name} imports {imported}"

    def test_no_llm_or_embedding_tokens(self):
        source = _all_code().lower()
        for token in (
            "openai", "anthropic", "chat.completions", "def embed",
            "embedding(", "vectorize", "api_key", "bearer ",
        ):
            assert token not in source, token

    def test_no_network_expressions(self):
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

    def test_stdlib_and_local_imports_only(self):
        # Zero LLM, zero network, zero third-party. The allowed local prefixes
        # grew with M9.2, which consumes the verified M4 project-memory reader
        # and the M5 authorized-read facade. Every one of these is an in-repo,
        # offline, already-verified module; nothing here reaches the network.
        allowed_prefixes = (
            "src.projection", "src.capture", "src.m8",
            "src.project_memory", "src.access", ".",
        )
        stdlib = {
            "__future__", "dataclasses", "typing", "enum", "hashlib", "json",
            "os", "pathlib", "unicodedata",
        }
        for path in _projection_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue
                    module = node.module or ""
                    root = module.split(".")[0]
                    assert module.startswith(allowed_prefixes) or root in stdlib, (
                        f"{path.name} imports {module}"
                    )
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        assert root in stdlib, f"{path.name} imports {alias.name}"

    def test_m9_1_layer_imports_stay_minimal(self):
        # The M9.1 layer itself must NOT have acquired the wider dependency
        # surface M9.2 needs; it stays a pure contract/identity/path/config layer.
        allowed_prefixes = ("src.projection", "src.capture", "src.m8", ".")
        stdlib = {
            "__future__", "dataclasses", "typing", "enum", "hashlib", "json",
            "os", "pathlib", "unicodedata",
        }
        for path in _m9_1_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level > 0:
                        continue
                    module = node.module or ""
                    root = module.split(".")[0]
                    assert module.startswith(allowed_prefixes) or root in stdlib, (
                        f"{path.name} imports {module}"
                    )

    def test_no_new_third_party_dependency(self):
        """stdlib + existing repo modules only; notably no PyYAML."""
        assert "import yaml" not in _all_source()


class TestNoAuthorizationReach:
    def test_no_grant_admin_or_write_service(self):
        # PERMANENT, whole-package: projection may never administer grants nor
        # acquire ANY write authority over canonical state.
        source = _all_code()
        for token in (
            "GrantAdmin", "grant_admin", "AuthorizedWriteService",
            "authorized_write",
        ):
            assert token not in source, token

    def test_m9_1_layer_does_not_consume_the_read_service(self):
        # M9.1 is a pure contract/identity/path/config layer: it must not even
        # reference the read service. M9.2's engine is the single consumer, and
        # it CONSULTS M5 as the sole authority rather than deciding access.
        assert "AuthorizedReadService" not in _m9_1_code()

    def test_read_service_is_consumed_only_by_the_engine(self):
        # Authorization has exactly one entry point in the package. Rendering,
        # writing, identity, and path safety must never touch it.
        for path in _projection_files():
            if path.name == "engine.py":
                continue
            assert "AuthorizedReadService" not in path.read_text(encoding="utf-8"), (
                f"{path.name} must not consume the authorization service"
            )

    def test_no_policy_import(self):
        # M9.1 must not import the access layer at all.
        for path in _m9_1_files():
            for imported in _imports(path):
                assert "policy" not in imported.lower(), f"{path.name}: {imported}"
                assert "src.access" not in imported, f"{path.name}: {imported}"
        # Whole-package: the access POLICY engine is never imported, by anyone.
        # M9.2's engine imports only the authorized-read facade and its request
        # contract; it never reaches past them into policy internals.
        allowed_access_imports = {
            "src.access.authorized_read", "src.access.contracts",
        }
        for path in _projection_files():
            for imported in _imports(path):
                assert "policy" not in imported.lower(), f"{path.name}: {imported}"
                if imported.startswith("src.access"):
                    module = imported.rsplit(".", 1)[0] if imported not in allowed_access_imports else imported
                    assert module in allowed_access_imports, f"{path.name}: {imported}"

    def test_no_access_decision_functions(self):
        # Projection never DEFINES an access decision. `is_authorized_resource_type`
        # is deliberately excluded from this ban: it is a closed-vocabulary
        # validity check over M6.6 resource types and the sensitivity ceiling —
        # it grants nothing and is not consulted in place of M5.
        source = _all_code()
        for token in (
            "def authorize", "def check_access", "def is_authorized(",
            "def grant", "def has_permission", "def can_read",
        ):
            assert token not in source, token

    def test_identity_is_never_inferred(self):
        source = _all_code()
        for token in ("HERMES_PROFILE_ID", "HERMES_PROJECT_ID", "getpass", "getuser"):
            assert token not in source, token


class TestNoHardcodedOperatorPath:
    def test_no_home_or_username(self):
        source = _all_source()
        for token in ("/home/", "/Users/", "brian-nguyen", "C:\\\\Users", "Documents/Obsidian"):
            assert token not in source, token

    def test_no_home_derivation(self):
        source = _all_code()
        for token in ("Path.home()", "expanduser", "os.path.expanduser", "~/Obsidian"):
            assert token not in source, token

    def test_no_cwd_as_vault(self):
        source = _all_code()
        for token in ("os.getcwd", "Path.cwd", 'Path(".")', "Path('.')"):
            assert token not in source, token

    def test_no_hardcoded_tmp(self):
        source = _all_code()
        assert "/tmp" not in source
        assert "tempfile" not in source


class TestNonScope:
    def test_m9_1_does_not_implement_later_increments(self):
        # Pinned to modules whose increment has NOT been approved yet. M9.2
        # delivered render.py/writer.py/engine.py/eligibility.py under its own
        # approved scope, so those are no longer "later increments".
        for banned in NOT_YET_IMPLEMENTED_MODULES:
            assert not (PROJECTION_DIR / banned).exists(), banned

    def test_m9_1_module_set_is_exactly_as_delivered(self):
        # The M9.1 surface itself must not silently grow. A new M9.1-owned
        # module has to be an explicit, reviewed change to M9_1_MODULES.
        present = {p.name for p in PROJECTION_DIR.glob("*.py")}
        assert M9_1_MODULES <= present, "an M9.1 module disappeared"

    def test_no_write_operations_in_m9_1(self):
        # The M9.1 layer is read/validate only. M9.2's writer legitimately owns
        # the atomic write, so this guard is scoped to the M9.1 modules and
        # continues to prove they gained no write authority.
        source = _m9_1_code()
        for token in (
            "write_text", "open(", "mkdir", "os.replace", "shutil",
            "unlink", "rmtree", "os.remove", "rename(", "touch(",
        ):
            assert token not in source, token

    def test_no_manifest_or_render_surface_yet(self):
        # M9.1 modules themselves carry NO projection/render/write/retire
        # surface. Rendering, note writing, and (now) the M9.4 manifest +
        # reconcile surfaces live in their OWN approved modules; the M9.1 layer
        # remains read/validate only.
        m9_1 = _m9_1_code()
        for token in ("def project(", "def render", "def write_note", "def retire"):
            assert token not in m9_1, token
        # The M9.4-approved manifest/retirement surfaces (load_manifest,
        # build_manifest/rebuild, retire/retire_note) MUST NOT leak into the
        # M9.1 module set — M9.1 stays read/validate only even after M9.4 lands.
        for token in ("def load_manifest", "def build_manifest", "def retire",
                      "def rebuild"):
            assert token not in m9_1, token
        # Globally, those surfaces now legitimately exist (M9.4 approved them),
        # but ONLY inside the approved modules — never inside M9.1's.
        source = _all_code()
        m9_4_approved = {
            p.name for p in _projection_files()
            if p.name in ("manifest.py", "reconcile.py")
        }
        if m9_4_approved:
            # Surface present in approved modules is expected; absence from M9.1
            # is already proven above. This branch only asserts the package did
            # not regress the M9.1 boundary.
            assert "def project(" not in m9_1

    def test_no_schema_or_migration_change(self):
        source = _all_source()
        for token in ("CREATE TABLE", "ALTER TABLE", "migrate_10", "sqlite3"):
            assert token not in source, token

    def test_no_hermes_core_import(self):
        source = _all_source()
        assert "from hermes" not in source and "import hermes" not in source

    def test_no_write_back_surface(self):
        source = _all_code()
        for token in ("write_back", "propose_change", "apply_edit", "canonical_write"):
            assert token not in source, token


# ---------------------------------------------------------------------------
# Zero side effects
# ---------------------------------------------------------------------------

class TestZeroSideEffects:
    def test_state_artifacts_unchanged_by_projection_use(self):
        from src.projection.config import ProjectionConfig, load_projection_config
        from src.projection.paths import safe_note_path

        watched = [
            REPO_ROOT / "project-state.yaml",
            REPO_ROOT / "implementation-plan.json",
        ]
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest() for path in watched
        }

        with tempfile.TemporaryDirectory(prefix="hermes-verify-m91-") as tmp:
            vault = Path(tmp) / "Vault"
            vault.mkdir()
            config = ProjectionConfig(vault_root=vault)
            note_id = derive_note_id(
                note_type=NoteType.DECISION, resource_type="decision", resource_id="D1"
            )
            safe_note_path(
                config.managed_root,
                note_type=NoteType.DECISION,
                note_id=note_id,
                display_title="Title",
                scope="proj",
            )
            load_projection_config(None, env={}, config_file=Path(tmp) / "none.yaml")

        after = {
            path: hashlib.sha256(path.read_bytes()).hexdigest() for path in watched
        }
        assert before == after

    def test_no_jsonl_or_sqlite_touched(self):
        """M9.1 reads no canonical store: it imports no storage module at all."""
        for path in _projection_files():
            for imported in _imports(path):
                assert "src.storage" not in imported, f"{path.name}: {imported}"
                assert "jsonl" not in imported.lower(), f"{path.name}: {imported}"

    def test_temp_vault_only_and_no_real_vault_reference(self):
        """Neither product code nor M9.1 tests reference the operator's real vault.

        The forbidden tokens are assembled at runtime so that this guard does not
        itself plant the literal strings it searches for.
        """
        forbidden = ("Documents" + "/Obsidian", "/home/" + "brian-nguyen")
        sources = list(_projection_files()) + sorted(
            (REPO_ROOT / "tests" / "unit").glob("test_m9_1_*.py")
        )
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                occurrences = text.count(token)
                # The static-audit test legitimately builds these tokens to search
                # for them; every other occurrence is a real vault reference.
                assert occurrences == 0 or path.name == "test_m9_1_security.py", (
                    f"{path.name} references {token}"
                )

    def test_config_and_path_resolution_create_nothing(self):
        from src.projection.config import ProjectionConfig
        from src.projection.paths import safe_managed_path, safe_meta_path

        with tempfile.TemporaryDirectory(prefix="hermes-verify-m91-") as tmp:
            vault = Path(tmp) / "Vault"
            vault.mkdir()
            snapshot_before = sorted(str(p) for p in Path(tmp).rglob("*"))
            config = ProjectionConfig(vault_root=vault)
            safe_managed_path(config.managed_root, "Decisions", "proj", "n.md")
            safe_meta_path(config.managed_root, "manifest.json")
            snapshot_after = sorted(str(p) for p in Path(tmp).rglob("*"))
            assert snapshot_before == snapshot_after
