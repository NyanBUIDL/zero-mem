# Zero-Mem v1.6.0 — Multi-Knowledge-Space

**Trạng thái:** `RELEASE_SOURCE_REMOTE_QUALIFIED`

**Branch:** `v160/multi-ks` · **Package:** `1.6.0` · **Schema derived:** `13`

v1.6.0 cho phép một canonical event thuộc nhiều Knowledge Space. C1–C10 đã
hoàn thành; exact wizard SHA `68bdf29` đã đạt 9/9 CI trên Ubuntu/Windows/macOS ×
Python 3.11–3.13. Tag và GitHub Release là publication layer bất biến của source
đã qualification.

## Điều hướng

- [`ROADMAP.md`](ROADMAP.md): scope, trạng thái C1–C10 và điều kiện release.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): canonical/derived boundary và Multi-KS data flow.
- [`TECH_STACK.md`](TECH_STACK.md): stack và quyết định dependency.
- [`DEVELOPMENT.md`](DEVELOPMENT.md): quy trình phát triển, test và evidence.
- [`MODULE-MAP.md`](MODULE-MAP.md): vai trò `zero_mem/`, `src/` và các domain.
- [`ONBOARDING.md`](ONBOARDING.md): wizard, Project ID/Profile ID và automation.
- [`EVIDENCE.md`](EVIDENCE.md): chỉ mục evidence chính thức.
- [`decisions/ADR-V160-01-MULTI-KS.md`](decisions/ADR-V160-01-MULTI-KS.md): quyết định đã áp dụng.
- [`work-packages/`](work-packages/): C01–C10 và DX01.
- [`evidence/`](evidence/): evidence mới và pointer tới evidence lịch sử.

## Semantics cốt lõi

- Event mới có thể mang `knowledge_space_ids: list[str]`; event cũ với
  `knowledge_space_id` vẫn đọc được.
- `zm_event_spaces` là junction derived và là ranh giới cho structured/FTS
  authorization; request nhiều KS dùng UNION, grant cần giao với membership row.
- `zm_meta.knowledge_space_id` giữ phần tử đầu tiên làm PRIMARY-KS cho tương thích,
  graph và temporal; không thay thế junction.
- Event không có KS không tự nhận quyền từ space grant.
- Corpus unit vẫn singular trong v1.6.0.

## Authority và lịch sử

`project-state.yaml` là machine state hiện hành. Proposal, remediation record và
probe ban đầu vẫn ở [`../v1.6/`](../v1.6/README.md); các file đó không bị di
chuyển. Mọi evidence cũ được truy cập qua [`EVIDENCE.md`](EVIDENCE.md).
