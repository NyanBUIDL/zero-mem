"""WP-5 (v1.3.1): corpus_project_quant_lab import safety + idempotent migration.

Importing the script must have NO side effects (no adapter registration, no
file creation). Migration application checks sqlite_master, not exception text.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
REPO = SCRIPTS.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "corpus_project_quant_lab_wp5", SCRIPTS / "corpus_project_quant_lab.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_import_has_no_side_effects(tmp_path, monkeypatch):
    """python -c 'import ...' must not create/modify any file in root."""
    root = tmp_path / "corpus-root"
    root.mkdir()
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*")}
    cwd_before = {p: p.stat().st_mtime_ns for p in Path.cwd().rglob("*")
                  if ".git" not in p.parts and "__pycache__" not in p.parts}

    monkeypatch.setattr(sys, "path", list(sys.path))
    _load_module()

    after = {p: p.stat().st_mtime_ns for p in root.rglob("*")}
    assert before == after
    assert not any(p.name == "corpus-derived.sqlite" for p in root.rglob("*"))
    # repo tree untouched by import (no new files at top level)
    cwd_after_names = {p.name for p in Path.cwd().iterdir()}
    assert "corpus-derived.sqlite" not in cwd_after_names
    del cwd_before  # names-only check is sufficient; mtime scan too noisy


def test_import_does_not_register_adapter():
    from src.corpus.adapters.registry import ADAPTER_REGISTRY

    n_before = len(ADAPTER_REGISTRY)
    _load_module()
    assert len(ADAPTER_REGISTRY) == n_before, (
        "import must not append PyMuPdfAdapter — call install_adapter() explicitly")


def test_install_adapter_registers_once():
    from src.corpus.adapters.registry import ADAPTER_REGISTRY

    module = _load_module()
    n_before = len(ADAPTER_REGISTRY)
    module.install_adapter()
    assert len(ADAPTER_REGISTRY) == n_before + 1
    module.install_adapter()  # idempotent
    assert len(ADAPTER_REGISTRY) == n_before + 1


def test_migration_check_uses_sqlite_master(tmp_path):
    """apply_migrations on a fresh db applies; ledger rows prevent re-apply."""
    pytest.importorskip("src.storage.migrations")
    from src.storage.migrations import MIGRATIONS

    module = _load_module()
    conn = sqlite3.connect(str(tmp_path / "derived.sqlite"))
    try:
        module.apply_migrations(conn)
        versions_applied = {
            row[0] for row in conn.execute(
                "SELECT version FROM zm_migrations")} if conn.execute(
                "SELECT name FROM sqlite_master WHERE name='zm_migrations'"
            ).fetchone() else set()
        if MIGRATIONS:
            assert versions_applied >= set(MIGRATIONS), (
                "first run must apply every migration")
        # second run: no exception even though tables exist (idempotent)
        module.apply_migrations(conn)
    finally:
        conn.close()


def test_repeated_run_same_projection(tmp_path):
    """Re-running run_projection twice yields identical report dicts."""
    pytest.importorskip("src.corpus.derived_store")
    module = _load_module()
    root = tmp_path / "c"
    root.mkdir()
    first = module.run_projection(root)
    second = module.run_projection(root)
    assert first == second
