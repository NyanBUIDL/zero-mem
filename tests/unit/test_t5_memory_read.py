"""T5 - Memory read path: recall (private + ks-shared merge), context bundle, status, forget."""
from __future__ import annotations

import json
import sqlite3

import pytest

from tests.unit.t5_memory_helpers import SHARED, Env
from zero_mem.memory import Memory


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.close()


# ----------------------------------------------------------------------------- recall: basics
def test_recall_returns_typed_hits_with_provenance_and_score(env):
    m = env.open("claude-code")
    added = m.add("Alice prefers PostgreSQL for storage.", "fact")
    res = m.recall("which database does Alice prefer? PostgreSQL")
    assert res.status == "ok" and res.ok and len(res) == 1
    hit = res[0]
    assert hit.text == "Alice prefers PostgreSQL for storage."
    assert hit.external_ref == added.external_ref and hit.memory_type == "fact"
    assert hit.score > 0 and hit.source_id == added.source_id and hit.scope == "private"
    assert hit.profile_id == "claude-code" and hit.knowledge_space_id is None
    json.dumps(res.as_dict())  # JSON-safe


def test_recall_empty_and_invalid_queries_are_typed(env):
    m = env.open("claude-code")
    m.add("something stored")
    assert m.recall("zzzzunknownterm").status == "empty" and m.recall("zzzzunknownterm").ok
    for bad in ("", "   ", "?!", None, 5):
        res = m.recall(bad)  # type: ignore[arg-type]
        assert res.status == "invalid" and res.reason == "empty_query" and not res.ok
    assert m.recall("x" * 1001).reason == "query_too_long"
    for bad in (0, -1, 201, True, 2.5, "3"):
        assert m.recall("stored", limit=bad).reason == "invalid_limit"  # type: ignore[arg-type]
    assert m.recall("stored", memory_types=["nope"]).reason == "invalid_memory_types"
    assert m.recall("stored", include_private="yes").reason == "invalid_include_private"  # type: ignore[arg-type]
    assert m.recall("stored", project_id="bad id").reason == "invalid_project_id"


def test_recall_works_on_an_empty_store(env):
    assert env.open("claude-code").recall("anything at all").status == "empty"


@pytest.mark.parametrize("query,needle", [("pre-commit", "pre-commit hook"), ("blue-green", "blue-green deploy"),
                                           ("C++", "C++ templates")])
def test_recall_finds_hyphenated_and_symbol_terms(env, query, needle):
    m = env.open("claude-code")
    m.add(f"We always run the {needle} before merging.")
    m.add("Unrelated line about fruit.")
    assert needle in m.recall(query)[0].text


def test_recall_respects_limit_and_orders_by_score(env):
    m = env.open("claude-code")
    for i in range(6):
        m.add(f"kafka note {i} " + "padding word " * i)
    res = m.recall("kafka", limit=3)
    assert len(res) == 3
    scores = [h.score for h in res]
    assert scores == sorted(scores, reverse=True)


def test_recall_memory_type_filter_single_and_multiple(env):
    m = env.open("claude-code")
    m.add("Terse answers please, no emojis.", "persona", name="style")
    m.add("Run pytest before every commit; keep answers terse.", "workflow", name="commit")
    m.add("Terse fact about caching.", "fact")
    all_types = {h.memory_type for h in m.recall("terse", limit=10)}
    assert all_types == {"persona", "workflow", "fact"}
    assert {h.memory_type for h in m.recall("terse", memory_types=["persona"])} == {"persona"}
    assert {h.memory_type for h in m.recall("terse", memory_types="workflow")} == {"workflow"}
    assert {h.memory_type for h in m.recall("terse", memory_types=["persona", "fact"], limit=10)} == {"persona", "fact"}


def test_recall_does_not_return_stale_units_after_an_update(env):
    m = env.open("claude-code")
    m.add("Persona line one.\n\nLine two will be deleted.", "persona", name="style")
    assert m.recall("deleted")[0].text == "Line two will be deleted."
    m.add("Persona line one.\n\nLine three replaced it.", "persona", name="style")
    assert m.recall("deleted").status == "empty" and m.recall("replaced").status == "ok"


