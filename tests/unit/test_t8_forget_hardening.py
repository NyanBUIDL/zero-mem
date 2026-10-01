"""T8 - ``Memory.forget`` must not be an oracle: no foreign private ids in an ambiguous answer, and a source the
caller cannot read answers exactly like one that does not exist (library level, two profiles on one data root).
"""
from __future__ import annotations

import json

import pytest

from tests.unit.t5_memory_helpers import SHARED, Env


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


NOT_FOUND = {"status": "not_found", "reason": "unknown_source", "ok": False}


def _ids(env):
    return {line["source_id"] for line in env.registry_lines()}


# ----------------------------------------------------------------------------------------- ambiguity leak
def test_an_ambiguous_ref_never_lists_another_profiles_private_source(env):
    a, b = env.open("claude-code"), env.open("codex")
    mine = a.add("same words in two private stores", "fact")
    theirs = b.add("same words in two private stores", "fact")
    assert mine.external_ref == theirs.external_ref and mine.source_id != theirs.source_id
    res = a.forget(mine.external_ref)
    # codex's copy is invisible to claude-code, so the ref names exactly ONE source for it: no ambiguity at all
    assert res.status == "forgotten" and res.source_id == mine.source_id
    assert theirs.source_id not in json.dumps(res.as_dict())
    assert b.recall("private stores").status == "ok" and a.recall("private stores").status == "empty"


def test_ambiguous_candidates_are_limited_to_sources_the_caller_can_read(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")
    a_private = a.add("copy about civets", "persona", name="same", scope="private")
    a_shared = a.add("shared copy about civets", "persona", name="same", scope="shared")
    b_private = b.add("copy about civets", "persona", name="same", scope="private")
    res = a.forget("mem://persona/same")
    assert res.status == "ambiguous" and res.reason == "multiple_sources_match"
    assert set(res.candidates) == {a_private.source_id, a_shared.source_id}
    assert b_private.source_id not in json.dumps(res.as_dict())
    # codex sees its own private copy and the shared one (not claude-code's private one)
    res_b = b.forget("mem://persona/same")
    assert res_b.status == "ambiguous" and set(res_b.candidates) == {b_private.source_id, a_shared.source_id}
    assert a_private.source_id not in json.dumps(res_b.as_dict())


def test_a_forgotten_ambiguity_resolves_by_the_listed_candidate_and_touches_nothing_else(env):
    a, b = env.open("claude-code"), env.open("codex")
    mine = a.add("copy about lemurs", "persona", name="twin", scope="private")
    b.add("copy about lemurs", "persona", name="twin", scope="private")
    assert a.forget(mine.external_ref).source_id == mine.source_id
    assert b.recall("lemurs").status == "ok"
    tombs = [r for r in env.registry_lines() if r["lifecycle_status"] == "deleted"]
    assert [t["source_id"] for t in tombs] == [mine.source_id]


# ----------------------------------------------------------------------------------------- existence oracle
def test_every_way_to_name_a_source_the_caller_cannot_read_looks_like_a_missing_one(env):
    a = env.agent("claude-code", write_shared=True, write_projects=("alpha",), read_projects=("alpha",))
    b = env.agent("codex")  # reads ks-shared only: no grant on project alpha
    private = a.add("claude-code private note about gnus", "fact", name="gnus")
    project = a.add("alpha devlog about gnus", "devlog", scope="project", project_id="alpha")
    ghost_stream_before = len(env.stream_events())
    missing = b.forget("f" * 64).as_dict()
    assert missing == NOT_FOUND
    for ident in (private.source_id, private.source_id[:10], private.external_ref,
                  project.source_id, project.source_id[:12], project.external_ref):
        assert b.forget(ident).as_dict() == missing, ident
    # nothing was forgotten, nothing was audited for the probes
    assert not [r for r in env.registry_lines() if r["lifecycle_status"] == "deleted"]
    assert len(env.stream_events()) == ghost_stream_before
    assert a.recall("gnus", project_id="alpha").status == "ok"


def test_an_unregistered_profile_cannot_tell_a_shared_source_from_a_missing_one(env):
    a = env.agent("claude-code", write_shared=True)
    shared = a.add("shared note about ibexes", "fact", scope="shared")
    ghost = env.open("ghost")  # never `agents add`-ed: no READ grant on ks-shared
    for ident in (shared.source_id, shared.external_ref, shared.source_id[:9]):
        assert ghost.forget(ident).as_dict() == NOT_FOUND
    assert a.recall("ibexes").status == "ok"


def test_a_readable_source_is_still_reported_as_denied_without_the_write_approval(env):
    a = env.agent("claude-code", write_shared=True, write_projects=("alpha",), read_projects=("alpha",))
    reader = env.agent("codex", read_projects=("alpha",))
    shared = a.add("shared note about quokkas", "fact", scope="shared")
    project = a.add("alpha devlog about quokkas", "devlog", scope="project", project_id="alpha")
    for source in (shared, project):
        res = reader.forget(source.source_id)
        assert res.status == "denied" and res.reason == "DENY_CROSS_PROFILE_WRITE"
        assert res.source_id == source.source_id and not res.ok
    assert reader.recall("quokkas", project_id="alpha").status == "ok"


def test_a_readable_forgotten_source_stays_already_forgotten_and_a_foreign_one_stays_missing(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")
    shared = a.add("shared note about numbats", "fact", scope="shared")
    private = a.add("private note about numbats", "fact")
    assert a.forget(shared.source_id).status == "forgotten"
    assert a.forget(private.source_id).status == "forgotten"
    assert b.forget(shared.source_id).status == "already_forgotten"  # b could read it: not a secret
    assert b.forget(private.source_id).as_dict() == NOT_FOUND  # b never could


def test_the_answer_for_a_missing_and_an_unreadable_source_is_identical_even_in_text(env):
    a = env.agent("claude-code")
    b = env.agent("codex")
    mine = a.add("private note about pangolins", "fact")
    unreadable = b.forget(mine.source_id)
    missing = b.forget("0" * 16)
    assert (unreadable.status, unreadable.reason, unreadable.source_id, unreadable.external_ref,
            unreadable.memory_type, unreadable.version, unreadable.candidates) == \
           (missing.status, missing.reason, None, None, None, None, ())
    assert json.dumps(unreadable.as_dict(), sort_keys=True) == json.dumps(missing.as_dict(), sort_keys=True)


def test_forget_of_a_global_source_is_denied_for_everyone_who_can_read_it(env):
    """A source with no profile / project / space (operator-curated) is readable by all and never forgettable."""
    from src.corpus.blob_store import CorpusBlobStore
    from src.corpus.derived_store import project_source
    from src.corpus.registry import CorpusSourceRegistry

    a = env.agent("claude-code")
    registry = CorpusSourceRegistry(root=env.layout.corpus_root)
    blobs = CorpusBlobStore(root=env.layout.corpus_root)
    record = registry.register_source_with_blob(
        content=b"operator curated note about tenrecs", external_ref="mem://fact/curated", kind="txt",
        sensitivity="internal", lifecycle_status="observed", custom_meta={"memory_type": "fact"},
        provenance={"channel": "test"}, blob_store=blobs)
    conn = a._conn()
    project_source(conn, registry, record, blob_store=blobs)
    conn.commit()
    res = a.forget(record.source_id)
    assert res.status == "denied" and res.reason == "DENY_GLOBAL_WRITE" and res.source_id == record.source_id
