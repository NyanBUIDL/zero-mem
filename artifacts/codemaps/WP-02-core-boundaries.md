# WP-02 Core Boundaries CodeMap

## Observed

The durable tree had no current WP-02 packet or runtime facade. The planning-ref WP-02 contract was read-only recovered from commit `2f1763f1335326b83bf90f263cada5c3715f21eb` and reconciled into the task packet.

## Production map

`Hermes PluginContext.register_hook` → `RegistrationAdapter.register` → callback → payload mapping → `_CaptureWriter` → `ZeroMemClient.capture` → existing `adapt_mapped_event`/store.

Generic callers use `zero_mem.ZeroMemClient` directly. `zero_mem/core.py` contains no Hermes, transport, storage, retrieval, or authorization imports.

## Changed owners

- `zero_mem/core.py`: immutable `CoreConfig`, typed `CaptureResult`, writer protocol, and client-owned `ZeroMemClient`.
- `zero_mem/__init__.py`: public additive exports.
- `src/integration/hermes_registration.py`: adapter translates into the public client boundary while retaining hook mapping and capture ownership.

## Boundaries preserved

Storage, retrieval, authorization, transport, and Hermes payload semantics remain in their existing owners. No canonical data, dependency metadata, Product Memory, or Hermes installation was changed.

## Graphify corroboration

Post-integration code-only Graphify extraction on `/home/lenovo/Hermes Workspace/zero-mem-v1.1` found `zero_mem/core.py` imported by the Hermes registration adapter, public package, focused tests, and benchmark. Graphify remains disposable evidence and did not enter the repository.
