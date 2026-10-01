"""T8 - backup / restore round trip of a POPULATED shared memory: what the agents rely on survives.

A data root with registered agents, an operator-approved shared write grant, shared / private / project memories, an
ingested file and a forgotten memory is backed up and restored (into a new data root, and over the live one after
further changes). After the restore: recall and context answer identically for every agent, the forgotten memory stays
forgotten (and is not resurrected by the rebuild), the grants and the operator approval are intact (the approved agent
may still write shared memory, the unapproved one is still denied), and ``zero-mem doctor`` is READY.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from tests.unit.t6b_helpers import apply_env
from zero_mem import cli
from zero_mem.memory import Memory
from zero_mem.memory_layout import Layout
from zero_mem.provisioning import Provisioner

AGENTS = ("claude-code", "codex")
QUERIES = ("terse answers", "release checklist", "okapi", "flaky lock", "private diary", "gone memory")


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


def populate(tmp_path: Path):
    layout = Layout.resolve(None)
    layout.ensure()
    prov = Provisioner(layout, operator="tester")
    for agent in AGENTS:
        prov.add_agent(agent)
    prov.grant_write("claude-code", space="ks-shared", basis="owner approved")
    prov.grant_write("claude-code", project="proj", basis="owner approved")
    prov.grant_read("codex", project="proj")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "plan.md").write_text("# Plan\n\nShip the okapi feature after the release checklist.\n", encoding="utf-8")
    with Memory.open("claude-code") as cc:
        assert cc.add("The user prefers terse answers and no emojis.", "persona", name="style", scope="shared").ok
        assert cc.add("Release checklist: run the suite, tag, never force-push.", "workflow", name="release",
                      scope="shared").ok
        assert cc.add("Fixed the flaky lock test today.", "devlog", scope="project", project_id="proj").ok
        assert cc.add("My private diary entry about herons.", "fact").ok
        assert cc.ingest(docs, memory_type="file", scope="shared", allow_roots=[docs]).ok
        gone = cc.add("This gone memory was a mistake.", "fact", scope="shared")
        assert gone.ok and cc.forget(gone.source_id).status == "forgotten"
    with Memory.open("codex") as cx:
        assert cx.add("Codex private note about owls.", "fact").ok
        assert cx.add("shared attempt without approval", "fact", scope="shared").status == "denied"
    return gone


def snapshot(root=None) -> dict:
    out = {}
    for agent in AGENTS:
        with Memory.open(agent, data_root=root) as m:
            out[agent] = {
                "recall": {q: [h.as_dict() for h in m.recall(q, limit=8, project_id="proj")] for q in QUERIES},
                "context": m.context(max_chars=1500, project_id="proj").as_dict(),
                "status": {k: v for k, v in m.status().items() if k not in ("data_root", "corpus_root")},
            }
    return out


def agents_table(root=None) -> list:
    layout = Layout.resolve(root)
    return Provisioner(layout, operator="tester").list_agents()


def test_a_backup_restored_into_a_new_data_root_answers_exactly_like_the_original(home, tmp_path):
    gone = populate(tmp_path)
    before, grants_before = snapshot(), agents_table()
    assert before["claude-code"]["recall"]["terse answers"] and not before["claude-code"]["recall"]["gone memory"]
    assert before["codex"]["recall"]["terse answers"] and not any("herons" in h["text"] for h in before["codex"]["recall"]["private diary"])
    code, out, err = run_cli("backup", "create", "--output", str(tmp_path / "backup"), "--json")
    assert code == 0, err
    assert run_cli("backup", "verify", str(tmp_path / "backup"))[0] == 0
    target = tmp_path / "restored"
    code, out, err = run_cli("backup", "restore", str(tmp_path / "backup"), "--yes", "--data-root", str(target))
    assert code == 0, err
    # recall / context / status are identical for every agent, from the restored store
    after = snapshot(target)
    for agent in AGENTS:
        assert after[agent]["recall"] == before[agent]["recall"], agent
        assert after[agent]["context"] == before[agent]["context"], agent
        assert after[agent]["status"] == before[agent]["status"], agent
    # forget survives: still invisible, the tombstone is a second registry line, a second forget is idempotent
    with Memory.open("claude-code", data_root=target) as cc:
        assert cc.recall("gone memory").status == "empty"
        assert cc.forget(gone.source_id).status == "already_forgotten"
    lines = [json.loads(l) for l in (target / "data" / "corpus" / "corpus_sources.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert [l["lifecycle_status"] for l in lines if l["source_id"] == gone.source_id] == ["observed", "deleted"]
    # grants and the operator approval survive: the approved agent may write shared memory, the other still may not
    assert agents_table(target) == grants_before
    with Memory.open("claude-code", data_root=target) as cc:
        assert cc.add("Written after the restore.", "fact", scope="shared").status == "created"
    with Memory.open("codex", data_root=target) as cx:
        res = cx.add("Codex tries again after the restore.", "fact", scope="shared")
        assert res.status == "denied" and res.reason == "DENY_CROSS_PROFILE_WRITE"
        assert cx.recall("written after the restore").status == "ok"  # shared writes of the approved agent are readable


def test_restoring_over_the_live_data_root_rolls_back_every_later_change(home, tmp_path):
    gone = populate(tmp_path)
    before, grants_before = snapshot(), agents_table()
    assert run_cli("backup", "create", "--output", str(tmp_path / "backup"))[0] == 0
    # later changes: a new memory, the forgotten one resurrected, the approved agent's write approval revoked
    with Memory.open("claude-code") as cc:
        assert cc.add("Later note about quokkas.", "fact", scope="shared").ok
        assert cc.add("This gone memory was a mistake.", "fact", scope="shared").status == "created"  # resurrection
    Provisioner(Layout.resolve(None), operator="tester").revoke("claude-code", space="ks-shared", operation="WRITE")
    assert agents_table() != grants_before
    code, _out, err = run_cli("backup", "restore", str(tmp_path / "backup"), "--yes")
    assert code == 0, err
    after = snapshot()
    for agent in AGENTS:
        assert after[agent]["recall"] == before[agent]["recall"], agent
        assert after[agent]["context"] == before[agent]["context"], agent
    assert agents_table() == grants_before
    with Memory.open("claude-code") as cc:
        assert cc.recall("quokkas").status == "empty" and cc.recall("gone memory").status == "empty"
        assert cc.add("Written after the in-place restore.", "fact", scope="shared").status == "created"
    assert run_cli("doctor")[0] == 0


def test_a_restored_store_passes_doctor_and_reports_the_memory_runtime(home, tmp_path, monkeypatch):
    populate(tmp_path)
    assert run_cli("backup", "create", "--output", str(tmp_path / "backup"))[0] == 0
    target = tmp_path / "restored"
    assert run_cli("backup", "restore", str(tmp_path / "backup"), "--yes", "--data-root", str(target))[0] == 0
    monkeypatch.setenv("ZERO_MEM_DATA_ROOT", str(target))
    code, out, err = run_cli("doctor", "--json")
    report = json.loads(out)
    assert code == 0 and report["overall"] == "READY", report
    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["memory_sources"]["status"] == "PASS" and "forgotten" in by_id["memory_sources"]["message"]
    assert by_id["memory_grants"]["status"] == "PASS"
