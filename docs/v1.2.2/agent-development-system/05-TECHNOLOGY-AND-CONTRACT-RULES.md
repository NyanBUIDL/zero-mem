# 05 — Technology and contract rules

## Approved baseline technology

| Layer | Technology/constraint | Reason |
|---|---|---|
| Runtime | CPython `>=3.11,<3.14` | Existing package constraint in [`pyproject.toml`](../../../pyproject.toml). |
| Canonical store | Append-only JSONL, durable flush/fsync policy | Preserves event history and provenance. |
| Derived store | SQLite WAL and FTS5, read-only query connections | Queryable/rebuildable materialization. |
| Authorization | Existing access contracts and `AuthorizedReadService` | Single policy decision point. |
| Projection | Existing ingestion plus one bounded `ProjectionCoordinator` | Idempotent canonical-to-derived flow. |
| Transport | Typed local sidecar envelope, no implicit network listener | Bounded, local-first integration. |
| Hermes | Project-local plugin boundary, no Hermes-core patch | Preserves orchestration ownership/non-interference. |
| Testing | pytest, process fixtures, clean virtual environments, CI matrix | Executable evidence over self-report. |

No cloud service, hosted vector DB, LLM call, new embedding model, FastAPI/MCP server, or dependency upgrade is allowed in v1.2.2 unless a package explicitly proposes it and the maintainer approves it. The current objective is completion, not technology expansion.

## Required public read contract

Each standard method accepts a mapping/dataclass request with:

- explicit requesting identity and requested project/profile scope;
- bounded `limit` and cursor where pagination applies;
- an explicit consistency mode (`require_current`, `bounded_wait`, or `allow_stale`);
- a finite deadline;
- no caller-supplied filesystem path, SQL, raw filter expression or authorization grant.

Each response contains:

```text
capability, status, reason_code, items, provenance, freshness, diagnostics
```

- `items` is present only for authorized, safe-to-return material.
- `provenance` identifies canonical event(s) and derived query version without exposing unrelated scope.
- `freshness` contains canonical/projected sequence or an explicitly unavailable state.
- `diagnostics` is bounded and sanitized; it is never a serialized exception.

## Freshness algorithm

1. Read canonical watermark and derived checkpoint under the platform coordination contract.
2. If policy/grant fails, return `POLICY_DENIED` **before** this step can reveal candidate data.
3. If derived state is missing/corrupt, return `UNAVAILABLE` or trigger approved bounded rebuild; never return it as current.
4. If `projected_sequence >= required_canonical_sequence`, read derived state and return `READY`/`EMPTY`.
5. For `bounded_wait`, wait only until the request deadline for the coordinator watermark; then return `READY`, `EMPTY`, or `STALE`.
6. For `allow_stale`, return a marked `STALE` result with both sequences and no claim of currentness.

## Portability contract

The domain code uses a platform service, never raw `fcntl`, `/proc`, `O_DIRECTORY`, `O_NOFOLLOW`, `LockFileEx`, or OS-specific errno values. Platform adapters may use those primitives internally and normalize outcomes.

| Requirement | Linux | macOS | Windows |
|---|---|---|---|
| Exclusive/shared process lock | POSIX backend | POSIX backend, tested | Win32 handle backend, tested |
| Symlink/reparse protection | no-follow/descriptor checks | no-follow/descriptor checks | reparse-point/handle checks |
| Atomic promotion | same-volume atomic replace + fsync rules | same | documented Win32 replace/rename rule |
| Test state | qualified only after CI pass | qualified only after CI pass | qualified only after CI pass |

If exact safety semantics differ, document the supported threat model and return a typed safe failure; do not silently degrade to ordinary `Path.open()` or an unlocked write.
