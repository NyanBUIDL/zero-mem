# 03 — Mandatory production E2E contract

All scenarios run against a fresh temporary runtime root. Fixture events contain only safe synthetic content.

| Scenario | Direct API | Sidecar | Hermes host | Required assertion |
|---|---|---|---|---|
| Authorized search | `zero_mem` public factory | advertised `search` capability | registered read tool | Same normalized items/provenance/freshness. |
| Trace/state/decision reads | all three methods | all three names | all three tools where supported | Real derived data, no unavailable stub. |
| Denied scope | denied public request | denied transport request | denied host request | No items, count, identifier, snippet or source metadata. |
| Projection lag | `require_current`, `bounded_wait`, `allow_stale` | same | same | Typed current/stale policy, finite deadline. |
| Derived loss | delete/corrupt derived fixture | same request after rebuild | same after restart | JSONL bytes unchanged; derived rebuilt; no false current claim. |
| Capture lifecycle | capture fixture then wait/flush | capture through supported path | capture hook | Durable receipt precedes projection; restart sees data. |
| Disabled lifecycle | disabled composition | disabled sidecar | disabled host | No writer, DB, query or registration side effect. |
| Restart | close/reopen all owners | start/stop/start | register/shutdown/re-register | No duplicate writer/worker/tool; same semantic response. |

## Result normalizer

Tests compare only public fields:

```text
capability, status, reason_code, items, provenance, freshness
```

They must not compare internal database paths, object addresses, raw exceptions or timing exact values. They must assert bounded maximum time for deadline/overload paths.

## Platform additions

Every capture/recovery scenario is rerun on Linux, Windows and macOS. Link/reparse tests are separate from normal capture tests: inability to create a Windows symlink must not prevent validation of ordinary JSONL capture.
