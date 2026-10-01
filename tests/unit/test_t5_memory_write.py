"""T5 - Memory write path: validation, authorization, secret pre-scan, lock+register+project, ingest."""
from __future__ import annotations

import os
import re
import sqlite3

import pytest

from tests.unit import adapters_fixtures as fx
from tests.unit.t5_memory_helpers import SECRET_ENV, SECRET_TOKEN, SHARED, Env
from zero_mem.memory import Memory, MemoryConfigError


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


@pytest.fixture
def mem(env):
    return env.open("claude-code")


# ----------------------------------------------------------------------------- open / setup
def test_open_runs_setup_and_pins_the_profile(tmp_path):
    root = tmp_path / "fresh"
    m = Memory.open("claude-code", data_root=root)
    try:
        assert m.profile_id == "claude-code" and m.shared_space == "ks-shared" == Memory.SHARED_SPACE
        assert (root / "data/derived/memory.sqlite3").is_file()
        assert (root / "data/corpus/corpus_sources.jsonl").is_file()
        assert (root / "data/memory/traces/events-v1.jsonl").is_file()
        with pytest.raises(AttributeError):
            m.profile_id = "someone-else"  # type: ignore[misc]
    finally:
        m.close()
    again = Memory.open("claude-code", data_root=root)  # idempotent
    again.close()


@pytest.mark.parametrize("bad", ["", " ", "a b", "../x", "-x", "x" * 65, None, 7])
def test_open_rejects_invalid_profile_ids(tmp_path, bad):
    with pytest.raises(MemoryConfigError):
        Memory.open(bad, data_root=tmp_path / "z")  # type: ignore[arg-type]


def test_open_uses_the_environment_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(tmp_path / "envroot"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "ca"))
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    m = Memory.open("default")
    try:
        assert m.layout.data_root == tmp_path / "envroot"
        assert m.add("env based fact").status == "created"
    finally:
        m.close()


# ----------------------------------------------------------------------------- add: refs and idempotence
def test_add_private_fact_returns_a_structured_created_result(mem, env):
    res = mem.add("Alice prefers PostgreSQL for storage.", "fact")
    assert res.ok and res.status == "created" and res.reason is None
    assert re.fullmatch(r"mem://fact/[0-9a-f]{12}", res.external_ref)
    assert res.memory_type == "fact" and res.scope == "private" and res.units == 1
    assert res.profile_id == "claude-code" and res.knowledge_space_id is None and res.project_id is None
    assert res.source_id and res.version and res.extraction in {"complete", "partial"}
    line = env.registry_lines()[-1]
    assert line["profile_id"] == "claude-code" and line["knowledge_space_id"] is None
    assert line["lifecycle_status"] == "observed" and line["custom_meta"] == {"memory_type": "fact"}
    assert line["provenance"]["channel"] == "library"
    assert env.units() == ["Alice prefers PostgreSQL for storage."]


def test_add_is_a_noop_for_identical_text_and_idempotent_across_instances(mem, env):
    first = mem.add("Deploy staging on fly.io.")
    again = mem.add("Deploy staging on fly.io.")
    other = env.open("claude-code").add("  Deploy staging on fly.io.\n")  # whitespace is not identity
    assert again.status == "unchanged" == other.status and again.source_id == first.source_id
    assert len(env.registry_lines()) == 1 and env.blob_count() == 1


def test_text_is_nfc_normalized_so_composed_and_decomposed_forms_are_one_fact(mem, env):
    import unicodedata
    text = "Ti\u1ebfng Vi\u1ec7t c\u00f3 d\u1ea5u"
    first = mem.add(text)
    decomposed = unicodedata.normalize("NFD", text)
    assert decomposed != text
    second = mem.add(decomposed)
    assert second.status == "unchanged" and second.source_id == first.source_id
    assert env.units() == [text]


