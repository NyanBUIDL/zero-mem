# V141 HANDOFF — DEF-012 wire corpus resolution into production (v1.4.1)

- **Ngày:** 2026-08-25 · **Repo:** zero-mem-v123-engineering @ `69c337b`+`3a40b7a` (master, local)
- **Authorization:** maintainer duyệt scope v1.4.1 = chỉ F1/DEF-012 (2026-08-25), phương án A
  (tường minh) + CLI kênh thiết lập chính + Grant CLI; XDG config file.

## Kiến trúc & luồng dữ liệu (sau fix)

```
Operator ──► zero-mem config set corpus-store-path <path>   (XDG ~/.config/zero-mem/config.json)
         ──► zero-mem grant add agent-bob --space quant-theory --read
                └─► GrantAdminService (trusted control plane)
                      ├─ project_grant_event → zm_access_grants (derived, rebuildable)
                      └─ canonical writer → grants-events.jsonl (append-only)

MCP client / hook ─► m6 dispatcher ─► _open_facade
                       ├─ AuthorizedReadService(store, profile,
                       │      grant_conn=store.conn,
                       │      corpus_conn=runtime.open_corpus_conn())   ← FIX
                       └─ space grant → resolve_space_members(corpus_conn)
                             → expand scope → _scope_allows authorizes event rows
```

Precedence cấu hình: **flag > env `ZM_M6_CORPUS_STORE_PATH` > XDG config > fail-closed**.
Chưa cấu hình → hành vi y hệt v1.4.0 (space grant non-authorizing).
Cấu hình sai → fail-loud `CorpusStoreConfigError` ngay lúc configure/set (không âm thầm).

## Changed paths

| File | Thay đổi |
|---|---|
| `src/integration/m6/runtime.py` | `corpus_store_path` param + `open_corpus_conn()` (mode=ro+query_only) + validation |
| `src/integration/m6/handlers.py` | `_open_facade` truyền `corpus_conn` |
| `src/integration/m7/injection_adapter.py` | `_make_service` truyền corpus_conn từ default runtime |
| `src/integration/zero_mem_runtime.py` | public read adapter wired tương tự |
| `src/integration/m7/m8_integration.py` | ghi chú fail-closed (không có runtime handle tại đó — không đổi behavior) |
| `zero_mem/userconfig.py` | MỚI — XDG config file (atomic write 0o600) |
| `zero_mem/commands_config_grant.py` | MỚI — `config set/unset/show` + `grant add/list/revoke` bọc `GrantAdminService` |
| `zero_mem/cli.py` | đăng ký subparsers + dispatch |
| `zero_mem/commands_doctor.py` | check `corpus_authorization` (+ hướng dẫn khi chưa set) |
| `tests/unit/test_v141_def012_wiring.py` | MỚI — 13 tests |
| `docs/defects/DEFECT-REGISTRY.md` | DEF-012 entry OPEN → FIXED |

## Ranh giới bảo vệ (có test)

- Grant CLI KHÔNG INSERT thẳng `zm_access_grants` — mọi grant là canonical event trước,
  projection rebuild lại được (`test_grant_persists_across_projection_rebuild`).
- Revoke = event tombstone (state=revoked), hiệu lực ngay khi resolve.
- `grant add --space X` dùng chính resolver: space không tồn tại trong corpus projection → từ chối.
- Connection corpus luôn read-only ở driver level (test DELETE phải fail).
- WRITE grant yêu cầu `--verification-ref` (kế thừa predicate sẵn có của admin service).

## Evidence (verbatim)

- RED trên tree v1.4.0: `10 failed, 3 passed` (`/tmp/red_run.txt`)
- GREEN sau fix: `tests/unit/test_v141_def012_wiring.py` → **13 passed** (`/tmp/green5.txt`)
- Full suite: **3515 passed, 6 skipped, 0 failed** (130.44s, Py venv `.venv-v124`) (`/tmp/full_v141.txt`)
- Commits: `69c337b` fix + review report · `3a40b7a` registry closure. Local only.

## Risks / Gaps

- `m8_integration` path chưa wired (thiếu runtime handle tại call site) — space grant vẫn
  fail-closed trên nhánh đó; nếu cần thì WP kế nối tiếp.
- Định danh grant = tên subject tự khai báo của client (không xác thực) — chấp nhận ở tier
  cá nhân, enterprise cần auth thật (đã ghi trong docs CLI).
- Multi-corpus: biến/config hiện single-path; thiết kế hàm đã list-ready cho v1.6.
- F2 (hardcode path trong test_v140_03) và F3 (hardcode version mcp_server) CHƯA sửa —
  ngoài scope v1.4.1 theo quyết định maintainer.

## Next

- Bump version 1.4.0 → 1.4.1 (cập nhật pins ở `release_common.py` + test assertions) →
  preflight → tag v1.4.1 LOCAL. Push/release chờ duyệt.
