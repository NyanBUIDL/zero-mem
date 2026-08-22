# v1.3.0 — Kiến trúc

> Tạo từ `docs/VERSION-TEMPLATE.md` (mục ARCHITECTURE). Điền trước khi code.
> Kiến trúc nền tảng vẫn theo `docs/architecture/ARCHITECTURE.md` (M0+) và `docs/v1.2.4/ARCHITECTURE.md`;
> ghi ở đây chỉ những quyết định RIÊNG của v1.3.

## Component topology
<diagram text — bắt đầu từ v1.2.4 topology, đánh dấu thứ sẽ đổi>

## Ownership boundaries
| Component | Owner | State authority |

## Interaction protocols
| Boundary | Protocol | Quyết định |

## State and failure semantics
<CURRENT/STALE/UNAVAILABLE/DENIED/EMPTY — giữ nguyên chuẩn v1.2.4 trừ khi có lý do>

## Quyết định kiến trúc version này
- ADR/SPEC-AMENDMENT mới (nếu có): link.
- Các P1 findings dự kiến xử lý: FTS-AND fallback, state-as-primary, knowledge-space filter, temporal read integration.