@pytest.mark.parametrize("mtype,name,expected", [
    ("persona", "style", "mem://persona/style"),
    ("workflow", "release", "mem://workflow/release"),
    ("skill", "tdd", "mem://skill/tdd"),
    ("fact", "pg-choice", "mem://fact/pg-choice"),
    ("file", "notes/a.md", "file://notes/a.md"),
])
def test_named_sources_use_the_design_ref_scheme(mem, mtype, name, expected):
    res = mem.add("Some body text for the source.", mtype, name=name)
    assert res.ok and res.external_ref == expected and res.memory_type == mtype


@pytest.mark.parametrize("mtype", ["persona", "workflow", "skill"])
def test_unnamed_types_get_immutable_content_hash_ids(mem, mtype):
    a = mem.add("First text.", mtype)
    b = mem.add("Second text.", mtype)
    assert re.fullmatch(rf"mem://{mtype}/[0-9a-f]{{12}}", a.external_ref) and a.external_ref != b.external_ref


def test_named_source_update_creates_a_new_version_and_drops_stale_units(mem, env):
    v1 = mem.add("Persona line one.\n\nPersona line two will be removed.", "persona", name="style")
    v2 = mem.add("Persona line one.\n\nPersona line three is new.", "persona", name="style")
    assert (v1.status, v2.status) == ("created", "updated") and v1.source_id == v2.source_id
    assert v1.version != v2.version
    assert "Persona line two will be removed." not in " ".join(env.units())  # DEF-050 behaviour through the library
    assert len(env.registry_lines()) == 2 and env.registry_lines()[1]["supersedes"] == v1.version


def test_devlog_ref_carries_project_date_and_entry_hash(env):
    m = env.agent("claude-code", write_projects=["zero-mem"])
    res = m.add("Fixed the flaky lock test.", "devlog", project_id="zero-mem")
    assert res.ok and res.scope == "project" and res.project_id == "zero-mem" and res.knowledge_space_id is None
    assert re.fullmatch(r"mem://devlog/zero-mem/2026-10-01/[0-9a-f]{8}", res.external_ref)
    env.clock.set("2026-10-02T01:00:00+00:00")
    nxt = m.add("Next day entry.", "devlog", project_id="zero-mem")
    assert "/2026-10-02/" in nxt.external_ref
    assert m.add("Fixed the flaky lock test.", "devlog", project_id="zero-mem").status == "created"  # new day = new entry


def test_two_distinct_devlog_entries_on_one_day_are_both_kept(env):
    m = env.agent("claude-code", write_projects=["zero-mem"])
    a = m.add("Entry one.", "devlog", project_id="zero-mem")
    b = m.add("Entry two.", "devlog", project_id="zero-mem")
    assert a.ok and b.ok and a.external_ref != b.external_ref


# ----------------------------------------------------------------------------- validation (closed schema, byte caps)
@pytest.mark.parametrize("kwargs,reason", [
    ({"text": ""}, "invalid_text"),
    ({"text": "   \n "}, "invalid_text"),
    ({"text": None}, "invalid_text"),
    ({"text": 5}, "invalid_text"),
    ({"text": b"bytes"}, "invalid_text"),
    ({"text": "a\x00b"}, "invalid_text"),
    ({"text": "a\ud800b"}, "invalid_text"),
    ({"text": "x" * (256 * 1024 + 1)}, "text_too_large"),
    ({"text": "ok", "memory_type": "note"}, "invalid_memory_type"),
    ({"text": "ok", "memory_type": None}, "invalid_memory_type"),
    ({"text": "ok", "memory_type": ["fact"]}, "invalid_memory_type"),
    ({"text": "ok", "scope": "global"}, "invalid_scope"),
    ({"text": "ok", "scope": 3}, "invalid_scope"),
    ({"text": "ok", "name": ""}, "invalid_name"),
    ({"text": "ok", "name": "../etc/passwd"}, "invalid_name"),
    ({"text": "ok", "name": "a//b"}, "invalid_name"),
    ({"text": "ok", "name": "/abs"}, "invalid_name"),
    ({"text": "ok", "name": "has space"}, "invalid_name"),
    ({"text": "ok", "name": "x" * 129}, "invalid_name"),
    ({"text": "ok", "name": 5}, "invalid_name"),
    ({"text": "ok", "scope": "project"}, "project_id_required"),
    ({"text": "ok", "scope": "project", "project_id": "bad id"}, "invalid_project_id"),
    ({"text": "ok", "scope": "private", "project_id": "p"}, "project_id_not_allowed"),
    ({"text": "ok", "scope": "shared", "project_id": "p"}, "project_id_not_allowed"),
    ({"text": "ok", "memory_type": "devlog"}, "project_id_required"),
    ({"text": "ok", "memory_type": "devlog", "scope": "private", "project_id": "p"}, "devlog_requires_project_scope"),
    ({"text": "ok", "memory_type": "devlog", "scope": "shared"}, "devlog_requires_project_scope"),
    ({"text": "ok", "kind": "exe"}, "invalid_kind"),
])
def test_invalid_input_is_a_typed_result_never_an_exception_or_a_write(mem, env, kwargs, reason):
    res = mem.add(**kwargs)
    assert res.status == "invalid" and res.reason == reason and not res.ok
    assert env.registry_lines() == [] and env.blob_count() == 0 and env.units() == []


