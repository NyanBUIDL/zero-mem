# Current Module Map

## Hai package Python

| Cây | Vai trò | Quy tắc phụ thuộc |
|---|---|---|
| `zero_mem/` | Public facade, CLI, config, setup/doctor/backup/upgrade và lifecycle | Có thể gọi implementation nội bộ; là bề mặt hỗ trợ cho người dùng |
| `src/` | Internal implementation theo domain: capture, storage, retrieval, access, projection, integration, corpus | Không được xem là public compatibility promise dù được đóng gói để runtime dùng |

Tên `src` đồng thời là Python package do lịch sử kiến trúc. Không tạo thêm một
package `src` khác hoặc chuyển public API vào đó. Consumer bên ngoài nên import
`zero_mem`, không phụ thuộc đường dẫn `src.*` nếu không phải integration nội bộ.

## Domain chính trong `src/`

- `capture/`, `storage/`: envelope, canonical append, ingest, migration.
- `retrieval/`, `access/`: structured/FTS query và authorization-before-retrieval.
- `projection/`, `m8/`: note projection, graph và temporal consumers.
- `corpus/`: registry/blob/unit retrieval với KS singular ở v1.6.0.
- `integration/`: Hermes/public adapters và non-interference boundary.

## Root management map

| Path | Vai trò |
|---|---|
| `project-state.yaml` | Machine state hiện hành; nhận overlay mới |
| `implementation-plan.json` | Historical frozen record; không cập nhật |
| `benchmark-plan.json` | Hợp đồng benchmark M0 ban đầu |
| `Review V1.1/` | Review lịch sử, giữ để audit |
| `docs/v1.6.0/EVIDENCE.md` | Evidence index chính thức của candidate hiện tại |
