"""T4 — end-to-end: register -> project_corpus -> authorized corpus_unit_search, per format.

Follows the call sequence of docs/design/SHARED-MEMORY-RUNTIME.md section 1 (registry +
blob store, SQLiteStore, project_corpus, GrantAdminService READ grant on a knowledge
space, open_readonly, AuthorizedReadService.corpus_unit_search). Asserts every new
adapter's units are discoverable through the authorized path, that a secret-bearing
unit is rejected by the pipeline projection (adapters do not sanitize), that the
projection is deterministic, and that corrupt sources never take down a pass.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.access import AccessRequest, AuthorizedReadService
from src.access.admin import GrantAdminRequest, GrantAdminService
from src.corpus.adapters import ImageAdapter
from src.corpus.adapters import registry as adapter_registry
from src.corpus.blob_store import CorpusBlobStore
from src.corpus.derived_store import project_corpus
from src.corpus.registry import CorpusSourceRegistry
from src.retrieval.db import open_readonly
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

from tests.unit.adapters_fixtures import (
    make_docx,
    make_png,
    make_pptx,
    make_xlsx,
)

OCR_LIBS_PRESENT = any(
    importlib.util.find_spec(m) is not None for m in ("rapidocr_onnxruntime", "pytesseract")
)

OWNER = "claude-code"
READER = "codex"
KS = "ks-shared"

TXT_DOC = b"First sentence about gardening.\nSecond line same paragraph txtmarkerquokka.\n\nUnrelated closing paragraph.\n"
MD_DOC = (
    b"# Deploy Guide\n\nThe blue process mdmarkerwombat is documented here.\n\n"
    b"```sh\necho mdcodekoala\n```\n\n| Env | Owner |\n|---|---|\n| prod | mdtablefalcon |\n"
)
CSV_DOC = b"name,city\nAnn,csvmarkerlemur\nBob,Hanoi\n"
TSV_DOC = b"name\tcity\nCy\ttsvmarkerbadger\n"
JSONL_DOC = (
    json.dumps({"role": "user", "content": "remember jsonlmarkerotter please"}) + "\n"
    + json.dumps({"role": "assistant", "content": "noted"}) + "\n"
).encode()
JSON_CHAT_DOC = json.dumps({"messages": [{"role": "user", "content": "jsonchatmarkerheron"}]}).encode()
JSON_PLAIN_DOC = json.dumps({"service": {"name": "jsonplainmarkerlynx", "port": 8080}}).encode()
CLAUDE_EXPORT = json.dumps([{"name": "Export chat", "chat_messages": [
    {"sender": "human", "text": "claudeexportmarkerstoat"}, {"sender": "assistant", "text": "ok"}]}]).encode()
DOCX_DOC = make_docx([("h", 1, "Policy"), ("p", "docxmarkermoose applies to everyone"),
                      ("table", [["Item", "Owner"], ["docxtablemarkerelk", "Ops"]])])
XLSX_DOC = make_xlsx([("Budget", [["Region", "Amount"], ["xlsxmarkerbison", 42]])])
PPTX_DOC = make_pptx([{"title": "Launch plan", "body": ["pptxmarkerzebra milestone"]}])

#: (kind, bytes, token that must be searchable)
FORMAT_CASES = [
    ("txt", TXT_DOC, "txtmarkerquokka"),
    ("md", MD_DOC, "mdmarkerwombat"),
    ("md", MD_DOC, "mdcodekoala"),
    ("md", MD_DOC, "mdtablefalcon"),
    ("csv", CSV_DOC, "csvmarkerlemur"),
    ("tsv", TSV_DOC, "tsvmarkerbadger"),
    ("jsonl", JSONL_DOC, "jsonlmarkerotter"),
    ("json", JSON_CHAT_DOC, "jsonchatmarkerheron"),
    ("json", JSON_PLAIN_DOC, "jsonplainmarkerlynx"),
    ("json", CLAUDE_EXPORT, "claudeexportmarkerstoat"),
    ("docx", DOCX_DOC, "docxmarkermoose"),
    ("docx", DOCX_DOC, "docxtablemarkerelk"),
    ("xlsx", XLSX_DOC, "xlsxmarkerbison"),
    ("pptx", PPTX_DOC, "pptxmarkerzebra"),
]


class Env:
    """Registry + blob store + derived DB for one scenario."""

    def __init__(self, base: Path, tag: str = "e") -> None:
        self.root = base / f"corpus_{tag}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.registry = CorpusSourceRegistry(root=self.root)
        self.blobs = CorpusBlobStore(root=self.root)
        self.db_path = base / f"derived_{tag}.sqlite"
        self.records: dict[str, object] = {}

    def add(self, ref: str, kind: str, content: bytes, *, profile=OWNER, ks=KS):
        rec = self.registry.register_source_with_blob(
            content=content, external_ref=f"file://{ref}", kind=kind,
            profile_id=profile, project_id=None, knowledge_space_id=ks,
            custom_meta={"memory_type": "file"},
        )
        self.records[ref] = rec
        return rec

    def project(self):
        store = SQLiteStore(SQLiteStoreConfig(path=self.db_path))
        store.ensure_schema()
        store._conn.execute("PRAGMA journal_mode=DELETE")  # fresh read-only conn sees data
        report = project_corpus(store._conn, self.registry, blob_store=self.blobs)
        store._conn.commit()
        GrantAdminService(store._conn, lambda ev: None, None).create(GrantAdminRequest(
            action="create", grant_id=f"g-{READER}-{KS}", subject_profile=READER, operation="READ",
            target_type="knowledge_space", target_id=KS, created_at="2026-10-01T00:00:00Z"))
        store._conn.commit()
        store.close()
        return report

    def search(self, text: str, *, who: str = READER, limit: int = 20):
        ro = open_readonly(self.db_path)
        try:
            svc = AuthorizedReadService(ro, who, grant_conn=ro.conn)
            return svc.corpus_unit_search(
                AccessRequest(operation="READ", requesting_profile_id=who,
                              knowledge_space_ids=[KS], resource_type="corpus_unit"),
                text, limit=limit)
        finally:
            ro.close()

    def rows(self, sql: str, params=()):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    env = Env(tmp_path_factory.mktemp("t4e2e"), "all")
    seen: set[tuple[str, bytes]] = set()
    for i, (kind, content, _tok) in enumerate(FORMAT_CASES):
        if (kind, content) in seen:
            continue
        seen.add((kind, content))
        env.add(f"doc{i}.{kind}", kind, content)
    env.add("pic.png", "png", make_png(7, 5))
    env.report = env.project()
    return env


def test_projection_report_all_valid_formats_project_without_failures(corpus):
    rep = corpus.report
    assert rep.extractions_failed == 0
    assert rep.units_rejected_secret == 0
    assert rep.units_projected >= 20
    assert rep.sources_projected == len(corpus.records)


@pytest.mark.parametrize("kind,content,token", FORMAT_CASES, ids=[f"{k}-{t}" for k, _c, t in FORMAT_CASES])
def test_each_format_is_discoverable_through_the_authorized_path(corpus, kind, content, token):
    res = corpus.search(token)
    assert res.allowed is True, res.reason_code
    hits = [h for h in res.items if token in (h.normalized_text or "").lower()]
    assert hits, f"{token} not found for kind={kind}"
    assert all(h.knowledge_space_id == KS and h.profile_id == OWNER for h in hits)


def test_unauthorized_profile_sees_nothing(corpus):
    res = corpus.search("mdmarkerwombat", who="hermes")
    assert not [h for h in res.items if "mdmarkerwombat" in (h.normalized_text or "")]


@pytest.mark.skipif(OCR_LIBS_PRESENT, reason="OCR library installed; degrade path not exercised")
def test_image_without_ocr_is_findable_by_its_metadata_unit(corpus):
    res = corpus.search("png")
    hits = [h for h in res.items if h.kind == "metadata"]
    assert hits and "ocr unavailable" in hits[0].normalized_text and "7x5" in hits[0].normalized_text


def test_unit_kinds_and_structure_survive_into_the_derived_store(corpus):
    kinds = {r["kind"] for r in corpus.rows("SELECT DISTINCT kind FROM zm_corpus_units")}
    assert {"text", "heading", "table", "code"} <= kinds
    md_rec = next(r for ref, r in corpus.records.items() if ref.endswith(".md"))
    rows = corpus.rows(
        "SELECT kind, normalized_text, source_location_id, parent_ref FROM zm_corpus_units WHERE source_ref=? ORDER BY unit_order",
        (md_rec.source_id,))
    heading = next(r for r in rows if r["kind"] == "heading")
    assert heading["normalized_text"] == "Deploy Guide"
    children = [r for r in rows if r["kind"] != "heading"]
    assert children and all(r["parent_ref"] == heading["source_location_id"] for r in children)
    assert any(r["kind"] == "table" and r["normalized_text"] == "Env=prod; Owner=mdtablefalcon" for r in rows)


def test_txt_paragraph_granularity_in_the_derived_store(corpus):
    txt_rec = next(r for ref, r in corpus.records.items() if ref.endswith(".txt"))
    rows = corpus.rows("SELECT normalized_text FROM zm_corpus_units WHERE source_ref=?", (txt_rec.source_id,))
    texts = [r["normalized_text"] for r in rows]
    assert len(texts) == 2
    assert any("gardening" in t and "txtmarkerquokka" in t for t in texts)  # two lines, one unit


# ---------------------------------------------------------------------------
# Secrets: the pipeline projection (require_safe) rejects, adapters pass text through
# ---------------------------------------------------------------------------

SECRET_CASES = [
    ("txt", b"clean paragraph cleanmarkertxt\n\npassword=hunter2 in a notes line\n"),
    ("md", b"# Notes\n\nclean paragraph cleanmarkermd\n\npassword=hunter2 stored in a paragraph\n"),
    ("csv", b"user,note\nann,cleanmarkercsv\nbob,password=hunter2\n"),
    ("jsonl", (json.dumps({"role": "user", "content": "cleanmarkerjsonl"}) + "\n"
               + json.dumps({"role": "user", "content": "my password=hunter2 here"}) + "\n").encode()),
    ("docx", make_docx([("p", "cleanmarkerdocx here"), ("p", "password=hunter2 inside the doc")])),
    ("xlsx", make_xlsx([("S", [["cleanmarkerxlsx", 1], ["password=hunter2", 2]])])),
    ("pptx", make_pptx([{"title": "cleanmarkerpptx", "body": ["password=hunter2 on slide"]}])),
]


@pytest.mark.parametrize("kind,content", SECRET_CASES, ids=[k for k, _ in SECRET_CASES])
def test_secret_unit_is_rejected_by_projection_clean_units_survive(tmp_path, kind, content):
    env = Env(tmp_path, f"sec_{kind}")
    env.add(f"s.{kind}", kind, content)
    rep = env.project()
    assert rep.units_rejected_secret >= 1, rep.as_dict()
    assert rep.units_projected >= 1
    stored = " ".join(r["normalized_text"] for r in env.rows("SELECT normalized_text FROM zm_corpus_units"))
    assert "hunter2" not in stored
    assert f"cleanmarker{kind}" in stored
    assert not [h for h in env.search("hunter2").items]
    assert [h for h in env.search(f"cleanmarker{kind}").items]


# ---------------------------------------------------------------------------
# Determinism, idempotence, isolation of failures
# ---------------------------------------------------------------------------

def _snapshot(env: Env):
    return env.rows(
        "SELECT source_location_id, kind, normalized_text, parent_ref, page, unit_order "
        "FROM zm_corpus_units ORDER BY source_ref, unit_order, source_location_id")


def test_same_bytes_project_to_identical_unit_ids_in_independent_stores(tmp_path):
    a, b = Env(tmp_path, "det_a"), Env(tmp_path, "det_b")
    for env in (a, b):
        for i, (kind, content, _t) in enumerate(FORMAT_CASES):
            env.add(f"d{i}.{kind}", kind, content)
        env.add("pic.png", "png", make_png(7, 5))
        env.project()
    snap_a, snap_b = _snapshot(a), _snapshot(b)
    assert snap_a and snap_a == snap_b


def test_reprojection_is_idempotent(tmp_path):
    env = Env(tmp_path, "idem")
    for i, (kind, content, _t) in enumerate(FORMAT_CASES):
        env.add(f"d{i}.{kind}", kind, content)
    env.project()
    before = _snapshot(env)
    store = SQLiteStore(SQLiteStoreConfig(path=env.db_path))
    store.ensure_schema()
    project_corpus(store._conn, env.registry, blob_store=env.blobs)
    store._conn.commit()
    store.close()
    assert _snapshot(env) == before


def test_corrupt_sources_are_counted_and_do_not_break_the_pass(tmp_path):
    env = Env(tmp_path, "corrupt")
    env.add("good.md", "md", b"# Good\n\ngoodmarkerpass here\n")
    env.add("bad.docx", "docx", b"PK\x03\x04 definitely not a docx")
    env.add("bad.xlsx", "xlsx", b"garbage")
    env.add("bad.json", "json", b"{broken")
    env.add("bad.pptx", "pptx", b"")
    env.add("empty.md", "md", b"\n\n")
    rep = env.project()
    assert rep.extractions_failed >= 4
    assert [h for h in env.search("goodmarkerpass").items]


def test_unsupported_kind_is_counted_not_raised(tmp_path):
    env = Env(tmp_path, "unsup")
    env.add("blob.bin", "binary", bytes(range(256)))
    env.add("ok.txt", "txt", b"unsupportedmarkerok\n")
    rep = env.project()
    assert rep.extractions_failed == 1
    assert [h for h in env.search("unsupportedmarkerok").items]


def test_partial_status_sources_are_projected(tmp_path):
    env = Env(tmp_path, "partial")
    rows = "".join(f"r{i},v{i}\n" for i in range(30))
    env.add("t.csv", "csv", ("k,v\n" + rows).encode())
    env.add("bad.jsonl", "jsonl", b'{"role":"user","content":"partialmarkerjsonl"}\nnot json\n')
    rep = env.project()
    assert rep.extractions_failed == 0
    assert [h for h in env.search("partialmarkerjsonl").items]


# ---------------------------------------------------------------------------
# OCR path through the pipeline with an injected engine
# ---------------------------------------------------------------------------

def test_image_ocr_text_is_searchable_when_an_engine_is_injected(tmp_path, monkeypatch):
    fake = ImageAdapter(ocr_engine=lambda data: "Receipt total 42 USD ocrmarkerpanda")
    monkeypatch.setattr(
        adapter_registry, "ADAPTER_REGISTRY",
        [fake if a.format == fake.format else a for a in adapter_registry.ADAPTER_REGISTRY],
    )
    env = Env(tmp_path, "ocr")
    env.add("scan.png", "png", make_png(4, 4))
    rep = env.project()
    assert rep.extractions_failed == 0
    hits = env.search("ocrmarkerpanda").items
    assert hits and hits[0].kind == "text"
    assert not [h for h in env.search("unavailable").items]


@pytest.mark.skipif(
    not (importlib.util.find_spec("rapidocr_onnxruntime") and importlib.util.find_spec("PIL")),
    reason="optional 'ocr' extra (rapidocr-onnxruntime) + Pillow not installed",
)
def test_real_rapidocr_on_rendered_png_is_recalled(tmp_path):
    """DEF-078: real engine, real PNG (rendered with Pillow), through project + authorized search."""
    import io
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.load_default(36)
    except TypeError:  # Pillow < 10.1
        pytest.skip("Pillow too old for scalable default font")
    img = Image.new("RGB", (900, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "Invoice 4471 due on March 3rd", fill="black", font=font)
    draw.text((20, 100), "Contact Priya Natarajan about the zebra project", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    env = Env(tmp_path, "realocr")
    env.add("real.png", "png", buf.getvalue())
    rep = env.project()
    assert rep.extractions_failed == 0
    texts = " ".join(h.normalized_text.lower() for h in env.search("Natarajan zebra").items)
    assert "priya natarajan about the zebra project" in texts
    assert env.search("Invoice 4471").items