def test_a_text_at_the_cap_is_accepted(mem):
    assert mem.add(("word " * 51_000)[: 256 * 1024]).ok


# ----------------------------------------------------------------------------- secrets: reject, never store
@pytest.mark.parametrize("secret", [
    SECRET_TOKEN,
    "AKIA" + "IOSFODNN7EXAMPLE",
    "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789",
    SECRET_ENV,
    "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789ABCD",
    "postgres://admin:s3cretpw@db.internal:5432/app",
])
def test_secret_text_is_rejected_before_anything_is_persisted(mem, env, secret):
    stream_before = env.layout.memory_stream.read_bytes()
    res = mem.add(f"remember this: {secret} please", "fact")
    assert res.status == "rejected_secret" and not res.ok and res.reason == "secret_detected"
    assert res.rule_ids  # fixed rule ids, never the value
    assert secret not in repr(res) and secret not in str(res.as_dict())
    assert env.registry_lines() == [] and env.blob_count() == 0 and env.units() == []
    assert env.files_containing(secret) == []
    assert env.layout.memory_stream.read_bytes() == stream_before


def test_a_credential_shaped_name_is_rejected_because_the_ref_is_canonical(mem, env):
    res = mem.add("harmless body", "fact", name="AKIA" + "IOSFODNN7EXAMPLE")
    assert res.status == "rejected_secret"
    assert env.files_containing("AKIA" + "IOSFODNN7EXAMPLE") == []
    assert env.registry_lines() == []


def test_secret_inside_an_office_container_is_rejected_via_the_extracted_text(mem, env):
    docx = fx.make_docx([("h", 1, "Runbook"), ("p", f"deploy with {SECRET_ENV} then restart")])
    report = mem.ingest(docx, filename="runbook.docx", memory_type="file")
    (res,) = report.files
    assert res.status == "rejected_secret" and report.counts["rejected_secret"] == 1
    assert env.registry_lines() == [] and env.blob_count() == 0 and env.units() == []


def test_secret_split_across_a_json_escape_is_still_caught(mem, env):
    payload = '{"role":"user","content":"my key is %s"}\n{"role":"assistant","content":"noted"}\n' % SECRET_TOKEN.replace("-", "\\u002d")
    (res,) = mem.ingest(payload.encode(), filename="chat.jsonl", memory_type="fact").files
    assert res.status == "rejected_secret"
    assert env.registry_lines() == []


def test_a_rejected_secret_does_not_block_following_writes(mem):
    assert mem.add(SECRET_TOKEN).status == "rejected_secret"
    assert mem.add("a normal fact").status == "created"


# ----------------------------------------------------------------------------- authorization (write)
def test_private_write_needs_no_grant(mem):
    assert mem.add("private note", scope="private").ok


