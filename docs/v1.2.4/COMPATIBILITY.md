# Zero-Mem v1.2.4 Compatibility Decisions

This document records public semantic changes introduced during the R124 remediation
so that downstream integrators and the verification agent can distinguish intentional
contract changes from regressions.

## COMPAT-001 — Default runtime mode changed from `assist` to `observe` (R124-01)

**Prior contract (before ff631d5a...):** When no `ZERO_MEM_MODE` was set, the
production `HermesBoundary` defaulted to `assist` and therefore registered the
authorized read tools automatically.

**New contract (R124-01):** The default effective mode is now `observe`.

- `ZERO_MEM_ENABLED=false` → `off`
- `ZERO_MEM_MODE` present → that explicit mode (invalid → fail-closed `off`)
- canonical config `capture_mode=observation_only` → `observe`
- canonical config `capture_mode=<mode>` → that mode
- nothing configured → `observe` (least privilege)

**Rationale:** R124-01 mandates that the default setup registers OBSERVE behavior and
that a missing environment variable must never self-elevate a boundary from
`observe` into `assist`. The prior `assist` default registered read tools without an
explicit operator opt-in, violating least-privilege and the audit baseline.

**Migration guidance:** Integrators who relied on read-tool registration by default
must set `ZERO_MEM_MODE=assist` (or `inject`) explicitly, or write the canonical
`capture_mode` config. No data migration is required; canonical JSONL and the derived
store schema are unchanged.

**Test impact:** `tests/integration/test_v123_hermes_host_composition.py` previously
asserted the `assist` default. That E2E read-path coverage now runs under explicit
`assist` (test `test_public_host_factory_assist_register_capture_projection_read_restart_shutdown`),
and a new `test_host_factory_default_observes_only` asserts the new `observe` default.
No assertion was silently deleted; the prior read-path behavior remains covered.

## COMPAT-002 — Single production storage topology (R124-02)

**Change:** `HermesBoundary` now composes exactly one `ZeroMemRuntime` (one canonical
writer, one derived SQLite store, one bounded `ProjectionCoordinator`). The previously
independent `store_path` argument is now a *compatibility* input only: it must resolve
to the runtime-owned derived store `<capture_root>/derived/events.sqlite`; a mismatched
`store_path` fails closed (no registration, no writer, no projection).

**Rationale:** The prior split-topology (capture → DB-A, read → DB-B) could desync
canonical vs derived and produced duplicate writers/projection workers on restart.

## COMPAT-003 — Truthful public health/sync (R124-03)

**Change:** `zero_mem.api` `health()` and `sync()` now return the runtime's real
freshness/watermark state. `sync()` no longer returns `SYNCED` merely because a flush
method was called; it returns `CURRENT` only when canonical/derived identity is valid,
the projection watermark has caught up, checkpoints are valid, and no unresolved
projection failure exists. `OFF`/`CLOSED`/`UNAVAILABLE`/`STALE`/`TIMEOUT` are emitted
truthfully.

## COMPAT-004 — Secure HITL correction lifecycle (R124-04)

**Change:** The correction controller now emits ingest-compatible control events
(`event_type=control`, `source=operator`, `lifecycle_status`/`deletion`/`superseded_by`
blocks per `src/capture/validation.py`), redacts user-controlled fields before
persistence/log, mints occurrence-safe unique proposal/event IDs (no fixed
`ctrl-{target}` collision), and exposes correction only via the reviewed operator/HITL
surface — never as an automatic read tool.

## COMPAT-005 — Distribution version 1.2.3 → 1.2.4 (R124-09)

**Change:** `zero_mem/version.py` and the release manifest now report `1.2.4`.
The `release/v1.2.4` branch previously built wheels labeled `1.2.3`, which made
every packaging/upgrade assertion and any downstream version check inconsistent
with the branch name.

**Migration guidance:** No data migration; the derived schema and canonical JSONL
are unchanged. Downstream version checks should expect `zero-mem 1.2.4`.

## COMPAT-006 — Windows byte-determinism and installer layout (R124-07/09)

**Change:** All data-write file handles now open in binary mode (`O_BINARY`) on
Windows, so canonical JSONL, projected notes, and the manifest are byte-identical
across platforms (previously CRT text mode translated `\n` → `\r\n`). The
ownership fingerprint check reads managed notes with explicit UTF-8 encoding
(previously platform locale, e.g. cp1252, could mangle non-ASCII content).
The installer now creates Windows venv layout (`Scripts/`), a `.cmd` CLI shim,
and a directory-junction `current` pointer where symlink privileges are absent.

**Impact:** Canonical JSONL produced on Windows before this change may contain
CRLF line endings; such files remain valid JSONL (line-oriented readers already
tolerate trailing `\r`) but are superseded by LF output from this version.
Fingerprints computed under the old locale-default read are corrected going
forward; no stored data was invalidated.

## COMPAT-007 — Release helper package renamed (R124-09)

**Change:** The repository-local `packaging/` helper package (build/install
tooling) was renamed to `release_helpers/` because its name shadowed the PyPI
`packaging` distribution and broke `python -m build` from the repo root.
Downstream tooling must import `release_helpers.*` instead of `packaging.*`.
