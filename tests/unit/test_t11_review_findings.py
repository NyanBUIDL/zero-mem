"""T11 - reviewer findings on PR #3: zip member scan, grant_write atomicity, punctuation-only recall."""
from __future__ import annotations

import io
import zipfile

import pytest

from tests.unit import adapters_fixtures as fx
from tests.unit.t5_memory_helpers import SHARED, Env
from zero_mem import provisioning as provmod

GH_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


def _with_parts(blob: bytes, parts: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blob)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info.filename, src.read(info.filename))
        for name, data in parts.items():
            dst.writestr(name, data)
    return out.getvalue()


def _docx(parts=None):
    base = fx.make_docx([("h", 1, "Runbook"), ("p", "all clear here")])
    return _with_parts(base, parts) if parts else base


def _xlsx(parts=None):
    base = fx.make_xlsx([("S", [["a", "b"], ["c", "d"]])])
    return _with_parts(base, parts) if parts else base


def _pptx(parts=None):
    base = fx.make_pptx([{"title": "T", "body": ["clean"]}])
    return _with_parts(base, parts) if parts else base


def _nested(inner_name: str, inner: bytes) -> bytes:
    return _with_parts(_docx(), {inner_name: inner})


def _tiny_zip(member: str, data: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, data)
    return out.getvalue()


