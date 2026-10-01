"""T8 - ``zero-mem doctor`` checks of the memory runtime and the ``runtime`` block of ``zero-mem memory-status --json``.

Read-only, cheap, no paths and no memory content in the output: data root writable, corpus root present, schema
current, grant counts, source / unit counts (live and forgotten), projection drift and the time of the last write.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sqlite3

import pytest

from tests.unit.t6b_helpers import apply_env
from zero_mem import cli
from zero_mem.memory import Memory
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import Provisioner


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def home(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    return tmp_path


def doctor(home):
    code, out, err = run_cli("doctor", "--json")
    report = json.loads(out)
    return code, {c["id"]: c for c in report["checks"]}, report, out


def populate():
    layout = Layout.resolve(None)
    layout.ensure()
    prov = Provisioner(layout, operator="tester")
    for agent in ("claude-code", "codex"):
        prov.add_agent(agent)
    prov.grant_write("claude-code", space="ks-shared", basis="owner approved")
    with Memory.open("claude-code") as cc:
        cc.add("The user prefers terse answers.", "persona", name="style", scope="shared")
        cc.add("A private fact about herons.", "fact")
        gone = cc.add("A mistaken fact.", "fact")
        cc.forget(gone.source_id)
    with Memory.open("codex") as cx:
        cx.add("Codex private note about owls.", "fact")
    return layout


def test_a_fresh_setup_reports_the_memory_runtime_as_ready_with_honest_warnings(home):
    assert run_cli("setup")[0] == 0
    before = sorted((p.relative_to(home), p.stat().st_mtime_ns, p.stat().st_size) for p in home.rglob("*") if p.is_file())
    code, checks, report, raw = doctor(home)
    after = sorted((p.relative_to(home), p.stat().st_mtime_ns, p.stat().st_size) for p in home.rglob("*") if p.is_file())
    assert code == 0 and report["overall"] == "READY" and before == after  # read-only
    assert checks["memory_data_root"]["status"] == "PASS" and "writable" in checks["memory_data_root"]["message"]
    assert checks["memory_schema"]["status"] == "PASS" and re.search(r"version \d+", checks["memory_schema"]["message"])
    assert checks["memory_grants"]["status"] == "WARN" and "agents add" in checks["memory_grants"]["message"]
    assert checks["memory_sources"]["status"] == "WARN" and "no memories" in checks["memory_sources"]["message"]
    assert str(home) not in raw  # no paths


def test_a_populated_store_reports_grants_sources_units_and_the_last_write(home):
    layout = populate()
    code, checks, report, raw = doctor(home)
    assert code == 0 and report["overall"] == "READY"
    grants = checks["memory_grants"]
    assert grants["status"] == "PASS"
    assert "3 active grant(s)" in grants["message"] and "2 agent(s)" in grants["message"]
    assert "2 read" in grants["message"] and "1 write" in grants["message"]
    sources = checks["memory_sources"]
    conn = sqlite3.connect(layout.derived_db)
    try:
        units = conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0]
    finally:
        conn.close()
    assert sources["status"] == "PASS"
    assert "4 source(s) (1 forgotten)" in sources["message"] and f"{units} unit(s)" in sources["message"]
    assert re.search(r"last write 20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ", sources["message"])
    assert checks["memory_data_root"]["status"] == "PASS"
    assert str(home) not in raw and "herons" not in raw and "terse" not in raw  # no paths, no content


def test_projection_drift_is_a_warning_that_names_the_fix(home):
    layout = populate()
    conn = sqlite3.connect(layout.derived_db)
    try:
        conn.execute("UPDATE zm_corpus_sources SET content_hash='stale' "
                     "WHERE source_id=(SELECT source_id FROM zm_corpus_sources LIMIT 1)")
        conn.commit()
    finally:
        conn.close()
    code, checks, report, _raw = doctor(home)
    assert checks["memory_sources"]["status"] == "WARN"
    assert "1 source(s) not projected" in checks["memory_sources"]["message"]
    assert "zero-mem upgrade" in checks["memory_sources"]["message"]
    assert report["overall"] == "READY"  # a rebuildable derived state never blocks upgrade / restore


def test_an_unwritable_data_root_is_a_warning(home, monkeypatch):
    populate()
    from zero_mem import memory_health

    monkeypatch.setattr(memory_health.os, "access", lambda path, mode: False)
    _code, checks, report, _raw = doctor(home)
    assert checks["memory_data_root"]["status"] == "WARN" and "not writable" in checks["memory_data_root"]["message"]
    assert report["overall"] == "READY"


def test_an_uninitialised_install_is_reported_without_creating_anything(home):
    code, checks, report, raw = doctor(home)
    assert not (home / "data").exists()
    for check_id in ("memory_data_root", "memory_schema", "memory_grants", "memory_sources"):
        assert checks[check_id]["status"] == "WARN" and "zero-mem setup" in checks[check_id]["message"], check_id
    assert "Traceback" not in raw


def test_memory_status_json_carries_a_runtime_block(home):
    populate()
    code, out, err = run_cli("memory-status", "--json", "--profile", "claude-code")
    assert code == 0, err
    status = json.loads(out)
    assert status["profile_id"] == "claude-code" and status["can_write_shared"] is True  # unchanged keys
    runtime = status["runtime"]
    assert runtime["data_root_writable"] is True and runtime["corpus_root_exists"] is True
    assert runtime["schema_current"] is True and isinstance(runtime["schema_version"], int)
    assert runtime["sources"] == {"total": 4, "live": 3, "forgotten": 1}
    assert runtime["units"] >= 3 and runtime["drift"] == 0
    assert runtime["grants"] == {"active": 3, "read": 2, "write": 1, "agents": 2}
    assert re.fullmatch(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ", runtime["last_write"])
    assert "herons" not in out


def test_memory_status_text_mentions_the_last_write(home):
    populate()
    code, out, _err = run_cli("memory-status", "--profile", "claude-code")
    assert code == 0 and "last write" in out and "agents" in out
