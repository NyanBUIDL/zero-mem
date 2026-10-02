"""T19 - ``zero-mem ui`` command: options, banner, browser opening, idle exit, real subprocess."""
from __future__ import annotations

import http.client
import os
import re
import subprocess
import sys
import threading
import time

import pytest

from tests.unit.t19_helpers import env, layout  # noqa: F401  (fixtures)
from zero_mem import cli


def test_parser_defaults_and_options():
    args = cli.build_parser().parse_args(["--profile", "codex", "ui", "--allow-root", "/a", "--allow-root", "/b", "--port", "5"])
    assert args.profile == "codex" and args.allow_root == ["/a", "/b"] and args.port == 5
    assert args.open_browser is False and args.idle_timeout == 60.0 and args.host == "127.0.0.1"
    assert cli.build_parser().parse_args(["ui", "--open"]).open_browser is True  # accepted for compatibility, ignored
    assert cli.build_parser().parse_args(["ui", "--open", "--no-open"]).open_browser is False
    assert cli.build_parser().parse_args(["ui", "--profile", "x"]).profile == "x"


def test_banner_warns_prints_the_secret_url_and_does_not_open_a_browser_by_default(env, capsys, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    assert cli.main(["ui", "--idle-timeout", "0.02"]) == 0
    out = capsys.readouterr().out
    assert opened == []
    assert re.search(r"http://127\.0\.0\.1:\d+/s/[A-Za-z0-9_-]{43}/", out)
    assert out.count("/s/") == 1 and "bookmarks" in out and "Ctrl+C" in out
    assert "approve rules" in out and "grant write access" in out and "shell" in out and "idle timeout" in out


def test_open_flag_never_passes_the_secret_url_to_a_browser_process(env, capsys, monkeypatch):
    """The URL would be visible in the process list (argv of the browser launcher): --open is accepted but does nothing."""
    import subprocess

    opened, spawned = [], []
    monkeypatch.setattr("webbrowser.open", lambda *a, **k: opened.append(a) or True)
    monkeypatch.setattr("webbrowser.open_new", lambda *a, **k: opened.append(a) or True)
    monkeypatch.setattr("webbrowser.open_new_tab", lambda *a, **k: opened.append(a) or True)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: spawned.append(a) or (_ for _ in ()).throw(AssertionError("spawn")))
    assert cli.main(["ui", "--open", "--idle-timeout", "0.02"]) == 0
    captured = capsys.readouterr()
    assert opened == [] and spawned == []
    assert "--open is ignored" in captured.err
    url = re.search(r"http://127\.0\.0\.1:\d+/s/[A-Za-z0-9_-]{43}/", captured.out)
    assert url and url.group(0) not in captured.err


def test_port_in_use_and_bad_roots_are_clean_errors(env, capsys):
    import socket

    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    try:
        assert cli.main(["ui", "--port", str(holder.getsockname()[1])]) == 2
        assert "port" in capsys.readouterr().err
    finally:
        holder.close()
    assert cli.main(["ui", "--allow-root", "nope"]) == 2
    err = capsys.readouterr().err
    assert "allow-root" in err and "Traceback" not in err


def test_the_panel_follows_the_resolved_data_root_and_profile(env, capsys):
    assert cli.main(["--profile", "codex", "ui", "--idle-timeout", "0.02"]) == 0
    out = capsys.readouterr().out
    assert str(env / "data") in out and "acting as   codex" in out


def test_real_subprocess_serves_stops_on_idle_and_prints_no_traceback(env):
    environment = dict(os.environ)
    code = "import sys; from zero_mem.cli import main; sys.exit(main(['ui','--idle-timeout','0.1']))"
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env=environment, cwd=os.getcwd())
    try:
        url = None
        deadline = time.monotonic() + 30
        lines = []
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            lines.append(line)
            match = re.search(r"http://127\.0\.0\.1:(\d+)(/s/[A-Za-z0-9_-]{43}/)", line)
            if match:
                url = match
                break
        assert url, lines
        port, path = int(url.group(1)), url.group(2)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 200
        proc.wait(timeout=40)
        assert proc.returncode == 0
        assert "Traceback" not in proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.stderr.close()


@pytest.mark.skipif(os.name == "nt", reason="SIGINT delivery differs on Windows")
def test_ctrl_c_stops_the_server_cleanly(env):
    import signal

    code = "import sys; from zero_mem.cli import main; sys.exit(main(['ui']))"
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(100):
            if "/s/" in proc.stdout.readline():
                break
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=30)
        assert proc.returncode == 0
        assert "Traceback" not in proc.stderr.read()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.stderr.close()
