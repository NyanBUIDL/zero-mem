"""T4 — docx / xlsx / pptx adapters (stdlib zipfile + ElementTree), zip-bomb guards."""
from __future__ import annotations

import io
import zipfile

import pytest

from src.corpus.adapters import DocxAdapter, PptxAdapter, XlsxAdapter
from src.corpus.extract import ExtractionStatus

from tests.unit.adapters_fixtures import (
    W_NS,
    make_docx,
    make_pptx,
    make_xlsx,
    zip_bytes,
)

REF = "SRC"
CORRUPT = ExtractionStatus.CORRUPT_SOURCE.value
EMPTY = ExtractionStatus.EMPTY_SOURCE.value
COMPLETE = ExtractionStatus.COMPLETE.value
PARTIAL = ExtractionStatus.PARTIAL.value


def _docx(content: bytes, **kw):
    return DocxAdapter(**kw).extract(source_ref=REF, content=content, kind_hint="docx")


def _xlsx(content: bytes, **kw):
    return XlsxAdapter(**kw).extract(source_ref=REF, content=content, kind_hint="xlsx")


def _pptx(content: bytes, **kw):
    return PptxAdapter(**kw).extract(source_ref=REF, content=content, kind_hint="pptx")


def _by_text(res):
    return {u.text: u for u in res.units}


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def test_docx_headings_paragraphs_tables_and_hierarchy():
    doc = make_docx([
        ("title", "Quarterly Review"),
        ("p", "Opening remarks."),
        ("h", 1, "Revenue"),
        ("p", "Revenue grew steadily."),
        ("h", 2, "By region"),
        ("table", [["Region", "Amount"], ["APAC", "120"], ["EMEA", "95"]]),
        ("h", 1, "Costs"),
        ("p", "Costs were flat."),
    ])
    res = _docx(doc)
    assert res.status == COMPLETE
    t = _by_text(res)
    title, rev, region, costs = t["Quarterly Review"], t["Revenue"], t["By region"], t["Costs"]
    assert all(u.kind == "heading" for u in (title, rev, region, costs))
    assert rev.parent_ref is None or rev.parent_ref == title.unit_id
    assert region.parent_ref == rev.unit_id
    assert costs.parent_ref != region.unit_id
    assert t["Revenue grew steadily."].kind == "text"
    assert t["Revenue grew steadily."].parent_ref == rev.unit_id
    assert t["Costs were flat."].parent_ref == costs.unit_id
    rows = [u for u in res.units if u.kind == "table"]
    assert [u.text for u in rows] == ["Region | Amount", "APAC | 120", "EMEA | 95"]
    assert all(u.parent_ref == region.unit_id for u in rows)
    ids = [u.unit_id for u in res.units]
    assert len(ids) == len(set(ids)) and all(i.startswith(f"{REF}#") for i in ids)


def test_docx_localized_heading_style_resolved_via_styles_xml():
    styles = (
        f'<w:styles xmlns:w="{W_NS}"><w:style w:type="paragraph" w:styleId="Ueberschrift1">'
        '<w:name w:val="heading 1"/></w:style></w:styles>'
    )
    res = _docx(make_docx([("styled", "Ueberschrift1", "Lokalisiert"), ("p", "text")], styles_xml=styles))
    assert _by_text(res)["Lokalisiert"].kind == "heading"


def test_docx_outline_level_makes_a_heading():
    res = _docx(make_docx([("outline", 0, "Outlined"), ("p", "below")]))
    t = _by_text(res)
    assert t["Outlined"].kind == "heading" and t["below"].parent_ref == t["Outlined"].unit_id


