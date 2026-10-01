"""T4 — seeded structural fuzz: invariants hold for arbitrary block soup / JSON / CSV.

Deterministic (``random.Random(seed)``), so a failure names its seed and reproduces.
Invariants: same input -> identical output, unique unit ids, strictly sequential
``order``, bounded unit size, ``parent_ref`` always names an *earlier heading unit*,
typed status, and a non-success result always carries an ``error_reason``.
"""
from __future__ import annotations

import json
import random

import pytest

from src.corpus.adapters import CsvAdapter, JsonAdapter, MarkdownAdapter, TxtAdapter
from src.corpus.extract import ExtractionStatus

REF = "SRC"
ALL_STATUS = {s.value for s in ExtractionStatus}


def _md(text: str):
    return MarkdownAdapter().extract(source_ref=REF, content=text.encode("utf-8"), kind_hint="md")


def _random_markdown(rng: random.Random) -> str:
    snippets = [
        lambda: "#" * rng.randint(1, 6) + " Heading " + str(rng.randint(0, 99)),
        lambda: "Setext " + str(rng.randint(0, 9)) + "\n" + rng.choice(["===", "---", "-----"]),
        lambda: " ".join(rng.choice(["alpha", "beta", "gamma", "delta.", "epsilon"]) for _ in range(rng.randint(1, 260))),
        lambda: "\n".join("- item " + str(i) for i in range(rng.randint(1, 8))),
        lambda: rng.choice(["```", "~~~", "````"]) + rng.choice(["", "py", "sh"]) + "\ncode " + str(rng.randint(0, 9))
        + "\n" + rng.choice(["```", "~~~", ""]),
        lambda: "| a | b |\n|---|:--:|\n" + "\n".join(f"| {i} | v{i} |" for i in range(rng.randint(0, 4))),
        lambda: rng.choice(["---", "***", "___", "- - -"]),
        lambda: "",
        lambda: "   ",
        lambda: "| stray | pipe",
        lambda: "> quote line",
        lambda: "<!-- comment -->",
    ]
    doc = "\n".join(rng.choice(snippets)() for _ in range(rng.randint(1, 40)))
    if rng.random() < 0.2:
        doc = "---\nname: fuzz\ndescription: random\n---\n" + doc
    if rng.random() < 0.2:
        doc = doc.replace("\n", "\r\n")
    return doc


@pytest.mark.parametrize("seed", range(150))
def test_md_fuzz_invariants(seed):
    doc = _random_markdown(random.Random(seed))
    a, b = _md(doc), _md(doc)
    assert a.as_dict() == b.as_dict()
    assert a.status in ALL_STATUS
    ids = [u.unit_id for u in a.units]
    assert len(ids) == len(set(ids))
    assert [u.order for u in a.units] == list(range(1, len(a.units) + 1))
    headings = {u.unit_id: i for i, u in enumerate(a.units) if u.kind == "heading"}
    for i, u in enumerate(a.units):
        assert u.text.strip()
        assert len(u.text) <= 800, (seed, len(u.text), u.kind)
        if u.parent_ref is not None:
            assert u.parent_ref in headings and headings[u.parent_ref] < i
    if not a.ok:
        assert a.error_reason


@pytest.mark.parametrize("seed", range(80))
def test_txt_fuzz_invariants(seed):
    rng = random.Random(seed)
    words = ["alpha", "beta", "gamma.", "Việt", "x" * rng.randint(1, 900), ""]
    lines = [" ".join(rng.choice(words) for _ in range(rng.randint(0, 120))) for _ in range(rng.randint(1, 30))]
    data = rng.choice(["\n", "\r\n", "\r"]).join(lines).encode("utf-8")
    a = TxtAdapter().extract(source_ref=REF, content=data, kind_hint="txt")
    b = TxtAdapter().extract(source_ref=REF, content=data, kind_hint="txt")
    assert a.as_dict() == b.as_dict()
    assert a.status in ALL_STATUS
    ids = [u.unit_id for u in a.units]
    assert len(ids) == len(set(ids))
    assert all(0 < len(u.text) <= 800 for u in a.units)
    # lossless apart from whitespace
    joined = "".join("".join(u.text.split()) for u in a.units)
    assert joined == "".join("".join(data.decode().split()))


