"""V141-R2 remediation tests (DEF-013/014/015) + V141-R3 acceptance (DEF-016).

GATE-R1 CHỌN A: the ``zero-mem grant`` admin surface is REVERTED from v1.4.1
because its store is disconnected from the production authorization path
(m6/handlers._resolve_grants reads the sidecar's main derived store). These
tests pin the REQUIRED post-remediation behavior:

DEF-013  The ``grant`` subcommand MUST NOT exist; the ``config`` subcommand
         (core-fix support) MUST still work.
DEF-014  AuthorizedReadService.close() MUST also close the injected
         corpus connection (no fd accumulation across requests).
DEF-015  The doctor check ``corpus_authorization`` MUST NOT report PASS from
         mere configuration existence: a configured-but-missing path is FAIL,
         and an unconfigured runtime stays WARN (fail-closed notice).
DEF-016  Acceptance goes through the REAL handler facade (_open_facade) with
         an env-configured corpus store: a knowledge-space grant authorizes an
         event read end-to-end through production construction.

RED state on the v1.4.1-WIP tree:
- grant subcommand still exists (test_grant_subcommand_absent fails)
- close() ignores corpus_conn (test_service_close_closes_corpus_conn fails)
- doctor reports PASS for a stale configured path (test_stale_path_fails_not_passes)
"""

from __future__ import annotations

import json
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _corpus_db(tmp_path):
    """Minimal derived corpus DB with one space member (mirrors V140-02)."""
    p = tmp_path / "corpus-derived.sqlite"
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE zm_corpus_sources ("
        " source_id TEXT PRIMARY KEY, profile_id TEXT, project_id TEXT,"
        " knowledge_space_id TEXT)"
    )
    conn.execute(
        "CREATE TABLE zm_corpus_units ("
        " unit_id TEXT PRIMARY KEY, source_ref TEXT, source_location_id TEXT,"
        " content_hash TEXT, normalized_text TEXT, kind TEXT, profile_id TEXT,"
        " project_id TEXT, knowledge_space_id TEXT, lifecycle_status TEXT,"
        " sensitivity TEXT, page INTEGER, unit_order INTEGER)"
    )
    conn.execute(
        "INSERT INTO zm_corpus_sources VALUES ('s1','prof-X','proj-Y','quant-theory')"
    )
    conn.execute(
        "INSERT INTO zm_corpus_units VALUES ("
        "'u1','s1','loc','h','kelly criterion text','md','prof-X','proj-Y',"
        "'quant-theory','active','public',NULL,0)"
    )
    conn.commit()
    conn.close()
    return p


