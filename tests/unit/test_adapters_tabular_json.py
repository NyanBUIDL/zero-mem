"""T4 — csv/tsv and json/jsonl/ndjson chat-log adapters."""
from __future__ import annotations

import json

import pytest

from src.corpus.adapters import CsvAdapter, JsonAdapter
from src.corpus.extract import ExtractionStatus

REF = "SRC"


def _csv(text: str | bytes, hint: str = "csv", **kw):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return CsvAdapter(**kw).extract(source_ref=REF, content=data, kind_hint=hint)


def _json(obj_or_text, hint: str = "json", **kw):
    if isinstance(obj_or_text, (dict, list)):
        data = json.dumps(obj_or_text, ensure_ascii=False).encode("utf-8")
    elif isinstance(obj_or_text, str):
        data = obj_or_text.encode("utf-8")
    else:
        data = obj_or_text
    return JsonAdapter(**kw).extract(source_ref=REF, content=data, kind_hint=hint)


# ---------------------------------------------------------------------------
# CSV / TSV
# ---------------------------------------------------------------------------

CSV_DOC = 'name,role,note\nAnn,Dev,"likes, commas"\nBob,Ops,\n,,\nCy,QA,"multi\nline"\n'


def test_csv_header_heading_and_row_table_units():
    res = _csv(CSV_DOC)
    assert res.status == ExtractionStatus.COMPLETE.value
    head = res.units[0]
    assert head.kind == "heading" and head.unit_id == f"{REF}#h"
    assert head.text == "name, role, note"
    rows = res.units[1:]
    assert all(u.kind == "table" and u.parent_ref == head.unit_id for u in rows)
    assert [u.text for u in rows] == [
        "name=Ann; role=Dev; note=likes, commas",
        "name=Bob; role=Ops",
        "name=Cy; role=QA; note=multi\nline",
    ]
    # ids use the 1-based record index (header = 1; blank record 4 still counted)
    assert [u.unit_id for u in rows] == [f"{REF}#r2", f"{REF}#r3", f"{REF}#r5"]


def test_tsv_hint_forces_tab_delimiter():
    res = _csv("a\tb\n1,5\t2\n", hint="tsv")
    assert [u.text for u in res.units if u.kind == "table"] == ["a=1,5; b=2"]


def test_csv_sniffs_semicolon_and_pipe_delimiters():
    assert [u.text for u in _csv("a;b\n1;2\n").units if u.kind == "table"] == ["a=1; b=2"]
    assert [u.text for u in _csv("a|b\n1|2\n").units if u.kind == "table"] == ["a=1; b=2"]


def test_csv_quoted_quotes_and_unicode():
    res = _csv('q,v\n"say ""hi""",Việt Nam\n')
    assert [u.text for u in res.units if u.kind == "table"] == ['q=say "hi"; v=Việt Nam']


def test_csv_blank_duplicate_and_extra_columns():
    res = _csv("a,,a\n1,2,3,4\n")
    assert res.units[0].text == "a, col2, a"
    assert [u.text for u in res.units if u.kind == "table"] == ["a=1; col2=2; a=3; col4=4"]


def test_csv_header_only_is_complete_with_heading_unit():
    res = _csv("alpha,beta\n")
    assert res.status == ExtractionStatus.COMPLETE.value
    assert [u.kind for u in res.units] == ["heading"]


def test_csv_leading_blank_lines_and_crlf_and_bom():
    res = _csv(b"\xef\xbb\xbf\r\n\r\nk,v\r\nx,1\r\n")
    assert res.units[0].text == "k, v"
    assert res.units[1].text == "k=x; v=1"


def test_csv_row_cap_marks_partial():
    rows = "\n".join(f"r{i},{i}" for i in range(50))
    res = _csv("k,v\n" + rows + "\n", max_rows=5)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert len([u for u in res.units if u.kind == "table"]) == 5
    assert "row cap" in (res.error_reason or "")


