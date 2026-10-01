"""T5 - CLI: add / ingest / search / context / forget / devlog / agents / serve / import-notes / status."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit import adapters_fixtures as fx
from tests.unit.t5_memory_helpers import SECRET_ENV, SECRET_TOKEN
from zero_mem import cli

SHARED = "ks-shared"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, sub in (("ZERO_MEM_DATA_ROOT", "data"), ("XDG_CONFIG_HOME", "cfg"), ("XDG_STATE_HOME", "st"),
                      ("XDG_CACHE_HOME", "ca")):
        monkeypatch.setenv(name, str(tmp_path / sub))
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    monkeypatch.delenv("ZERO_MEM_PROFILE", raising=False)
    return tmp_path


def run(capsys, *argv, stdin: str | None = None, monkeypatch=None):
    if stdin is not None:
        assert monkeypatch is not None
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def jrun(capsys, *argv, **kw):
    code, out, err = run(capsys, *argv, **kw)
    return code, (json.loads(out) if out.strip() else None), err


# ----------------------------------------------------------------------------- existing commands keep working
def test_existing_subcommands_still_work(home, capsys):
    assert run(capsys, "version")[0] == 0
    code, out, _ = run(capsys, "setup")
    assert code == 0 and out.strip() == "READY"
    assert run(capsys, "doctor", "--json")[0] in (0, 1)
    assert run(capsys, "config", "show")[0] == 0


def test_the_global_options_exist_and_default_sensibly(home, monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args(["search", "x"])
    assert args.profile == "default" and args.json is False
    monkeypatch.setenv("ZERO_MEM_PROFILE", "from-env")
    assert cli.build_parser().parse_args(["search", "x"]).profile == "from-env"
    assert cli.build_parser().parse_args(["--profile", "p1", "--json", "search", "x"]).profile == "p1"
    after = cli.build_parser().parse_args(["search", "x", "--profile", "p2", "--json"])
    assert after.profile == "p2" and after.json is True
    # a global value given before the subcommand survives when the subcommand does not repeat it
    assert cli.build_parser().parse_args(["--profile", "p3", "search", "x"]).profile == "p3"


# ----------------------------------------------------------------------------- add / search
def test_add_then_search_round_trip_json(home, capsys):
    code, res, _ = jrun(capsys, "--json", "add", "Alice", "prefers", "PostgreSQL", "for", "storage")
    assert code == 0 and res["status"] == "created" and res["ok"] is True and res["scope"] == "private"
    assert res["external_ref"].startswith("mem://fact/")
    code, found, _ = jrun(capsys, "search", "--json", "which", "database", "does", "Alice", "prefer")
    assert code == 0 and found["status"] == "ok" and found["hits"][0]["text"] == "Alice prefers PostgreSQL for storage"
    assert found["hits"][0]["memory_type"] == "fact" and found["hits"][0]["external_ref"] == res["external_ref"]


def test_add_human_output_and_idempotence(home, capsys):
    code, out, _ = run(capsys, "add", "Deploy staging on fly.io")
    assert code == 0 and out.startswith("created") and "mem://fact/" in out and "private" in out
    code, out, _ = run(capsys, "add", "Deploy staging on fly.io")
    assert code == 0 and out.startswith("unchanged")


def test_add_options_type_scope_name_project(home, capsys):
    code, res, _ = jrun(capsys, "--json", "add", "Terse answers.", "--type", "persona", "--name", "style")
    assert code == 0 and res["external_ref"] == "mem://persona/style" and res["memory_type"] == "persona"
    with pytest.raises(SystemExit) as exc:
        cli.main(["--json", "add", "x", "--type", "nope"])
    assert exc.value.code == 2 and "invalid choice" in capsys.readouterr().err


def test_add_reads_stdin_when_asked(home, capsys, monkeypatch):
    code, res, _ = jrun(capsys, "--json", "add", "-", stdin="from stdin\nsecond line\n", monkeypatch=monkeypatch)
    assert code == 0 and res["status"] == "created"
    _, found, _ = jrun(capsys, "search", "--json", "second")
    assert found["hits"][0]["text"].startswith("from stdin")


def test_add_a_secret_exits_4_with_a_friendly_message_and_stores_nothing(home, capsys):
    code, out, err = run(capsys, "add", f"my token is {SECRET_TOKEN}")
    assert code == 4 and out == ""
    assert "credential" in err and "Nothing was stored" in err and SECRET_TOKEN not in err
    code, found, _ = jrun(capsys, "search", "--json", "token")
    assert found["status"] == "empty"
    code, res, err = jrun(capsys, "--json", "add", SECRET_ENV)
    assert code == 4 and res["status"] == "rejected_secret" and SECRET_ENV not in json.dumps(res)


def test_add_invalid_input_exits_2(home, capsys):
    code, _out, err = run(capsys, "add", "   ")
    assert code == 2 and "text" in err.lower()


def test_shared_scope_is_denied_until_the_operator_grants_write(home, capsys):
    run(capsys, "agents", "add", "codex")
    code, out, err = run(capsys, "--profile", "codex", "add", "team rule: tabs", "--scope", "shared")
    assert code == 3 and "denied" in err.lower()
    assert "zero-mem agents grant-write codex --space ks-shared" in err  # tells the human how to approve
    assert run(capsys, "agents", "grant-write", "codex", "--space", SHARED, "--yes")[0] == 0
    code, res, _ = jrun(capsys, "--profile", "codex", "--json", "add", "team rule: tabs", "--scope", "shared")
    assert code == 0 and res["scope"] == "shared" and res["knowledge_space_id"] == SHARED


def test_two_agents_share_and_isolate_through_the_cli(home, capsys):
    run(capsys, "agents", "add", "claude-code", "codex")
    run(capsys, "agents", "grant-write", "claude-code", "--space", SHARED, "--yes")
    run(capsys, "--profile", "claude-code", "add", "convention about quokkas", "--scope", "shared")
    run(capsys, "--profile", "claude-code", "add", "private idea about quokkas", "--scope", "private")
    _, hits, _ = jrun(capsys, "--profile", "codex", "search", "--json", "quokkas")
    assert [h["text"] for h in hits["hits"]] == ["convention about quokkas"]
    _, hits, _ = jrun(capsys, "--profile", "claude-code", "search", "--json", "quokkas")
    assert {h["text"] for h in hits["hits"]} == {"convention about quokkas", "private idea about quokkas"}


def test_search_options_limit_type_and_human_output(home, capsys):
    for i in range(5):
        run(capsys, "add", f"kafka note {i}")
    run(capsys, "add", "kafka persona text", "--type", "persona", "--name", "k")
    code, out, _ = run(capsys, "search", "kafka", "-k", "2")
    assert code == 0 and len([ln for ln in out.splitlines() if ln.strip()[:2] in ("1.", "2.")]) == 2
    _, typed, _ = jrun(capsys, "search", "kafka", "--json", "--type", "persona")
    assert [h["memory_type"] for h in typed["hits"]] == ["persona"]
    _, two, _ = jrun(capsys, "search", "kafka", "--json", "--type", "persona", "--type", "fact", "-k", "10")
    assert {h["memory_type"] for h in two["hits"]} == {"persona", "fact"}
    code, out, _ = run(capsys, "search", "zzzznothing")
    assert code == 0 and "no results" in out.lower()
    code, _o, err = run(capsys, "search", "??")
    assert code == 2 and "query" in err.lower()


# ----------------------------------------------------------------------------- ingest
def _docs(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_text("# A\n\nNotes about postgres vacuum.\n")
    (root / "b.txt").write_text("Notes about redis eviction.\n")
    (root / "c.docx").write_bytes(fx.make_docx([("p", "Notes about nginx buffering.")]))
    return root


def test_ingest_folder_reports_and_is_idempotent(home, capsys):
    root = _docs(home)
    code, res, _ = jrun(capsys, "--json", "ingest", str(root), "--type", "file")
    assert code == 0 and res["status"] == "ok" and res["counts"]["created"] == 3
    assert {f["external_ref"] for f in res["files"]} == {"file://docs/a.md", "file://docs/b.txt", "file://docs/c.docx"}
    code, again, _ = jrun(capsys, "--json", "ingest", str(root), "--type", "file")
    assert code == 0 and again["counts"]["unchanged"] == 3 and again["counts"]["created"] == 0
    code, out, _ = run(capsys, "ingest", str(root), "--type", "file")
    assert code == 0 and "3 unchanged" in out
    _, found, _ = jrun(capsys, "search", "--json", "nginx")
    assert found["hits"][0]["external_ref"] == "file://docs/c.docx"


def test_ingest_with_a_secret_file_exits_1_and_lists_it(home, capsys):
    root = _docs(home)
    (root / "env.txt").write_text(f"db {SECRET_ENV}\n")
    (root / ".hidden").write_text("x")
    code, out, err = run(capsys, "ingest", str(root))
    assert code == 1
    assert "1 rejected" in out + err and "env.txt" in out + err and "credential" in (out + err).lower()
    assert SECRET_ENV not in out + err
    assert ".hidden" in out + err  # the skip report names skipped paths


def test_ingest_options_and_errors(home, capsys, tmp_path):
    assert run(capsys, "ingest", str(tmp_path / "nope"))[0] == 2
    assert "not found" in run(capsys, "ingest", str(tmp_path / "nope"))[2].lower()
    root = _docs(tmp_path)
    # the pre-T5 `--format` flag is accepted and ignored (formats are detected now)
    code, _o, err = run(capsys, "ingest", str(root), "--format", "text")
    assert code == 0 and "ignored" in err.lower()


def test_ingest_into_shared_needs_the_grant(home, capsys):
    root = _docs(home)
    run(capsys, "agents", "add", "codex")
    code, _o, err = run(capsys, "--profile", "codex", "ingest", str(root), "--scope", "shared")
    assert code == 3 and "grant-write" in err


# ----------------------------------------------------------------------------- context / devlog / forget / status
def test_context_prints_the_bundle_and_honours_max_chars(home, capsys):
    run(capsys, "add", "Terse answers.", "--type", "persona", "--name", "style")
    run(capsys, "add", "Run pytest before commits.", "--type", "workflow", "--name", "commit")
    code, out, _ = run(capsys, "context")
    assert code == 0 and "## Persona" in out and "Terse answers." in out and "## Workflow" in out
    code, small, _ = run(capsys, "context", "--max-chars", "30")
    assert code == 0 and len(small.rstrip("\n")) <= 30
    code, res, _ = jrun(capsys, "--json", "context", "--max-chars", "500")
    assert res["status"] == "ok" and res["max_chars"] == 500 and "Terse answers." in res["text"]
    code, _o, err = run(capsys, "context", "--max-chars", "0")
    assert code == 2


def test_context_of_an_empty_store_is_empty_and_ok(home, capsys):
    code, out, err = run(capsys, "context")
    assert code == 0 and out == "" and "empty" in err.lower()


def test_devlog_needs_a_project_and_a_project_grant(home, capsys):
    run(capsys, "agents", "add", "claude-code")
    code, _o, err = run(capsys, "--profile", "claude-code", "devlog", "fixed flaky test", "--project", "zero-mem")
    assert code == 3 and "grant-write claude-code --project zero-mem" in err
    run(capsys, "agents", "grant-write", "claude-code", "--project", "zero-mem", "--yes")
    code, res, _ = jrun(capsys, "--profile", "claude-code", "--json", "devlog", "fixed flaky test", "--project", "zero-mem")
    assert code == 0 and res["scope"] == "project" and res["external_ref"].startswith("mem://devlog/zero-mem/")
    code, out, _ = run(capsys, "--profile", "claude-code", "context")
    assert "fixed flaky test" in out and "## Recent devlog" in out
    with pytest.raises(SystemExit):
        cli.main(["devlog", "text only"])  # --project is required


def test_forget_by_id_ref_and_unknown(home, capsys):
    _, res, _ = jrun(capsys, "--json", "add", "Forget me about otters")
    code, out, _ = run(capsys, "forget", res["source_id"])
    assert code == 0 and "forgotten" in out
    assert run(capsys, "search", "otters")[1].lower().count("no results") == 1
    assert run(capsys, "forget", res["source_id"])[0] == 0  # already forgotten is fine
    code, _o, err = run(capsys, "forget", "f" * 64)
    assert code == 5 and "not found" in err.lower()
    code, _o, err = run(capsys, "forget", "ab")
    assert code == 2
    _, res2, _ = jrun(capsys, "--json", "add", "named", "--type", "persona", "--name", "p1")
    code, out2, _ = jrun(capsys, "--json", "forget", "mem://persona/p1")
    assert code == 0 and out2["status"] == "forgotten"


def test_forget_someone_elses_shared_source_is_denied_with_a_hint(home, capsys):
    run(capsys, "agents", "add", "claude-code", "codex")
    run(capsys, "agents", "grant-write", "claude-code", "--space", SHARED, "--yes")
    _, res, _ = jrun(capsys, "--profile", "claude-code", "--json", "add", "shared fact about kiwis", "--scope", "shared")
    code, _o, err = run(capsys, "--profile", "codex", "forget", res["source_id"])
    assert code == 3 and "denied" in err.lower()


def test_memory_status_command(home, capsys):
    run(capsys, "add", "a fact")
    code, st, _ = jrun(capsys, "--json", "memory-status")
    assert code == 0 and st["profile_id"] == "default" and st["sources"]["total"] == 1
    code, out, _ = run(capsys, "memory-status")
    assert code == 0 and "profile" in out and "sources" in out


def test_invalid_profile_is_a_friendly_error(home, capsys):
    code, _o, err = run(capsys, "--profile", "bad profile!", "add", "x")
    assert code == 2 and "profile" in err.lower()


# ----------------------------------------------------------------------------- agents
def test_agents_add_list_revoke(home, capsys):
    code, res, _ = jrun(capsys, "--json", "agents", "add", "claude-code", "codex")
    assert code == 0 and [r["profile"] for r in res["agents"]] == ["claude-code", "codex"]
    assert all(r["status"] == "added" for r in res["agents"])
    code, res, _ = jrun(capsys, "--json", "agents", "add", "codex")
    assert res["agents"][0]["status"] == "exists"
    code, res, _ = jrun(capsys, "--json", "agents", "grant-write", "codex", "--space", SHARED, "--yes",
                        "--basis", "owner approved in chat")
    assert code == 0 and res["status"] == "granted" and res["approval_ref"].startswith("opapp-")
    code, listed, _ = jrun(capsys, "--json", "agents", "list")
    rows = {r["profile"]: r for r in listed["agents"]}
    assert rows["codex"]["can_write_shared"] is True and rows["claude-code"]["can_write_shared"] is False
    code, out, _ = run(capsys, "agents", "list")
    assert "codex" in out and "write" in out.lower()
    code, res, _ = jrun(capsys, "--json", "agents", "revoke", "codex", "--space", SHARED, "--write")
    assert code == 0 and res["status"] == "revoked"
    code, listed, _ = jrun(capsys, "--json", "agents", "list")
    assert {r["profile"]: r for r in listed["agents"]}["codex"]["can_write_shared"] is False
    code, _o, err = run(capsys, "agents", "revoke", "codex", "--space", SHARED, "--write")
    assert code == 5 and "nothing to revoke" in err.lower()


def test_grant_write_requires_explicit_confirmation(home, capsys, monkeypatch):
    run(capsys, "agents", "add", "codex")
    # no --yes and not a terminal: refuse, grant nothing
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code, _o, err = run(capsys, "agents", "grant-write", "codex", "--space", SHARED)
    assert code == 2 and "--yes" in err
    _, listed, _ = jrun(capsys, "--json", "agents", "list")
    assert listed["agents"][0]["can_write_shared"] is False
    # an interactive operator can answer the prompt
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True, raising=False)
    from zero_mem import commands_memory
    monkeypatch.setattr(commands_memory, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_a: "n")
    assert run(capsys, "agents", "grant-write", "codex", "--space", SHARED)[0] == 2
    monkeypatch.setattr("builtins.input", lambda *_a: "yes")
    assert run(capsys, "agents", "grant-write", "codex", "--space", SHARED)[0] == 0


def test_grant_write_unknown_agent_and_bad_target(home, capsys):
    code, _o, err = run(capsys, "agents", "grant-write", "ghost", "--space", SHARED, "--yes")
    assert code == 2 and "agents add ghost" in err
    run(capsys, "agents", "add", "codex")
    with pytest.raises(SystemExit):
        cli.main(["agents", "grant-write", "codex", "--yes"])  # a target is required
    with pytest.raises(SystemExit):
        cli.main(["agents", "grant-write", "codex", "--space", SHARED, "--project", "p", "--yes"])


def test_agents_grant_read_for_a_project(home, capsys):
    run(capsys, "agents", "add", "codex")
    code, res, _ = jrun(capsys, "--json", "agents", "grant-read", "codex", "--project", "zero-mem")
    assert code == 0 and res["status"] == "granted"


# ----------------------------------------------------------------------------- serve
# T6b: the placeholder refusal ("this build's MCP server cannot pin an identity") is gone - the MCP server pins
# --profile-id since T6a - and ``serve`` / ``mcp-config`` now live in zero_mem/commands_mcp.py. Their tests are in
# tests/unit/test_t6b_cli.py (exec argv, refusals, a real stdio server started through ``serve``).


# ----------------------------------------------------------------------------- import-notes
def _old_notes(home, records):
    path = home / "data" / "data" / "notes" / "notes-v1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def test_import_notes_migrates_idempotently_and_keeps_the_old_file(home, capsys):
    path = _old_notes(home, [
        {"chunk_id": "c1", "text": "Alice prefers PostgreSQL for storage.", "source": "cli", "ts": 1},
        {"chunk_id": "c2", "text": "Deploy staging on fly.io.", "source": "plan.md", "ts": 2},
        {"chunk_id": "c3", "text": f"leaked {SECRET_ENV}", "source": "old.md", "ts": 3},
    ])
    before = path.read_bytes()
    code, res, _ = jrun(capsys, "--json", "import-notes")
    assert code == 1  # one record was rejected as a secret
    assert res["counts"] == {"created": 2, "updated": 0, "unchanged": 0, "rejected_secret": 1, "rejected_content": 0,
                             "invalid": 0, "denied": 0, "error": 0, "skipped": 0}
    code, again, _ = jrun(capsys, "--json", "import-notes")
    assert again["counts"]["created"] == 0 and again["counts"]["unchanged"] == 2
    assert path.read_bytes() == before  # raw traces are never deleted
    _, found, _ = jrun(capsys, "search", "--json", "PostgreSQL")
    hit = found["hits"][0]
    assert hit["text"] == "Alice prefers PostgreSQL for storage." and hit["memory_type"] == "fact"
    import sqlite3
    conn = sqlite3.connect(home / "data" / "data/derived/memory.sqlite3")
    try:
        prov = json.loads(conn.execute(
            "SELECT provenance FROM zm_corpus_sources WHERE external_ref=?", (hit["external_ref"],)).fetchone()[0])
    finally:
        conn.close()
    assert prov["imported_from"] == "notes-v1" and prov["notes_source"] == "cli" and prov["notes_chunk_id"] == "c1"


def test_import_notes_human_output_and_missing_file(home, capsys):
    code, _o, err = run(capsys, "import-notes")
    assert code == 2 and "notes-v1.jsonl" in err and "nothing to import" in err.lower()
    _old_notes(home, [{"chunk_id": "c1", "text": "A single note.", "source": "cli", "ts": 1}])
    code, out, _ = run(capsys, "import-notes")
    assert code == 0 and "1 created" in out
    path = home / "elsewhere.jsonl"
    path.write_text(json.dumps({"chunk_id": "z", "text": "From another file.", "source": "x", "ts": 1}) + "\n")
    code, out, _ = run(capsys, "import-notes", "--path", str(path), "--scope", "private")
    assert code == 0 and "1 created" in out


def test_import_notes_skips_malformed_lines(home, capsys):
    path = home / "data" / "data" / "notes" / "notes-v1.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"chunk_id": "c1", "text": "Good note.", "source": "cli", "ts": 1}\nnot json\n{"no_text": 1}\n[1]\n')
    code, res, _ = jrun(capsys, "--json", "import-notes")
    assert code == 1 and res["counts"]["created"] == 1 and res["counts"]["skipped"] == 3


def test_status_stays_unregistered_for_the_release_layer_gate(capsys):
    """PKG-1/PKG-3 pin ``status`` and ``rebuild`` as not-yet-exposed commands."""
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    help_text = capsys.readouterr().out
    assert " status" not in help_text and " rebuild" not in help_text
    assert "memory-status" in help_text and "agents" in help_text


# ----------------------------------------------------------------------------- real process
def test_the_module_runs_as_a_real_process(home, tmp_path):
    import os
    env = {**os.environ, "ZERO_MEM_DATA_ROOT": str(tmp_path / "proc"), "XDG_CONFIG_HOME": str(tmp_path / "pcfg"),
           "XDG_STATE_HOME": str(tmp_path / "pst"), "XDG_CACHE_HOME": str(tmp_path / "pca"), "PYTHONPATH": str(ROOT)}
    out = subprocess.run([sys.executable, "-m", "zero_mem.cli", "--json", "add", "process level fact"],
                         env=env, capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["status"] == "created"
    found = subprocess.run([sys.executable, "-m", "zero_mem.cli", "search", "--json", "process"],
                           env=env, capture_output=True, text=True, cwd=str(ROOT), timeout=120)
    assert json.loads(found.stdout)["hits"][0]["text"] == "process level fact"
