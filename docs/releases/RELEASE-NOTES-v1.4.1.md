# RELEASE-NOTES — Zero-Mem v1.4.1

**Trạng thái:** RELEASE_READY_LOCAL (tag/push chờ duyệt riêng)

## Đây là bản hotfix gì

v1.4.1 sửa lỗi wiring của DEF-004 Option B: lớp phân giải knowledge-space có ở library
nhưng chưa được nối vào bất kỳ điểm dựng service production nào, nên space grant trên
event path vẫn non-authorizing khi runtime dù test pass. v1.4.1 nối nó vào 3 đường
production và kèm remediation các defect phát hiện trong quá trình review.

## Nội dung

### Core fix (DEF-012)
- `M6Runtime.corpus_store_path`: cấu hình corpus-derived store cho lớp phân giải.
  Precedence: flag > env `ZM_M6_CORPUS_STORE_PATH` > XDG config file > fail-closed.
  Path sai → fail-loud `CorpusStoreConfigError` ngay lúc configure.
- Wire `corpus_conn` (read-only nghiêm ngặt) vào `_open_facade`, `injection_adapter`,
  `zero_mem_runtime` public-read adapter. Không cấu hình → hành vi y hệt v1.4.0.
- CLI `zero-mem config set/unset/show corpus-store-path` (XDG file, atomic write 0600).

### Remediation (DEF-013…016)
- **Thu hồi `zero-mem grant` admin surface** (GATE-R1 Option A): store của nó tách biệt
  đường ủy quyền production — grants tạo qua đó không bao giờ hiệu lực và tạo nguồn sự
  thật thứ hai. Quản trị grant tiếp tục qua control-plane nội bộ; admin CLI đa-agent là
  backlog v1.5+ (ADR-V141-01).
- Connection lifecycle: `AuthorizedReadService.close()` đóng cả corpus connection
  (tránh tích tụ fd trên sidecar chạy dài).
- Doctor `corpus_authorization` trung thực: unconfigured=WARN, stale/unreadable=FAIL,
  usable=PASS (verify lúc chạy, không PASS chỉ vì config tồn tại).
- Acceptance test mới đi qua handler facade thật (`_open_facade`) end-to-end.

## Không thay đổi

- Schema/migration: không đổi. JSONL canonical append-only: không đổi.
- Behavior fail-closed: không nới lỏng. m8_integration nhánh relation-distances vẫn
  fail-closed (documented limitation).

## Chất lượng

- Full suite: **3521 passed, 6 skipped, 0 failed**, tái lập ×2 chạy liên tiếp
  (Python 3.11, isolated HOME). RED-first cho mọi defect fix.
- Chi tiết: `docs/defects/DEFECT-REGISTRY.md`, `artifacts/handoffs/V141-R2-R4-REMEDIATION-HANDOFF.md`.