def test_shared_write_without_a_grant_is_denied_and_nothing_is_stored(env):
    m = env.agent("codex")  # READ shared only
    res = m.add("team convention: tabs", "fact", scope="shared")
    assert res.status == "denied" and res.reason == "DENY_CROSS_PROFILE_WRITE" and not res.ok
    assert env.registry_lines() == [] and env.blob_count() == 0 and env.units() == []


def test_a_denied_write_is_audited_without_content(env):
    m = env.agent("codex")
    secret_free = "team convention: tabs"
    m.add(secret_free, "fact", scope="shared")
    audits = env.stream_events("policy_decision")
    assert len(audits) == 1
    body = audits[0]["m4"]
    assert body["allow"] is False and body["reason_code"] == "DENY_CROSS_PROFILE_WRITE"
    assert body["requester"] == "codex" and body["operation"] == "WRITE"
    assert body["target_scope"] == f"knowledge_space:{SHARED}"
    assert secret_free not in open(env.layout.memory_stream, encoding="utf-8").read()
    conn = sqlite3.connect(env.layout.derived_db)
    try:
        row = conn.execute("SELECT requester, allow, reason_code FROM zm_policy_audit").fetchall()
    finally:
        conn.close()
    assert row == [("codex", 0, "DENY_CROSS_PROFILE_WRITE")]


def test_shared_write_with_an_operator_approved_grant_is_stored_in_the_shared_space(env):
    m = env.agent("codex", write_shared=True)
    res = m.add("team convention: spaces", "fact", scope="shared")
    assert res.ok and res.scope == "shared" and res.knowledge_space_id == SHARED and res.profile_id == "codex"
    line = env.registry_lines()[-1]
    assert line["knowledge_space_id"] == SHARED and line["profile_id"] == "codex" and line["project_id"] is None
    audits = env.stream_events("policy_decision")
    assert [a["m4"]["reason_code"] for a in audits] == ["ALLOW_EXPLICIT_CROSS_PROFILE_WRITE"]
    assert audits[0]["m4"]["grant_refs"]


def test_revoking_the_write_grant_denies_further_shared_writes(env):
    m = env.agent("codex", write_shared=True)
    assert m.add("first shared", scope="shared").ok
    env.prov.revoke("codex", space=SHARED, operation="WRITE")
    res = m.add("second shared", scope="shared")
    assert res.status == "denied"
    assert m.add("still private", scope="private").ok


def test_a_forged_unapproved_write_grant_does_not_authorize_shared_writes(env):
    from zero_mem.provisioning import append_canonical_event
    from src.access.rebuild import rebuild_policy_state
    env.prov.add_agent("codex")
    append_canonical_event(env.layout.memory_stream, {
        "event_id": "forged", "event_type": "access_grant", "created_at": "2026-10-01T00:00:00Z",
        "m4": {"domain": "access_grant", "identity": "g-f", "op": "create", "grant_id": "g-f", "subject_profile": "codex",
               "operation": "WRITE", "target_type": "knowledge_space", "target_id": SHARED,
               "resource_types": ["corpus_source"], "lifecycle_status": "active", "verification_ref": "opapp-bogus"}})
    store_conn = sqlite3.connect(env.layout.derived_db)
    store_conn.row_factory = sqlite3.Row
    try:
        rebuild_policy_state(store_conn, env.layout.memory_stream)
        store_conn.commit()
    finally:
        store_conn.close()
    res = env.open("codex").add("sneaky", scope="shared")
    assert res.status == "denied"


def test_devlog_needs_a_project_write_grant(env):
    m = env.agent("codex")
    res = m.add("did things", "devlog", project_id="zero-mem")
    assert res.status == "denied" and res.reason == "DENY_CROSS_PROFILE_WRITE"
    env.prov.grant_write("codex", project="zero-mem", basis="test")
    assert m.add("did things", "devlog", project_id="zero-mem").ok
    assert m.add("did things", "devlog", project_id="other-project").status == "denied"