def test_csv_byte_cap_marks_partial_and_cuts_at_line_boundary():
    body = "".join(f"row{i},value{i}\n" for i in range(200))
    res = _csv("k,v\n" + body, max_bytes=200)
    assert res.status == ExtractionStatus.PARTIAL.value
    texts = [u.text for u in res.units if u.kind == "table"]
    assert texts and all(t.startswith("k=row") and "; v=value" in t for t in texts)
    assert len(texts) < 200


def test_csv_long_row_is_chunked_not_dropped():
    res = _csv("k,v\nx," + ("word " * 400) + "\n")
    rows = [u for u in res.units if u.kind == "table"]
    assert len(rows) >= 3 and all(len(u.text) <= 800 for u in rows)
    assert rows[0].unit_id == f"{REF}#r2" and rows[1].unit_id == f"{REF}#r2.1"


def test_csv_oversized_field_is_typed_failure_not_exception():
    huge = "x" * 200_000
    res = _csv(f"a,b\n{huge},2\n")
    assert res.status in (ExtractionStatus.CORRUPT_SOURCE.value, ExtractionStatus.PARTIAL.value,
                          ExtractionStatus.COMPLETE.value)


def test_csv_binary_and_empty_inputs():
    assert _csv(b"\x00\x01\x02\x03,\x04\n").status == ExtractionStatus.CORRUPT_SOURCE.value
    assert _csv(b"").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _csv("\n\n,,\n").status == ExtractionStatus.EMPTY_SOURCE.value


def test_csv_ids_deterministic_and_unique():
    a, b = _csv(CSV_DOC), _csv(CSV_DOC)
    assert [u.unit_id for u in a.units] == [u.unit_id for u in b.units]
    assert len({u.unit_id for u in a.units}) == len(a.units)


def test_csv_secret_value_flows_through_for_pipeline_rejection():
    res = _csv("user,token\nann,password=hunter2\n")
    assert any("hunter2" in u.text for u in res.units)


# ---------------------------------------------------------------------------
# JSON chat logs
# ---------------------------------------------------------------------------

def _texts(res):
    return [u.text for u in res.units]


def test_json_messages_object_role_content():
    res = _json({"messages": [
        {"role": "user", "content": "hello world"},
        {"role": "assistant", "content": "hi there"},
    ]})
    assert res.status == ExtractionStatus.COMPLETE.value
    assert _texts(res) == ["user: hello world", "assistant: hi there"]
    assert [u.unit_id for u in res.units] == [f"{REF}#m1", f"{REF}#m2"]
    assert all(u.kind == "text" for u in res.units)


def test_json_top_level_array_of_messages():
    res = _json([{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}])
    assert _texts(res) == ["user: q", "assistant: a"]


def test_jsonl_lines_are_messages_with_line_anchored_ids():
    lines = [
        json.dumps({"role": "user", "content": "first"}),
        "",
        json.dumps({"role": "assistant", "content": "second"}),
    ]
    res = _json("\n".join(lines), hint="jsonl")
    assert _texts(res) == ["user: first", "assistant: second"]
    assert [u.unit_id for u in res.units] == [f"{REF}#m1", f"{REF}#m3"]


@pytest.mark.parametrize("hint", ["jsonl", "ndjson", "chat", "json"])
def test_jsonl_content_works_under_any_json_hint(hint):
    data = '{"role":"user","content":"a1"}\n{"role":"assistant","content":"b2"}\n'
    assert _texts(_json(data, hint=hint)) == ["user: a1", "assistant: b2"]


def test_json_content_as_list_of_parts_ignores_non_text_parts():
    res = _json({"messages": [{"role": "user", "content": [
        {"type": "text", "text": "look at this"},
        {"type": "image_url", "image_url": {"url": "http://x/y.png"}},
        {"type": "text", "text": "and that"},
    ]}]})
    assert _texts(res) == ["user: look at this\nand that"]
    assert "http://x" not in res.units[0].text


