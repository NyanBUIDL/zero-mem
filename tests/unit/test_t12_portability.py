"""T12 - cross-platform portability regressions (DEF-085..), simulated on Linux.

Each test reproduces on POSIX the exact condition that failed on Windows / macOS CI.
"""
from __future__ import annotations

import os
import sys

import pytest

from tests.unit._symlink_guard import require_symlinks


# ---- Windows: os.pread does not exist --------------------------------------------------------
def test_append_canonical_event_works_without_os_pread(tmp_path, monkeypatch):
    from zero_mem.provisioning import append_canonical_event

    monkeypatch.delattr(os, "pread", raising=False)
    stream = tmp_path / "events.jsonl"
    append_canonical_event(stream, {"event_id": "e1"})
    append_canonical_event(stream, {"event_id": "e2"})
    assert stream.read_bytes() == b'{"event_id":"e1"}\n{"event_id":"e2"}\n'


def test_append_canonical_event_still_refuses_a_torn_tail_without_os_pread(tmp_path, monkeypatch):
    from zero_mem.provisioning import ProvisioningError, append_canonical_event

    monkeypatch.delattr(os, "pread", raising=False)
    stream = tmp_path / "events.jsonl"
    stream.write_bytes(b'{"event_id":"e1"')
    with pytest.raises(ProvisioningError) as exc:
        append_canonical_event(stream, {"event_id": "e2"})
    assert exc.value.code == "stream_not_terminated"


def test_no_posix_only_os_calls_in_product_code():
    """pread/pwrite/fork/getuid/mkfifo have no Windows equivalent: product code must not call them bare."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    banned = re.compile(r"\bos\.(pread|pwrite|fork|getuid|geteuid|getgid|mkfifo|killpg|setsid)\(")
    hits = []
    for base in ("zero_mem", "src"):
        for path in (root / base).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if banned.search(line) and not line.lstrip().startswith("#"):
                    hits.append(f"{path.relative_to(root)}:{number}")
    assert hits == []


# ---- Windows: DirEntry.stat() reports st_dev/st_ino == 0 --------------------------------------
def test_directory_walk_does_not_flag_nested_dirs_as_loops_when_entry_stat_has_no_inode(tmp_path, monkeypatch):
    from src.corpus import detect_kind as mod

    (tmp_path / "a.md").write_text("alpha beta gamma\n", encoding="utf-8")
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "sub" / "c.txt").write_text("charlie\n", encoding="utf-8")
    (tmp_path / "sub" / "deep" / "d.txt").write_text("delta\n", encoding="utf-8")

    real_scandir = os.scandir

    class _Entry:
        def __init__(self, entry):
            self._e = entry
            self.name, self.path = entry.name, entry.path

        def stat(self, *, follow_symlinks=True):
            info = self._e.stat(follow_symlinks=follow_symlinks)
            fields = list(info)
            fields[1] = 0  # st_ino
            fields[2] = 0  # st_dev
            return os.stat_result(fields)

    monkeypatch.setattr(mod.os, "scandir", lambda p: [_Entry(e) for e in real_scandir(p)])
    walk = mod.iter_ingestable(tmp_path)
    got = sorted(rel for rel, _p, _k in walk)
    assert got == ["a.md", "sub/c.txt", "sub/deep/d.txt"]
    assert not [s for s in walk.skipped if s.reason == "symlink_loop"]


def test_directory_symlink_loop_is_still_detected(tmp_path):
    require_symlinks()
    from src.corpus.detect_kind import iter_ingestable

    (tmp_path / "a.md").write_text("alpha beta\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "loop").symlink_to(tmp_path, target_is_directory=True)
    walk = iter_ingestable(tmp_path, follow_symlinks=True)
    assert [rel for rel, _p, _k in walk] == ["a.md"]
    assert any(s.reason == "symlink_loop" for s in walk.skipped)


# ---- macOS: temp dirs live behind a /var -> /private/var alias --------------------------------
def test_memory_qa_benchmark_engine_accepts_a_symlink_aliased_temp_root(tmp_path, monkeypatch):
    require_symlinks()
    import tempfile

    real = tmp_path / "private" / "var"
    real.mkdir(parents=True)
    alias = tmp_path / "var"
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(alias))
    sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    from benchmarks import memory_qa_benchmark as bench

    haystack, cleanup = bench._open_haystack([("the quokka likes apples", "t")], "turn", bench.MemoryEngine, None)
    try:
        assert haystack.adds >= 1
    finally:
        cleanup()


def test_layout_still_rejects_a_symlinked_ancestor_the_caller_did_not_resolve(tmp_path):
    require_symlinks()
    from zero_mem.memory_layout import Layout, LayoutError

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(LayoutError):
        Layout.resolve(link / "zm").ensure()


def test_layout_accepts_the_same_root_once_resolved(tmp_path):
    require_symlinks()
    from zero_mem.memory_layout import Layout

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    layout = Layout.resolve((link / "zm").resolve())
    layout.ensure()
    assert layout.memory_stream.is_file()


def test_layout_rejects_a_symlink_planted_inside_the_data_dir(tmp_path):
    require_symlinks()
    from zero_mem.memory_layout import Layout, LayoutError

    root = tmp_path / "zm"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root.mkdir()
    (root / "data").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(LayoutError):
        Layout.resolve(root).ensure()
    assert not any(elsewhere.iterdir())


# ---- Windows: redirected stdio uses the ANSI code page (cp1252) ------------------------------
def test_cli_prints_non_latin_text_even_when_stdio_defaults_to_cp1252(tmp_path):
    import subprocess

    env = {**os.environ, "ZERO_MEM_DATA_ROOT": str(tmp_path / "zm"), "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
           "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252", "LC_ALL": "C.UTF-8"}  # argv/paths UTF-8, streams ANSI
    env.pop("ZERO_MEM_CORPUS_ROOT", None)
    code = "import sys; from zero_mem.cli import main; sys.exit(main(sys.argv[1:]))"
    add = subprocess.run([sys.executable, "-c", code, "add", "Truyện 日本語 quokka"], env=env, capture_output=True)
    assert add.returncode == 0, add.stderr
    found = subprocess.run([sys.executable, "-c", code, "search", "quokka"], env=env, capture_output=True)
    assert found.returncode == 0, found.stderr
    assert "日本語".encode("utf-8") in found.stdout


def test_use_utf8_stdio_reconfigures_a_non_utf8_stream_and_tolerates_foreign_ones(monkeypatch):
    import io

    from src.storage.platform import use_utf8_stdio

    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="\r\n")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", object())  # no reconfigure(): left alone
    use_utf8_stdio(lf_newlines=True)
    out.write("日本語\n")
    out.flush()
    assert out.buffer.getvalue() == "日本語\n".encode("utf-8")
