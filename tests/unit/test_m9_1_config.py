"""M9.1 — configuration boundary and vault-root resolution tests.

Every test uses an OS-safe temporary vault. The operator's real vault is never
constructed, written, or referenced (plan-m9.md §26.1).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.projection.config import (
    CONFIG_FILE_RELATIVE_PATH,
    CONFIG_FILE_VAULT_KEY,
    DEFAULT_MANAGED_DIR_NAME,
    REASON_VAULT_NOT_CONFIGURED,
    VAULT_ROOT_ENV_VAR,
    ProjectionConfig,
    load_projection_config,
    resolve_vault_root,
    unavailable_result,
    validate_vault_root,
)
from src.projection.contracts import (
    DEFAULT_PROJECTION_SENSITIVITY_CEILING,
    NoteType,
    ProjectionConfigError,
    ProjectionStatus,
)


@pytest.fixture()
def temp_vault():
    with tempfile.TemporaryDirectory(prefix="hermes-verify-m91-") as tmp:
        vault = Path(tmp) / "Vault"
        vault.mkdir()
        yield vault


@pytest.fixture(autouse=True)
def _no_operator_env(monkeypatch):
    """Structural guard: an operator env var can never leak into a test run."""
    monkeypatch.delenv(VAULT_ROOT_ENV_VAR, raising=False)


class TestExplicitConfiguration:
    def test_valid_explicit_vault_root(self, temp_vault):
        config = ProjectionConfig(vault_root=temp_vault)
        assert config.vault_root == temp_vault
        assert config.managed_root == temp_vault / DEFAULT_MANAGED_DIR_NAME

    def test_explicit_argument_beats_environment(self, temp_vault, monkeypatch):
        other = temp_vault.parent / "Other"
        other.mkdir()
        monkeypatch.setenv(VAULT_ROOT_ENV_VAR, str(other))
        assert resolve_vault_root(temp_vault) == temp_vault

    def test_environment_used_when_no_explicit_value(self, temp_vault):
        env = {VAULT_ROOT_ENV_VAR: str(temp_vault)}
        assert resolve_vault_root(None, env=env) == temp_vault

    def test_config_file_used_when_no_explicit_or_env(self, temp_vault):
        config_file = temp_vault.parent / "projection.yaml"
        config_file.write_text(
            f"# comment\n{CONFIG_FILE_VAULT_KEY}: {temp_vault}\n", encoding="utf-8"
        )
        assert resolve_vault_root(None, env={}, config_file=config_file) == temp_vault

    def test_config_file_quoted_value(self, temp_vault):
        config_file = temp_vault.parent / "projection.yaml"
        config_file.write_text(
            f'{CONFIG_FILE_VAULT_KEY}: "{temp_vault}"\n', encoding="utf-8"
        )
        assert resolve_vault_root(None, env={}, config_file=config_file) == temp_vault

    def test_config_file_unknown_key_ignored(self, temp_vault):
        config_file = temp_vault.parent / "projection.yaml"
        config_file.write_text("some_other_key: /elsewhere\n", encoding="utf-8")
        assert resolve_vault_root(None, env={}, config_file=config_file) is None

    def test_config_file_nested_structure_fails_closed(self, temp_vault):
        config_file = temp_vault.parent / "projection.yaml"
        config_file.write_text("projection:\n  vault_root: /x\n", encoding="utf-8")
        with pytest.raises(ProjectionConfigError):
            resolve_vault_root(None, env={}, config_file=config_file)

    def test_config_file_absent_is_normal(self, temp_vault):
        missing = temp_vault.parent / "absent.yaml"
        assert resolve_vault_root(None, env={}, config_file=missing) is None

    def test_repo_config_example_exists_and_has_no_operator_path(self):
        repo_root = Path(__file__).resolve().parents[2]
        example = repo_root / (CONFIG_FILE_RELATIVE_PATH + ".example")
        assert example.is_file()
        text = example.read_text(encoding="utf-8")
        assert "/home/" not in text
        assert VAULT_ROOT_ENV_VAR in text


class TestUnconfigured:
    def test_no_configuration_returns_none(self):
        assert load_projection_config(None, env={}, config_file=Path("/nonexistent.yaml")) is None

    def test_empty_string_configuration_is_unconfigured(self):
        assert resolve_vault_root("", env={}, config_file=Path("/nonexistent.yaml")) is None

    def test_whitespace_configuration_is_unconfigured(self):
        assert resolve_vault_root("   ", env={}, config_file=Path("/nonexistent.yaml")) is None

    def test_empty_env_value_is_unconfigured(self):
        env = {VAULT_ROOT_ENV_VAR: ""}
        assert resolve_vault_root(None, env=env, config_file=Path("/nonexistent.yaml")) is None

    def test_unavailable_result_is_silent_and_writes_nothing(self):
        result = unavailable_result()
        assert result.status is ProjectionStatus.UNAVAILABLE
        assert result.reason == REASON_VAULT_NOT_CONFIGURED
        assert result.notes_written == 0
        assert result.notes == ()

    def test_unconfigured_creates_no_directory_anywhere(self, tmp_path, monkeypatch):
        """No cwd fallback, no HOME fallback, no invented ~/Obsidian."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        monkeypatch.chdir(workdir)

        before_home = sorted(p.name for p in fake_home.iterdir())
        before_cwd = sorted(p.name for p in workdir.iterdir())

        assert load_projection_config(None, env={}, config_file=tmp_path / "none.yaml") is None
        unavailable_result()

        assert sorted(p.name for p in fake_home.iterdir()) == before_home
        assert sorted(p.name for p in workdir.iterdir()) == before_cwd
        assert not (fake_home / "Obsidian").exists()
        assert not (workdir / DEFAULT_MANAGED_DIR_NAME).exists()

    def test_cwd_is_never_treated_as_vault(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert resolve_vault_root(None, env={}, config_file=tmp_path / "none.yaml") is None

    def test_home_is_never_treated_as_vault(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert resolve_vault_root(None, env={}, config_file=tmp_path / "none.yaml") is None


class TestInvalidVaultRoots:
    def test_relative_path_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "rel").mkdir()
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(Path("rel"))
        assert "not_absolute" in str(exc.value)

    def test_tilde_path_rejected(self):
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(Path("~/Obsidian"))
        assert "not_absolute" in str(exc.value)

    def test_nonexistent_path_rejected(self, tmp_path):
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(tmp_path / "missing")
        assert "missing" in str(exc.value)

    def test_file_instead_of_directory_rejected(self, tmp_path):
        target = tmp_path / "notes.md"
        target.write_text("x", encoding="utf-8")
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(target)
        assert "not_a_directory" in str(exc.value)

    def test_symlinked_vault_root_rejected(self, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real, target_is_directory=True)
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(link)
        assert "symlink" in str(exc.value)

    def test_home_directory_rejected(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(home)
        assert "home_directory" in str(exc.value)

    def test_repository_root_rejected(self):
        repo_root = Path(__file__).resolve().parents[2]
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(repo_root)
        assert "repository_root" in str(exc.value)

    def test_obsidian_config_dir_rejected(self, tmp_path):
        config_dir = tmp_path / ".obsidian"
        config_dir.mkdir()
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(config_dir)
        assert "obsidian_config" in str(exc.value)

    def test_nul_in_path_rejected(self):
        with pytest.raises(ProjectionConfigError):
            validate_vault_root(Path("/tmp/a\x00b"))

    def test_error_never_echoes_the_path(self, tmp_path):
        secret_dir = tmp_path / "super-secret-operator-dir"
        with pytest.raises(ProjectionConfigError) as exc:
            validate_vault_root(secret_dir)
        assert "super-secret-operator-dir" not in str(exc.value)


class TestPortability:
    def test_vault_root_with_spaces(self, tmp_path):
        vault = tmp_path / "My Obsidian Vault"
        vault.mkdir()
        config = ProjectionConfig(vault_root=vault)
        assert config.managed_root == vault / DEFAULT_MANAGED_DIR_NAME

    def test_unicode_vault_root(self, tmp_path):
        vault = tmp_path / "Kho tri thức — Zero Mem"
        vault.mkdir()
        config = ProjectionConfig(vault_root=vault)
        assert config.managed_root.parent == vault

    def test_operator_path_portability_needs_no_code_change(self, tmp_path):
        """Two different operators, one env var, zero source change."""
        for name in ("operator-a", "operator-b"):
            vault = tmp_path / name / "Zero-Mem-Vault"
            vault.mkdir(parents=True)
            env = {VAULT_ROOT_ENV_VAR: str(vault)}
            config = load_projection_config(None, env=env)
            assert config is not None
            assert config.managed_root == vault / DEFAULT_MANAGED_DIR_NAME


class TestConfigFields:
    def test_default_ceiling_is_internal(self, temp_vault):
        config = ProjectionConfig(vault_root=temp_vault)
        assert config.sensitivity_ceiling == DEFAULT_PROJECTION_SENSITIVITY_CEILING
        assert config.sensitivity_ceiling == "internal"

    def test_secret_ceiling_rejected(self, temp_vault):
        with pytest.raises(ProjectionConfigError):
            ProjectionConfig(vault_root=temp_vault, sensitivity_ceiling="secret")

    def test_unknown_ceiling_rejected(self, temp_vault):
        with pytest.raises(ProjectionConfigError):
            ProjectionConfig(vault_root=temp_vault, sensitivity_ceiling="medium")

    def test_note_types_default_to_all_curated_types(self, temp_vault):
        config = ProjectionConfig(vault_root=temp_vault)
        assert set(config.note_types) == set(NoteType)

    def test_note_types_order_is_deterministic(self, temp_vault):
        forward = ProjectionConfig(
            vault_root=temp_vault, note_types=(NoteType.DECISION, NoteType.PROJECT)
        )
        reverse = ProjectionConfig(
            vault_root=temp_vault, note_types=(NoteType.PROJECT, NoteType.DECISION)
        )
        assert forward.note_types == reverse.note_types

    def test_empty_note_types_rejected(self, temp_vault):
        with pytest.raises(ProjectionConfigError):
            ProjectionConfig(vault_root=temp_vault, note_types=())

    def test_unknown_note_type_rejected(self, temp_vault):
        with pytest.raises(ProjectionConfigError):
            ProjectionConfig(vault_root=temp_vault, note_types=("not_a_type",))  # type: ignore[arg-type]

    def test_managed_dir_name_cannot_be_obsidian_config(self, temp_vault):
        with pytest.raises(ProjectionConfigError):
            ProjectionConfig(vault_root=temp_vault, managed_dir_name=".obsidian")

    def test_managed_dir_name_cannot_traverse(self, temp_vault):
        for bad in ("..", "../escape", "/abs", "a/b", "a\\b", ".", ""):
            with pytest.raises(ProjectionConfigError):
                ProjectionConfig(vault_root=temp_vault, managed_dir_name=bad)

    def test_to_dict_excludes_absolute_paths(self, temp_vault):
        descriptor = ProjectionConfig(vault_root=temp_vault).to_dict()
        serialized = repr(descriptor)
        assert str(temp_vault) not in serialized
        assert descriptor["projection_configured"] is True

    def test_config_is_frozen(self, temp_vault):
        config = ProjectionConfig(vault_root=temp_vault)
        with pytest.raises(Exception):
            config.vault_root = Path("/elsewhere")  # type: ignore[misc]

    def test_constructing_config_creates_nothing(self, temp_vault):
        before = sorted(p.name for p in temp_vault.iterdir())
        ProjectionConfig(vault_root=temp_vault)
        assert sorted(p.name for p in temp_vault.iterdir()) == before
        assert not (temp_vault / DEFAULT_MANAGED_DIR_NAME).exists()

    def test_dry_run_must_be_bool(self, temp_vault):
        with pytest.raises(ProjectionConfigError):
            ProjectionConfig(vault_root=temp_vault, dry_run="yes")  # type: ignore[arg-type]
