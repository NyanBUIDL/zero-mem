# Zero-Mem — Chỉ mục tài liệu

`docs/` chứa thiết kế, kế hoạch, quyết định, hướng dẫn vận hành và chỉ mục bằng
chứng. Canonical user data vẫn là JSONL; tài liệu và SQLite không thay thế nguồn
sự thật đó.

## Bắt đầu ở đâu

- Patch đang qualification: [`v1.6.1/EVIDENCE.md`](v1.6.1/EVIDENCE.md) và
  [`releases/RELEASE-NOTES-v1.6.1.md`](releases/RELEASE-NOTES-v1.6.1.md).
- Kiến trúc release hiện hành: [`v1.6.0/`](v1.6.0/README.md).
- Kiến trúc xuyên phiên bản: [`architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md).
- Quy tắc Git/GitHub: [`governance/GITHUB-POLICY.md`](governance/GITHUB-POLICY.md).
- Defect registry append-only: [`defects/DEFECT-REGISTRY.md`](defects/DEFECT-REGISTRY.md).
- Release notes: [`releases/`](releases/).
- Acceptance milestone lịch sử: [`acceptance/`](acceptance/).

## Cấu trúc chuẩn cho minor/major version

Mỗi minor/major version mới dùng tên đầy đủ `docs/vX.Y.Z/` và tối thiểu có:

```text
README.md
ROADMAP.md
ARCHITECTURE.md
TECH_STACK.md
DEVELOPMENT.md
EVIDENCE.md
decisions/
work-packages/
evidence/
probes/
```

Patch release nhỏ có thể dùng release notes + defect registry + overlay trong
`project-state.yaml` nếu không mở work-package kiến trúc mới.

## Bản đồ phiên bản

| Đường dẫn | Trạng thái | Ghi chú |
|---|---|---|
| [`v1.6.1/`](v1.6.1/EVIDENCE.md) | **Active patch candidate** | Audit remediation; exact-commit remote 9-cell qualification pending |
| [`v1.6.0/`](v1.6.0/README.md) | **Released / immutable** | Tag và GitHub Release tại source SHA `267fd9ae830eff41aeaf85cbfbd41f38c03849a6` |
| [`v1.6/`](v1.6/README.md) | Historical staging | Proposal, remediation record và probe ban đầu; đã được index từ `v1.6.0/` |
| [`v1.5/`](v1.5/) | Historical v1.5.0 | Enterprise authorization work |
| [`v1.5.1/`](v1.5.1/) | Historical patch docs | Qualification/remediation v1.5.1 |
| [`v1.4/`](v1.4/) | Historical v1.4.0 | Tên cũ thiếu patch component; không rename để giữ link/evidence |
| [`v1.4.1/`](v1.4.1/) | Historical patch docs | Remediation v1.4.1 |
| [`v1.3.0/`](v1.3.0/)–[`v1.3.2/`](v1.3.2/) | Released history | Các version folder đầy đủ/tiệm cận chuẩn |
| `v1.1.0/`–`v1.2.4/` | Released history | Cấu trúc cũ được giữ nguyên để audit |

Tên `v1.4/`, `v1.5/`, `v1.6/` là di sản. Không đổi tên hoặc di chuyển vì có thể
làm hỏng liên kết và checksum lịch sử. Từ v1.6.0 trở đi dùng `vX.Y.Z` nhất quán.

## Evidence authority

Chỉ mục kiến trúc/Multi-KS chính thức của v1.6.0 là
[`v1.6.0/EVIDENCE.md`](v1.6.0/EVIDENCE.md); patch overlay hiện tại nằm tại
[`v1.6.1/EVIDENCE.md`](v1.6.1/EVIDENCE.md). Evidence lịch sử ở `audit/`,
`artifacts/evidence/` và `docs/acceptance/` không bị sửa hoặc di chuyển.

## Quy tắc bảo toàn lịch sử

- Không sửa nội dung evidence đã nghiệm thu; nếu kết luận thay đổi, thêm record
  supersede/addendum mới.
- Không coi `implementation-plan.json` là trạng thái hiện hành; file đó đã đóng
  băng. Trạng thái máy hiện hành nằm trong `project-state.yaml`.
- Không tuyên bố release chỉ từ tài liệu hoặc local tests; tag/publication cần
  qualification trên đúng release SHA.