def test_json_tool_result_parts_contribute_text():
    res = _json({"messages": [{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "exit code 0"}]},
    ]}]})
    assert _texts(res) == ["user: exit code 0"]


def test_json_claude_export_chat_messages_sender_text():
    export = [{
        "uuid": "c1", "name": "Planning chat",
        "chat_messages": [
            {"sender": "human", "text": "what is the plan"},
            {"sender": "assistant", "text": "ship it", "content": [{"type": "text", "text": "ship it"}]},
            {"sender": "human", "text": "", "content": [{"type": "text", "text": "from parts"}]},
        ],
    }]
    res = _json(export)
    head = res.units[0]
    assert head.kind == "heading" and head.text == "Planning chat" and head.unit_id == f"{REF}#c1"
    msgs = res.units[1:]
    assert [u.text for u in msgs] == ["user: what is the plan", "assistant: ship it", "user: from parts"]
    assert [u.unit_id for u in msgs] == [f"{REF}#c1m1", f"{REF}#c1m2", f"{REF}#c1m3"]
    assert all(u.parent_ref == head.unit_id for u in msgs)


def test_json_claude_export_single_conversation_object():
    res = _json({"name": "Solo", "chat_messages": [{"sender": "human", "text": "hey"}]})
    assert [u.kind for u in res.units] == ["heading", "text"]
    assert res.units[0].unit_id == f"{REF}#title"
    assert res.units[1].unit_id == f"{REF}#m1"
    assert res.units[1].parent_ref == f"{REF}#title"


def _chatgpt_conv(current=True, title="Trip planning"):
    mapping = {
        "root": {"id": "root", "message": None, "parent": None, "children": ["sys"]},
        "sys": {"id": "sys", "parent": "root", "children": ["u1"],
                "message": {"author": {"role": "system"}, "content": {"content_type": "text", "parts": [""]},
                            "metadata": {"is_visually_hidden_from_conversation": True}}},
        "u1": {"id": "u1", "parent": "sys", "children": ["a_old", "a_new"],
               "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["plan a trip to Hue"]}}},
        "a_old": {"id": "a_old", "parent": "u1", "children": [],
                  "message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["REGENERATED-DISCARDED"]}}},
        "a_new": {"id": "a_new", "parent": "u1", "children": ["u2"],
                  "message": {"author": {"role": "assistant"},
                              "content": {"content_type": "text", "parts": ["Day one: citadel.", {"content_type": "image_asset_pointer"}, "Day two: tombs."]}}},
        "u2": {"id": "u2", "parent": "a_new", "children": ["code"],
               "message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["thanks"]}}},
        "code": {"id": "code", "parent": "u2", "children": [],
                 "message": {"author": {"role": "assistant"}, "content": {"content_type": "code", "text": "print('ok')"}}},
    }
    conv = {"title": title, "mapping": mapping}
    if current:
        conv["current_node"] = "code"
    return conv


@pytest.mark.parametrize("current", [True, False])
def test_json_chatgpt_export_mapping_tree_follows_active_branch(current):
    res = _json([_chatgpt_conv(current=current)])
    head = res.units[0]
    assert head.kind == "heading" and head.text == "Trip planning"
    assert [u.text for u in res.units[1:]] == [
        "user: plan a trip to Hue",
        "assistant: Day one: citadel.\nDay two: tombs.",
        "user: thanks",
        "assistant: print('ok')",
    ]
    assert "REGENERATED-DISCARDED" not in " ".join(_texts(res))


def test_json_chatgpt_mapping_survives_cycles_and_dangling_nodes():
    mapping = {
        "a": {"id": "a", "parent": "b", "children": ["b"],
              "message": {"author": {"role": "user"}, "content": {"parts": ["loop a"]}}},
        "b": {"id": "b", "parent": "a", "children": ["a"],
              "message": {"author": {"role": "assistant"}, "content": {"parts": ["loop b"]}}},
        "c": {"id": "c", "parent": "missing", "children": [],
              "message": {"author": {"role": "user"}, "content": {"parts": ["orphan"]}}},
    }
    res = _json({"mapping": mapping, "current_node": "b"})
    assert res.status in (ExtractionStatus.COMPLETE.value, ExtractionStatus.PARTIAL.value)
    assert len(res.units) <= 3


def test_json_claude_code_transcript_jsonl_unwraps_message_and_skips_non_messages():
    lines = [
        {"type": "summary", "summary": "ignored"},
        {"type": "user", "message": {"role": "user", "content": "fix the bug"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "looking now"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
        ]}},
        {"type": "file-history-snapshot", "snapshot": {}},
    ]
    res = _json("\n".join(json.dumps(x) for x in lines), hint="jsonl")
    assert _texts(res) == ["user: fix the bug", "assistant: looking now"]


def test_json_transcript_with_many_interleaved_non_message_lines_is_still_chat():
    noise = [{"type": "attachment", "attachment": {"kind": "x"}}] * 5 + [{"type": "queue-operation", "op": "enqueue"}] * 4
    lines = noise[:3] + [
        {"type": "user", "message": {"role": "user", "content": "first question"}},
        *noise[3:7],
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "first answer"}]}},
        *noise[7:],
        {"type": "user", "message": {"role": "user", "content": "second question"}},
    ]
    res = _json("\n".join(json.dumps(x) for x in lines), hint="jsonl")
    assert _texts(res) == ["user: first question", "assistant: first answer", "user: second question"]


