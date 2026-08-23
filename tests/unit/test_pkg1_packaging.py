"""Permanent PKG-1 release-layer contract tests."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tomllib
from pathlib import Path

import zero_mem
from zero_mem.cli import main
from zero_mem.version import __version__

ROOT = Path(__file__).resolve().parents[2]


def _project() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_single_version_source_matches_project_metadata() -> None:
    document = _project()
    project = document["project"]
    assert project["dynamic"] == ["version"]
    assert document["tool"]["setuptools"]["dynamic"]["version"]["attr"] == (
        "zero_mem.version.__version__"
    )
    assert __version__ == "1.3.3"


def test_release_and_core_namespaces_are_importable() -> None:
    import src
    import src.corpus
    import src.corpus.adapters.txt
    import src.storage.sqlite_store

    assert Path(zero_mem.__file__).name == "__init__.py"
    assert Path(src.__path__[0]).name == "src"
    assert src.corpus.__name__ == "src.corpus"


def test_console_entry_point_is_declared_exactly_once() -> None:
    document = _project()
    assert document["project"]["scripts"] == {"zero-mem": "zero_mem.cli:main"}


def test_cli_help_version_and_version_subcommand() -> None:
    help_result = subprocess.run(
        [sys.executable, "-m", "zero_mem.cli", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "usage: zero-mem" in help_result.stdout

    version_result = subprocess.run(
        [sys.executable, "-m", "zero_mem.cli", "--version"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert version_result.stdout.strip() == f"zero-mem {__version__}"

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert main(["version"]) == 0
    assert output.getvalue().strip() == __version__


def test_runtime_dependencies_are_stdlib_first_and_pdf_is_optional() -> None:
    project = _project()["project"]
    assert project["dependencies"] == []
    assert project["optional-dependencies"]["pdf"] == ["pypdf"]


def test_packaging_contract_includes_both_namespaces_and_excludes_data() -> None:
    find = _project()["tool"]["setuptools"]["packages"]["find"]
    assert set(find["include"]) == {"zero_mem*", "src*"}
    assert {"tests*", "benchmarks*", "config*", "scripts*", "output*"}.issubset(
        set(find["exclude"])
    )


def test_corpus_resolution_contract_has_no_home_or_cwd_fallback() -> None:
    from src.corpus.config import resolve_root

    assert resolve_root(None, env_name="ZERO_MEM_TEST_MISSING", config_path=None) is None


def test_release_layer_does_not_register_later_phase_commands() -> None:
    parser_output = subprocess.run(
        [sys.executable, "-m", "zero_mem.cli", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for supported in ("setup", "doctor"):
        assert f" {supported}" in parser_output
    for unfinished in ("status", "rebuild"):
        assert f" {unfinished}" not in parser_output
    assert " backup" in parser_output
    assert " upgrade" in parser_output
