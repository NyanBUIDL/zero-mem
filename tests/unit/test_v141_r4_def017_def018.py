"""V141-R4 remediation — DEF-017 + DEF-018 test portability/robustness.

DEF-017: ``tests/unit/test_v140_04_benchmark.py`` must not contain a
machine-specific absolute literal; its CORPUS_DB must resolve from
``ZM_TEST_CORPUS_DB`` first, then fall back to a repo-relative dev-data path.

DEF-018: ``tests/unit/test_m9_6_hardening.py`` must not crash with
``FileNotFoundError`` when the HOME directory does not exist on disk;
the unconfigured-vault test must skip (or pass) instead of failing.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BENCH_FILE = REPO / "tests" / "unit" / "test_v140_04_benchmark.py"
HARDENING_FILE = REPO / "tests" / "unit" / "test_m9_6_hardening.py"


class TestDef017BenchmarkPortability:
    def test_benchmark_test_file_has_no_machine_specific_literal(self):
        text = BENCH_FILE.read_text(encoding="utf-8")
        assert "/home/" not in text, (
            "test_v140_04_benchmark.py contains a machine-specific absolute "
            "path literal — resolve via ZM_TEST_CORPUS_DB / repo-relative "
            "fallback instead")

    def test_corpus_db_resolves_from_env_then_repo_relative(self, tmp_path, monkeypatch):
        import importlib

        monkeypatch.setenv("ZM_TEST_CORPUS_DB", str(tmp_path / "env.sqlite"))
        mod = importlib.import_module("tests.unit.test_v140_04_benchmark")
        importlib.reload(mod)
        assert mod.CORPUS_DB == Path(os.environ["ZM_TEST_CORPUS_DB"])

        monkeypatch.delenv("ZM_TEST_CORPUS_DB")
        mod = importlib.reload(mod)
        # The fallback must be repo-relative (derived from REPO), not a
        # machine-specific literal — equality with REPO-derived path is the
        # real property. On this dev machine REPO itself lives under /home,
        # so asserting "not /home/" would be wrong.
        expected_fallback = (
            REPO.parent / "zero-mem-dev-data" / "corpus-quant-lab"
            / "corpus-derived.sqlite")
        assert str(mod.CORPUS_DB) == str(expected_fallback)


class TestDef018HomeAbsentRobustness:
    def test_unconfigured_vault_skips_when_home_absent(self, tmp_path):
        ghost_home = tmp_path / "ghost-home-that-does-not-exist"
        assert not ghost_home.exists()
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("XDG_CONFIG_HOME", "PYTEST_CURRENT_TEST",
                         "ZM_M6_CORPUS_STORE_PATH")
        }
        env["HOME"] = str(ghost_home)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "-x",
             "tests/unit/test_m9_6_hardening.py::"
             "test_unconfigured_returns_unavailable_and_creates_nothing"],
            cwd=str(REPO), env=env, capture_output=True, text=True,
            timeout=120)
        assert result.returncode == 0, (
            f"hardening test crashed with absent HOME "
            f"(rc={result.returncode}):\n{result.stdout[-2000:]}\n"
            f"{result.stderr[-1000:]}")


def test_defect_files_exist():
    # Guard both target files still exist so the above tests fail loudly,
    # not silently, if tests are reorganized.
    assert BENCH_FILE.exists()
    assert HARDENING_FILE.exists()
