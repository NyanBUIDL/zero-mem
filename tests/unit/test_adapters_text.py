"""T4 — txt (paragraph granularity) and markdown adapters."""
from __future__ import annotations

import pytest

from src.corpus.adapters import MarkdownAdapter, TxtAdapter
from src.corpus.extract import ExtractionStatus

REF = "SRC"


def _txt(content: bytes, hint: str = "txt"):
    return TxtAdapter().extract(source_ref=REF, content=content, kind_hint=hint)


def _md(text: str | bytes, hint: str = "md", **kw):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return MarkdownAdapter(**kw).extract(source_ref=REF, content=data, kind_hint=hint)


# ---------------------------------------------------------------------------
# TXT: paragraph-level units
# ---------------------------------------------------------------------------

def test_txt_emits_one_unit_per_paragraph_not_per_line():
    res = _txt(b"para one line a\npara one line b\n\n\npara two\n")
    assert res.status == ExtractionStatus.COMPLETE.value
    assert [u.text for u in res.units] == ["para one line a\npara one line b", "para two"]
    assert [u.unit_id for u in res.units] == [f"{REF}#L1", f"{REF}#L5"]
    assert [u.order for u in res.units] == [1, 2]
    assert all(u.kind == "text" for u in res.units)


def test_txt_crlf_and_cr_line_endings():
    res = _txt(b"one\r\ntwo\r\n\r\nthree\rfour\r\rfive")
    assert [u.text for u in res.units] == ["one\ntwo", "three\nfour", "five"]


def test_txt_whitespace_only_lines_are_separators():
    res = _txt(b"a\n   \t \nb\n")
    assert [u.text for u in res.units] == ["a", "b"]


def test_txt_long_paragraph_is_chunked_to_cap():
    sentence = "Persona rule number one is to answer tersely. "
    res = _txt((sentence * 50).encode())
    assert len(res.units) >= 3
    assert all(len(u.text) <= 800 for u in res.units)
    ids = [u.unit_id for u in res.units]
    assert ids[0] == f"{REF}#L1"
    assert ids[1:] == [f"{REF}#L1.{k}" for k in range(1, len(ids))]
    assert len(set(ids)) == len(ids)


def test_txt_unbroken_blob_is_hard_split():
    res = _txt(b"z" * 2000)
    assert [len(u.text) for u in res.units] == [800, 800, 400]


def test_txt_ids_are_stable_across_runs_and_unique():
    content = b"alpha\n\nbeta\n\nalpha\n"
    a, b = _txt(content), _txt(content)
    assert [u.unit_id for u in a.units] == [u.unit_id for u in b.units]
    assert len({u.unit_id for u in a.units}) == 3  # identical text still distinct locations


def test_txt_empty_and_blank_sources():
    assert _txt(b"").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _txt(b"  \n\n\t\n").status == ExtractionStatus.EMPTY_SOURCE.value


def test_txt_strips_bom_and_decodes_utf16_and_latin1():
    assert _txt(b"\xef\xbb\xbfhello\n").units[0].text == "hello"
    assert _txt("héllo\n\nwörld".encode("utf-16")).units[1].text == "wörld"
    assert _txt("café naïve".encode("latin-1")).units[0].text == "café naïve"


def test_txt_vietnamese_text_preserved():
    res = _txt("Xin chào thế giới\n\nTiếng Việt có dấu".encode("utf-8"))
    assert [u.text for u in res.units] == ["Xin chào thế giới", "Tiếng Việt có dấu"]


def test_txt_unit_cap_marks_result_partial():
    adapter = TxtAdapter(max_units=3)
    res = adapter.extract(source_ref=REF, content=b"\n\n".join(b"p%d" % i for i in range(10)), kind_hint="txt")
    assert res.status == ExtractionStatus.PARTIAL.value
    assert len(res.units) == 3
    assert "cap" in (res.error_reason or "")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

SKILL_MD = """---
name: demo-skill
description: Does demo things
---
# Title

Intro paragraph line one
continues here.

## Section A

- item one
- item two

```python
# not a heading
print("hi")
```

| Name | Role |
|------|:----:|
| Ann  | Dev  |
| Bob  | Ops  |

### Sub

Text under sub.

## Section B

Setext Heading
==============

After setext.
"""


