"""T19 - control panel ingestion: upload and allow-root paths, preview then confirm, refusals (traversal, symlink, outside
roots, reserved paths, secrets)."""
from __future__ import annotations

import os
import re

import pytest

from tests.unit.t19_helpers import (  # noqa: F401  (fixtures)
    SECRET_TOKEN, Client, env, layout, panel, populate, populated, ppanel, start, state_fingerprint, stop,
)
from zero_mem.memory import Memory


def total_sources():
    with Memory.open("codex", channel="test") as mem:
        return mem.status()["sources"]["total"]


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "notes"
    (root / "sub").mkdir(parents=True)
    (root / "ok.md").write_text("# Plan\nShip the control panel on Friday.\n", encoding="utf-8")
    (root / "sub" / "more.txt").write_text("The deploy key rotates monthly.\n", encoding="utf-8")
    (root / "leak.txt").write_text(f"credentials: {SECRET_TOKEN}\n", encoding="utf-8")
    (root / ".hidden.md").write_text("hidden note\n", encoding="utf-8")
    (root / "empty.txt").write_text("", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dep.md").write_text("dependency\n", encoding="utf-8")
    (root / "blob.bin").write_bytes(b"\x00\x01\x02\x03" * 50)
    return root


@pytest.fixture
def rpanel(env, tree):
    server, thread = start(profile="codex", allow_roots=[str(tree)])
    try:
        client = Client(server)
        client.tree = tree
        yield client
    finally:
        stop(server, thread)


def preview_path(client, path, **extra):
    fields = {"mode": "path", "path": str(path), "memory_type": "file", "scope": "private", "profile": "codex", **extra}
    return client.post("/ingest/preview", fields)


# ----------------------------------------------------------------------------------------------- path + preview + confirm
def test_path_preview_lists_what_would_be_ingested_skipped_and_rejected_and_stores_nothing(rpanel):
    status, _h, body = preview_path(rpanel, rpanel.tree)
    assert status == 200 and "would ingest" in body
    assert "ok.md" in body and "more.txt" in body
    assert "rejected: a credential-like value was detected" in body and "leak.txt" in body and SECRET_TOKEN not in body
    assert "skipped: hidden" in body and "skipped: excluded_dir" in body and "skipped: unsupported_binary" in body
    assert "Would ingest</dt><dd>2<" in body and "Confirm ingest" in body
    assert total_sources() == 0  # a preview never stores anything


def test_confirm_ingests_and_shows_the_report_with_source_ids(rpanel):
    _s, _h, body = preview_path(rpanel, rpanel.tree, name="notes")
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    status, _h, body = rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})
    assert status == 200 and "Ingest report (partial)" in body and "2 created" in body
    assert "file://notes/ok.md" in body and "(source " in body and "rejected leak.txt" in body and "credential-like" in body
    assert "skipped .hidden.md: hidden" in body
    assert total_sources() == 2
    with Memory.open("codex", channel="test") as mem:
        assert mem.recall("control panel Friday").hits
        assert not mem.recall("credentials").hits
    # a repeat is a no-op ("unchanged"), as with the CLI
    _s, _h, body = preview_path(rpanel, rpanel.tree, name="notes")
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    assert "2 unchanged" in rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})[2]


def test_a_preview_is_single_use_and_needs_the_checkbox(rpanel):
    _s, _h, body = preview_path(rpanel, rpanel.tree / "ok.md")
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    assert "not confirmed" in rpanel.post("/ingest/confirm", {"id": key})[2].lower()
    assert total_sources() == 0
    assert "Ingest report" in rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})[2]
    assert "expired" in rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})[2].lower()
    assert "expired" in rpanel.post("/ingest/confirm", {"id": "made-up", "approve": "1"})[2].lower()
    assert rpanel.get("/ingest/preview?id=" + key)[0] == 404