def test_docx_runs_hyperlinks_tabs_breaks_and_tracked_changes():
    xml = (
        '<w:p><w:r><w:t>Alpha</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>Beta</w:t></w:r><w:r><w:br/></w:r>'
        '<w:hyperlink><w:r><w:t>Link</w:t></w:r></w:hyperlink>'
        '<w:ins><w:r><w:t> Inserted</w:t></w:r></w:ins>'
        '<w:del><w:r><w:delText>Deleted</w:delText></w:r></w:del></w:p>'
    )
    res = _docx(make_docx([("raw", xml)]))
    assert len(res.units) == 1
    text = " ".join(res.units[0].text.split())
    assert text == "Alpha Beta Link Inserted"
    assert "Deleted" not in res.units[0].text


def test_docx_content_controls_and_nested_tables():
    sdt = f'<w:sdt xmlns:w="{W_NS}"><w:sdtContent><w:p><w:r><w:t>Inside control</w:t></w:r></w:p></w:sdtContent></w:sdt>'
    nested = (
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>outer</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>inner</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "</w:tc></w:tr></w:tbl>"
    )
    res = _docx(make_docx([("raw", sdt), ("raw", nested)]))
    texts = [u.text for u in res.units]
    assert "Inside control" in texts
    assert any("outer" in t and "inner" in t for t in texts)


def test_docx_footnotes_and_headers_are_included_separator_skipped():
    res = _docx(make_docx([("p", "body")], footnotes=["See the appendix."], headers=["Confidential draft"]))
    texts = [u.text for u in res.units]
    assert "See the appendix." in texts and "Confidential draft" in texts
    assert len(texts) == 3


def test_docx_long_paragraph_is_chunked_and_empty_paragraphs_skipped():
    res = _docx(make_docx([("p", ""), ("p", "Sentence here. " * 120), ("p", "")]))
    assert len(res.units) >= 3
    assert all(len(u.text) <= 800 for u in res.units)


def test_docx_with_no_text_is_empty_source():
    assert _docx(make_docx([("p", ""), ("p", "")])).status == EMPTY


def test_docx_deterministic_ids():
    doc = make_docx([("h", 1, "H"), ("p", "x"), ("table", [["a", "b"]])])
    assert [u.unit_id for u in _docx(doc).units] == [u.unit_id for u in _docx(doc).units]


def test_docx_unicode_text_preserved():
    res = _docx(make_docx([("p", "Báo cáo quý ba: doanh thu tăng")]))
    assert res.units[0].text == "Báo cáo quý ba: doanh thu tăng"


@pytest.mark.parametrize("content", [
    b"not a zip at all",
    b"PK\x03\x04truncated-zip-garbage",
])
def test_docx_corrupt_container_is_corrupt_source(content):
    res = _docx(content)
    assert res.status == CORRUPT and res.error_reason


