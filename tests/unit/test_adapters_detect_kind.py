"""T4 — detect_kind (extension + magic bytes -> registry kind hint) and iter_ingestable."""
from __future__ import annotations

import os
import stat

import pytest

from src.corpus.adapters import select_adapter
from src.corpus.detect_kind import (
    DEFAULT_MAX_BYTES,
    IngestPathError,
    detect_kind,
    iter_ingestable,
)

from tests.unit.adapters_fixtures import (
    make_bmp,
    make_docx,
    make_gif,
    make_jpeg,
    make_png,
    make_pptx,
    make_tiff,
    make_webp,
    make_xlsx,
    zip_bytes,
)

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"


# ---------------------------------------------------------------------------
# detect_kind: magic bytes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("content,expected", [
    (PDF, "pdf"),
    (make_png(), "png"),
    (make_jpeg(), "jpg"),
    (make_gif(), "gif"),
    (make_bmp(), "bmp"),
    (make_webp(), "webp"),
    (make_tiff(), "tiff"),
    (make_tiff(big_endian=True), "tiff"),
    (make_docx([("p", "x")]), "docx"),
    (make_xlsx([("S", [["a"]])]), "xlsx"),
    (make_pptx([{"title": "t"}]), "pptx"),
])
def test_magic_bytes_decide_without_a_filename(content, expected):
    assert detect_kind(None, content) == expected


@pytest.mark.parametrize("name", ["", "noext", "wrong.txt", "wrong.md", "photo.PNG"])
def test_content_beats_extension_for_binary_formats(name):
    assert detect_kind(name, make_png()) == "png"
    assert detect_kind(name, PDF) == "pdf"


def test_zip_container_is_inspected_by_member_names():
    assert detect_kind("a.zip", make_docx([("p", "x")])) == "docx"
    assert detect_kind("renamed.bin", make_xlsx([("S", [["a"]])])) == "xlsx"
    assert detect_kind("renamed.bin", make_pptx([{"title": "t"}])) == "pptx"


def test_plain_zip_and_other_archives_are_binary():
    assert detect_kind("a.zip", zip_bytes({"a.txt": "hello"})) == "binary"
    assert detect_kind("a.gz", b"\x1f\x8b\x08\x00" + bytes(40)) == "binary"
    assert detect_kind("a.exe", b"MZ\x90\x00" + bytes(60)) == "binary"
    assert detect_kind("legacy.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(100)) == "binary"
    assert detect_kind("a.sqlite", b"SQLite format 3\x00" + bytes(100)) == "binary"


def test_unreadable_zip_falls_back_to_office_extension_else_binary():
    broken = make_docx([("p", "x" * 500)])[:100]
    assert detect_kind("report.docx", broken) == "docx"  # adapter will say corrupt_source
    assert detect_kind("report.xlsx", broken) == "xlsx"
    assert detect_kind("report.bin", broken) == "binary"


def test_hostile_entry_count_is_binary_without_listing_the_archive(monkeypatch):
    import src.corpus.detect_kind as mod

    many = zip_bytes({f"f{i}.bin": b"x" for i in range(200)})
    monkeypatch.setattr(mod, "_MAX_ZIP_ENTRIES_SNIFFED", 50)
    monkeypatch.setattr(mod.zipfile, "ZipFile", lambda *a, **k: (_ for _ in ()).throw(AssertionError("listed")))
    assert detect_kind("bomb.docx", many) == "binary"


def test_empty_zip_signature():
    assert detect_kind("x.zip", b"PK\x05\x06" + bytes(18)) == "binary"


def test_bmp_magic_needs_plausible_dib_header():
    assert detect_kind("t.bmp", b"BM is not a bitmap, just text starting with BM") == "txt"


# ---------------------------------------------------------------------------
# detect_kind: text sniffing + extensions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("notes.md", "md"), ("README.MD", "md"), ("a/b/c.markdown", "md"), ("x.mdown", "md"),
    ("data.csv", "csv"), ("DATA.CSV", "csv"), ("data.tsv", "tsv"), ("data.tab", "tsv"),
    ("conf.json", "json"), ("log.jsonl", "jsonl"), ("log.ndjson", "jsonl"),
    ("a.txt", "txt"), ("server.log", "txt"), ("script.py", "txt"), ("noext", "txt"), ("", "txt"),
    (".hidden", "txt"), ("archive.tar.txt", "txt"),
])
def test_text_extension_mapping(name, expected):
    assert detect_kind(name, b"some plain text content\nline two\n") == expected


def test_filename_none_text_defaults_to_txt():
    assert detect_kind(None, b"hello world\n") == "txt"


def test_extensionless_json_is_sniffed():
    assert detect_kind("blob", b'{"a": 1, "b": [1,2,3]}') == "json"
    assert detect_kind(None, b'  \n[{"a": 1}]') == "json"


def test_extensionless_jsonl_is_sniffed():
    data = b'{"role":"user","content":"a"}\n{"role":"assistant","content":"b"}\n'
    assert detect_kind("transcript", data) == "jsonl"


