"""M9.1 — path-safety and symlink-escape tests (security boundary).

The full docs/plans/plan-m9.md §10 attack matrix. Every case must fail CLOSED, inside an
OS-safe temporary vault. The operator's real vault is never referenced.

The load-bearing property under test is PHYSICAL containment: a rejection must
hold even when the path STRING looks contained, which is exactly what a symlink
component defeats.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from tests.unit._symlink_guard import require_symlinks

from src.projection.contracts import (
    META_DIR_NAME,
    NOTE_TYPE_DIRECTORIES,
    NoteType,
    OwnershipSignals,
    ProjectionPathError,
    is_zero_mem_managed,
)
from src.projection.identity import derive_note_id
from src.projection.paths import (
    MAX_RELATIVE_DEPTH,
    OBSIDIAN_CONFIG_DIR,
    assert_within_managed_root,
    is_obsidian_config_path,
    is_within_managed_root,
    managed_relative_path,
    path_ownership_signal,
    resolve_managed_root,
    safe_managed_path,
    safe_meta_path,
    safe_note_path,
    validate_path_component,
)


@pytest.fixture()
def vault():
    with tempfile.TemporaryDirectory(prefix="hermes-verify-m91-") as tmp:
        root = Path(tmp) / "Vault"
        root.mkdir()
        yield root


@pytest.fixture()
def managed(vault):
    root = resolve_managed_root(vault, "Zero-Mem")
    root.mkdir()
    return root


def _note_id() -> str:
    return derive_note_id(
        note_type=NoteType.DECISION,
        resource_type="decision",
        resource_id="DEC-1",
        project_id="proj",
        profile_id=None,
    )


class TestManagedRootResolution:
    def test_managed_root_is_beneath_vault(self, vault):
        managed = resolve_managed_root(vault, "Zero-Mem")
        assert managed.parent == vault
        assert managed.name == "Zero-Mem"

    def test_managed_root_is_deterministic(self, vault):
        assert resolve_managed_root(vault, "Zero-Mem") == resolve_managed_root(
            vault, "Zero-Mem"
        )

    def test_managed_root_is_not_created(self, vault):
        managed = resolve_managed_root(vault, "Zero-Mem")
        assert not managed.exists()

    def test_managed_root_never_the_whole_vault(self, vault):
        managed = resolve_managed_root(vault, "Zero-Mem")
        assert managed != vault
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(managed, vault)

    def test_obsidian_config_cannot_be_managed_dir(self, vault):
        with pytest.raises(ProjectionPathError):
            resolve_managed_root(vault, OBSIDIAN_CONFIG_DIR)

    def test_obsidian_config_is_outside_managed_root(self, vault, managed):
        config_dir = vault / OBSIDIAN_CONFIG_DIR
        config_dir.mkdir()
        assert not is_within_managed_root(managed, config_dir)
        assert not is_within_managed_root(managed, config_dir / "workspace.json")
        assert is_obsidian_config_path(vault, config_dir / "workspace.json")

    def test_dot_dot_managed_dir_rejected(self, vault):
        for bad in ("..", "../escape", "./x", "/abs", "a/b", "a\\b", "", "   "):
            with pytest.raises(ProjectionPathError):
                resolve_managed_root(vault, bad)

    def test_absolute_child_injection_rejected(self, vault):
        with pytest.raises(ProjectionPathError):
            resolve_managed_root(vault, "/etc")

    def test_relative_vault_root_rejected(self, vault, monkeypatch):
        monkeypatch.chdir(vault.parent)
        with pytest.raises(ProjectionPathError):
            resolve_managed_root(Path("Vault"), "Zero-Mem")

    def test_managed_root_symlink_to_outside_rejected(self, vault, tmp_path):
        require_symlinks()  # WP-05: skip when platform cannot create symlinks
        outside = tmp_path / "outside"
        outside.mkdir()
        link = vault / "Zero-Mem"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ProjectionPathError) as exc:
            resolve_managed_root(vault, "Zero-Mem")
        assert "symlink" in str(exc.value)

    def test_managed_root_as_file_rejected(self, vault):
        (vault / "Zero-Mem").write_text("x", encoding="utf-8")
        with pytest.raises(ProjectionPathError):
            resolve_managed_root(vault, "Zero-Mem")


class TestComponentValidation:
    @pytest.mark.parametrize(
        "component",
        [
            "..",
            ".",
            "",
            "/x",
            "x/y",
            "x\\y",
            "..\\..\\foo",
            "C:",
            "C:\\x",
            "C:/x",
            "a:b",
            "a\x00b",
            "a\nb",
            "a\tb",
            "a\x7fb",
            " leading",
            "trailing ",
            "trailing.",
            ".hidden",
            "CON",
            "con.md",
            "NUL",
            "nul.md",
            "COM1",
            "LPT9",
            "x" * 500,
        ],
    )
    def test_unsafe_component_rejected(self, component):
        with pytest.raises(ProjectionPathError):
            validate_path_component(component)

    @pytest.mark.parametrize(
        "component", ["Decisions", "project-alpha", "note--abc123.md", META_DIR_NAME]
    )
    def test_safe_component_accepted(self, component):
        assert validate_path_component(component) == component

    def test_error_reason_does_not_echo_value(self):
        with pytest.raises(ProjectionPathError) as exc:
            validate_path_component("../../etc/passwd")
        assert "passwd" not in str(exc.value)


class TestSafeManagedPath:
    @pytest.mark.parametrize(
        "components",
        [
            ("..", "x.md"),
            ("..", "..", "x.md"),
            ("/x",),
            ("C:\\x",),
            ("C:/x",),
            ("foo/bar",),
            ("foo\\bar",),
            (".",),
            ("",),
            ("\x00",),
            ("Decisions", "..", "..", "..", "etc"),
        ],
    )
    def test_traversal_and_injection_rejected(self, managed, components):
        with pytest.raises(ProjectionPathError):
            safe_managed_path(managed, *components)

    def test_depth_cap_enforced(self, managed):
        with pytest.raises(ProjectionPathError):
            safe_managed_path(managed, "a", "b", "c", "d")

    def test_valid_depth_allowed(self, managed):
        target = safe_managed_path(managed, "Decisions", "proj", "note.md")
        assert target.parent.parent.parent == managed

    def test_total_length_bounded(self, managed):
        with pytest.raises(ProjectionPathError):
            safe_managed_path(managed, "a" * 100, "b" * 100, "c" * 100)

    def test_meta_path_contained(self, managed):
        target = safe_meta_path(managed, "manifest.json")
        assert target.parent == managed / META_DIR_NAME
        assert is_within_managed_root(managed, target)

    def test_nothing_is_created_by_validation(self, managed):
        before = sorted(p.name for p in managed.iterdir())
        safe_managed_path(managed, "Decisions", "proj", "note.md")
        safe_meta_path(managed, "manifest.json")
        assert sorted(p.name for p in managed.iterdir()) == before


class TestSafeNotePath:
    def test_category_comes_from_closed_enum(self, managed):
        note_id = _note_id()
        for note_type in NoteType:
            typed_id = derive_note_id(
                note_type=note_type,
                resource_type="decision",
                resource_id="R-1",
                project_id="proj",
            )
            target = safe_note_path(
                managed,
                note_type=note_type,
                note_id=typed_id,
                display_title="Title",
                scope="proj",
            )
            assert target.parent.parent.name == NOTE_TYPE_DIRECTORIES[note_type]
            assert is_within_managed_root(managed, target)
        assert note_id  # sanity

    @pytest.mark.parametrize(
        "title",
        [
            "../../secret",
            "/home/user/file",
            "A/B/C",
            "..\\..\\foo",
            "CON",
            "NUL",
            "..",
            ".",
            "",
            "   ",
            "!!!???",
            "a" * 5000,
            "\x00nul",
            "\u202eevil",       # right-to-left override
            "zero\u200bwidth",  # zero-width space
            "café",             # NFC/NFD ambiguity
            "cafe\u0301",       # decomposed form of the same word
            "#tag [[link]] |pipe",
            "---\nfake: yaml",
        ],
    )
    def test_hostile_title_stays_contained(self, managed, title):
        target = safe_note_path(
            managed,
            note_type=NoteType.DECISION,
            note_id=_note_id(),
            display_title=title,
            scope="proj",
        )
        assert is_within_managed_root(managed, target)
        assert target.parent == managed / "Decisions" / "proj"
        assert target.name.endswith(".md")
        assert "/" not in target.name and "\\" not in target.name

    @pytest.mark.parametrize(
        "scope", ["../../etc", "/etc", "a/b", "..", ".", "", "CON", "\x00x"]
    )
    def test_hostile_scope_stays_contained(self, managed, scope):
        target = safe_note_path(
            managed,
            note_type=NoteType.DECISION,
            note_id=_note_id(),
            display_title="Title",
            scope=scope,
        )
        assert is_within_managed_root(managed, target)
        assert target.parent.parent == managed / "Decisions"

    def test_malicious_title_cannot_choose_parent_directory(self, managed):
        target = safe_note_path(
            managed,
            note_type=NoteType.DECISION,
            note_id=_note_id(),
            display_title="../../../Requirements/owned",
            scope="proj",
        )
        assert target.parent == managed / "Decisions" / "proj"

    def test_unknown_note_type_rejected(self, managed):
        with pytest.raises(Exception):
            safe_note_path(
                managed,
                note_type="not_a_type",  # type: ignore[arg-type]
                note_id=_note_id(),
                display_title="x",
                scope="proj",
            )


class TestSymlinkEscape:
    @pytest.fixture(autouse=True)
    def _symlink_guard(self):
        require_symlinks()  # WP-05: skip when platform cannot create symlinks

    def test_symlink_inside_managed_root_to_outside(self, managed, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (managed / "safe-link").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ProjectionPathError) as exc:
            safe_managed_path(managed, "safe-link", "file.md")
        assert "symlink" in str(exc.value)

    def test_lexical_check_alone_would_have_passed(self, managed, tmp_path):
        """Proof the guard is physical, not lexical."""
        outside = tmp_path / "outside"
        outside.mkdir()
        (managed / "safe-link").symlink_to(outside, target_is_directory=True)
        target = managed / "safe-link" / "file.md"
        assert target.is_relative_to(managed)          # lexical check passes
        assert not is_within_managed_root(managed, target)  # physical check fails

    def test_nested_symlink_to_outside(self, managed, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        nested = managed / "Decisions"
        nested.mkdir()
        (nested / "proj").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ProjectionPathError):
            safe_managed_path(managed, "Decisions", "proj", "file.md")

    def test_existing_parent_symlink_rejected(self, managed, tmp_path):
        outside = tmp_path / "outside"
        (outside / "deep").mkdir(parents=True)
        (managed / "Decisions").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(managed, managed / "Decisions" / "deep" / "n.md")

    def test_target_filename_beneath_escaping_symlink(self, managed, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (managed / "Artifacts").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ProjectionPathError):
            safe_note_path(
                managed,
                note_type=NoteType.ARTIFACT,
                note_id=derive_note_id(
                    note_type=NoteType.ARTIFACT,
                    resource_type="artifact",
                    resource_id="A-1",
                ),
                display_title="x",
                scope="proj",
            )

    def test_file_symlink_target_rejected(self, managed, tmp_path):
        outside_file = tmp_path / "outside.md"
        outside_file.write_text("human data", encoding="utf-8")
        nested = managed / "Decisions" / "proj"
        nested.mkdir(parents=True)
        (nested / "note.md").symlink_to(outside_file)
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(managed, nested / "note.md")

    def test_managed_root_symlink_attack(self, vault, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        link = vault / "Zero-Mem"
        link.symlink_to(outside, target_is_directory=True)
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(link, link / "note.md")

    def test_symlink_pointing_back_inside_still_rejected(self, managed):
        """Even a benign-looking symlink fails closed: ownership must stay decidable."""
        real = managed / "Decisions"
        real.mkdir()
        (managed / "alias").symlink_to(real, target_is_directory=True)
        with pytest.raises(ProjectionPathError):
            safe_managed_path(managed, "alias", "proj", "note.md")

    def test_rejection_happens_before_any_write(self, managed, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (managed / "safe-link").symlink_to(outside, target_is_directory=True)
        before = sorted(p.name for p in outside.iterdir())
        with pytest.raises(ProjectionPathError):
            safe_managed_path(managed, "safe-link", "file.md")
        assert sorted(p.name for p in outside.iterdir()) == before
        assert not (outside / "file.md").exists()


class TestContainmentEdgeCases:
    def test_absolute_outside_path_rejected(self, managed, tmp_path):
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(managed, tmp_path / "elsewhere.md")

    def test_managed_root_itself_is_not_a_target(self, managed):
        with pytest.raises(ProjectionPathError) as exc:
            assert_within_managed_root(managed, managed)
        assert "managed_root" in str(exc.value)

    def test_parent_of_managed_root_rejected(self, vault, managed):
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(managed, vault / "human-note.md")

    def test_relative_target_rejected(self, managed):
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(managed, Path("relative.md"))

    def test_sibling_prefix_directory_rejected(self, vault, managed):
        """`Zero-Mem-Other/` must not count as inside `Zero-Mem/`."""
        sibling = vault / "Zero-Mem-Other"
        sibling.mkdir()
        assert not is_within_managed_root(managed, sibling / "note.md")

    def test_not_yet_existing_target_is_supported(self, managed):
        target = managed / "Decisions" / "proj" / "unwritten.md"
        assert is_within_managed_root(managed, target)
        assert not target.exists()

    def test_managed_relative_path_is_posix_and_relative(self, managed):
        nested = managed / "Decisions" / "proj"
        nested.mkdir(parents=True)
        note = nested / "note.md"
        note.write_text("x", encoding="utf-8")
        assert managed_relative_path(managed, note) == "Decisions/proj/note.md"


class TestOwnershipFoundation:
    def test_path_alone_is_only_a_signal(self, managed):
        human = managed / "human.md"
        human.write_text("human note", encoding="utf-8")
        assert path_ownership_signal(managed, human) is True
        assert is_zero_mem_managed(OwnershipSignals(inside_managed_root=True)) is False

    def test_all_three_signals_required(self):
        assert is_zero_mem_managed(
            OwnershipSignals(
                inside_managed_root=True,
                has_managed_marker=True,
                listed_in_manifest=True,
            )
        )
        for missing in ("inside_managed_root", "has_managed_marker", "listed_in_manifest"):
            kwargs = {
                "inside_managed_root": True,
                "has_managed_marker": True,
                "listed_in_manifest": True,
                missing: False,
            }
            assert is_zero_mem_managed(OwnershipSignals(**kwargs)) is False

    def test_missing_signals_reported_deterministically(self):
        signals = OwnershipSignals()
        assert signals.missing_signals == (
            "inside_managed_root",
            "has_managed_marker",
            "listed_in_manifest",
        )

    def test_existing_human_file_at_generated_target_is_not_claimed(self, managed):
        """A filename collision is never ownership."""
        note_id = _note_id()
        target = safe_note_path(
            managed,
            note_type=NoteType.DECISION,
            note_id=note_id,
            display_title="Adopt SQLite",
            scope="proj",
        )
        target.parent.mkdir(parents=True)
        target.write_text("human wrote this by hand", encoding="utf-8")

        signals = OwnershipSignals(
            inside_managed_root=path_ownership_signal(managed, target),
            has_managed_marker=False,   # no frontmatter marker
            listed_in_manifest=False,   # not in any manifest
        )
        assert signals.inside_managed_root is True
        assert is_zero_mem_managed(signals) is False
        assert target.read_text(encoding="utf-8") == "human wrote this by hand"

    def test_obsidian_path_is_rejected_by_containment(self, vault, managed):
        config_file = vault / OBSIDIAN_CONFIG_DIR / "workspace.json"
        config_file.parent.mkdir()
        config_file.write_text("{}", encoding="utf-8")
        assert path_ownership_signal(managed, config_file) is False
        with pytest.raises(ProjectionPathError):
            assert_within_managed_root(managed, config_file)

    def test_outside_file_is_never_owned(self, managed, tmp_path):
        outside = tmp_path / "human.md"
        outside.write_text("mine", encoding="utf-8")
        assert path_ownership_signal(managed, outside) is False
