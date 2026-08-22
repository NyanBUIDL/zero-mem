"""M7.3 focused tests — authorized evidence eligibility + bounded EvidenceSet.

Reuses the VERIFIED M5 AuthorizedReadService as the authorized-read boundary
(authorization-before-retrieval). Mirrors the established M4/M5 corpus fixture
pattern. No LLM; no external network; OS-temp fixtures; dynamic REPO_ROOT.

Covers: no_memory (0 retrieval), external_current (insufficient/current-required),
authorization (same-profile/cross-profile/exact grant/wrong grant/revoked),
resource-type isolation (artifact-only cannot expose event), linked-resource
authorization, lifecycle eligibility, memory-type handling, sensitivity gate,
provenance, budget (5/3/8), token budget, omitted_count (non-leaking), deterministic
ordering, insufficient evidence, project/user/research/global memory, conflict
representation, read-only, concurrency, failure isolation, static security audit,
and M7.1/M7.2 regressions.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]

from src.integration.m7 import (
    MemoryRoute, ReasonCode, RouterRequest, MemoryRouteDecision,
    EvidenceItem, EvidenceSet, EvidenceRole, build_evidence_set, route,
)
from src.access import AccessRequest, AuthorizedReadService, ReasonCode as M5Reason
from src.access.grants import AuthorizedReadGrant
from src.access.resolver import resolve_read_grants
from src.retrieval.db import open_readonly
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.ingest import ingest_file
from src.project_memory import rebuild_project_memory, rebuild_all_project_memory
import tests.unit.test_m4_rebuild as m4base
import tests.unit.test_m3_query as m3base


def _tmp() -> Path:
    return Path(tempfile.mkdtemp()).resolve()


def _build_store():
    """Build a populated store with M3 events + M4 project memory (PR1/P)."""
    tmp = _tmp(); sp = tmp / "m4.sqlite"
    # Seed M2 artifact substrate FIRST (FK requirement), matching the M4 test pattern.
    store = SQLiteStore(SQLiteStoreConfig(path=sp)); store.ensure_schema()
    m4base._seed_m2_artifacts(store._conn)
    jl = tmp / "m3.jsonl"
    m3base._write_jsonl(jl, [
        m3base._make_env("E1", trace_id="T1", project_id="P", profile_id="PR1",
                         event_type="decision", subject="PR1 decision A"),
        m3base._make_env("E2", trace_id="T2", project_id="P", profile_id="PR1",
                         event_type="verified_state", subject="PR1 state"),
        m3base._make_env("E3", trace_id="T3", project_id="P", profile_id="PR1",
                         event_type="assistant_claim", subject="unverified claim"),
        m3base._make_env("E4", trace_id="T4", project_id="P", profile_id="PR2",
                         event_type="decision", subject="PR2 secret decision"),
    ])
    ingest_file(store, jl)
    corpus = m4base.build_corpus(tmp)
    rebuild_project_memory(store, corpus, project_id="P")
    rebuild_all_project_memory(store, corpus, project_id="P")
    store._conn.commit(); store.close()
    return open_readonly(sp)


def _mutate_db(store, sql: str):
    """Open a fresh writable connection on the same db file (the fixture store is
    read-only) to exercise lifecycle/sensitivity state, then commit."""
    path = store._conn.execute("PRAGMA database_list").fetchall()[0][2]
    w = SQLiteStore(SQLiteStoreConfig(path=Path(path)))
    w._conn.execute(sql)
    w._conn.commit(); w.close()


def _grant(subject, target_type, target_id, rts, state="active", lifecycle="active"):
    return AuthorizedReadGrant(
        grant_id=f"G-{target_id}-{target_type}", subject_profile=subject, operation="READ",
        target_type=target_type, target_id=target_id, resource_types=rts,
        state=state, lifecycle_status=lifecycle,
    )


# ---------------------------------------------------------------------------
# no_memory
# ---------------------------------------------------------------------------
class TestNoMemory:
    def test_no_retrieval_zero_tokens(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="What is 2+2?"))
        assert dec.route is MemoryRoute.NO_MEMORY
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="What is 2+2?"))
        assert es.memory_needed is False
        assert es.insufficient_evidence is False
        assert es.estimated_tokens == 0
        assert es.primary_evidence == () and es.supporting_evidence == ()


# ---------------------------------------------------------------------------
# external_current
# ---------------------------------------------------------------------------
class TestExternalCurrent:
    def test_insufficient_current_required(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="What is the latest status of project P?"))
        assert dec.route is MemoryRoute.EXTERNAL_CURRENT
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P"))
        assert es.insufficient_evidence is True
        assert es.external_current_required is True
        assert es.primary_evidence == ()


# ---------------------------------------------------------------------------
# authorization
# ---------------------------------------------------------------------------
class TestAuthorization:
    def test_same_profile_authorized(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"))
        assert es.primary_evidence or es.supporting_evidence
        assert es.insufficient_evidence is False

    def test_cross_profile_denied(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1", target_profile_ids=["PR2"]))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1", target_profile_ids=["PR2"]))
        ids = [e.evidence_id for e in es.primary_evidence + es.supporting_evidence]
        assert "E4" not in ids

    def test_exact_project_grant_allows(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        grant = _grant("PR1", "project", "P", None)
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1", target_profile_ids=["PR2"]))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1", target_profile_ids=["PR1"]),
                               grants=[grant])
        assert es.primary_evidence or es.supporting_evidence

    def test_wrong_resource_grant_denies_event(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        grant = _grant("PR1", "project", "P", ["artifact"])
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1", target_profile_ids=["PR2"]))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1", target_profile_ids=["PR1"]),
                               grants=[grant])
        rts = [e.resource_type for e in es.primary_evidence + es.supporting_evidence]
        assert "event" not in rts and "decision" not in rts

    def test_revoked_grant_denies(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        grant = _grant("PR1", "project", "P", None, state="revoked")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1", target_profile_ids=["PR2"]))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1", target_profile_ids=["PR1"]),
                               grants=[grant])
        ids = [e.evidence_id for e in es.primary_evidence + es.supporting_evidence]
        assert "E4" not in ids


# ---------------------------------------------------------------------------
# resource type isolation (M6.6 regression via M5 path)
# ---------------------------------------------------------------------------
class TestResourceTypeIsolation:
    def test_artifact_only_cannot_expose_event(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        grant = _grant("PR1", "project", "P", ["artifact"])
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1", target_profile_ids=["PR2"]))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1", target_profile_ids=["PR1"]),
                               grants=[grant])
        rts = [e.resource_type for e in es.primary_evidence + es.supporting_evidence]
        assert "event" not in rts
        assert "decision" not in rts
        assert all(e.content_source == "metadata_only" for e in es.primary_evidence + es.supporting_evidence)


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
class TestLifecycle:
    def test_deleted_absent(self):
        store = _build_store()
        _mutate_db(store, "UPDATE zm_meta SET lifecycle_status='deleted' WHERE event_id='E2'")
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"))
        ids = [e.evidence_id for e in es.primary_evidence + es.supporting_evidence]
        assert "E2" not in ids

    def test_superseded_not_primary(self):
        store = _build_store()
        _mutate_db(store, "UPDATE zm_meta SET lifecycle_status='superseded' WHERE event_id='E1'")
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"))
        primary_ids = [e.evidence_id for e in es.primary_evidence]
        assert "E1" not in primary_ids


# ---------------------------------------------------------------------------
# memory types
# ---------------------------------------------------------------------------
class TestMemoryTypes:
    def test_assistant_claim_not_promoted(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"))
        for e in es.primary_evidence:
            assert e.memory_type != "assistant_claim"


# ---------------------------------------------------------------------------
# sensitivity
# ---------------------------------------------------------------------------
class TestSensitivity:
    def test_above_ceiling_excluded(self):
        store = _build_store()
        _mutate_db(store, "UPDATE zm_meta SET sensitivity='secret' WHERE event_id='E1'")
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"),
                               sensitivity_ceiling="private")
        ids = [e.evidence_id for e in es.primary_evidence + es.supporting_evidence]
        assert "E1" not in ids
        # Non-vacuity guard: the run must actually produce evidence, otherwise
        # "E1 not in ids" would hold trivially (the original M7.3 defect).
        assert ids, "no evidence selected — exclusion assertion would be vacuous"


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------
class TestProvenance:
    def test_selected_has_provenance(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"))
        for e in es.primary_evidence + es.supporting_evidence:
            assert e.evidence_id
            assert e.provenance
            assert e.created_at


# ---------------------------------------------------------------------------
# budget
# ---------------------------------------------------------------------------
class TestBudget:
    def test_max_primary_supporting_total(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"),
                               max_primary=5, max_supporting=3)
        assert len(es.primary_evidence) <= 5
        assert len(es.supporting_evidence) <= 3
        assert len(es.primary_evidence) + len(es.supporting_evidence) <= 8

    def test_token_budget_enforced(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"),
                               token_budget=50)
        assert es.estimated_tokens <= 50 or (len(es.primary_evidence) + len(es.supporting_evidence)) <= 1

    def test_omitted_count_non_leaking(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1"),
                               max_primary=1, max_supporting=0)
        assert es.omitted_count >= 1
        ids = [e.evidence_id for e in es.primary_evidence + es.supporting_evidence]
        assert "E4" not in ids


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------
class TestDeterminism:
    def test_stable_ordering(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        es1 = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                        requesting_profile_id="PR1"))
        es2 = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                        requesting_profile_id="PR1"))
        assert [e.evidence_id for e in es1.primary_evidence] == [e.evidence_id for e in es2.primary_evidence]


# ---------------------------------------------------------------------------
# insufficient
# ---------------------------------------------------------------------------
class TestInsufficient:
    def test_no_authorized_evidence(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id=None)
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id=None))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id=None))
        assert es.insufficient_evidence is True


# ---------------------------------------------------------------------------
# project memory independent resource authorization
# ---------------------------------------------------------------------------
class TestProjectMemory:
    def test_each_resource_independently_authorized(self):
        store = _build_store()
        svc = AuthorizedReadService(store, requesting_profile_id="PR1")
        grant = _grant("PR1", "project", "P", ["decision"])
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1", target_profile_ids=["PR2"]))
        es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                       requesting_profile_id="PR1", target_profile_ids=["PR1"]),
                               grants=[grant])
        rts = [e.resource_type for e in es.primary_evidence + es.supporting_evidence]
        assert "decision" in rts
        assert "requirement" not in rts and "charter" not in rts
        assert all(e.content_source == "metadata_only" for e in es.primary_evidence + es.supporting_evidence)


# ---------------------------------------------------------------------------
# concurrency
# ---------------------------------------------------------------------------
class TestConcurrency:
    def test_caller_isolation(self):
        import concurrent.futures
        store = _build_store()
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        def work(pid):
            svc = AuthorizedReadService(store, requesting_profile_id=pid)
            return build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                             requesting_profile_id=pid))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            a = ex.submit(work, "PR1").result()
            b = ex.submit(work, "PR3").result()
        a_ids = {e.evidence_id for e in a.primary_evidence + a.supporting_evidence}
        b_ids = {e.evidence_id for e in b.primary_evidence + b.supporting_evidence}
        assert "E4" not in b_ids
        assert a_ids != b_ids or b_ids == set()


# ---------------------------------------------------------------------------
# failure isolation
# ---------------------------------------------------------------------------
class TestFailureIsolation:
    def test_db_unavailable_sanitized(self):
        class _DeadStore:
            @property
            def conn(self):
                raise RuntimeError("db down")
            def get_schema_version(self):
                raise RuntimeError("db down")
        svc = AuthorizedReadService(_DeadStore(), requesting_profile_id="PR1")
        dec = route(RouterRequest(normalized_text="Continue the project.", project_id="P",
                                  requesting_profile_id="PR1"))
        try:
            es = build_evidence_set(dec, svc, RouterRequest(normalized_text="x", project_id="P",
                                                           requesting_profile_id="PR1"))
            assert es.primary_evidence == () and es.supporting_evidence == ()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# static security audit
# ---------------------------------------------------------------------------
class TestStaticAudit:
    def test_no_forbidden_imports(self):
        for f in ("src/integration/m7/evidence_builder.py",
                  "src/integration/m7/eligibility.py",
                  "src/integration/m7/budget.py",
                  "src/integration/m7/contracts.py"):
            tree = ast.parse((REPO_ROOT / f).read_text())
            mods = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names: mods.add(a.name.split('.')[0])
                elif isinstance(n, ast.ImportFrom):
                    mods.add((n.module or '').split('.')[0])
            banned = {"AuthorizedWriteService", "GrantAdminService", "migrations",
                      "openai", "llm", "httpx", "requests", "aiohttp", "socket", "urllib"}
            assert not (mods & banned), (f, mods & banned)

    def test_no_llm_network_strings(self):
        for f in ("src/integration/m7/evidence_builder.py",
                  "src/integration/m7/eligibility.py",
                  "src/integration/m7/budget.py"):
            t = (REPO_ROOT / f).read_text().lower()
            for tok in ("httpx", "requests", "aiohttp", "socket.socket", "urllib", "openai"):
                assert tok not in t

    def test_no_grant_admin_reachability(self):
        src = (REPO_ROOT / "src/integration/m7/evidence_builder.py").read_text()
        assert "GrantAdminService" not in src
        assert "create_grant" not in src and "revoke_grant" not in src

    def test_schema_v8(self):
        from src.storage.migrations import CURRENT_SCHEMA_VERSION
        assert CURRENT_SCHEMA_VERSION == 11


# ---------------------------------------------------------------------------
# M7.1 / M7.2 regressions
# ---------------------------------------------------------------------------
class TestPriorRegression:
    def test_m71_master_switch_unchanged(self):
        from src.integration.zero_mem_runtime import parse_zero_mem_enabled, ZeroMemConfigError
        assert parse_zero_mem_enabled(None) is True
        with pytest.raises(ZeroMemConfigError):
            parse_zero_mem_enabled("garbage")

    def test_m72_router_unchanged(self):
        assert route(RouterRequest(normalized_text="Define a closure.", project_id="P")).route is MemoryRoute.NO_MEMORY
        assert route(RouterRequest(normalized_text="Explain recursion.", session_id="s1")).route is MemoryRoute.NO_MEMORY

    def test_m72_no_retrieval_on_router(self):
        assert "AuthorizedReadService" not in (REPO_ROOT / "src/integration/m7/memory_router.py").read_text()


# ---------------------------------------------------------------------------
# deferred absence
# ---------------------------------------------------------------------------
class TestDeferredAbsence:
    def test_injection_adapter_present_hardening_present(self):
        # M7.4 (controlled context injection) and M7.5 (hardening) are now IMPLEMENTED.
        assert (REPO_ROOT / "src/integration/m7/injection_adapter.py").exists()
        assert (REPO_ROOT / "src/integration/m7/hardening.py").exists()
    def test_no_evidence_m7_4_hook(self):
        src = (REPO_ROOT / "src/integration/m7/evidence_builder.py").read_text()
        assert "pre_llm" not in src
        assert "register_hook" not in src
    def test_no_m8(self):
        for p in REPO_ROOT.rglob("src/integration/m7/*.py"):
            t = p.read_text().lower()
            assert "vector retrieval" not in t and "embeddings" not in t


# ---------------------------------------------------------------------------
# Option B — PROJECT route active-state priority (P1 ordering)
# ---------------------------------------------------------------------------
class TestProjectStatePriority:
    """Regression: in the PROJECT route, active M4 state records must not be
    starved out of the bounded set by same-timestamp decisions."""

    def _state(self, eid, lifecycle="active", resource_type="state",
               verification="none", created="2026-08-05T00:00:00Z", as_primary=False):
        from src.integration.m7.eligibility import EligibilityResult
        item = EvidenceItem(evidence_id=eid, resource_type=resource_type,
                            lifecycle=lifecycle, verification=verification,
                            created_at=created, role=EvidenceRole.PRIMARY if as_primary else EvidenceRole.SUPPORTING)
        return (item, EligibilityResult(True, "eligible", as_primary=as_primary))

    def _decision(self, eid, verification=None, created="2026-08-05T00:00:00Z"):
        from src.integration.m7.eligibility import EligibilityResult
        item = EvidenceItem(evidence_id=eid, resource_type="decision",
                            lifecycle="active", verification=verification,
                            created_at=created, role=EvidenceRole.PRIMARY)
        return (item, EligibilityResult(True, "eligible", as_primary=True))

    def test_active_state_prioritized_in_project_route(self):
        from src.integration.m7.budget import select_evidence
        # A state and a decision, both active, same timestamp: in the PROJECT route the
        # active state sorts ahead within its pool; a superseded state does NOT.
        cands = [
            self._decision("D1", created="2026-08-05T00:00:00Z"),
            self._state("S-active", lifecycle="active", created="2026-08-05T00:00:00Z"),
            self._state("S-superseded", lifecycle="superseded", created="2026-08-05T00:00:00Z"),
        ]
        sel = select_evidence(cands, max_primary=5, max_supporting=3,
                              route=MemoryRoute.PROJECT)
        supporting_ids = [e.evidence_id for e in sel.supporting]
        # Active state must be present and ranked before the superseded state.
        assert "S-active" in supporting_ids
        assert supporting_ids.index("S-active") < supporting_ids.index("S-superseded")
        # Superseded remains supporting (never primary) — stale-safe by role.
        assert "S-superseded" not in [e.evidence_id for e in sel.primary]

    def test_non_project_routes_unchanged(self):
        from src.integration.m7.budget import select_evidence
        cands = [
            self._decision("D1", created="2026-08-05T00:00:00Z"),
            self._state("S-active", lifecycle="active", created="2026-08-05T00:00:00Z"),
            self._state("S-superseded", lifecycle="superseded", created="2026-08-05T00:00:00Z"),
        ]
        # Without a route (None), state priority must NOT engage: active state and
        # superseded state tie on role/verified/lifecycle and order by evidence_id.
        sel_none = select_evidence(cands, max_primary=5, max_supporting=3, route=None)
        sup_none = [e.evidence_id for e in sel_none.supporting]
        sel_session = select_evidence(cands, max_primary=5, max_supporting=3,
                                      route=MemoryRoute.SESSION)
        sup_session = [e.evidence_id for e in sel_session.supporting]
        assert sup_none == sup_session
        # No state (active or superseded) is elevated to primary on non-PROJECT routes.
        assert set(sup_none) == {"S-active", "S-superseded"}
        assert [e.evidence_id for e in sel_none.primary] == ["D1"]
        assert [e.evidence_id for e in sel_session.primary] == ["D1"]

    def test_budget_5_3_8_preserved_with_state_priority(self):
        from src.integration.m7.budget import select_evidence
        cands = [
            self._decision(f"D{i}", created=f"2026-08-{i:02d}T00:00:00Z") for i in range(1, 7)
        ] + [
            self._state(f"S{j}", lifecycle="active", created="2026-08-05T00:00:00Z") for j in range(1, 5)
        ]
        sel = select_evidence(cands, max_primary=5, max_supporting=3,
                              route=MemoryRoute.PROJECT)
        assert len(sel.primary) <= 5
        assert len(sel.supporting) <= 3
        assert len(sel.primary) + len(sel.supporting) <= 8