def _by_text(res):
    return {u.text: u for u in res.units}


def test_md_structure_kinds_and_hierarchy():
    res = _md(SKILL_MD)
    assert res.status == ExtractionStatus.COMPLETE.value
    t = _by_text(res)

    fm = [u for u in res.units if u.kind == "metadata"]
    assert len(fm) == 1 and "demo-skill" in fm[0].text and "Does demo things" in fm[0].text

    title, sec_a, sub, sec_b, setext = t["Title"], t["Section A"], t["Sub"], t["Section B"], t["Setext Heading"]
    assert all(u.kind == "heading" for u in (title, sec_a, sub, sec_b, setext))
    assert title.parent_ref is None
    assert sec_a.parent_ref == title.unit_id
    assert sub.parent_ref == sec_a.unit_id
    assert sec_b.parent_ref == title.unit_id          # popped back to level 1 parent
    assert setext.parent_ref is None                  # setext level 1 = sibling of "# Title"

    intro = t["Intro paragraph line one\ncontinues here."]
    assert intro.kind == "text" and intro.parent_ref == title.unit_id
    assert t["Text under sub."].parent_ref == sub.unit_id
    assert t["After setext."].parent_ref == setext.unit_id

    items = t["- item one\n- item two"]
    assert items.kind == "text" and items.parent_ref == sec_a.unit_id


def test_md_fenced_code_is_one_code_unit_and_hashes_inside_are_not_headings():
    res = _md(SKILL_MD)
    code = [u for u in res.units if u.kind == "code"]
    assert len(code) == 1
    assert code[0].text == '# not a heading\nprint("hi")'
    assert code[0].meta.get("lang") == "python"
    assert "not a heading" not in [u.text for u in res.units if u.kind == "heading"]


def test_md_pipe_table_rows_are_table_units_with_column_names():
    res = _md(SKILL_MD)
    rows = [u for u in res.units if u.kind == "table"]
    assert [u.text for u in rows] == ["Name=Ann; Role=Dev", "Name=Bob; Role=Ops"]
    sec_a = _by_text(res)["Section A"]
    assert all(r.parent_ref == sec_a.unit_id for r in rows)


def test_md_table_without_outer_pipes_and_with_empty_cells():
    res = _md("a | b | c\n--|--|--\n1 | | 3\n")
    rows = [u for u in res.units if u.kind == "table"]
    assert [u.text for u in rows] == ["a=1; c=3"]


def test_md_table_header_only_is_still_findable():
    res = _md("| Alpha | Beta |\n|---|---|\n")
    rows = [u for u in res.units if u.kind == "table"]
    assert len(rows) == 1 and "Alpha" in rows[0].text and "Beta" in rows[0].text


def test_md_pipe_in_prose_is_not_a_table():
    res = _md("This a | b statement has a pipe but no delimiter row.\n")
    assert [u.kind for u in res.units] == ["text"]


def test_md_table_ends_at_blank_line():
    res = _md("| k | v |\n|---|---|\n| x | 1 |\n\nafter table\n")
    assert [u.kind for u in res.units] == ["table", "text"]
    assert res.units[1].text == "after table"


def test_md_tilde_fence_and_longer_nested_fence():
    doc = "~~~sh\necho hi\n~~~\n\n````md\n```\ninner\n```\n````\n"
    res = _md(doc)
    codes = [u.text for u in res.units if u.kind == "code"]
    assert codes == ["echo hi", "```\ninner\n```"]


def test_md_unclosed_fence_runs_to_eof():
    res = _md("intro\n\n```\nnever closed\nmore code\n")
    assert [u.kind for u in res.units] == ["text", "code"]
    assert res.units[1].text == "never closed\nmore code"


def test_md_atx_heading_edge_cases():
    res = _md("#hashtag not heading\n\n####### seven\n\n## Closed ##\n\n#\n\n###   Spaced   ###   \n")
    heads = [u.text for u in res.units if u.kind == "heading"]
    assert heads == ["Closed", "Spaced"]
    texts = [u.text for u in res.units if u.kind == "text"]
    assert "#hashtag not heading" in texts and "####### seven" in texts


def test_md_text_before_any_heading_has_no_parent():
    res = _md("preface\n\n# H\n\nbody\n")
    assert res.units[0].parent_ref is None
    assert res.units[2].parent_ref == res.units[1].unit_id