def test_the_profile_is_pinned_a_write_is_always_attributed_to_the_opened_profile(env):
    a = env.open("claude-code")
    b = env.open("codex")
    ra, rb = a.add("fact from a"), b.add("fact from b")
    assert {l["profile_id"] for l in env.registry_lines()} == {"claude-code", "codex"}
    assert ra.profile_id == "claude-code" and rb.profile_id == "codex"
    import inspect
    for name in ("add", "ingest", "recall", "context", "forget"):
        assert "profile" not in " ".join(inspect.signature(getattr(Memory, name)).parameters)


def test_write_result_is_json_safe_and_hides_none(mem):
    import json
    res = mem.add("json safe check").as_dict()
    assert json.loads(json.dumps(res))["status"] == "created" and "reason" not in res


# ----------------------------------------------------------------------------- crash safety / healing
def test_unchanged_add_heals_a_missing_projection(mem, env):
    res = mem.add("healable fact")
    conn = sqlite3.connect(env.layout.derived_db)
    try:
        conn.execute("DELETE FROM zm_corpus_fts")
        conn.execute("DELETE FROM zm_corpus_units")
        conn.execute("DELETE FROM zm_corpus_sources")
        conn.commit()
    finally:
        conn.close()
    assert env.units() == []
    again = mem.add("healable fact")
    assert again.status == "unchanged" and again.source_id == res.source_id
    assert env.units() == ["healable fact"]


def test_projection_failure_is_reported_not_raised_and_retry_succeeds(mem, env, monkeypatch):
    import src.corpus.derived_store as derived_mod
    calls = {"n": 0}
    real = derived_mod.project_source

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(*a, **kw)

    monkeypatch.setattr(derived_mod, "project_source", flaky)
    first = mem.add("flaky projection fact")
    assert first.status == "error" and first.reason == "projection_failed" and first.source_id
    assert env.units() == []
    retry = mem.add("flaky projection fact")
    assert retry.ok and env.units() == ["flaky projection fact"]


# ----------------------------------------------------------------------------- ingest
def _tree(tmp_path):
    root = tmp_path / "docs"
    (root / "sub").mkdir(parents=True)
    (root / "node_modules").mkdir()
    (root / "a.md").write_text("# Title\n\nAlpha paragraph about postgres tuning.\n", encoding="utf-8", newline="\n")
    (root / "b.txt").write_text("Beta plain text about redis caching.\n", encoding="utf-8", newline="\n")
    (root / "sub" / "data.csv").write_text("name,role\nalice,admin\nbob,viewer\n", encoding="utf-8", newline="\n")
    (root / "sub" / "chat.jsonl").write_text(
        '{"role":"user","content":"hello gamma"}\n{"role":"assistant","content":"hi delta"}\n', encoding="utf-8", newline="\n")
    (root / "report.docx").write_bytes(fx.make_docx([("h", 1, "Quarterly"), ("p", "Epsilon revenue grew.")]))
    (root / "sheet.xlsx").write_bytes(fx.make_xlsx([("S1", [["k", "v"], ["zeta", "9"]])]))
    (root / "empty.txt").write_text("", encoding="utf-8", newline="\n")
    (root / ".hidden.md").write_text("hidden text", encoding="utf-8", newline="\n")
    (root / "node_modules" / "x.md").write_text("node module text", encoding="utf-8", newline="\n")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02\xff" * 64)
    (root / "link.md").symlink_to(root / "a.md")
    (root / "secret.txt").write_text(f"notes\n{SECRET_ENV}\n", encoding="utf-8", newline="\n")
    return root