def test_text_that_merely_starts_with_a_brace_is_not_json():
    assert detect_kind("notes", b"{not json at all, just prose") == "txt"


def test_json_extension_with_bad_content_still_json_for_corrupt_reporting():
    assert detect_kind("broken.json", b"{oops") == "json"


def test_utf16_bom_text_is_text_not_binary():
    assert detect_kind("w.txt", "hello\nworld".encode("utf-16")) == "txt"
    assert detect_kind("w.csv", "a,b\n1,2\n".encode("utf-16")) == "csv"


def test_latin1_text_is_text():
    assert detect_kind("old.txt", "café naïve résumé".encode("latin-1")) == "txt"


def test_nul_bytes_mean_binary_even_with_text_extension():
    assert detect_kind("data.csv", b"a,b\x00\x01\x02\n1,2\n") == "binary"
    assert detect_kind("x.md", bytes(range(256)) * 4) == "binary"


def test_multibyte_char_split_at_sniff_boundary_is_still_text():
    content = ("a" + "é" * 40_000).encode("utf-8")  # the 64 KiB sniff window cuts a 2-byte char
    assert detect_kind("long.txt", content) == "txt"


def test_empty_content_follows_text_extension_else_txt():
    assert detect_kind("a.md", b"") == "md"
    assert detect_kind("a.csv", b"") == "csv"
    assert detect_kind("a.png", b"") == "txt"
    assert detect_kind("a.docx", b"") == "txt"
    assert detect_kind(None, b"") == "txt"


def test_text_named_like_an_image_is_text():
    assert detect_kind("fake.png", b"just words, not pixels") == "txt"


def test_every_detected_kind_is_resolvable_or_binary():
    samples = [
        ("a.md", b"# h"), ("a.csv", b"a,b"), ("a.tsv", b"a\tb"), ("a.json", b"{}"), ("a.jsonl", b"{}\n"),
        ("a.txt", b"x"), (None, make_png()), (None, make_jpeg()), (None, PDF),
        (None, make_docx([("p", "x")])), (None, make_xlsx([("S", [["a"]])])), (None, make_pptx([{"title": "t"}])),
    ]
    for name, content in samples:
        kind = detect_kind(name, content)
        assert kind == "binary" or select_adapter(kind) is not None, (name, kind)
    assert select_adapter("binary") is None


# ---------------------------------------------------------------------------
# iter_ingestable
# ---------------------------------------------------------------------------

@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "sub" / "deep").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "node_modules" / "pkg").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / ".secret_dir").mkdir()
    (root / "a.md").write_text("# Alpha\n\nbody\n")
    (root / "b.txt").write_text("plain text\n")
    (root / "data.csv").write_text("k,v\n1,2\n")
    (root / "sub" / "c.json").write_text('{"x": 1}')
    (root / "sub" / "deep" / "d.docx").write_bytes(make_docx([("p", "deep doc")]))
    (root / ".hidden.txt").write_text("dotfile")
    (root / ".git" / "config").write_text("[core]\n")
    (root / ".secret_dir" / "inside.txt").write_text("inside hidden dir")
    (root / "node_modules" / "pkg" / "index.js").write_text("module.exports = 1")
    (root / "__pycache__" / "m.pyc").write_bytes(b"\x00\x01")
    (root / "empty.txt").write_bytes(b"")
    (root / "blob.dat").write_bytes(bytes(range(256)) * 8)
    (root / "image.png").write_bytes(make_png())
    return root


def _walk(*args, **kw):
    walk = iter_ingestable(*args, **kw)
    items = list(walk)
    return items, walk


def test_walk_yields_sorted_relative_names_with_kinds_and_skips_junk(tree):
    items, walk = _walk(tree)
    got = [(rel, kind) for rel, _path, kind in items]
    assert got == [
        ("a.md", "md"),
        ("b.txt", "txt"),
        ("data.csv", "csv"),
        ("image.png", "png"),
        ("sub/c.json", "json"),
        ("sub/deep/d.docx", "docx"),
    ]
    reasons = {(s.relative_name, s.reason) for s in walk.skipped}
    assert (".hidden.txt", "hidden") in reasons
    assert (".git", "hidden") in reasons
    assert (".secret_dir", "hidden") in reasons
    assert ("node_modules", "excluded_dir") in reasons
    assert ("__pycache__", "excluded_dir") in reasons
    assert ("empty.txt", "empty") in reasons
    assert ("blob.dat", "unsupported_binary") in reasons
    assert not any("inside.txt" in s.relative_name or "index.js" in s.relative_name for s in walk.skipped)


def test_walk_is_deterministic(tree):
    a = [(r, k) for r, _p, k in iter_ingestable(tree)]
    b = [(r, k) for r, _p, k in iter_ingestable(tree)]
    assert a == b


def test_items_unpack_as_triples_and_read_bytes(tree):
    items, _ = _walk(tree)
    rel, path, kind = items[0]
    assert rel == "a.md" and kind == "md"
    assert items[0].read_bytes() == (tree / "a.md").read_bytes()
    assert path == tree / "a.md"
    for item in items:
        assert item.kind == detect_kind(item.relative_name, item.read_bytes())