CASES = {
    "docx-customxml": ("a.docx", lambda: _docx({"customXml/item1.xml": f"<r>{GH_TOKEN}</r>"})),
    "docx-comments": ("a.docx", lambda: _docx({"word/comments.xml": f"<c>{GH_TOKEN}</c>"})),
    "docx-embedded-object": ("a.docx", lambda: _docx({"word/embeddings/o.bin": f"x {GH_TOKEN} y".encode()})),
    "xlsx-customxml": ("a.xlsx", lambda: _xlsx({"customXml/item1.xml": f"<r>{GH_TOKEN}</r>"})),
    "pptx-notes": ("a.pptx", lambda: _pptx({"ppt/notesSlides/notesSlide9.xml": f"<n>{GH_TOKEN}</n>"})),
    "nested-zip": ("a.docx", lambda: _nested("word/embeddings/in.zip", _tiny_zip("k.txt", GH_TOKEN))),
    "nested-docx": ("a.docx", lambda: _nested("word/embeddings/in.docx", _docx({"customXml/i.xml": GH_TOKEN}))),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_secret_in_a_non_extracted_zip_member_is_rejected_and_never_stored(env, case):
    name, build = CASES[case]
    mem = env.open("claude-code")
    (res,) = mem.ingest(build(), filename=name, memory_type="file").files
    assert res.status == "rejected_secret", res
    assert env.registry_lines() == [] and env.blob_count() == 0
    assert env.files_containing(GH_TOKEN) == []


@pytest.mark.parametrize("name,build", [("a.docx", _docx), ("a.xlsx", _xlsx), ("a.pptx", _pptx)])
def test_clean_containers_are_still_accepted(env, name, build):
    mem = env.open("claude-code")
    (res,) = mem.ingest(build(), filename=name, memory_type="file").files
    assert res.status == "created", res


def test_a_clean_nested_zip_is_accepted(env):
    mem = env.open("claude-code")
    (res,) = mem.ingest(_nested("word/embeddings/in.zip", _tiny_zip("k.txt", "nothing here")),
                        filename="a.docx", memory_type="file").files
    assert res.status == "created", res


def test_container_that_cannot_be_completely_scanned_is_rejected(env):
    from src.redaction import prescan

    # an encrypted member cannot be inspected -> reject
    buf = _docx()
    raw = bytearray(_with_parts(buf, {"customXml/e.xml": "secret"}))
    # set the encryption flag in both the local header and the central directory entry
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = 0
        while True:
            i = raw.find(sig, i)
            if i < 0:
                break
            end = raw.find(b"customXml/e.xml", i, i + 80)
            if end > 0:
                raw[i + off] |= 1
            i += 4
    verdict = prescan.scan_zip_members(bytes(raw))
    assert not verdict.safe and verdict.reason == "container_unscannable"
    # too many nested levels / entries beyond the bound
    deep = _tiny_zip("k.txt", "x")
    for _ in range(prescan.MAX_ZIP_DEPTH + 2):
        deep = _with_parts(_docx(), {"in.zip": deep})
    v2 = prescan.scan_zip_members(deep)
    assert not v2.safe and v2.reason == "container_unscannable"
    many = io.BytesIO()
    with zipfile.ZipFile(many, "w") as z:
        for n in range(20):
            z.writestr(f"m{n}.txt", "x")
    v3 = prescan.scan_zip_members(many.getvalue(), max_entries=5)
    assert not v3.safe and v3.reason == "container_unscannable"


def test_pdf_and_image_raw_bytes_are_scanned(env):
    mem = env.open("claude-code")
    for name, head in (("a.pdf", b"%PDF-1.4\n% "), ("a.png", b"\x89PNG\r\n\x1a\n")):
        (res,) = mem.ingest(head + GH_TOKEN.encode() + b"\n", filename=name, memory_type="file").files
        assert res.status == "rejected_secret", (name, res)
    assert env.files_containing(GH_TOKEN) == []


# ------------------------------------------------------------------ finding 2: grant_write atomicity
def test_failed_canonical_append_leaves_no_residual_write_authorization(env, monkeypatch):
    env.prov.add_agent("codex")
    real = provmod.Provisioner._writer
    calls = {"n": 0}

    def failing(self, event):
        calls["n"] += 1
        raise OSError("disk full")

    monkeypatch.setattr(provmod.Provisioner, "_writer", failing)
    with pytest.raises(Exception):
        env.prov.grant_write("codex", space=SHARED, basis="b")
    monkeypatch.setattr(provmod.Provisioner, "_writer", real)
    assert calls["n"] >= 1
    # no derived authorization survives: the agent cannot write to the shared space
    mem = env.open("codex")
    assert mem.add("shared fact", "fact", scope="shared").status in {"denied", "error"}
    assert mem.add("shared fact", "fact", scope="shared").status != "created"
    # a clean retry works and yields exactly one effective grant
    out = env.prov.grant_write("codex", space=SHARED, basis="b")
    assert out["status"] == "granted"
    assert mem.add("shared fact", "fact", scope="shared").status == "created"
    again = env.prov.grant_write("codex", space=SHARED, basis="b")
    assert again["status"] == "exists"


# ------------------------------------------------------------------ finding 3: punctuation-only queries
BAD_QUERIES = ["_", "__", "-", "---", "***"]


@pytest.mark.parametrize("q", BAD_QUERIES)
def test_punctuation_only_recall_returns_no_arbitrary_units(env, q):
    mem = env.open("claude-code")
    assert mem.add("alpha beta gamma", "fact").status == "created"
    res = mem.recall(q)
    assert res.status in {"invalid", "empty"} and res.hits == []


@pytest.mark.parametrize("q", BAD_QUERIES)
def test_punctuation_only_mcp_recall_returns_no_hits(env, q):
    from src.integration.m6w import build_tool_set

    env.prov.add_agent("claude-code")
    ts = build_tool_set(profile_id="claude-code", layout=env.layout, enable_write=True, allow_roots=[], config=None)
    ts.call("memory_add", {"text": "alpha beta gamma", "memory_type": "fact"})
    out = ts.call("memory_recall", {"query": q})["structuredContent"]
    assert not out.get("hits")
    assert out["status"] in {"EMPTY", "INVALID"}


def test_metadata_only_retrieval_still_works(env):
    mem = env.open("claude-code")
    mem.add("be concise", "persona", name="style")
    assert mem.context().status == "ok"
    assert mem.recall("concise").status == "ok"


def test_retrieval_layer_empty_fts_expression_is_empty_not_metadata_only(env):
    from src.corpus.query_planner import CorpusMetadataFilter, CorpusQueryPlan  # noqa: F401
    mem = env.open("claude-code")
    mem.add("alpha beta gamma", "fact")
    res = mem._search(mem._read_requests(True, None), "_", None, 8)
    assert not res[0]