def test_ingest_directory_reports_created_rejected_and_skipped(mem, env, tmp_path):
    root = _tree(tmp_path)
    report = mem.ingest(root, memory_type="file")
    names = {r.name: r for r in report.files}
    assert {n for n, r in names.items() if r.status == "created"} == {
        "a.md", "b.txt", "sub/data.csv", "sub/chat.jsonl", "report.docx", "sheet.xlsx"}
    assert names["secret.txt"].status == "rejected_secret"
    skipped = {s["name"]: s["reason"] for s in report.skipped}
    assert skipped == {
        "empty.txt": "empty", ".hidden.md": "hidden", "node_modules": "excluded_dir",
        "blob.bin": "unsupported_binary", "link.md": "symlink"}
    assert report.counts["created"] == 6 and report.counts["rejected_secret"] == 1 and report.counts["skipped"] == 5
    assert report.status == "partial" and not report.ok
    assert env.files_containing(SECRET_ENV) == []
    refs = {r.external_ref for r in report.files if r.status == "created"}
    assert "file://docs/a.md" in refs and "file://docs/sub/data.csv" in refs
    for needle in ("Alpha paragraph", "Epsilon revenue", "gamma", "alice", "zeta"):
        assert any(needle in u for u in env.units()), needle


def test_ingest_clean_directory_is_ok_and_reingest_is_a_noop(mem, env, tmp_path):
    root = tmp_path / "clean"
    root.mkdir()
    (root / "one.md").write_text("# One\n\nFirst note about kafka.\n", encoding="utf-8", newline="\n")
    (root / "two.txt").write_text("Second note about nginx.\n", encoding="utf-8", newline="\n")
    first = mem.ingest(root)
    assert first.ok and first.status == "ok" and first.counts["created"] == 2
    lines_before, blobs_before = len(env.registry_lines()), env.blob_count()
    second = mem.ingest(root)
    assert second.ok and second.counts["unchanged"] == 2 and second.counts["created"] == 0
    assert len(env.registry_lines()) == lines_before and env.blob_count() == blobs_before


def test_changed_file_becomes_a_new_version_and_old_text_is_gone(mem, env, tmp_path):
    root = tmp_path / "ver"
    root.mkdir()
    f = root / "note.md"
    f.write_text("Old claim about mongo.\n", encoding="utf-8", newline="\n")
    mem.ingest(root)
    f.write_text("New claim about sqlite.\n", encoding="utf-8", newline="\n")
    report = mem.ingest(root)
    assert report.counts["updated"] == 1 and report.counts["created"] == 0
    assert env.units() == ["New claim about sqlite."]
    assert [l["supersedes"] is not None for l in env.registry_lines()] == [False, True]


def test_ingest_single_file_and_bytes(mem, env, tmp_path):
    f = tmp_path / "solo.md"
    f.write_text("Solo file about haskell.\n", encoding="utf-8", newline="\n")
    r1 = mem.ingest(f, memory_type="fact")
    assert r1.ok and r1.files[0].external_ref == "mem://fact/solo.md"
    r2 = mem.ingest(b"Bytes about erlang.\n", filename="bytes.txt", memory_type="file")
    assert r2.ok and r2.files[0].external_ref == "file://bytes.txt"
    r3 = mem.ingest(b"id,v\n1,2\n", filename="t.csv", memory_type="fact", name="tables/t")
    assert r3.ok and r3.files[0].external_ref == "mem://fact/tables/t"


def test_non_ascii_names_are_percent_encoded_and_collision_free(mem, tmp_path):
    root = tmp_path / "vn"
    root.mkdir()
    (root / "tài liệu.md").write_text("Nội dung một.\n", encoding="utf-8", newline="\n")
    (root / "tai lieu.md").write_text("Nội dung hai.\n", encoding="utf-8", newline="\n")
    report = mem.ingest(root, memory_type="file")
    refs = [r.external_ref for r in report.files]
    assert report.ok and len(set(refs)) == 2 and all(re.fullmatch(r"file://vn/[A-Za-z0-9%._~+@-]+", r) for r in refs)


def test_names_that_start_with_a_non_ascii_letter_or_punctuation_are_ingested(mem, tmp_path):
    root = tmp_path / "odd"
    root.mkdir()
    for name in ("ánh.md", "_draft.md", "-dash.md", "~tilde.md", "+plus.md", "@at.md", "2026 notes.md"):
        (root / name).write_text(f"Content of {name} about narwhals.\n", encoding="utf-8", newline="\n")
    report = mem.ingest(root, memory_type="file")
    assert report.ok and report.counts["created"] == 7, report.as_dict()