def test_json_array_with_a_stray_role_text_object_stays_a_plain_document():
    records = [{"id": i, "city": f"city{i}"} for i in range(12)] + [{"role": "admin", "text": "stray"}]
    res = _json(records)
    blob = "\n".join(_texts(res))
    assert "[0].city: city0" in blob and "[12].role: admin" in blob


def test_json_long_message_is_chunked_with_role_prefix_each_chunk():
    long_text = "Detailed explanation sentence. " * 100
    res = _json({"messages": [{"role": "assistant", "content": long_text}]})
    assert len(res.units) >= 3
    assert all(u.text.startswith("assistant: ") and len(u.text) <= 820 for u in res.units)
    assert [u.unit_id for u in res.units][:2] == [f"{REF}#m1", f"{REF}#m1.1"]


def test_json_empty_and_non_text_messages_skipped():
    res = _json({"messages": [
        {"role": "user", "content": ""},
        {"role": "user", "content": None},
        {"role": "tool", "content": []},
        {"role": "user", "content": "real"},
    ]})
    assert _texts(res) == ["user: real"]
    assert res.units[0].unit_id == f"{REF}#m4"


def test_json_message_cap_marks_partial():
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    res = _json({"messages": msgs}, max_messages=3)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert len(res.units) == 3


def test_json_unicode_preserved():
    res = _json({"messages": [{"role": "user", "content": "Xin chào, tôi tên là Nhân"}]})
    assert res.units[0].text == "user: Xin chào, tôi tên là Nhân"


# ---------------------------------------------------------------------------
# JSON plain documents -> flattened key paths
# ---------------------------------------------------------------------------

def test_json_plain_document_flattens_key_paths():
    res = _json({"name": "proj", "settings": {"theme": "dark", "retries": 3, "tags": ["a", "b"]},
                 "empty": "", "nothing": None, "flag": True, "ratio": 0.5})
    assert res.status == ExtractionStatus.COMPLETE.value
    blob = "\n".join(_texts(res))
    for expect in ("name: proj", "settings.theme: dark", "settings.retries: 3",
                   "settings.tags[0]: a", "settings.tags[1]: b", "flag: true", "ratio: 0.5"):
        assert expect in blob, expect
    assert "empty" not in blob and "nothing" not in blob and "null" not in blob
    assert all(u.kind == "text" and len(u.text) <= 800 for u in res.units)


