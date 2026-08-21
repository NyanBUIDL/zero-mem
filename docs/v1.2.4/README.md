# Zero-Mem v1.2.4 — Contract-Correction Development System

**Branch:** `release/v1.2.4`
**Release status:** `IN_PROGRESS`
**Purpose:** sửa sự lệch nhau giữa hành vi runtime, kỳ vọng người dùng và tài liệu thống nhất trước khi mở rộng v1.3.

Thư mục này là cổng điều hành duy nhất cho công việc v1.2.4. Nó không thay thế tài liệu quyền lực [`Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`](../../Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx), [`AGENTS.md`](../../AGENTS.md), ADR-009 hoặc bằng chứng kiểm thử.

## Thứ tự đọc bắt buộc

1. [`00-START-HERE.md`](00-START-HERE.md)
2. [`MASTER_PLAN.md`](MASTER_PLAN.md)
3. [`ARCHITECTURE.md`](ARCHITECTURE.md)
4. [`CODE_TRACEABILITY.md`](CODE_TRACEABILITY.md)
5. [`AGENT_PROTOCOL.md`](AGENT_PROTOCOL.md)
6. [`TECH_STACK.md`](TECH_STACK.md)
7. [`VALIDATION_SPEC.md`](VALIDATION_SPEC.md)
8. [`WORK_PACKAGE_TEMPLATE.md`](WORK_PACKAGE_TEMPLATE.md) khi tạo work package mới

## Trạng thái gói công việc

| Gói | Nội dung | Trạng thái |
|---|---|---|
| V124-01 | Capture message có ngữ nghĩa và event identity an toàn | `IMPLEMENTED_VERIFIED` |
| V124-02 | Runtime mode `off/observe/assist/inject` | `APPROVED` |
| V124-03 | Một storage topology và freshness trung thực | `APPROVED` |
| V124-04 | Hermes pillars, HITL và Agent Skills boundary | `APPROVED` |
| V124-05 | Đa nền tảng, packaging, E2E và release qualification | `APPROVED` |

`APPROVED` chỉ cho phép bắt đầu theo đúng dependency và protocol; không có nghĩa là đã triển khai.