@pytest.mark.parametrize("bad", ["..", "a/../b", "a/./b", "./a", "a/..", "../a", "a//b", "/a", "a/", "a b", "a\\b"])
def test_dot_segments_and_separators_stay_invalid_in_names(mem, bad):
    assert mem.add("body", "fact", name=bad).reason == "invalid_name"


def test_ingest_invalid_inputs_are_typed(mem, tmp_path):
    assert mem.ingest(tmp_path / "does-not-exist").status == "invalid"
    assert mem.ingest(tmp_path / "does-not-exist").reason == "path_not_found"
    assert mem.ingest(12345).reason == "invalid_source"  # type: ignore[arg-type]
    for bad in ("", "..", "a\x00b", "x" * 256, 5):
        assert mem.ingest(b"x", filename=bad, memory_type="fact").reason == "invalid_filename", bad  # type: ignore[arg-type]
    (empty,) = mem.ingest(b"", filename="e.txt").files
    assert empty.status == "rejected_content" and empty.reason == "empty_source"
    assert mem.ingest(b"x" * 10, memory_type="nope").reason == "invalid_memory_type"
    big = b"a" * (16 * 1024 * 1024 + 1)
    assert mem.ingest(big, filename="big.txt").files[0].reason == "content_too_large"


def test_ingest_honours_allow_roots(mem, tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (root / "f.md").write_text("inside\n", encoding="utf-8", newline="\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "g.md").write_text("outside\n", encoding="utf-8", newline="\n")
    assert mem.ingest(root, allow_roots=[root]).ok
    res = mem.ingest(outside, allow_roots=[root])
    assert res.status == "invalid" and res.reason == "path_outside_allow_roots"


def test_ingest_authorizes_once_per_call_and_denies_the_whole_batch(env, tmp_path):
    m = env.agent("codex")  # no shared write
    root = tmp_path / "shared-docs"
    root.mkdir()
    for i in range(3):
        (root / f"f{i}.md").write_text(f"shared doc number {i}\n", encoding="utf-8", newline="\n")
    report = m.ingest(root, scope="shared")
    assert report.status == "denied" and report.reason == "DENY_CROSS_PROFILE_WRITE"
    assert report.files == [] and env.registry_lines() == []
    assert len(env.stream_events("policy_decision")) == 1  # one decision for the whole batch


def test_ingest_into_shared_with_a_grant_stores_every_file_in_the_shared_space(env, tmp_path):
    m = env.agent("codex", write_shared=True)
    root = tmp_path / "shared-docs"
    root.mkdir()
    for i in range(3):
        (root / f"f{i}.md").write_text(f"shared doc number {i}\n", encoding="utf-8", newline="\n")
    report = m.ingest(root, scope="shared", memory_type="file")
    assert report.ok and report.counts["created"] == 3
    assert {l["knowledge_space_id"] for l in env.registry_lines()} == {SHARED}
    assert len(env.stream_events("policy_decision")) == 1


def test_ingest_unsupported_and_corrupt_inputs_are_rejected_with_a_reason(mem, env):
    corrupt = b"PK\x03\x04" + b"not really a zip" * 20
    (res,) = mem.ingest(corrupt, filename="broken.docx").files
    assert res.status == "rejected_content" and res.reason == "corrupt_source"
    (binary,) = mem.ingest(b"\x00\x01\x02\xff" * 64, filename="blob.bin").files
    assert binary.status == "rejected_content" and binary.reason == "unsupported_format"
    assert env.registry_lines() == [] and env.blob_count() == 0


def test_secret_file_in_a_batch_does_not_stop_the_other_files(mem, tmp_path):
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "a_secret.txt").write_text(SECRET_TOKEN + "\n", encoding="utf-8", newline="\n")
    (root / "b_fine.txt").write_text("a fine note about grpc\n", encoding="utf-8", newline="\n")
    report = mem.ingest(root)
    statuses = {r.name: r.status for r in report.files}
    assert statuses == {"a_secret.txt": "rejected_secret", "b_fine.txt": "created"}


# ----------------------------------------------------------------------------- concurrency inside one process
def test_two_instances_adding_concurrently_land_every_source_once(env):
    import threading
    a, b = env.open("claude-code"), env.open("claude-code")
    errors = []

    def work(m, tag):
        try:
            for i in range(15):
                r = m.add(f"{tag} fact number {i} about topic {i % 3}")
                assert r.ok, r
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(m, t)) for m, t in ((a, "alpha"), (b, "beta"))]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert len(env.registry_lines()) == 30 and len(env.units()) == 30


