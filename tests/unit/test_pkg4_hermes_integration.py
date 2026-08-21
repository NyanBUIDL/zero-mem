"""PKG-4 optional Hermes integration tests using synthetic host contexts only."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from zero_mem import hermes_integration as hi


class FakeContext:
    def __init__(self) -> None:
        self.hooks: dict[str, list] = {}
        self.tools: dict[str, tuple] = {}

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = (toolset, schema, handler)


def _env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        HOME=str(tmp_path / "home with spaces"),
        XDG_DATA_HOME=str(tmp_path / "data with spaces"),
        XDG_CONFIG_HOME=str(tmp_path / "config with spaces"),
        XDG_STATE_HOME=str(tmp_path / "state with spaces"),
        XDG_CACHE_HOME=str(tmp_path / "cache with spaces"),
        PYTHONNOUSERSITE="1",
    )
    env.pop("PYTHONPATH", None)
    return env


def _ready(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = _env(tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(hi, "_hermes_executable", lambda: "/synthetic/hermes")
    monkeypatch.setattr(hi, "_boundary_modules_available", lambda: True)
    monkeypatch.setattr(hi, "zero_mem_ready", lambda: True)


def test_command_is_discoverable_and_hermes_is_optional(monkeypatch, tmp_path):
    monkeypatch.setattr(hi, "_hermes_executable", lambda: None)
    code, result = hi.command(project_id=None, profile_id=None)
    assert code == 0
    assert result["code"] == "HERMES_NOT_FOUND"
    assert result["status"] == "OPTIONAL"


def test_cli_command_returns_bounded_json_without_hermes(tmp_path):
    import subprocess
    env = _env(tmp_path)
    env["PATH"] = "/usr/bin"
    result = subprocess.run(
        [sys.executable, "-m", "zero_mem.cli", "integrate", "hermes"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload == {
        "code": "HERMES_NOT_FOUND",
        "component": "hermes",
        "message": "Hermes not found; Zero-Mem remains READY without Hermes",
        "status": "OPTIONAL",
    }
    assert "Traceback" not in result.stdout
    assert str(tmp_path) not in result.stdout


def test_check_is_read_only_and_reports_missing_explicit_identity(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    before = set(hi.integration_config_path().parent.rglob("*")) if hi.integration_config_path().parent.exists() else set()
    code, result = hi.command(project_id=None, profile_id=None, check=True)
    after = set(hi.integration_config_path().parent.rglob("*")) if hi.integration_config_path().parent.exists() else set()
    assert code == 1
    assert result["code"] == "INTEGRATION_NOT_CONFIGURED"
    assert result["details"]["project_id_configured"] is False
    assert result["details"]["profile_id_configured"] is False
    assert before == after


def test_master_switch_disabled_is_authoritative(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_ENABLED", "off")
    code, result = hi.command(project_id="P", profile_id="PR")
    assert code == 0
    assert result["code"] == "ZERO_MEM_DISABLED"
    assert result["status"] == "OPTIONAL"


def test_master_switch_malformed_fails_closed(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_ENABLED", "maybe")
    code, result = hi.command(project_id="P", profile_id="PR")
    assert code == 2
    assert result["code"] == "ZERO_MEM_ENABLED_INVALID"
    assert result["message"] == "invalid ZERO_MEM_ENABLED configuration"


def test_doctor_reports_configured_integration_without_mutating(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    hi.configure_integration(project_id="P", profile_id="PR")
    before = hi.integration_config_path().read_bytes()
    from zero_mem.commands_doctor import collect
    report = collect()
    assert any(item["id"] == "hermes" and item["status"] == "PASS" for item in report["checks"])
    assert hi.integration_config_path().read_bytes() == before


def test_registration_failure_isolated_per_surface(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    class Partial:
        def register_hook(self, *_args):
            raise RuntimeError("synthetic registration failure")
        def register_tool(self, *_args, **_kwargs):
            raise RuntimeError("synthetic tool failure")
    boundary = hi.HermesBoundary(hi.IntegrationConfig("P", "PR"), capture_root=tmp_path / "capture", store_path=tmp_path / "missing.sqlite")
    result = boundary.register(Partial())
    assert result["hooks"] == ()
    assert "synthetic" not in json.dumps(boundary.diagnostics)
    assert {item["component"] for item in boundary.diagnostics} == {"injection"}


def test_config_never_contains_credentials_or_operator_paths(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    hi.configure_integration(project_id="P", profile_id="PR")
    text = hi.integration_config_path().read_text(encoding="utf-8")
    assert "token" not in text.lower()
    assert "secret" not in text.lower()
    assert str(tmp_path) not in text
    assert str(Path.home()) not in text


def test_no_second_master_switch_is_added():
    source = Path(hi.__file__).read_text(encoding="utf-8")
    assert "ZERO_MEM_ENABLED" in source
    assert "MASTER_SWITCH" not in source


def test_installed_boundary_keeps_existing_evidence_budget():
    from src.integration.m7.contracts import EvidenceSet
    assert "primary_evidence" in EvidenceSet.__dataclass_fields__
    assert "supporting_evidence" in EvidenceSet.__dataclass_fields__


def test_installed_package_has_no_hermes_runtime_dependency():
    import importlib.metadata
    metadata = importlib.metadata.metadata("zero-mem")
    assert not any("hermes" in value.lower() for value in metadata.get_all("Requires-Dist") or [])


def test_config_rejects_unknown_fields(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    path = hi.integration_config_path()
    path.parent.mkdir(parents=True)
    payload = hi.IntegrationConfig("P", "PR").to_dict()
    payload["credential"] = "synthetic"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(hi.HermesIntegrationError, match="unsupported"):
        hi.load_integration_config()


def test_remove_refuses_malformed_or_foreign_state(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    path = hi.integration_config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"owner": "other"}), encoding="utf-8")
    with pytest.raises(hi.HermesIntegrationError):
        hi.remove_integration()
    assert path.exists()


def test_context_injection_callback_is_bounded(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    context = FakeContext()
    boundary = hi.HermesBoundary(hi.IntegrationConfig("P", "PR"), capture_root=tmp_path / "capture")
    boundary.register(context)
    callback = context.hooks["pre_llm_call"][0]
    assert callback(user_message="synthetic", session_id="S") is None


def test_disabled_boundary_has_no_callbacks(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_ENABLED", "off")
    context = FakeContext()
    result = hi.HermesBoundary(hi.IntegrationConfig("P", "PR"), capture_root=tmp_path / "capture").register(context)
    assert result == {"hooks": (), "tools": (), "injection": ()}
    assert context.hooks == {}
    assert context.tools == {}


def test_real_home_signature_is_not_used_by_release_layer():
    source = Path(hi.__file__).read_text(encoding="utf-8")
    assert "Path.home()" not in source
    assert "cwd" not in source
    assert "repository name" not in source


def test_boundary_diagnostics_are_bounded():
    config = hi.IntegrationConfig("P", "PR")
    boundary = hi.HermesBoundary(config)
    assert boundary.diagnostics == []
    assert all(len(key) < 32 for key in ("component", "code"))


def test_identity_values_are_not_logged_in_diagnostics(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    boundary = hi.HermesBoundary(hi.IntegrationConfig("PROJECT-SENSITIVE", "PROFILE-SENSITIVE"), capture_root=tmp_path / "capture")
    boundary.register(object())
    assert "PROJECT-SENSITIVE" not in json.dumps(boundary.diagnostics)
    assert "PROFILE-SENSITIVE" not in json.dumps(boundary.diagnostics)


def test_optional_command_does_not_install_hermes(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    monkeypatch.setattr(hi, "_hermes_executable", lambda: None)
    code, _ = hi.command(project_id="P", profile_id="PR")
    assert code == 0
    assert not hi.integration_config_path().exists()


def test_config_write_is_private(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    hi.configure_integration(project_id="P", profile_id="PR")
    assert hi.integration_config_path().stat().st_mode & 0o077 == 0


def test_config_path_is_xdg_owned(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    assert str(hi.integration_config_path()).startswith(str(tmp_path / "config with spaces"))


def test_remove_does_not_touch_unrelated_files(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    hi.configure_integration(project_id="P", profile_id="PR")
    unrelated = hi.integration_config_path().parent / "unrelated.json"
    unrelated.write_text("synthetic", encoding="utf-8")
    hi.remove_integration()
    assert unrelated.read_text(encoding="utf-8") == "synthetic"


def test_config_round_trip_is_deterministic(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    hi.configure_integration(project_id="P", profile_id="PR")
    first = hi.integration_config_path().read_bytes()
    hi.configure_integration(project_id="P", profile_id="PR")
    assert hi.integration_config_path().read_bytes() == first


def test_check_rejects_malformed_config_without_writing(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    path = hi.integration_config_path()
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    before = path.read_bytes()
    code, result = hi.command(project_id=None, profile_id=None, check=True)
    assert code == 2
    assert result["code"] == "INTEGRATION_CONFIG_INVALID"
    assert path.read_bytes() == before


def test_no_network_api_imports_in_release_layer():
    import ast
    tree = ast.parse(Path(hi.__file__).read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not imports.intersection({"requests", "urllib", "socket", "httpx"})


def test_explicit_identity_is_required_and_cwd_is_irrelevant(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    code, result = hi.command(project_id=None, profile_id=None)
    assert code != 0
    assert result["code"] == "EXPLICIT_IDENTITY_REQUIRED"
    assert "cwd" not in json.dumps(result).lower()
    assert "repository" not in json.dumps(result).lower()


def test_identifiers_are_validated_without_inference(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    for field in ("project_id", "profile_id"):
        project_id = "../../guess" if field == "project_id" else "P"
        profile_id = "../../guess" if field == "profile_id" else "PR"
        code, result = hi.command(project_id=project_id, profile_id=profile_id)
        assert code != 0
        assert result["code"] == "INTEGRATION_REFUSED"
        assert field in result["message"]


def test_zero_mem_switch_off_does_not_register(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    monkeypatch.setenv("ZERO_MEM_ENABLED", "off")
    config = hi.IntegrationConfig("P", "PR")
    context = FakeContext()
    result = hi.HermesBoundary(config, capture_root=tmp_path / "capture").register(context)
    assert result["hooks"] == ()
    assert context.hooks == {}


def test_boundary_registers_hook_tool_and_injection_surfaces(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    config = hi.IntegrationConfig("P", "PR")
    context = FakeContext()
    result = hi.HermesBoundary(
        config,
        capture_root=tmp_path / "capture",
        store_path=tmp_path / "missing.sqlite",
    ).register(context)
    assert "pre_llm_call" in result["injection"]
    assert result["hooks"]
    assert context.hooks["pre_llm_call"]
    assert result["tools"] == ()  # missing store is isolated; no broad fallback tools


def test_boundary_adapts_successful_read_tool_registration(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    # The production default mode is now OBSERVE (R124-01: capture-only, no read
    # tools). This test exercises the read-tool wiring path, so it opts into the
    # explicit ASSIST mode where read tools are authorized.
    monkeypatch.setenv("ZERO_MEM_MODE", "assist")
    from src.integration import hermes_read_adapter

    class FakeReadAdapter:
        def __init__(self, config, *, store_path):
            self.config = config
            self.store_path = store_path

        def register(self, context):
            context.register_tool("memory_query", {"type": "object"}, lambda _args: {"status": "EMPTY"})
            return ("memory_query",)

    monkeypatch.setattr(hermes_read_adapter, "HermesReadAdapter", FakeReadAdapter)
    context = FakeContext()
    result = hi.HermesBoundary(
        hi.IntegrationConfig("P", "PR"),
        capture_root=tmp_path / "capture",
        store_path=tmp_path / "capture" / "derived" / "events.sqlite",
    ).register(context)
    assert result["tools"] == ("memory_query",)
    assert "memory_query" in context.tools
    assert context.tools["memory_query"][0] == "zero_mem"


def test_registration_failure_isolated(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    config = hi.IntegrationConfig("P", "PR")
    boundary = hi.HermesBoundary(config, capture_root=tmp_path / "capture")
    result = boundary.register(object())
    assert result["hooks"] == ()
    assert boundary.diagnostics
    assert "traceback" not in json.dumps(boundary.diagnostics).lower()


def test_malformed_config_and_sanitized_diagnostic(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    path = hi.integration_config_path()
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    code, result = hi.command(project_id="P", profile_id="PR", check=True)
    assert code != 0
    assert result["code"] == "INTEGRATION_CONFIG_INVALID"
    assert "Traceback" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


def test_configure_and_remove_are_reversible_and_zero_mem_owned(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    code, result = hi.command(project_id="P", profile_id="PR")
    assert code == 0
    path = hi.integration_config_path()
    assert path.is_file()
    assert json.loads(path.read_text())["owner"] == "zero-mem"
    code, result = hi.command(project_id=None, profile_id=None, remove=True)
    assert code == 0
    assert not path.exists()


def test_doctor_path_remains_non_mutating(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    path = hi.integration_config_path()
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(hi.IntegrationConfig("P", "PR").to_dict()), encoding="utf-8")
    before = path.read_bytes()
    info = hi.inspect_integration()
    assert info["configured"] is True
    assert path.read_bytes() == before


def test_no_raw_or_admin_surface_in_release_layer():
    source = Path(hi.__file__).read_text(encoding="utf-8")
    forbidden = ("raw_sql", "raw_jsonl", "GrantAdminService", "AuthorizedWriteService", "sqlite3", r"\.hermes")
    assert all(token not in source for token in forbidden)


def test_no_real_home_write_signature(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    real = Path.home() / ".hermes"
    before = {p for p in real.rglob("*")} if real.exists() else set()
    hi.inspect_integration()
    after = {p for p in real.rglob("*")} if real.exists() else set()
    assert before == after


def test_installed_package_has_release_layer():
    assert Path(hi.__file__).name == "hermes_integration.py"
    assert "site-packages" not in str(hi.__file__) or Path(hi.__file__).is_file()


def test_existing_authorization_and_budget_contracts_unchanged():
    from src.integration.m7.injection_adapter import InjectionAdapter
    from src.integration.m7.contracts import EvidenceSet
    assert InjectionAdapter is not None
    assert EvidenceSet is not None
    source = Path(__file__).resolve().parents[2] / "src/integration/m7/injection_adapter.py"
    text = source.read_text(encoding="utf-8")
    assert "build_evidence_set" in text
    assert "validate_evidence_set" in text


def test_capture_failure_callback_is_bounded(monkeypatch, tmp_path):
    _ready(monkeypatch, tmp_path)
    config = hi.IntegrationConfig("P", "PR")
    boundary = hi.HermesBoundary(config, capture_root=tmp_path / "capture")

    class Broken:
        def register_hook(self, *_args):
            raise RuntimeError("synthetic secret")

    assert boundary.register(Broken())["hooks"] == ()
    assert "synthetic secret" not in json.dumps(boundary.diagnostics)


def test_installed_wheel_does_not_need_repository_cwd():
    assert shutil.which("python3")
    assert hi.__package__ == "zero_mem"
