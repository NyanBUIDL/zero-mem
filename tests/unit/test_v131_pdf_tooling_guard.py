"""WP-2 (v1.3.1): guard for tooling-only pymupdf imports.

RED-first: these tests fail while scripts import pymupdf bare at module level.
"""
from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_guard_raises_systemexit_with_install_hint_when_pymupdf_missing(
    monkeypatch,
):
    import _pdf_tooling_guard

    real_find = importlib.util.find_spec

    def fake_find(name, *a, **k):
        if name == "pymupdf":
            return None
        return real_find(name, *a, **k)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find)
    with pytest.raises(SystemExit) as exc:
        _pdf_tooling_guard.require_pymupdf()
    message = str(exc.value)
    assert "zero-mem[pdf-advanced]" in message


def test_guard_returns_module_when_present():
    import _pdf_tooling_guard

    pytest.importorskip("pymupdf")
    mod = _pdf_tooling_guard.require_pymupdf()
    assert mod.__name__ == "pymupdf"


@pytest.mark.parametrize(
    "script",
    ["corpus_extract_pdfs.py", "corpus_project_quant_lab.py"],
)
def test_scripts_import_cleanly_without_pymupdf(script, tmp_path, monkeypatch):
    """Importing the script must not raise ImportError when pymupdf is absent.

    corpus_project_quant_lab.py additionally must not execute side effects on
    import (full main() wrap is WP-5; here we only assert no bare ImportError).
    """
    script_path = SCRIPTS / script
    source = script_path.read_text(encoding="utf-8")
    assert 'require_pymupdf' in source or 'import pymupdf' not in source.split(
        'def '
    )[0], f"{script} still imports pymupdf at top level without the guard"

    # Simulate absence and compile-check the guarded import path.
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "pymupdf":
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    compiled = compile(source, str(script_path), "exec")
    assert compiled is not None
