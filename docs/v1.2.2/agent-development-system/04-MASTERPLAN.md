# 04 — v1.2.2 master plan: close audit findings

## Release objective

`v1.2.2` is complete only when the path below is executable, authorized, observable and qualified on the declared platforms:

```text
Hermes/direct caller
  → canonical public contract
  → authorization before discovery
  → durable JSONL capture or read-only query
  → derived projection/freshness policy
  → canonical sidecar/Hermes response
  → provenance-bearing typed result
```

The release must not claim Windows or macOS support until the relevant matrix rows pass. If an approved interface change makes the version semantically minor rather than patch-level, stop before tagging and ask the maintainer whether the release must become `v1.3.0`.

## Dependency graph

```text
V122-00 Baseline/evidence
       │
       ▼
V122-01 Platform storage contract ──┐
       │                             │
       ▼                             │
V122-02 Runtime + projection ───────┤
       │                             │
       ▼                             │
V122-03 Public authorized reads ────┤
       │                             │
       ▼                             │
V122-04 Canonical sidecar ──────────┤
       │                             │
       ▼                             │
V122-05 Hermes full lifecycle ──────┤
       │                             │
       └───────────────► V122-06 Qualification and release decision
```

## V122-00 — Baseline and evidence integrity

**Closes:** A-02 verification, A-07.

- Verify `v1.2.1` tag, GitHub assets and checksums from a clean clone.
- Ensure WP-33 benchmark imports, has deterministic output and is included in the source/test workflow where intended.
- Create an evidence manifest verifier that rejects a pass record missing exact SHA, raw log or asset hash.
- Do not claim a full-suite pass when collection has errors.

**Exit gate:** exact commands collect/run WP-33 on every declared platform; a manifest verifier detects altered SHA/log/hash fixtures.

## V122-01 — Cross-platform storage contract

**Closes:** A-06, A-08 foundation.

- Introduce one internal platform-storage protocol for lock acquisition, regular-file identity, safe read, atomic promotion and safe cleanup.
- Move POSIX-only `fcntl`, `O_DIRECTORY`, `O_NOFOLLOW`, descriptor-relative and `/proc/self/fd` behavior behind a POSIX backend.
- Implement an equivalent Windows backend using handle-based locking and reparse-point-aware path checks. Implement/qualify a macOS POSIX backend explicitly.
- Preserve typed domain errors: `LOCK_TIMEOUT`, `UNSAFE_PATH`, `UNAVAILABLE`; never leak OS-specific paths or raw error text.
- Test concurrent processes, abandoned locks, symlink/reparse attacks, timeout and promotion failures on each OS.

**Allowed owners:** `src/storage/coordination.py`, `src/storage/runtime_root.py`, `src/storage/jsonl_capture.py`, recovery/projection path callers, benchmark secure-root helper and their tests.

**Exit gate:** core capture, recovery and WP-33 tests pass on Windows, Linux and macOS without unconditional skip.

## V122-02 — Runtime-owned projection and freshness

**Closes:** A-03.

- `ZeroMemRuntime` owns one canonical writer, one bounded projection coordinator and deterministic shutdown.
- A durable append creates an idempotent projection submission keyed by event ID/sequence. Queue saturation has a declared, typed policy.
- Expose canonical sequence, projected sequence, lag, last successful projection timestamp and sanitized last error through a health/freshness object.
- Recovery/rebuild uses canonical JSONL, establishes a checkpoint/watermark and cannot mutate canonical records.

**Allowed owners:** `src/integration/zero_mem_runtime.py`, `src/storage/projection.py`, `zero_mem/core.py`, `zero_mem/recovery.py`, health/status contracts and focused tests.

**Exit gate:** capture → restart → query observes event; forced projection failure returns stale/unavailable correctly without a false capture failure; no duplicate writer/worker on restart.

## V122-03 — Canonical public authorized reads

**Closes:** A-01.

- Define versioned typed contracts for `search`, `get_trace`, `get_task_state`, `get_decisions`.
- Keep `zero_mem.api` neutral by injecting a read-service protocol; implement the adapter with `AuthorizedReadService`, not direct SQL.
- Enforce identity/grants before retrieval and expose no candidate count, ID, snippet or timing-derived scope on deny.
- Apply explicit consistency options: require-current, bounded wait, or allow-stale. Results include provenance and freshness.
- Preserve old callers where compatible; any semantic incompatibility requires a reviewed version decision.

**Allowed owners:** `zero_mem/api.py`, public contracts, `src/access/authorized_read.py` adapters, status/freshness types, tests.

**Exit gate:** all four methods return real authorized results; denial happens before read; stale/missing derived state has a typed response; public source remains storage/Hermes neutral.

## V122-04 — Canonical sidecar transport

**Closes:** A-04.

- Publish one canonical sidecar façade whose methods and normalized envelopes match V122-03.
- Route it to the same authorized read service/public contract, with bounded bytes/depth/items/queue/deadline/executor behavior.
- Retain `LocalSidecar` only as a documented deprecated adapter with contract tests and a removal milestone.
- Add direct-versus-sidecar golden tests for success, empty, denied, stale, timeout, overload and disabled states.

**Allowed owners:** `zero_mem/sidecar.py`, `src/integration/sidecar.py`, sidecar tests and public exports.

**Exit gate:** no public surface advertises legacy-only capabilities as canonical; parity tests prove identical semantics without duplicated auth/retrieval implementation.

## V122-05 — Hermes production lifecycle

**Closes:** A-05.

- Define a stable host factory/configuration entrypoint with explicit identity, storage root, enable gate, timeout and lifecycle ownership.
- Compose capture hooks, canonical read tools and approved controlled-injection boundary only through owned runtime/sidecar components.
- Register idempotently; disabled state performs no writer/DB/query side effect; shutdown/restart releases owned resources and does not duplicate registrations.
- Test against a contract fixture that represents the actual supported host callback/tool API. Record any host mismatch as blocked.

**Allowed owners:** `src/integration/hermes_plugin.py`, `src/integration/hermes_registration.py`, `src/integration/hermes_read_adapter.py`, `zero_mem/hermes_integration.py`, integration/E2E tests.

**Exit gate:** enabled host follows capture → projection → read; disabled host remains side-effect free; restart/shutdown/leakage/error paths pass on all qualified OSes.

## V122-06 — Release qualification

**Closes:** A-07, A-08 completion.

- Run the full test, security, benchmark, process-concurrency and E2E matrix for Windows, Linux and macOS on CPython 3.11–3.13.
- Build wheel/sdist from exact candidate SHA, clean-install in a new virtual environment and run public API + sidecar + Hermes smoke tests.
- Publish a manifest with tag/source SHA, build command, toolchain, SBOM, asset checksums and raw logs.
- Obtain an independent audit from a clean checkout. Any unclosed blocker is `NO-GO`.

**Exit gate:** every row in [06-TEST-EVIDENCE-AND-RELEASE.md](06-TEST-EVIDENCE-AND-RELEASE.md) passes and the maintainer explicitly authorizes tagging/publishing.