# ----------------------------------------------------------------------------- recall: sharing
def test_private_rows_stay_private_and_shared_rows_are_shared(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")  # READ shared only
    a.add("alpha private secret-free note about quokkas", scope="private")
    a.add("alpha shared note about quokkas", scope="shared")
    b.add("beta private note about quokkas", scope="private")
    texts_a = {h.text for h in a.recall("quokkas", limit=10)}
    texts_b = {h.text for h in b.recall("quokkas", limit=10)}
    assert texts_a == {"alpha private secret-free note about quokkas", "alpha shared note about quokkas"}
    assert texts_b == {"alpha shared note about quokkas", "beta private note about quokkas"}


def test_a_profile_without_a_read_grant_sees_only_its_own_rows(env):
    a = env.agent("claude-code", write_shared=True)
    a.add("shared about axolotls", scope="shared")
    outsider = env.open("hermes")  # never registered: no READ grant on ks-shared
    own = outsider.add("own note about axolotls")
    got = outsider.recall("axolotls", limit=10)
    assert [h.external_ref for h in got] == [own.external_ref]


def test_revoking_read_removes_access_to_shared_rows(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")
    a.add("shared about pangolins", scope="shared")
    assert b.recall("pangolins").status == "ok"
    env.prov.revoke("codex", space=SHARED, operation="READ")
    assert b.recall("pangolins").status == "empty"


def test_own_shared_rows_are_not_duplicated_by_the_two_requests(env):
    a = env.agent("claude-code", write_shared=True)
    a.add("shared once about ocelots", scope="shared")
    res = a.recall("ocelots", limit=10)
    assert len(res) == 1 and res[0].scope == "shared" and res[0].knowledge_space_id == SHARED


def test_include_private_false_returns_only_the_shared_space(env):
    a = env.agent("claude-code", write_shared=True)
    a.add("private about lemurs", scope="private")
    a.add("shared about lemurs", scope="shared")
    res = a.recall("lemurs", limit=10, include_private=False)
    assert [h.text for h in res] == ["shared about lemurs"]


def test_shared_rows_of_other_agents_are_scored_with_their_provenance(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")
    a.add("team convention: squash merges", "workflow", name="merging", scope="shared")
    hit = b.recall("squash merges")[0]
    assert hit.profile_id == "claude-code" and hit.scope == "shared" and hit.external_ref == "mem://workflow/merging"


def test_project_devlog_is_readable_by_a_project_reader_only(env):
    writer = env.agent("claude-code", write_projects=["zero-mem"])
    reader = env.agent("codex", read_projects=["zero-mem"])
    stranger = env.agent("hermes")
    writer.add("Refactored the lock helper.", "devlog", project_id="zero-mem")
    assert writer.recall("lock helper").status == "ok"  # own rows (implicit request)
    assert reader.recall("lock helper", project_id="zero-mem").status == "ok"
    assert reader.recall("lock helper").status == "empty"  # without naming the project nothing leaks in
    denied = stranger.recall("lock helper", project_id="zero-mem")
    assert denied.status == "empty" and denied.hits == []


def test_a_denied_sub_request_is_reported_in_notes(env):
    stranger = env.agent("hermes")
    res = stranger.recall("anything", project_id="zero-mem")
    assert res.notes["project"].startswith("DENY") and "private" in res.notes and "shared" in res.notes


def test_two_instances_of_one_profile_see_each_others_writes(env):
    a1, a2 = env.open("claude-code"), env.open("claude-code")
    a1.add("written through the first handle about wombats")
    assert a2.recall("wombats").status == "ok"


# ----------------------------------------------------------------------------- forget
def _hits(m, query, **kw):
    return [h.external_ref for h in m.recall(query, **kw)]


def test_forget_removes_the_source_from_recall_and_leaves_others_untouched(env):
    m = env.open("claude-code")
    keep = m.add("Keep this note about marmots.")
    gone = m.add("Forget this note about marmots too.")
    assert set(_hits(m, "marmots", limit=10)) == {keep.external_ref, gone.external_ref}
    res = m.forget(gone.source_id)
    assert res.status == "forgotten" and res.ok and res.source_id == gone.source_id
    assert res.external_ref == gone.external_ref and res.memory_type == "fact"
    assert _hits(m, "marmots", limit=10) == [keep.external_ref]
    assert m.recall("Forget this note").status in {"ok", "empty"}
    assert all("Forget this note" not in h.text for h in m.recall("forget note", limit=10))


def test_forget_keeps_the_raw_blob_and_appends_a_tombstone_version(env):
    m = env.open("claude-code")
    gone = m.add("Forget this note about stoats.")
    blobs_before = env.blob_count()
    m.forget(gone.source_id)
    assert env.blob_count() == blobs_before + 1  # the tombstone marker is a new blob; nothing was removed
    lines = env.registry_lines()
    assert [l["lifecycle_status"] for l in lines] == ["observed", "deleted"]
    assert lines[1]["supersedes"] == lines[0]["source_version_id"] and lines[1]["provenance"]["tool"] == "forget"
    assert env.files_containing("Forget this note about stoats.")  # canonical raw blob still there


def test_a_rebuild_keeps_a_forgotten_source_forgotten(env):
    from src.corpus.blob_store import CorpusBlobStore
    from src.corpus.derived_store import rebuild_from_corpus
    from src.corpus.registry import CorpusSourceRegistry
    from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

    m = env.open("claude-code")
    keep, gone = m.add("Keep this note about dingos."), m.add("Forget this note about dingos.")
    m.forget(gone.source_id)
    store = SQLiteStore(SQLiteStoreConfig(path=env.layout.derived_db))
    try:
        rebuild_from_corpus(store._conn, CorpusSourceRegistry(root=env.layout.corpus_root),
                            blob_store=CorpusBlobStore(root=env.layout.corpus_root))
    finally:
        store.close()
    assert _hits(m, "dingos", limit=10) == [keep.external_ref]


def test_forget_is_idempotent_and_typed_for_unknown_ids(env):
    m = env.open("claude-code")
    gone = m.add("Forget this note about okapis.")
    assert m.forget(gone.source_id).status == "forgotten"
    again = m.forget(gone.source_id)
    assert again.status == "already_forgotten" and again.ok
    assert len(env.registry_lines()) == 2  # no second tombstone
    unknown = m.forget("f" * 64)
    assert unknown.status == "not_found" and not unknown.ok
    for bad in ("", "ab", None, 5, "x" * 700):
        assert m.forget(bad).status == "invalid"  # type: ignore[arg-type]


def test_forget_accepts_an_external_ref_or_a_unique_prefix(env):
    m = env.open("claude-code")
    a = m.add("Persona facet about gibbons.", "persona", name="gibbon")
    b = m.add("Another note about gibbons.")
    assert m.forget(a.external_ref).status == "forgotten"
    assert m.forget(b.source_id[:10]).status == "forgotten"
    assert m.recall("gibbons").status == "empty"


def test_forget_with_an_ambiguous_ref_lists_candidates(env):
    a = env.agent("claude-code", write_shared=True)
    a.add("private copy about civets", "persona", name="same", scope="private")
    a.add("shared copy about civets", "persona", name="same", scope="shared")
    res = a.forget("mem://persona/same")
    assert res.status == "ambiguous" and len(res.candidates) == 2
    assert a.forget(res.candidates[0]).status == "forgotten"


def test_resurrection_after_forget_makes_the_source_recallable_again(env):
    m = env.open("claude-code")
    first = m.add("Remember this note about tapirs.")
    m.forget(first.source_id)
    assert m.recall("tapirs").status == "empty"
    again = m.add("Remember this note about tapirs.")
    assert again.status == "created" and again.source_id == first.source_id
    assert m.recall("tapirs").status == "ok"
    assert [l["lifecycle_status"] for l in env.registry_lines()] == ["observed", "deleted", "observed"]


def test_forgetting_another_profiles_private_source_looks_like_not_found(env):
    a, b = env.open("claude-code"), env.open("codex")
    secret_free = a.add("A private note about badgers.")
    res = b.forget(secret_free.source_id)
    assert res.status == "not_found" and res.reason == "unknown_source"
    assert a.recall("badgers").status == "ok"
    assert len(env.registry_lines()) == 1


def test_forgetting_a_shared_source_needs_a_write_grant(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")  # READ shared only
    shared = a.add("Shared note about kiwis.", scope="shared")
    denied = b.forget(shared.source_id)
    assert denied.status == "denied" and denied.reason == "DENY_CROSS_PROFILE_WRITE" and not denied.ok
    assert b.recall("kiwis").status == "ok"
    env.prov.grant_write("codex", space=SHARED, basis="test")
    assert b.forget(shared.source_id).status == "forgotten"
    assert a.recall("kiwis").status == "empty"


def test_a_denied_forget_is_audited(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")
    shared = a.add("Shared note about kakapos.", scope="shared")
    b.forget(shared.source_id)
    decisions = [e["m4"] for e in env.stream_events("policy_decision")]
    assert any(d["requester"] == "codex" and d["allow"] is False and d["target_scope"] == f"knowledge_space:{SHARED}"
               for d in decisions)


def test_forgetting_the_last_source_leaves_a_store_that_upgrade_accepts(env):
    from zero_mem import upgrade as upgrade_mod

    m = env.open("claude-code")
    only = m.add("The only note about yaks.")
    m.forget(only.source_id)
    m.close()
    db = env.layout.derived_db
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        conn.close()
    assert upgrade_mod._corpus_counts(db, immutable=True) == (0, 0)
    upgrade_mod._guard_corpus_projection(db, db)


# ----------------------------------------------------------------------------- context
def _context_env(env):
    m = env.agent("claude-code", write_shared=True, write_projects=["zero-mem"])
    m.add("Nyan prefers terse answers and no emojis.", "persona", name="style", scope="shared")
    m.add("Always run pytest before every commit.", "workflow", name="commit", scope="shared")
    m.add("---\nname: tdd\ndescription: Write the failing test first, then the smallest fix.\n---\n# TDD\n\nBody text.",
          "skill", name="tdd", scope="shared")
    m.add("A skill without front matter. It explains rebasing carefully.\n\nMore body.", "skill", name="rebase")
    env.clock.set("2026-09-30T10:00:00+00:00")
    m.add("Older entry: set up the repo.", "devlog", project_id="zero-mem")
    env.clock.set("2026-10-01T10:00:00+00:00")
    m.add("Newer entry: fixed the flaky lock test.", "devlog", project_id="zero-mem")
    return m


def test_context_orders_sections_persona_workflow_skills_devlog(env):
    m = _context_env(env)
    bundle = m.context()
    text = bundle.text
    assert bundle.status == "ok" and bundle.ok and not bundle.truncated
    order = [text.index(h) for h in ("## Persona", "## Workflow", "## Skills", "## Recent devlog")]
    assert order == sorted(order)
    assert "Nyan prefers terse answers and no emojis." in text
    assert "Always run pytest before every commit." in text
    assert "- tdd: Write the failing test first, then the smallest fix." in text
    assert "- rebase: A skill without front matter. It explains rebasing carefully." in text
    assert "Body text." not in text and "More body." not in text  # skills contribute descriptions only
    assert text.index("Newer entry") < text.index("Older entry")  # newest first
    assert "[2026-10-01 zero-mem]" in text
    assert bundle.sections == {"Persona": 1, "Workflow": 1, "Skills": 2, "Recent devlog": 2}
    assert bundle.sources[0] == "mem://persona/style" and str(bundle) == text


def test_context_is_deterministic_and_stable_across_handles(env):
    m = _context_env(env)
    first = m.context().text
    assert m.context().text == first == env.open("claude-code").context().text


@pytest.mark.parametrize("budget", [1, 5, 20, 60, 100, 250, 500, 1000, 4000])
def test_context_never_exceeds_the_character_budget(env, budget):
    m = _context_env(env)
    bundle = m.context(max_chars=budget)
    assert len(bundle.text) <= budget and bundle.max_chars == budget
    if budget < 400:
        assert bundle.truncated


def test_context_is_token_bounded_even_for_huge_sources(env):
    m = env.open("claude-code")
    m.add("persona word " * 20_000, "persona", name="big")
    for i in range(50):
        m.add(f"workflow step {i} " + "detail " * 200, "workflow", name=f"w{i}")
    bundle = m.context(max_chars=2000)
    assert len(bundle.text) <= 2000 and bundle.truncated
    assert "## Persona" in bundle.text and "## Workflow" in bundle.text


def test_context_budget_share_lets_unused_room_flow_to_later_sections(env):
    m = env.open("claude-code")
    m.add("tiny persona", "persona", name="p")
    m.add("w " + "workflow detail " * 80, "workflow", name="w")
    small = m.context(max_chars=1000)
    # the workflow share (25%) is 250 chars, but persona left most of its 350 unused
    wf = small.text.split("## Workflow\n", 1)[1]
    assert len(wf) > 250


def test_context_excludes_forgotten_other_private_and_unreadable_sources(env):
    a = env.agent("claude-code", write_shared=True)
    b = env.agent("codex")
    a.add("Shared persona facet.", "persona", name="shared-facet", scope="shared")
    a.add("Private persona of claude-code.", "persona", name="mine")
    gone = a.add("Forgotten persona facet.", "persona", name="old")
    a.forget(gone.source_id)
    ctx_b = b.context().text
    assert "Shared persona facet." in ctx_b
    assert "Private persona of claude-code." not in ctx_b and "Forgotten persona facet." not in ctx_b
    ctx_a = a.context().text
    assert "Private persona of claude-code." in ctx_a and "Forgotten persona facet." not in ctx_a


def test_context_on_an_empty_store_and_invalid_budgets(env):
    m = env.open("claude-code")
    empty = m.context()
    assert empty.status == "empty" and empty.text == "" and empty.ok
    for bad in (0, -5, 200_001, True, 2.5, "10"):
        res = m.context(max_chars=bad)  # type: ignore[arg-type]
        assert res.status == "invalid" and res.reason == "invalid_max_chars"
    assert m.context(project_id="bad id").reason == "invalid_project_id"


def test_context_includes_a_readable_project_devlog_only_when_asked(env):
    writer = env.agent("claude-code", write_projects=["zero-mem"])
    reader = env.agent("codex", read_projects=["zero-mem"])
    writer.add("Wrote the migration.", "devlog", project_id="zero-mem")
    assert "Wrote the migration." in writer.context().text  # own rows
    assert "Wrote the migration." not in reader.context().text
    assert "Wrote the migration." in reader.context(project_id="zero-mem").text


def test_context_finds_persona_even_in_a_store_larger_than_the_discovery_cap(env, monkeypatch):
    """Metadata-only discovery used to scan the first ``cap`` unit rows and only then filter by type, so a persona
    registered after thousands of other units was silently missing from the context bundle."""
    import zero_mem.memory as memory_mod
    from src.corpus import retrieval as retrieval_mod

    m = env.open("claude-code")
    for i in range(30):
        m.add(f"filler fact number {i}", "fact")
    m.add("Late persona facet must still appear.", "persona", name="late")
    # shrink the candidate window so a 31-unit store behaves like one larger than the real 5000-row floor
    monkeypatch.setattr(memory_mod, "_res_limit", lambda: 10)
    monkeypatch.setattr(retrieval_mod, "_DISCOVERY_FACTOR", 0)
    monkeypatch.setattr(retrieval_mod, "_DISCOVERY_CAP_FLOOR", 5)
    assert "Late persona facet must still appear." in m.context().text


# ----------------------------------------------------------------------------- status
def test_status_reports_counts_grants_and_drift(env):
    a = env.agent("claude-code", write_shared=True)
    a.add("note one")
    a.add("persona text", "persona", name="p", scope="shared")
    gone = a.add("to forget")
    a.forget(gone.source_id)
    st = a.status()
    assert st["profile_id"] == "claude-code" and st["shared_space"] == SHARED and st["schema_version"] >= 13
    assert st["sources"] == {"total": 2, "own": 2, "forgotten": 1, "by_type": {"fact": 1, "persona": 1}}
    assert st["units"] == 2 and st["can_read_shared"] is True and st["can_write_shared"] is True
    assert {(g["operation"], g["target_id"]) for g in st["grants"]} == {("READ", SHARED), ("WRITE", SHARED)}
    assert st["needs_rebuild"] is False
    json.dumps(st)


def test_status_flags_drift_between_registry_and_derived_state(env):
    m = env.open("claude-code")
    m.add("note about drift")
    conn = sqlite3.connect(env.layout.derived_db)
    try:
        conn.execute("DELETE FROM zm_corpus_fts")
        conn.execute("DELETE FROM zm_corpus_units")
        conn.execute("DELETE FROM zm_corpus_sources")
        conn.commit()
    finally:
        conn.close()
    st = m.status()
    assert st["needs_rebuild"] is True and st["drifted_sources"] == 1


def test_a_new_agent_status_shows_read_only_shared_access(env):
    m = env.agent("codex")
    st = m.status()
    assert st["can_read_shared"] is True and st["can_write_shared"] is False
    assert st["sources"]["total"] == 0