def test_preview_and_confirm_equal_the_cli_ingest_result(rpanel, env):
    from zero_mem import cli

    _s, _h, body = preview_path(rpanel, rpanel.tree / "ok.md", name="plan")
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})
    with Memory.open("codex", channel="test") as mem:
        ui_ref = mem.recall("Friday").hits[0].external_ref
    assert cli.main(["--profile", "codex", "ingest", str(rpanel.tree / "ok.md"), "--type", "file", "--name", "plan"]) == 0
    with Memory.open("codex", channel="test") as mem:
        assert mem.status()["sources"]["total"] == 1 and mem.recall("Friday").hits[0].external_ref == ui_ref


def test_confirm_reports_authorization_denials_like_the_cli(rpanel):
    _s, _h, body = preview_path(rpanel, rpanel.tree / "ok.md", scope="shared")  # codex has no write grant here
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    _s, _h, body = rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})
    assert "Ingest denied" in body and "grant-write" in body and total_sources() == 0


# ----------------------------------------------------------------------------------------------- allow-root enforcement
def test_no_allow_roots_means_no_path_ingestion(panel, tmp_path):
    (tmp_path / "x.md").write_text("hello world\n", encoding="utf-8")
    status, _h, body = panel.post("/ingest/preview", {"mode": "path", "path": str(tmp_path / "x.md"), "memory_type": "file"})
    assert status == 422 and "--allow-root" in body
    assert "No folders are allowed" in panel.page("/ingest")


def test_paths_outside_the_roots_or_with_traversal_are_refused(rpanel, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret plans\n", encoding="utf-8")
    sneaky = str(rpanel.tree / ".." / "outside.md")
    for path in (str(outside), sneaky, str(tmp_path), str(rpanel.tree.parent), "relative/path.md", "~/x.md", "",
                 str(rpanel.tree) + "/../notes/../outside.md", "a\x00b"):
        status, _h, body = rpanel.post("/ingest/preview", {"mode": "path", "path": path, "memory_type": "file"})
        assert status == 422, path
        assert 'class="err"' in body, path
    assert total_sources() == 0


def test_file_system_paths_outside_roots_reveal_nothing_about_existence(rpanel):
    a = rpanel.post("/ingest/preview", {"mode": "path", "path": os.path.abspath(os.sep), "memory_type": "file"})[2]
    b = rpanel.post("/ingest/preview", {"mode": "path", "path": os.path.abspath(os.sep + "no-such-dir-xyz"), "memory_type": "file"})[2]
    msg = re.compile(r'class="err"[^>]*>([^<]*)<')
    assert msg.search(a).group(1) == msg.search(b).group(1)


def test_symlinks_are_refused(rpanel, tmp_path):
    target = tmp_path / "elsewhere.md"
    target.write_text("do not read me\n", encoding="utf-8")
    link = rpanel.tree / "link.md"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    status, _h, body = rpanel.post("/ingest/preview", {"mode": "path", "path": str(link), "memory_type": "file"})
    assert status == 422 and "Symlinks are not followed" in body
    # a symlinked directory inside the root, and a file reached through it
    d = rpanel.tree / "linkdir"
    os.symlink(tmp_path, d)
    status, _h, body = rpanel.post("/ingest/preview", {"mode": "path", "path": str(d / "elsewhere.md"), "memory_type": "file"})
    assert status == 422 and "Symlinks" in body
    # walking the whole root skips the symlink instead of following it
    _s, _h, body = preview_path(rpanel, rpanel.tree)
    assert "do not read me" not in body and "skipped: symlink" in body
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})
    with Memory.open("codex", channel="test") as mem:
        assert not mem.recall("read me").hits


def test_symlink_swapped_in_after_the_preview_is_refused_at_confirm(rpanel, tmp_path):
    secret = tmp_path / "private.md"
    secret.write_text("private diary\n", encoding="utf-8")
    victim = rpanel.tree / "swap.md"
    victim.write_text("innocent\n", encoding="utf-8")
    _s, _h, body = preview_path(rpanel, victim)
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    victim.unlink()
    try:
        os.symlink(secret, victim)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    _s, _h, body = rpanel.post("/ingest/confirm", {"id": key, "approve": "1"})
    assert "Path refused" in body and total_sources() == 0


