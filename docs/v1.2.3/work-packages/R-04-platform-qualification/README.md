# R-04 — Platform Qualification

**Status:** OPEN
**Baseline SHA:** `5f1a329b6e5a18833fb4186cad7c91807a40b79e`
**Finding closed:** Windows/macOS qualification is absent; Linux has not been regenerated as v1.2.3 evidence.
**Allowed paths:** `src/storage/platform.py`, storage callers/tests, CI configuration, v1.2.3 evidence/work-package documentation.
**Public boundary tested:** Real storage API on each actual runner.
**Platform scope:** Linux, Windows, macOS; symlink privilege is a separate prerequisite status.

## Contract decision

Run capture, lock timeout, short write, promotion, recovery and link/reparse safety on real runners. Record `PASS`, `FAIL`, `NOT_RUN`, `UNSUPPORTED`, or `PREREQUISITE_UNAVAILABLE`; never infer support from Linux.

## Evidence

Pending R-00…R-03 dependency gates and actual runner availability.
