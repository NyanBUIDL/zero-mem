# WP-25 Technical Design

## Technologies and dependencies

Python 3.11 standard-library `dataclasses`, `pathlib`, and typing. Reuse `BridgeConfig` path validation, `CaptureStoreConfig`, and `JsonlCaptureStore`. No new dependency.

## Data structures

```python
@dataclass(frozen=True)
class RuntimeConfig:
    capture_root: Path
    enabled: bool = True

@dataclass(frozen=True)
class RuntimeHealth:
    status: Literal["OPEN", "CLOSED"]
    reason_code: str | None = None
```

`ZeroMemRuntime` holds one private writer reference, immutable configuration, and a closed flag guarded by the runtime's owning thread. It does not hold request, grant, retrieval, or projection state.

## Composition and lifecycle algorithm

```text
validated RuntimeConfig
  → if disabled: runtime with no writer
  → if enabled: create CaptureStoreConfig(root) and JsonlCaptureStore exactly once
  → expose writer while OPEN
  → close(): close owned writer once, clear access, mark CLOSED
  → future writer access/append: RuntimeError
```

An explicitly injected `store` is accepted only for tests and controlled adapters that already own a validated store; the runtime still owns its lifecycle after construction. Production construction uses the configured root and opens `JsonlCaptureStore` in the runtime.

## Interfaces

- `ZeroMemRuntime.open(config: RuntimeConfig, *, store: CaptureStore | None = None) -> ZeroMemRuntime`
- `ZeroMemRuntime.writer` property → `CaptureStore`
- `ZeroMemRuntime.health() -> RuntimeHealth`
- `ZeroMemRuntime.close() -> None`
- Existing `parse_zero_mem_enabled`, `configure`, `new_runtime`, and `get_runtime` remain compatibility APIs for the master boolean only.

## Configuration

`capture_root` must be an absolute path already resolved by the validated configuration boundary. Explicit roots inside the real home are rejected; relative/cwd-inferred roots are rejected. No cwd, repository, home, or environment path inference occurs in runtime.

## Concurrency and locking

The runtime is process-local composition ownership. Cross-process canonical append safety remains in `JsonlCaptureStore`'s existing `fcntl.flock`. WP-25 adds no polling, queue, retry, lease, or background worker; those belong to WP-26.

## Error/status vocabulary

- `OPEN`
- `CLOSED`
- `ZERO_MEM_DISABLED`
- `RUNTIME_CLOSED`
- `RUNTIME_WRITER_UNAVAILABLE`

Construction errors from the underlying store propagate as sanitized `CaptureRejected` errors. Shutdown is idempotent and does not swallow state transition errors.

## Security and data integrity

The runtime never writes derived state, never rewrites canonical JSONL, never accepts arbitrary paths from request payloads, and never logs event payloads or credentials. Adapters consume the runtime writer and do not instantiate `JsonlCaptureStore`.

## Compatibility

`RegistrationAdapter._observe` requires both its instance runtime and the current process master gate to be enabled. The master gate remains restart-scoped in supported operation; the additional check fails closed if test/composition code changes the compatibility state in-process. Existing injected-store adapter tests remain supported through `ZeroMemRuntime.open(..., store=...)`. No public Zero-Mem API or schema changes are introduced.

## Complexity

Runtime creation is O(1) plus the existing store's canonical replay cost. Close is O(1) beyond the store close. No unbounded memory or background task is introduced by WP-25.

## Prohibited approaches

- module-global mutable writer;
- adapter-local path inference or store construction;
- background projection worker;
- infinite retry;
- SQLite or derived-state mutation;
- hidden fallback to another root.

## Open decisions

None blocking. Projection ownership and derived lifecycle are WP-26 decisions.