# ----------------------------------------------------------------------------- ported from the retired notes store
def test_long_text_is_chunked_into_bounded_units(mem, env):
    res = mem.add("word " * 1000)
    assert res.ok and res.units > 1
    assert all(len(u) <= 800 for u in env.units())


def test_chat_logs_become_one_unit_per_turn(mem, env):
    jsonl = b'{"role":"user","content":"hi"}\n{"role":"assistant","content":[{"text":"yo"}]}\n'
    (res,) = mem.ingest(jsonl, filename="chat.jsonl", memory_type="fact").files
    assert res.ok and res.units == 2
    assert sorted(env.units()) == ["assistant: yo", "user: hi"]
    messages = b'{"messages":[{"role":"user","content":"ping"},{"role":"assistant","content":"pong"}]}'
    (res2,) = mem.ingest(messages, filename="export.json", memory_type="fact").files
    assert res2.ok and "assistant: pong" in env.units()


def test_notes_style_search_dedup_and_secret_rejection_end_to_end(mem):
    assert mem.add("Alice prefers PostgreSQL for storage.").status == "created"
    assert mem.add("Alice prefers PostgreSQL for storage.").status == "unchanged"
    assert "PostgreSQL" in mem.recall("which database does Alice prefer? PostgreSQL")[0].text
    assert mem.recall("zzzunknown").status == "empty"
    assert mem.add("token " + SECRET_TOKEN).status == "rejected_secret"
    assert mem.status()["sources"]["total"] == 1


# ----------------------------------------------------------------------------- caller provenance (closed, scanned)
def test_add_records_caller_provenance_outside_the_source_identity(mem, env):
    a = mem.add("provenance carrying fact", provenance={"imported_from": "notes-v1", "notes_ts": 5})
    line = env.registry_lines()[-1]
    assert line["provenance"]["imported_from"] == "notes-v1" and line["provenance"]["notes_ts"] == 5
    assert line["provenance"]["channel"] == "library" and line["provenance"]["tool"] == "add"
    b = mem.add("provenance carrying fact", provenance={"imported_from": "other"})
    assert b.status == "unchanged" and b.source_id == a.source_id  # provenance is not identity


def test_the_pinned_provenance_fields_cannot_be_overridden(mem, env):
    mem.add("override attempt", provenance={"channel": "mcp", "profile": "someone-else", "writer": "x", "tool": "y"})
    prov = env.registry_lines()[-1]["provenance"]
    assert prov["channel"] == "library" and prov["profile"] == "claude-code" and prov["writer"] == "zero_mem.memory"
    assert prov["tool"] == "add"


@pytest.mark.parametrize("bad", [
    "text", ["a"], {"k": ["nested"]}, {"k": {"n": 1}}, {"bad key": "v"}, {"": "v"}, {"k": "x" * 201},
    {f"k{i}": i for i in range(9)}, {"k": 1.5}, {"k": None},
])
def test_invalid_provenance_is_rejected_before_any_write(mem, env, bad):
    res = mem.add("provenance validation", provenance=bad)
    assert res.status == "invalid" and res.reason == "invalid_provenance" and env.registry_lines() == []


def test_a_secret_in_provenance_is_rejected_not_stored(mem, env):
    res = mem.add("harmless text", provenance={"note": SECRET_TOKEN})
    assert res.status == "rejected_secret" and env.files_containing(SECRET_TOKEN) == []
