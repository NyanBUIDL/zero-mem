# V141-R2–R4 REMEDIATION HANDOFF — DEF-013…016 (v1.4.1)

**Ngày:** 2026-08-25 · **Repo:** zero-mem-v123-engineering @ master (local)
**Authorization:** GATE-R0 APPROVED + GATE-R1 APPROVED (Option A). Maintainer ủy quyền
quyết định gate A/B theo tiêu chí tốt nhất cho hệ thống trước khi nghỉ (2026-08-25);
publish remote vẫn mặc định local-only.

## Observed (trạng thái trước)

- Core fix DEF-012 (`69c337b`/`3a40b7a`) đúng và verify được: focused 13/13, full suite
  tái lập độc lập.
- Nhưng deep review lần 2 phát hiện: grant CLI mới là bề mặt chết không nối đường ủy quyền
  production (nguồn sự thật kép — DEF-013); connection lifecycle leak (DEF-014); hygiene
  bundle + doctor PASS sai hướng (DEF-015); acceptance test không đi qua `_open_facade`
  thật + evidence lệch số (DEF-016).
- Version bump 1.4.1 đã tồn tại sẵn ở commit `c3e721e` (version.py + manifest guard +
  pkg pins + mcp_server import version) — không cần bump thêm.

## Changed (tree cuối)

| File | Thay đổi |
|---|---|
| `zero_mem/cli.py` | Gỡ wiring subcommand `grant` (giữ `config`) — DEF-013 |
| `zero_mem/commands_config_grant.py` | Thu về config-only; bỏ hack `sqlite3_error()`, dead code, naming sai — DEF-013/015 |
| `src/access/authorized_read.py` | `close()` giờ đóng cả `_corpus_conn` (guard sqlite3.Error) — DEF-014 |
| `zero_mem/commands_doctor.py` | `corpus_authorization`: WARN unconfigured / FAIL stale / PASS usable (verify LIVE) — DEF-015 |
| `tests/unit/test_v141_r2_remediation.py` | MỚI — 9 tests RED-first cho DEF-013/014/015/016 |
| `tests/unit/test_v141_def012_wiring.py` | Gỡ `TestGrantCli` (formally superseded, ghi chú lý do trong file) |
| `docs/v1.4.1/{ROADMAP,CHECKLIST,ADR-V141-01}.md` | MỚI — lộ trình remediation + ADR CHỌN A |
| `docs/defects/DEFECT-REGISTRY.md` | Đăng ký + đóng DEF-013…016 với evidence verbatim |
| `project-state.yaml` | Overlay V141 (status RELEASE_READY_LOCAL) |

## Verified (verbatim)

```
RED (trước fix):   tests/unit/test_v141_r2_remediation.py → 4 failed, 5 passed
GREEN (sau fix):   tests/unit/test_v141_r2_remediation.py → 9 passed (0.27s)
Wiring+remediation: test_v141_def012_wiring + test_v141_r2_remediation → 19 passed
Focused regression: test_m5_authorized_read + test_m6_memory_tools +
                    test_v122_public_reads → 90 passed
                    test_v140_02_ks_resolution + crash_durability → 11 passed
FULL SUITE ×2 liên tiếp trên tree cuối:
  run1: 3521 passed, 6 skipped in 87.43s (/tmp/zm_full_v141b_run1.txt)
  run2: 3521 passed, 6 skipped in 89.30s (/tmp/zm_full_v141b_run2.txt)
  (.venv-v124, Python 3.11.16, HOME=/tmp/zm-test-home, -p no:cacheprovider)
Giải trình số: 3515 (+9 test remediation −3 test superseded) = 3521 ✓
```

## Kiến trúc & data flow sau remediation

```
Operator ──► zero-mem config set corpus-store-path <path>   (XDG, atomic 0600)
                └─ chỉ trỏ ĐƯỜNG DẪN corpus-derived store; KHÔNG phải nguồn sự thật

MCP/hook ──► m6 dispatcher ──► _open_facade (THẬT, có acceptance test end-to-end)
              ├─ AuthorizedReadService(store, profile, grant_conn=store.conn,
              │                        corpus_conn=runtime.open_corpus_conn())
              ├─ space grant → resolve_space_members(corpus_conn) → expand scope
              └─ svc.close() đóng cả store conn lẫn corpus_conn (không rò fd)

Grants: quản trị QUA CONTROL-PLANE nội bộ (GrantAdminService) — duy nhất một nguồn
sự thật (canonical JSONL → derived projection). Không có admin surface song song.
Doctor: corpus_authorization phản ánh trạng thái LIVE (WARN/FAIL/PASS có ý nghĩa).
```

## Risk

- `m8_integration` nhánh `_optional_relation_distances` vẫn fail-closed (không có runtime
  handle tại call site) — documented limitation, giữ nguyên theo scope.
- Grant subject là self-declared identity (tier cá nhân chấp nhận; enterprise cần auth thật
  — cụm DEF-010/011 backlog v1.5+).
- Admin CLI đa-agent (phương án B của ADR-V141-01) chưa làm — backlog v1.5+, làm khi có
  thiết kế concurrency/canonical-layout đầy đủ.

## Next

1. Bạn review tree cuối + các gate files.
2. Nếu OK: tag `v1.4.1` local (mutation riêng, tôi thực hiện khi bạn gõ lệnh).
3. Push/GH Release: mặc định KHÔNG làm nếu bạn không chỉ thị.
