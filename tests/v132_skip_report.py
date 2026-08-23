"""V132-08 — pytest skip-transparency plugin.

Add `-p tests.v132_skip_report` (or run with `--v132-skips`) to print every
skipped test WITH its reason at session end. Stdlib only.
"""
from __future__ import annotations


def pytest_addoption(parser):
    group = parser.getgroup("v132-skip-report")
    group.addoption(
        "--v132-skips", action="store_true", default=False,
        help="print all skipped tests with reasons at session end",
    )


def _report(config, entries):
    if not entries:
        return
    w = config.get_terminal_writer()
    w.line("")
    w.line("=== V132 skip report: %d skipped ===" % len(entries))
    for nodeid, reason in entries:
        w.line("  SKIP %s — %s" % (nodeid, reason or "(no reason given)"))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not config.getoption("--v132-skips", False):
        return
    entries = []
    for rep in terminalreporter.stats.get("skipped", []):
        nodeid = getattr(rep, "nodeid", "?")
        reason = ""
        wasxfail = getattr(rep, "wasxfail", None)
        if wasxfail:
            reason = "xfail"
        else:
            longrepr = getattr(rep, "longrepr", None)
            if longrepr is not None:
                # pytest.skip raises Skipped whose repr is the reason text;
                # longrepr may be a tuple (path, lineno, message).
                if isinstance(longrepr, tuple) and len(longrepr) == 3:
                    reason = str(longrepr[2])
                else:
                    reason = str(longrepr).splitlines()[-1] if str(longrepr) else ""
        entries.append((nodeid, reason))
    _report(config, entries)
