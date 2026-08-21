# Master Plan v1.2.4

## Release objective

v1.2.4 hoàn tất khi người dùng có thể hiểu và kiểm chứng đúng chuỗi sau:

```text
message/tool/task/skill/subagent event
  → receipt có semantic type + occurrence-safe ID
  → canonical append
  → projection watermark/freshness
  → authorized read theo runtime mode
  → provenance-bearing result
  → HITL correction khi cần
```

## Dependency graph

```text
V124-01 Semantic capture [VERIFIED]
          │
          ▼
V124-02 Runtime modes
          │
          ▼
V124-03 Storage composition + freshness
          │
          ▼
V124-04 Hermes pillars + HITL + Skills
          │
          ▼
V124-05 Cross-platform + release qualification
```

## Work packages

### V124-01 — Semantic capture

**Trạng thái:** `IMPLEMENTED_VERIFIED`
**Commit:** `018407c`

- `pre_llm_call` → `user_statement`.
- `post_llm_call` → `assistant_claim`.
- Tool, skill lifecycle, subagent và session reset có hook quan sát riêng.
- Host occurrence identity tạo ID ổn định cho retry; event không đủ identity nhận UUID duy nhất.
- Không nhân đôi `conversation_history` trong mỗi message event.

**Gate đã đạt:** 103 focused unit/integration tests; compileall; `git diff --check`.

### V124-02 — Explicit runtime modes

**Trạng thái:** `IMPLEMENTED_VERIFIED`
**Commit:** `V124-02` (see work-packages/V124-02-runtime-modes)

- Explicit `off`/`observe`/`assist`/`inject` modes govern writer-open, capture, read-tool and injection-hook registration.
- `RuntimeMode` enum + `capability_matrix()` expose the exact truth table; each cell asserted directly.
- `off` opens no writer/derived store; `observe` captures only (no injection); `assist` adds read tools; `inject` adds the controlled `pre_llm_call` hook.
- Backward migration: `enabled=False` → `off`; missing mode defaults to `assist`.
- `ZERO_MEM_MODE` env selects the mode; invalid value fails closed to `off`.

**Gate đã đạt:** 39 unit mode tests + 3 host-composition tests (assist/observe/inject) + related regression 106 passed; compileall; `git diff --check`.

| Mode | Capture | Explicit read | Auto injection |
|---|---:|---:|---:|
| `off` | No | No | No |
| `observe` | Yes | No | No |
| `assist` | Yes | Yes | No |
| `inject` | Yes | Yes | Controlled |

**Thứ tự:** config schema → backward migration từ `observation_only` → composition gate → CLI/status → negative tests.

**Exit gate:** `observe` không tạo `InjectionAdapter`; `off` không mở writer/DB; mỗi mode báo đúng capability đang hoạt động.

### V124-03 — Single storage topology and truthful freshness

- Tạo một runtime composition root sở hữu canonical writer, projection coordinator, derived DB và authorized read service.
- Loại bỏ cấu hình cho phép capture ghi A nhưng read/injection đọc B.
- Health phải công bố tối thiểu: `capture_enabled`, `last_canonical_sequence`, `last_projected_sequence`, `lag`, `projection_status`, `read_store_identity`, `injection_enabled`.
- `sync()` chỉ trả current khi derived watermark bắt kịp canonical watermark.

**Exit gate:** capture → project → read → shutdown → restart E2E dùng một topology; projection failure vẫn giữ capture receipt và trả `STALE/UNAVAILABLE` trung thực.

### V124-04 — Hermes pillars, HITL and Agent Skills

| Hermes pillar | Zero-Mem trách nhiệm | Không được làm |
|---|---|---|
| Memory/FTS5 | Canonical evidence, derived retrieval, freshness | Thay thế Hermes orchestration |
| Skills | Observe lifecycle/name/action/provenance | Tự sửa `SKILL.md` |
| Soul | Ghi nhận reference nếu host cung cấp | Ghi đè SOUL/persona |
| Crons | Capture task/run/result provenance | Tự tạo/chạy cron ngoài Hermes |
| Self-improving loop | Cung cấp evidence + verified outcomes | Tự kích hoạt hành động không review |

HITL tối thiểu: inspect → propose correction/supersession/delete-request → preview effect → explicit confirm → append linked control event → rebuild projection.

**Exit gate:** không silent overwrite; denial không rò candidate; Skill fixture vẫn đúng chuẩn sau mọi lifecycle capture.

### V124-05 — Cross-platform and release qualification

- Thay mọi POSIX-only assumption còn lọt ra khỏi platform backend.
- Kiểm tra Windows/Linux/macOS, CPython 3.11–3.13.
- Wheel/sdist clean-install và Hermes smoke test từ candidate SHA.
- Evidence manifest chứa SHA, commands, environment, logs, checksums và support matrix.

**Exit gate:** không còn unconditional skip cho core path; full suite, security, concurrency, benchmark, packaging và E2E đạt trên mọi platform được công bố.

## Parallelism policy

| Có thể song song | Phải tuần tự |
|---|---|
| Viết fixture Windows/Linux/macOS sau khi contract platform đã khóa | V124-02 trước V124-03 |
| Viết docs/runbook và negative tests cho package đang active | Schema/config trước runtime composition |
| Packaging smoke scripts theo từng OS | Canonical append trước projection/read assertion |
| Review Agent Skills fixture độc lập với SOUL audit | V124-03 trước HITL integration |

Không merge các nhánh song song nếu chúng thay cùng public contract hoặc cùng composition root mà chưa reconciliation review.
