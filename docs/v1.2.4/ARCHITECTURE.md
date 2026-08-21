# Architecture v1.2.4

## Component topology

```text
User
 │ message / correction approval
 ▼
Hermes Master Agent ───── spawns ─────► Hermes Subagents
 │ hooks/tools                              │ lifecycle/result hooks
 └──────────────────┬───────────────────────┘
                    ▼
           Hermes registration adapter
                    │ normalized observation
                    ▼
       payload mapping + redaction + validation
                    │ append receipt
                    ▼
          canonical JSONL event stream
                    │ bounded async notification
                    ▼
           ProjectionCoordinator
                    │
                    ▼
             SQLite + FTS5
                    │
          authorization-before-read
                    ▼
       public adapter / local sidecar tools
                    │ typed result + provenance
                    ▼
              Hermes final action
```

## Ownership boundaries

| Component | Owner | State authority |
|---|---|---|
| Orchestration, SOUL, Skills, Crons, final response | Hermes | Hermes configuration/runtime |
| Raw sanitized event history | Zero-Mem capture | Canonical JSONL |
| Search/index/materialized relations | Zero-Mem projection | Derived SQLite/FTS5 |
| Read authorization | Zero-Mem access layer | Grants/policy derived from canonical records |
| User correction decision | Human operator | Explicit reviewed control event |
| Obsidian workspace | Projection layer | Rebuildable human view, never canonical |

## Interaction protocols

v1.2.4 dùng giao tiếp local/in-process để giảm cost và failure surface.

| Boundary | Protocol hiện tại/mục tiêu v1.2.4 | Quyết định |
|---|---|---|
| Hermes → capture | Python hook callbacks, immutable payload observation | Giữ |
| Public caller → Zero-Mem | Typed Python API | Giữ canonical contract |
| Hermes → read | Registered read tools over authorized adapter | Hoàn thiện theo mode |
| Sidecar façade | Local bounded request/response envelope | Giữ; không nhân đôi auth logic |
| Projection notification | In-process bounded queue/coordinator | Giữ; JSONL vẫn là durability boundary |
| REST/gRPC/JSON-RPC | Không cần cho v1.2.4 | Hoãn; chỉ thêm khi có remote-process requirement |
| Event bus ngoài tiến trình | Không dùng | Tránh tăng dependency/cost |

## State and failure semantics

```text
append rejected ─────────────► capture failure
append durable + project ok ─► CURRENT
append durable + project lag ► STALE (capture vẫn success)
derived missing/corrupt ─────► UNAVAILABLE + recovery path
authorization denied ────────► DENIED, không discovery leakage
no authorized evidence ──────► EMPTY, host không được diễn giải thành fact
```

## Async constraints

- Queue phải bounded; saturation có reason code và metric.
- Event ID + canonical sequence là idempotency/correlation boundary.
- Shutdown phải drain hoặc ghi rõ unprojected lag; không được mất canonical append.
- Restart phải rebuild/resume từ watermark, không tạo duplicate writer/worker.
- Health đọc state snapshot; không được tự tạo side effect để “làm xanh” status.

## User flow

```text
OBSERVE: User → Hermes → capture receipt → JSONL → projection
ASSIST:  OBSERVE + Hermes chủ động gọi read tool
INJECT:  ASSIST + controlled pre-LLM injection gate
HITL:    Inspect → proposal → preview → confirm → linked event
```
