#!/usr/bin/env python3
"""Run the PKG-1 installed-wheel acceptance outside the repository.

Usage: python tests/packaging/pkg1_wheel_acceptance.py dist/zero_mem-X.Y.Z-py3-none-any.whl
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _path_is_within(candidate: Path, root: Path) -> bool:
    """Return whether *candidate* is actually inside *root*, not just prefix-matching it."""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if wheel.suffix != ".whl" or not wheel.is_file():
        raise SystemExit(f"wheel not found: {wheel}")

    repo = Path(__file__).resolve().parents[2]
    default_test_root = repo.parent / "zero-mem-dev-data" / "pytest"
    test_root = Path(os.environ.get("ZERO_MEM_TEST_ROOT", str(default_test_root))).expanduser().resolve()
    test_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pkg1-", dir=str(test_root)) as temp:
        root = Path(temp)
        venv = root / "fresh venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, text=True)
        scripts_dir = venv / ("Scripts" if os.name == "nt" else "bin")
        python = scripts_dir / ("python.exe" if os.name == "nt" else "python")
        zero_mem = scripts_dir / ("zero-mem.exe" if os.name == "nt" else "zero-mem")
        pip = [str(python), "-m", "pip"]
        subprocess.run(
            pip + ["install", "--no-index", "--no-deps", str(wheel)],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"
        env["HOME"] = str(root / "home with spaces")
        env["PYTHONPATH"] = ""
        expected_version = run(
            [str(python), "-c", 'import importlib.metadata as m; print(m.version("zero-mem"))'],
            cwd=root,
            env=env,
        )
        code = (
            "import importlib.metadata as m, importlib.util, pathlib, zero_mem, src, src.corpus, "
            "src.storage.sqlite_store; "
            'assert zero_mem.__version__ == m.version("zero-mem"); '
            "assert 'site-packages' in str(pathlib.Path(zero_mem.__file__)); "
            "assert 'site-packages' in str(pathlib.Path(src.__path__[0])); "
            "assert importlib.util.find_spec('pypdf') is None; "
            "print(zero_mem.__file__); print(src.__path__[0])"
        )
        imports = run([str(python), "-c", code], cwd=root, env=env)
        help_text = run([str(zero_mem), "--help"], cwd=root, env=env)
        version_flag = run([str(zero_mem), "--version"], cwd=root, env=env)
        version_command = run([str(zero_mem), "version"], cwd=root, env=env)
        assert "usage: zero-mem" in help_text
        assert version_flag == f"zero-mem {expected_version}"
        assert version_command == expected_version
        import_paths = [Path(line) for line in imports.splitlines()]
        assert import_paths
        assert all(not _path_is_within(path, repo) for path in import_paths)
        print(f"wheel={wheel.name}")
        print(f"venv={venv}")
        print(f"imports={imports.replace(chr(10), ' | ')}")
        print("path_with_spaces=PASS")
        print("pypdf_absent=PASS")
        print("repository_independent=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