def _random_json_value(rng: random.Random, depth: int = 0):
    kind = rng.randint(0, 9 if depth < 5 else 5)
    if kind == 0:
        return None
    if kind == 1:
        return rng.choice([True, False])
    if kind == 2:
        return rng.randint(-5, 10_000)
    if kind == 3:
        return rng.random()
    if kind in (4, 5):
        return " ".join(rng.choice(["alpha", "beta", "Việt", "x" * 40, ""]) for _ in range(rng.randint(0, 30)))
    if kind in (6, 7):
        return [_random_json_value(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    if rng.random() < 0.3:
        return {"role": rng.choice(["user", "assistant", "human"]), "content": _random_json_value(rng, depth + 1)}
    return {rng.choice(["a", "b", "messages", "text", "name", "k.k"]): _random_json_value(rng, depth + 1)
            for _ in range(rng.randint(0, 5))}


@pytest.mark.parametrize("seed", range(200))
def test_json_fuzz_invariants(seed):
    rng = random.Random(seed)
    value = _random_json_value(rng)
    as_lines = rng.random() < 0.3 and isinstance(value, list)
    if as_lines:
        data, hint = "\n".join(json.dumps(v) for v in value), "jsonl"
    else:
        data, hint = json.dumps(value), "json"
    adapter = JsonAdapter()
    a = adapter.extract(source_ref=REF, content=data.encode(), kind_hint=hint)
    b = adapter.extract(source_ref=REF, content=data.encode(), kind_hint=hint)
    assert a.as_dict() == b.as_dict()
    assert a.status in ALL_STATUS
    if not a.ok:
        assert a.error_reason
        return
    ids = [u.unit_id for u in a.units]
    assert len(ids) == len(set(ids))
    heads = {u.unit_id for u in a.units if u.kind == "heading"}
    for u in a.units:
        assert u.text.strip() and len(u.text) <= 800
        assert u.parent_ref is None or u.parent_ref in heads


@pytest.mark.parametrize("seed", range(80))
def test_csv_fuzz_invariants(seed):
    rng = random.Random(seed)
    delim = rng.choice([",", "\t", ";", "|"])

    def cell() -> str:
        return rng.choice(["", "a", "b c", 'q"q', "x" * rng.randint(1, 30), "Việt", "1,5", "multi\nline"])

    def quote(c: str) -> str:
        if any(ch in c for ch in (delim, '"', "\n")):
            return '"' + c.replace('"', '""') + '"'
        return c

    lines = [delim.join(quote(cell()) for _ in range(rng.randint(0, 6))) for _ in range(rng.randint(0, 25))]
    data = "\n".join(lines).encode()
    hint = "tsv" if delim == "\t" else "csv"
    a = CsvAdapter().extract(source_ref=REF, content=data, kind_hint=hint)
    b = CsvAdapter().extract(source_ref=REF, content=data, kind_hint=hint)
    assert a.as_dict() == b.as_dict()
    assert a.status in ALL_STATUS
    ids = [u.unit_id for u in a.units]
    assert len(ids) == len(set(ids))
    assert all(len(u.text) <= 800 for u in a.units)
    if not a.ok:
        assert a.error_reason


# ---------------------------------------------------------------------------
# Office containers: mutated XML parts and flipped bytes never raise
# ---------------------------------------------------------------------------

def _office_samples():
    from tests.unit.adapters_fixtures import make_docx, make_pptx, make_xlsx

    return {
        "docx": make_docx([("title", "T"), ("h", 1, "Head"), ("p", "body text " * 30),
                           ("table", [["a", "b"], ["c", "d"]])], footnotes=["note"], headers=["hdr"]),
        "xlsx": make_xlsx([("Sheet One", [["a", 1, ("f", "A1", 1)], ["b", True, None]]), ("S2", [["x"]])]),
        "pptx": make_pptx([{"title": "T", "body": ["b1", "b2"], "table": [["k", "v"]]}, {"title": "U"}]),
    }


def _mutate_xml_parts(raw: bytes, rng: random.Random) -> bytes:
    import io
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(raw))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            data = src.read(name)
            if name.endswith(".xml") and data and rng.random() < 0.6:
                buf = bytearray(data)
                for _ in range(rng.randint(1, 4)):
                    op = rng.randint(0, 3)
                    pos = rng.randrange(len(buf))
                    if op == 0:
                        del buf[pos:pos + rng.randint(1, 40)]
                    elif op == 1:
                        buf[pos] = rng.choice(b"<>&\"'/= ")
                    elif op == 2:
                        buf[pos:pos] = rng.choice([b"<x>", b"</w:p>", b"&bogus;", b"<![CDATA[z]]>", b"\x00"])
                    else:
                        buf = buf[:pos]
                    if not buf:
                        break
                data = bytes(buf)
            dst.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize("fmt", ["docx", "xlsx", "pptx"])
@pytest.mark.parametrize("seed", range(120))
def test_office_xml_mutation_never_raises(fmt, seed):
    from src.corpus.adapters import select_adapter

    rng = random.Random(f"{fmt}-{seed}")
    raw = _office_samples()[fmt]
    mutated = _mutate_xml_parts(raw, rng)
    if rng.random() < 0.3:  # also corrupt the container bytes themselves
        buf = bytearray(mutated)
        for _ in range(rng.randint(1, 6)):
            buf[rng.randrange(len(buf))] = rng.randrange(256)
        mutated = bytes(buf)
    adapter = select_adapter(fmt)
    a = adapter.extract(source_ref=REF, content=mutated, kind_hint=fmt)
    b = adapter.extract(source_ref=REF, content=mutated, kind_hint=fmt)
    assert a.as_dict() == b.as_dict()
    assert a.status in ALL_STATUS
    if a.ok:
        ids = [u.unit_id for u in a.units]
        assert len(ids) == len(set(ids)) and all(len(u.text) <= 800 for u in a.units)
    else:
        assert a.error_reason