def test_the_memory_store_itself_cannot_be_ingested(env, layout):
    server, thread = start(profile="codex", allow_roots=[str(layout.data_root.parent)])
    try:
        c = Client(server)
        for path in (layout.data_root, layout.corpus_root, layout.memory_stream, layout.data_root.parent):
            status, _h, body = c.post("/ingest/preview", {"mode": "path", "path": str(path), "memory_type": "file"})
            assert status == 422 and "memory store itself" in body, path
    finally:
        stop(server, thread)


def test_a_bad_allow_root_is_a_startup_error(env, tmp_path):
    from zero_mem.ui import PanelConfigError, create_server

    for bad in ("relative", str(tmp_path / "missing"), os.path.abspath(os.sep)):
        with pytest.raises(PanelConfigError):
            create_server(allow_roots=[bad])


def test_the_panel_has_no_file_browser(rpanel):
    for route in ("/browse", "/files", "/fs", "/ls", "/download", "/ingest/list", "/static/notes"):
        assert rpanel.get(route)[0] == 404


# ----------------------------------------------------------------------------------------------- upload
def test_upload_preview_then_confirm_with_the_bytes_api(panel):
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file", "scope": "private",
                                                           "profile": "codex"}, "notes.md", b"# Title\nThe launch is on Friday.\n")
    assert status == 200 and "would ingest" in body and "notes.md" in body and "upload: notes.md" in body
    assert total_sources() == 0
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    _s, _h, body = panel.post("/ingest/confirm", {"id": key, "approve": "1"})
    assert "1 created" in body and "file://notes.md" in body
    with Memory.open("codex", channel="test") as mem:
        assert mem.recall("launch Friday").hits[0].external_ref == "file://notes.md"


def test_upload_with_a_secret_is_rejected_in_the_preview_and_in_the_write(panel):
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file"}, "k.txt",
                                       f"token {SECRET_TOKEN}".encode())
    assert "rejected: a credential-like value" in body and SECRET_TOKEN not in body and "Nothing can be ingested" in body
    assert 'action="/ingest/confirm"' not in body  # nothing to confirm
    assert total_sources() == 0


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b.txt", "..\\win.txt", "C:evil.txt", "..", ".", "dir/", "x" * 300,
                                  "/abs.txt", "\\\\server\\share.txt", "a\x01b.txt"])
def test_upload_names_with_path_components_are_rejected(panel, name):
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file"}, name, b"content here")
    assert status in (400, 422), name
    assert "would ingest" not in body and total_sources() == 0


def test_upload_without_a_file_or_with_a_text_field_named_file(panel):
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file"}, None)
    assert status == 422 and "Choose a file" in body
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file", "file": "just text"}, None)
    assert status == 422


def test_upload_filename_star_encoding_and_empty_file(panel):
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file"}, "e.txt", b"")
    assert status == 200 and "skipped: empty" in body and "Nothing can be ingested" in body
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file"}, "x.txt", b"hello there",
                                       raw_disposition="form-data; name=\"file\"; filename*=UTF-8''..%2F..%2Fx.txt")
    assert status in (400, 422)


def test_upload_unsupported_binary_is_rejected_cleanly(panel):
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file"}, "x.exe", b"MZ\x00\x01" * 100)
    assert status == 200 and "rejected" in body and total_sources() == 0


def test_upload_learned_types_are_allowed_for_the_owner_only_path(panel):
    status, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "rule", "scope": "private",
                                                           "profile": "codex", "name": "up-rule"}, "r.md", b"Always lint first.\n")
    key = re.search(r'name="id" value="([^"]+)"', body).group(1)
    _s, _h, body = panel.post("/ingest/confirm", {"id": key, "approve": "1"})
    assert "mem://rule/up-rule" in body or "1 created" in body


def test_preview_store_is_bounded(panel):
    keys = []
    for i in range(10):
        _s, _h, body = panel.multipart("/ingest/preview", {"mode": "upload", "memory_type": "file"}, f"f{i}.txt", b"some words %d" % i)
        keys.append(re.search(r'name="id" value="([^"]+)"', body).group(1))
    assert len(panel.server.panel._previews) <= 6
    assert panel.get("/ingest/preview?id=" + keys[0])[0] == 404 and panel.get("/ingest/preview?id=" + keys[-1])[0] == 200