def test_docx_truncated_real_docx_is_corrupt_source():
    doc = make_docx([("p", "some body text " * 50)])
    assert _docx(doc[: len(doc) // 2]).status == CORRUPT


def test_docx_zip_without_document_xml_is_corrupt_source():
    res = _docx(zip_bytes({"hello.txt": "hi"}))
    assert res.status == CORRUPT and "document.xml" in res.error_reason


def test_docx_invalid_xml_is_corrupt_source():
    res = _docx(zip_bytes({"word/document.xml": "<w:document><w:body><w:p>"}))
    assert res.status == CORRUPT


def test_docx_rejects_doctype_and_entities():
    evil = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>'
    )
    res = _docx(zip_bytes({"word/document.xml": evil}))
    assert res.status == CORRUPT and "dtd" in res.error_reason.lower()


def test_docx_zip_bomb_total_uncompressed_cap():
    bomb = make_docx([("p", "ok")], extra_parts={"word/media/big.bin": b"\x00" * 3_000_000})
    assert len(bomb) < 20_000  # highly compressible
    res = _docx(bomb, max_total_uncompressed=1_000_000)
    assert res.status == CORRUPT and "uncompressed" in res.error_reason
    # the default cap accepts the same (legitimate-size) document
    assert _docx(bomb).status == COMPLETE


def test_docx_zip_bomb_member_cap():
    big_para = "<w:p><w:r><w:t>" + ("a " * 400_000) + "</w:t></w:r></w:p>"
    doc = make_docx([("raw", big_para)])
    res = _docx(doc, max_member_bytes=200_000)
    assert res.status == CORRUPT and "member" in res.error_reason


def test_docx_entry_count_cap():
    parts = {f"word/media/f{i}.bin": b"x" for i in range(60)}
    doc = make_docx([("p", "ok")], extra_parts=parts)
    res = _docx(doc, max_entries=50)
    assert res.status == CORRUPT and "entries" in res.error_reason


def test_entry_cap_is_enforced_from_the_eocd_before_the_zip_is_listed(monkeypatch):
    import src.corpus.adapters._ooxml as ooxml

    many = zip_bytes({f"f{i}.bin": b"x" for i in range(300)})
    assert ooxml.declared_entry_count(many) == 300

    def boom(*_a, **_k):  # the archive must be refused without ever being opened/listed
        raise AssertionError("ZipFile was constructed for an over-cap archive")

    monkeypatch.setattr(ooxml.zipfile, "ZipFile", boom)
    with pytest.raises(ooxml.OoxmlError, match="300 entries exceed cap 100"):
        ooxml.open_package(many, max_entries=100)


def test_declared_entry_count_handles_garbage_and_zip64_marker():
    from src.corpus.adapters._ooxml import declared_entry_count

    assert declared_entry_count(b"") is None
    assert declared_entry_count(b"PK\x05\x06short") is None
    assert declared_entry_count(b"no zip here" * 100) is None
    eocd = bytearray(b"PK\x05\x06" + bytes(18))
    eocd[10:12] = b"\xff\xff"
    assert declared_entry_count(bytes(eocd)) is None


def test_docx_duplicate_footnote_ids_still_yield_unique_unit_ids():
    parts = {
        "word/footnotes.xml": (
            f'<w:footnotes xmlns:w="{W_NS}"><w:footnote w:id="1"><w:p><w:r><w:t>first note</w:t></w:r></w:p></w:footnote>'
            '<w:footnote w:id="1"><w:p><w:r><w:t>second note</w:t></w:r></w:p></w:footnote></w:footnotes>'
        )
    }
    res = _docx(make_docx([("p", "body")], extra_parts=parts))
    ids = [u.unit_id for u in res.units]
    assert len(ids) == len(set(ids)) == 3
    assert {u.text for u in res.units} >= {"first note", "second note"}


def test_docx_never_writes_files_for_traversal_names(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doc = make_docx([("p", "fine")], extra_parts={"../../evil.txt": b"x", "/abs/evil.txt": b"y"})
    res = _docx(doc)
    assert res.status == COMPLETE
    assert list(tmp_path.iterdir()) == []


def test_docx_secret_text_flows_through():
    res = _docx(make_docx([("p", "token password=hunter2 inside")]))
    assert "hunter2" in res.units[0].text


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

def test_xlsx_sheet_names_shared_strings_numbers_and_row_ids():
    wb = make_xlsx([
        ("Revenue", [["Region", "Amount"], ["APAC", 120], ["EMEA", 95.5]]),
        ("Notes", [["remember", "the", "milk"]]),
    ])
    res = _xlsx(wb)
    assert res.status == COMPLETE
    heads = [u for u in res.units if u.kind == "heading"]
    assert [h.text for h in heads] == ["Revenue", "Notes"]
    assert [h.unit_id for h in heads] == [f"{REF}#s1", f"{REF}#s2"]
    rows = [u for u in res.units if u.kind == "table"]
    assert [(u.unit_id, u.text) for u in rows] == [
        (f"{REF}#s1r1", "Region | Amount"),
        (f"{REF}#s1r2", "APAC | 120"),
        (f"{REF}#s1r3", "EMEA | 95.5"),
        (f"{REF}#s2r1", "remember | the | milk"),
    ]
    assert rows[0].parent_ref == heads[0].unit_id and rows[3].parent_ref == heads[1].unit_id


def test_xlsx_inline_strings_and_absolute_rel_targets():
    wb = make_xlsx([("S", [["inline one", "inline two"]])], inline_strings=True, absolute_targets=True)
    res = _xlsx(wb)
    assert [u.text for u in res.units if u.kind == "table"] == ["inline one | inline two"]


def test_xlsx_formulas_show_cached_values_and_skip_uncached():
    wb = make_xlsx([("S", [[1, 2, ("f", "A1+B1", 3)], ["x", ("f", 'CONCAT("a","b")', "ab"), ("f", "NOW()", None)]])])
    rows = [u.text for u in _xlsx(wb).units if u.kind == "table"]
    assert rows == ["1 | 2 | 3", "x | ab"]


def test_xlsx_dates_booleans_errors_left_raw():
    wb = make_xlsx([("S", [[45000, ("d", "2024-01-31T00:00:00"), True, False, ("e", "#DIV/0!"), 1e-07]])])
    row = [u.text for u in _xlsx(wb).units if u.kind == "table"][0]
    assert row == "45000 | 2024-01-31T00:00:00 | TRUE | FALSE | #DIV/0! | 1e-07"


def test_xlsx_blank_rows_skipped_and_row_numbers_preserved():
    wb = make_xlsx([("S", [["a"], None, None, ["d"], [None, None]])])
    rows = [u for u in _xlsx(wb).units if u.kind == "table"]
    assert [u.unit_id for u in rows] == [f"{REF}#s1r1", f"{REF}#s1r4"]


def test_xlsx_xml_entities_and_rich_text_shared_strings():
    wb = make_xlsx(
        [("S", [["Tom & Jerry <3", "x"]])],
        extra_parts={},
    )
    assert [u.text for u in _xlsx(wb).units if u.kind == "table"] == ["Tom & Jerry <3 | x"]
    rich = zip_bytes({
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="R" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="x/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<si><r><t>Rich </t></r><r><t>text</t></r><rPh><t>PHONETIC</t></rPh></si></sst>",
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>',
    })
    assert [u.text for u in _xlsx(rich).units if u.kind == "table"] == ["Rich text"]


def test_xlsx_missing_shared_string_index_is_skipped_not_fatal():
    broken = zip_bytes({
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="x/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>99</v></c><c r="B1"><v>7</v></c></row></sheetData></worksheet>',
    })
    assert [u.text for u in _xlsx(broken).units if u.kind == "table"] == ["7"]


def test_xlsx_row_cap_marks_partial():
    wb = make_xlsx([("S", [[f"r{i}", i] for i in range(100)])])
    res = _xlsx(wb, max_rows_per_sheet=10)
    assert res.status == PARTIAL
    assert len([u for u in res.units if u.kind == "table"]) == 10
    assert "row cap" in res.error_reason


def test_xlsx_total_row_cap_across_sheets():
    wb = make_xlsx([("A", [[i] for i in range(10)]), ("B", [[i] for i in range(10)])])
    res = _xlsx(wb, max_total_rows=12)
    assert res.status == PARTIAL
    assert len([u for u in res.units if u.kind == "table"]) == 12


def test_xlsx_empty_sheets_produce_no_units():
    assert _xlsx(make_xlsx([("Empty", [])])).status == EMPTY
    res = _xlsx(make_xlsx([("Empty", []), ("Full", [["x"]])]))
    assert [u.text for u in res.units if u.kind == "heading"] == ["Full"]


def test_xlsx_one_corrupt_sheet_yields_partial_with_the_rest():
    good = make_xlsx([("Good", [["alpha"]]), ("Bad", [["beta"]])])
    # replace sheet2 with broken XML
    src = zipfile.ZipFile(io.BytesIO(good))
    parts = {n: src.read(n) for n in src.namelist()}
    parts["xl/worksheets/sheet2.xml"] = b"<worksheet><sheetData><row"
    res = _xlsx(zip_bytes(parts))
    assert res.status == PARTIAL
    assert [u.text for u in res.units if u.kind == "table"] == ["alpha"]


def test_xlsx_long_row_chunked():
    wb = make_xlsx([("S", [["word " * 400]])])
    rows = [u for u in _xlsx(wb).units if u.kind == "table"]
    assert len(rows) >= 3 and all(len(u.text) <= 800 for u in rows)
    assert rows[0].unit_id == f"{REF}#s1r1" and rows[1].unit_id == f"{REF}#s1r1.1"


@pytest.mark.parametrize("content", [b"nope", b"PK\x03\x04junk", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy"])
def test_xlsx_corrupt_inputs(content):
    assert _xlsx(content).status == CORRUPT


def test_xlsx_missing_workbook_is_corrupt():
    assert _xlsx(zip_bytes({"a.txt": "x"})).status == CORRUPT


def test_xlsx_zip_bomb_guards():
    wb = make_xlsx([("S", [["a"]])], extra_parts={"xl/media/blob.bin": b"\x00" * 3_000_000})
    assert _xlsx(wb, max_total_uncompressed=1_000_000).status == CORRUPT
    many = make_xlsx([("S", [["a"]])], extra_parts={f"xl/media/f{i}": b"x" for i in range(40)})
    assert _xlsx(many, max_entries=20).status == CORRUPT
    big_sheet = make_xlsx([("S", [["w " * 200_000]])])
    assert _xlsx(big_sheet, max_member_bytes=100_000).status == CORRUPT


def test_xlsx_doctype_rejected():
    parts = {
        "xl/workbook.xml": '<!DOCTYPE x [<!ENTITY a "b">]><workbook/>',
    }
    res = _xlsx(zip_bytes(parts))
    assert res.status == CORRUPT


def test_xlsx_deterministic_and_unicode():
    wb = make_xlsx([("Doanh thu", [["Khu vực", "Tổng"], ["Miền Trung", 12]])])
    a, b = _xlsx(wb), _xlsx(wb)
    assert a.as_dict() == b.as_dict()
    assert a.units[0].text == "Doanh thu"
    assert "Miền Trung | 12" in [u.text for u in a.units]


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

def test_pptx_slide_titles_bodies_tables_and_page_numbers():
    deck = make_pptx([
        {"title": "Roadmap", "body": ["Ship adapters", "Review security"]},
        {"title": "Metrics", "table": [["KPI", "Value"], ["Recall", "0.9"]]},
        {"body": ["Untitled slide text"]},
    ])
    res = _pptx(deck)
    assert res.status == COMPLETE
    heads = [u for u in res.units if u.kind == "heading"]
    assert [(h.text, h.page) for h in heads] == [("Roadmap", 1), ("Metrics", 2)]
    t = _by_text(res)
    assert t["Ship adapters\nReview security"].parent_ref == heads[0].unit_id
    assert t["Ship adapters\nReview security"].page == 1
    assert [u.text for u in res.units if u.kind == "table"] == ["KPI | Value", "Recall | 0.9"]
    assert t["Untitled slide text"].page == 3 and t["Untitled slide text"].parent_ref is None
    ids = [u.unit_id for u in res.units]
    assert len(ids) == len(set(ids))


def test_pptx_follows_presentation_order_not_file_numbers():
    deck = make_pptx([{"title": "First"}, {"title": "Second"}, {"title": "Third"}], reverse_order=True)
    res = _pptx(deck)
    assert [(u.text, u.page) for u in res.units] == [("Third", 1), ("Second", 2), ("First", 3)]


def test_pptx_empty_and_corrupt():
    assert _pptx(make_pptx([{}, {}])).status == EMPTY
    assert _pptx(b"junk").status == CORRUPT
    assert _pptx(zip_bytes({"x": "y"})).status == CORRUPT


def test_pptx_slide_cap_marks_partial():
    deck = make_pptx([{"title": f"S{i}"} for i in range(12)])
    res = _pptx(deck, max_slides=5)
    assert res.status == PARTIAL and len(res.units) == 5


def test_pptx_zip_guards():
    deck = make_pptx([{"title": "ok"}])
    src = zipfile.ZipFile(io.BytesIO(deck))
    parts = {n: src.read(n) for n in src.namelist()}
    parts["ppt/media/bomb.bin"] = b"\x00" * 3_000_000
    assert _pptx(zip_bytes(parts), max_total_uncompressed=1_000_000).status == CORRUPT


# ---------------------------------------------------------------------------
# Hostile / unusual structure: always a typed status, never an exception
# ---------------------------------------------------------------------------

def test_docx_pathological_nesting_is_a_typed_failure():
    nested = "<w:sdt><w:sdtContent>" * 3000 + "<w:p><w:r><w:t>deep</w:t></w:r></w:p>" + "</w:sdtContent></w:sdt>" * 3000
    res = _docx(make_docx([("raw", nested)]))
    assert res.status in (COMPLETE, CORRUPT) and (res.status == COMPLETE or res.error_reason)


def test_docx_deeply_nested_tables_are_flattened_without_recursion():
    nested = "<w:tbl><w:tr><w:tc>" * 1500 + "<w:p><w:r><w:t>core text</w:t></w:r></w:p>" + "</w:tc></w:tr></w:tbl>" * 1500
    res = _docx(make_docx([("raw", nested)]))
    assert res.status == COMPLETE and "core text" in res.units[0].text


def test_docx_many_paragraphs_hit_the_unit_cap_as_partial():
    doc = make_docx([("p", f"paragraph {i}") for i in range(50)])
    res = _docx(doc, max_units=10)
    assert res.status == PARTIAL and len(res.units) == 10


def test_xlsx_all_sheets_unreadable_is_corrupt_not_empty():
    good = make_xlsx([("Bad", [["x"]])])
    src = zipfile.ZipFile(io.BytesIO(good))
    parts = {n: src.read(n) for n in src.namelist()}
    parts["xl/worksheets/sheet1.xml"] = b"<worksheet><sheetData><row"
    res = _xlsx(zip_bytes(parts))
    assert res.status == CORRUPT and "sheet 1" in res.error_reason


def test_pptx_all_slides_unreadable_is_corrupt_not_empty():
    deck = make_pptx([{"title": "x"}])
    src = zipfile.ZipFile(io.BytesIO(deck))
    parts = {n: src.read(n) for n in src.namelist()}
    parts["ppt/slides/slide1.xml"] = b"<p:sld><p:cSld"
    res = _pptx(zip_bytes(parts))
    assert res.status == CORRUPT and "slide 1" in res.error_reason


def test_xlsx_huge_sparse_row_numbers_do_not_matter():
    wb = make_xlsx([("S", [["a"]])])
    src = zipfile.ZipFile(io.BytesIO(wb))
    parts = {n: src.read(n) for n in src.namelist()}
    parts["xl/worksheets/sheet1.xml"] = (
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        b'<row r="1048576"><c r="A1048576" t="inlineStr"><is><t>last row</t></is></c></row></sheetData></worksheet>'
    )
    res = _xlsx(zip_bytes(parts))
    assert [u.unit_id for u in res.units if u.kind == "table"] == [f"{REF}#s1r1048576"]


def test_ooxml_encrypted_member_is_corrupt_not_exception():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
    raw = bytearray(buf.getvalue())
    # set the "encrypted" general-purpose flag in the local and central headers
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):
        idx = raw.find(sig)
        off = idx + (6 if sig == b"PK\x03\x04" else 8)
        raw[off] |= 0x01
    res = _docx(bytes(raw))
    assert res.status == CORRUPT