def test_oversized_files_are_skipped_with_reason(tree):
    (tree / "huge.txt").write_bytes(b"x" * 5000)
    items, walk = _walk(tree, max_bytes=1000)
    assert "huge.txt" not in [i.relative_name for i in items]
    assert any(s.relative_name == "huge.txt" and s.reason == "oversized" for s in walk.skipped)
    assert DEFAULT_MAX_BYTES >= 1 << 20


def test_symlinks_are_skipped_by_default(tree, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret")
    os.symlink(outside, tree / "link_out.txt")
    os.symlink(tree / "a.md", tree / "link_in.md")
    os.symlink(tree / "sub", tree / "linkdir")
    items, walk = _walk(tree)
    names = [i.relative_name for i in items]
    assert not any(n.startswith(("link_out", "link_in", "linkdir")) for n in names)
    reasons = {s.relative_name: s.reason for s in walk.skipped}
    assert reasons["link_out.txt"] == "symlink"
    assert reasons["link_in.md"] == "symlink"
    assert reasons["linkdir"] == "symlink"


def test_follow_symlinks_confined_to_allow_roots(tree, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret")
    os.symlink(outside, tree / "link_out.txt")
    os.symlink(tree / "a.md", tree / "link_in.md")
    items, walk = _walk(tree, follow_symlinks=True, allow_roots=[tree])
    names = [i.relative_name for i in items]
    assert "link_in.md" in names
    assert "link_out.txt" not in names
    assert any(s.relative_name == "link_out.txt" and s.reason == "outside_allowed_roots" for s in walk.skipped)


def test_follow_symlinks_without_allow_roots_still_confined_to_walk_root(tree, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret")
    os.symlink(outside, tree / "link_out.txt")
    items, walk = _walk(tree, follow_symlinks=True)
    assert "link_out.txt" not in [i.relative_name for i in items]
    assert any(s.reason == "outside_allowed_roots" for s in walk.skipped)


def test_symlink_directory_loop_terminates(tree):
    os.symlink(tree, tree / "sub" / "loop")
    items, walk = _walk(tree, follow_symlinks=True, allow_roots=[tree])
    names = [i.relative_name for i in items]
    assert len(names) == len(set(names))
    assert len(names) < 100


def test_path_outside_allow_roots_is_refused(tree, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(IngestPathError):
        list(iter_ingestable(tree, allow_roots=[other]))


def test_missing_path_and_non_directory_semantics(tree, tmp_path):
    with pytest.raises(IngestPathError):
        list(iter_ingestable(tmp_path / "nope"))
    items, _ = _walk(tree / "a.md")
    assert [(i.relative_name, i.kind) for i in items] == [("a.md", "md")]


def test_single_symlink_file_refused_unless_following(tree, tmp_path):
    os.symlink(tree / "a.md", tmp_path / "single_link.md")
    items, walk = _walk(tmp_path / "single_link.md")
    assert items == []
    assert walk.skipped and walk.skipped[0].reason == "symlink"


def test_fifo_and_special_files_are_skipped_not_opened(tree):
    fifo = tree / "pipe.txt"
    os.mkfifo(fifo)
    items, walk = _walk(tree)
    assert "pipe.txt" not in [i.relative_name for i in items]
    assert any(s.relative_name == "pipe.txt" and s.reason == "not_regular_file" for s in walk.skipped)
    assert stat.S_ISFIFO(fifo.lstat().st_mode)


def test_unreadable_file_is_skipped_with_reason(tree, monkeypatch):
    import src.corpus.detect_kind as mod

    real_open = os.open

    def fake_open(path, *a, **k):
        if str(path).endswith("b.txt"):
            raise PermissionError(13, "denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr(mod.os, "open", fake_open)
    items, walk = _walk(tree)
    assert "b.txt" not in [i.relative_name for i in items]
    assert any(s.relative_name == "b.txt" and s.reason == "unreadable" for s in walk.skipped)


def test_skip_report_is_json_friendly_and_has_no_absolute_paths(tree):
    _items, walk = _walk(tree)
    report = walk.skip_report()
    assert report["total"] == len(walk.skipped)
    assert report["by_reason"]["excluded_dir"] >= 2
    flat = repr(report)
    assert str(tree) not in flat


def test_skip_report_available_only_after_exhaustion_but_never_raises(tree):
    walk = iter_ingestable(tree)
    assert walk.skipped == []
    next(iter(walk))
    walk.skip_report()  # partial report is allowed


def test_binary_files_can_be_included_on_request(tree):
    items, walk = _walk(tree, include_unsupported=True)
    kinds = {i.relative_name: i.kind for i in items}
    assert kinds["blob.dat"] == "binary"
    assert not any(s.reason == "unsupported_binary" for s in walk.skipped)


def test_max_files_cap(tree):
    items, walk = _walk(tree, max_files=2)
    assert len(items) == 2
    assert any(s.reason == "max_files_reached" for s in walk.skipped)