def test_md_long_paragraph_chunked_and_ids_unique():
    para = "Sentence about deployment pipelines. " * 80
    res = _md("# H\n\n" + para + "\n")
    chunks = [u for u in res.units if u.kind == "text"]
    assert len(chunks) >= 3 and all(len(u.text) <= 800 for u in chunks)
    assert all(u.parent_ref == res.units[0].unit_id for u in chunks)
    ids = [u.unit_id for u in res.units]
    assert len(ids) == len(set(ids))


def test_md_front_matter_only_document():
    res = _md("---\ntitle: Only\n---\n")
    assert [u.kind for u in res.units] == ["metadata"]


def test_md_unclosed_front_matter_is_plain_content():
    res = _md("---\nfoo: bar\n\nreal text\n")
    assert not [u for u in res.units if u.kind == "metadata"]
    assert any("real text" in u.text for u in res.units)


def test_md_crlf_bom_and_utf16():
    res = _md(b"\xef\xbb\xbf# Head\r\n\r\nBody line\r\n")
    assert [u.text for u in res.units] == ["Head", "Body line"]
    res16 = _md("# Head\n\nBody\n".encode("utf-16"))
    assert [u.text for u in res16.units] == ["Head", "Body"]


def test_md_empty_blank_and_binary():
    assert _md(b"").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _md("\n  \n\n").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _md(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR").status == ExtractionStatus.CORRUPT_SOURCE.value


def test_md_ids_are_line_anchored_deterministic_and_prefixed():
    a, b = _md(SKILL_MD), _md(SKILL_MD)
    assert [u.unit_id for u in a.units] == [u.unit_id for u in b.units]
    assert all(u.unit_id.startswith(f"{REF}#") for u in a.units)
    assert len({u.unit_id for u in a.units}) == len(a.units)


def test_md_unit_cap_marks_partial():
    doc = "\n\n".join(f"para {i}" for i in range(20))
    res = _md(doc, max_units=5)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert len(res.units) == 5


def test_md_secret_text_flows_through_unmodified():
    res = _md("# Keys\n\napi_key=sk-1234567890abcdef\n")
    assert any("sk-1234567890abcdef" in u.text for u in res.units)


@pytest.mark.parametrize("hint", ["md", "markdown", ".MD"])
def test_md_hint_variants(hint):
    assert _md("# H\n", hint=hint).status == ExtractionStatus.COMPLETE.value


# ---------------------------------------------------------------------------
# Adversarial input (Markdown is untrusted): must stay linear and never raise
# ---------------------------------------------------------------------------

ADVERSARIAL_MD = {
    "heading_inner_spaces": lambda: "# a" + " " * 60_000 + "b\n",       # regex form took 140 s at 200k
    "fence_info_string": lambda: "```" + "b" * 60_000 + "`\n",
    "closing_hash_sequence": lambda: "# a " + "# " * 50_000 + "\n",
    "thematic_break": lambda: "-" + " -" * 50_000 + "x\n",
    "wide_table": lambda: "|" + "a|" * 50_000 + "\n|" + "-|" * 50_000 + "\n|" + "b|" * 50_000 + "\n",
    "many_fences": lambda: "```\n" * 50_000,
    "setext_spam": lambda: "a\n---\n" * 20_000,
    "blank_lines": lambda: "\n" * 200_000,
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL_MD))
def test_md_adversarial_lines_are_fast_and_typed(name):
    import time

    doc = ADVERSARIAL_MD[name]()
    start = time.perf_counter()
    res = _md(doc)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"{name} took {elapsed:.1f}s"
    assert res.status in {s.value for s in ExtractionStatus}


def test_md_hash_suffix_without_space_is_not_a_closing_sequence():
    assert [u.text for u in _md("## C#\n").units] == ["C#"]
    assert [u.text for u in _md("## Closed ##\n").units] == ["Closed"]
    assert [u.text for u in _md("## ##\n").units] == []


def test_txt_chunking_is_linear_for_huge_paragraphs():
    import time

    start = time.perf_counter()
    res = _txt(b"word " * 400_000)
    assert time.perf_counter() - start < 5.0
    assert all(len(u.text) <= 800 for u in res.units)