def test_json_plain_array_of_records_uses_index_paths():
    res = _json([{"id": 1, "city": "Hue"}, {"id": 2, "city": "Hanoi"}])
    blob = "\n".join(_texts(res))
    assert "[0].city: Hue" in blob and "[1].city: Hanoi" in blob


def test_json_plain_document_many_leaves_are_packed_under_cap():
    doc = {f"key{i}": f"value number {i}" for i in range(500)}
    res = _json(doc)
    assert 1 < len(res.units) < 500
    assert all(len(u.text) <= 800 for u in res.units)
    blob = "\n".join(_texts(res))
    assert "key0: value number 0" in blob and "key499: value number 499" in blob


def test_json_plain_document_leaf_cap_marks_partial():
    doc = {f"k{i}": i for i in range(100)}
    res = _json(doc, max_leaves=10)
    assert res.status == ExtractionStatus.PARTIAL.value
    assert "k9: 9" in "\n".join(_texts(res)) and "k10: 10" not in "\n".join(_texts(res))


def test_json_deep_nesting_is_bounded_and_never_raises():
    node: dict = {"leaf": "deep value"}
    for _ in range(80):
        node = {"n": node}
    res = _json(node)
    assert res.status in (ExtractionStatus.COMPLETE.value, ExtractionStatus.PARTIAL.value)


def test_json_pathological_depth_is_typed_failure():
    res = _json("[" * 200_000 + "]" * 200_000)
    assert res.status == ExtractionStatus.CORRUPT_SOURCE.value


def test_json_scalar_top_level_and_null():
    assert _texts(_json('"just a string"')) == ["$: just a string"]
    assert _json("null").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _json("{}").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _json("[]").status == ExtractionStatus.EMPTY_SOURCE.value


def test_json_invalid_empty_and_binary():
    assert _json("{not json").status == ExtractionStatus.CORRUPT_SOURCE.value
    assert _json(b"").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _json("   \n").status == ExtractionStatus.EMPTY_SOURCE.value
    assert _json(b"\x00\x01\x02").status == ExtractionStatus.CORRUPT_SOURCE.value


def test_jsonl_with_some_bad_lines_is_partial():
    data = '{"role":"user","content":"ok"}\nnot-json\n{"role":"assistant","content":"fine"}\n'
    res = _json(data, hint="jsonl")
    assert res.status == ExtractionStatus.PARTIAL.value
    assert _texts(res) == ["user: ok", "assistant: fine"]
    assert "line" in (res.error_reason or "")


def test_jsonl_all_bad_lines_is_corrupt():
    assert _json("nope\nstill nope\n", hint="jsonl").status == ExtractionStatus.CORRUPT_SOURCE.value


def test_json_bom_prefixed():
    res = _json(b"\xef\xbb\xbf" + json.dumps({"messages": [{"role": "user", "content": "bom ok"}]}).encode())
    assert _texts(res) == ["user: bom ok"]


def test_json_conversations_list_gets_per_conversation_prefixes():
    res = _json([
        {"title": "One", "messages": [{"role": "user", "content": "a"}]},
        {"title": "Two", "messages": [{"role": "user", "content": "b"}]},
    ])
    ids = [u.unit_id for u in res.units]
    assert ids == [f"{REF}#c1", f"{REF}#c1m1", f"{REF}#c2", f"{REF}#c2m1"]
    assert res.units[3].parent_ref == f"{REF}#c2"


def test_json_ids_unique_and_deterministic_for_large_logs():
    msgs = [{"role": "user" if i % 2 else "assistant", "content": f"message {i}"} for i in range(300)]
    a, b = _json({"messages": msgs}), _json({"messages": msgs})
    assert [u.unit_id for u in a.units] == [u.unit_id for u in b.units]
    assert len({u.unit_id for u in a.units}) == 300


def test_json_secret_message_flows_through_for_pipeline_rejection():
    res = _json({"messages": [{"role": "user", "content": "my password=hunter2 ok"}]})
    assert "hunter2" in res.units[0].text