@pytest.fixture()
def isolated_env(monkeypatch, tmp_path):
    monkeypatch.delenv("ZM_M6_CORPUS_STORE_PATH", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    return tmp_path


def _subcommands(parser) -> set:
    subs = set()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            subs |= set(choices)
    return subs


# ---------------------------------------------------------------------------
# DEF-013 — grant subcommand reverted, config subcommand retained
# ---------------------------------------------------------------------------


class TestDef013GrantCliReverted:
    def test_grant_subcommand_absent(self):
        from zero_mem import cli

        assert "grant" not in _subcommands(cli.build_parser()), (
            "DEF-013: 'grant' admin surface is disconnected from the "
            "production authorization path and must not ship in v1.4.1")

    def test_config_subcommand_retained(self):
        from zero_mem import cli

        assert "config" in _subcommands(cli.build_parser()), (
            "config CLI backs the core DEF-012 fix")

    def test_config_set_show_roundtrip_still_works(self, isolated_env, capsys):
        from zero_mem import cli

        corpus = _corpus_db(isolated_env)
        assert cli.main(["config", "set", "corpus-store-path", str(corpus)]) == 0
        capsys.readouterr()
        assert cli.main(["config", "show"]) == 0
        shown = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert shown["corpus_store_path"] == str(corpus)


# ---------------------------------------------------------------------------
# DEF-014 — corpus connection lifecycle
# ---------------------------------------------------------------------------


class TestDef014CorpusConnLifecycle:
    def test_service_close_closes_corpus_conn(self, tmp_path):
        from src.access.authorized_read import AuthorizedReadService
        from src.integration.m6 import runtime as rt

        corpus = _corpus_db(tmp_path)
        main = tmp_path / "main.sqlite"
        main.touch()
        r = rt.configure(main, corpus_store_path=corpus)
        try:
            store = r.open_store()
            svc = AuthorizedReadService(
                store, "requester",
                grant_conn=store.conn, corpus_conn=r.open_corpus_conn())
            probe = svc._corpus_conn
            assert probe is not None
            svc.close()
            with pytest.raises(sqlite3.ProgrammingError):
                probe.execute("SELECT 1")
        finally:
            rt.close_default()

    def test_facade_close_releases_corpus_conn(self, tmp_path, monkeypatch):
        """SUPERSEDED (V150-WP3): _open_facade no longer opens a corpus conn
        on the event path (per-row authorization). Replacement contract: the
        facade's store connection IS released on close."""
        from src.integration.m6 import handlers, runtime as rt

        main = tmp_path / "main.sqlite"
        main.touch()
        from src.storage.migrations import migrate_8
        gconn = sqlite3.connect(str(main))
        gconn.row_factory = sqlite3.Row
        migrate_8.up(gconn, "v141r2")
        gconn.commit()
        gconn.close()
        r = rt.configure(main)
        try:
            req = handlers.M6Request(tool="memory_query",
                                     requesting_profile_id="requester")
            svc, store, grants = handlers._open_facade(r, req)
            probe = store.conn
            assert probe is not None
            svc.close()
            with pytest.raises(Exception):
                probe.execute("SELECT 1")
        finally:
            rt.close_default()


# ---------------------------------------------------------------------------
# DEF-015 — doctor check honesty
# ---------------------------------------------------------------------------


class TestDef015DoctorHonesty:
    def _doctor_checks(self, capsys) -> dict:
        from zero_mem import commands_doctor

        commands_doctor.run(as_json=True)
        out = capsys.readouterr().out
        data = json.loads(out)
        return {c["id"]: c["status"] for c in data.get("checks", [])}

    def test_unconfigured_is_warn_not_pass(self, isolated_env, capsys):
        statuses = self._doctor_checks(capsys)
        assert "corpus_authorization" in statuses, (
            "doctor must surface corpus_authorization")
        assert statuses["corpus_authorization"] == "WARN", (
            "unconfigured => fail-closed notice (WARN), never PASS")

    def test_stale_path_fails_not_passes(self, isolated_env, capsys):
        from zero_mem.userconfig import set_corpus_store_path as _set

        # Persist through the validating path first, then remove the file so
        # only a STALE reference remains.
        corpus = _corpus_db(isolated_env)
        _set(str(corpus))
        corpus.unlink()
        capsys.readouterr()

        statuses = self._doctor_checks(capsys)
        assert statuses.get("corpus_authorization") != "PASS", (
            "configured-but-missing corpus store must NOT be reported PASS")

    def test_valid_path_reports_pass(self, isolated_env, capsys):
        from zero_mem.userconfig import set_corpus_store_path as _set

        corpus = _corpus_db(isolated_env)
        _set(str(corpus))
        capsys.readouterr()
        statuses = self._doctor_checks(capsys)
        assert statuses.get("corpus_authorization") == "PASS"


# ---------------------------------------------------------------------------
# DEF-016 — acceptance through the REAL handler facade
# ---------------------------------------------------------------------------


class TestDef016RealFacadeAcceptance:
    def test_space_grant_authorizes_event_read_via_open_facade(
            self, tmp_path, monkeypatch):
        """THE acceptance: env-configured corpus store + real _open_facade =>
        resolver expands space members and the event path authorizes."""
        from src.access.authorized_read import _scope_allows
        from src.access.contracts import AllowedScope, READ
        from src.integration.m6 import handlers, runtime as rt

        corpus = _corpus_db(tmp_path)
        main = tmp_path / "main.sqlite"
        conn = sqlite3.connect(str(main))
        conn.row_factory = sqlite3.Row
        from src.storage.migrations import migrate_8
        migrate_8.up(conn, "v141r3")
        conn.commit()
        conn.close()
        monkeypatch.setenv("ZM_M6_CORPUS_STORE_PATH", str(corpus))

        r = rt.configure(main)
        try:
            req = handlers.M6Request(tool="memory_query",
                                     requesting_profile_id="requester")
            svc, store, grants = handlers._open_facade(r, req)
            try:
                # V150-WP3: facade no longer carries corpus_conn (per-row
                # canonical authorization); assert the new contract.
                assert svc._corpus_conn is None, (
                    "V150-WP3: event path must not wire a corpus connection")
                scope = AllowedScope(operation=READ,
                                     allowed_knowledge_space_ids=["quant-theory"])
                # V150-WP3: expansion no-op — nothing merged from corpus members.
                expanded = svc._expand_scope_with_spaces(scope)
                assert expanded.allowed_profile_ids == []
                # V150-WP3: resolver still resolves (corpus path); event path
                # is per-row only — NULL ks never authorizes via members.
                # Per-row authorization via zm_meta.ks only.
                assert _scope_allows(expanded, "requester", "prof-X", "proj-Y",
                                     row_knowledge_space_id="quant-theory") is True
                assert _scope_allows(expanded, "requester", "prof-Z", "proj-W",
                                     row_knowledge_space_id="other-ks") is False
                assert _scope_allows(expanded, "requester", "prof-X", "proj-Y",
                                     row_knowledge_space_id=None) is False
            finally:
                svc.close()
        finally:
            rt.close_default()
