# DX01 — Guided wizard/onboarding

## Mục tiêu

Cung cấp một entry point đầu tiên dễ dùng nhưng vẫn giữ boundary an toàn của
`setup`, Hermes integration và `doctor`.

## Contract

- `zero-mem wizard` hỗ trợ interactive onboarding.
- Automation dùng `--non-interactive` với lựa chọn Hermes tường minh.
- Project/profile ID luôn đi theo cặp và không được suy luận.
- Standalone là trạng thái hợp lệ; Hermes không phải dependency.
- Validation request diễn ra trước mutation.
- Rerun giữ integration hợp lệ hiện có; `--skip-hermes` không mang nghĩa remove.
- Report JSON không chứa ID, secret hoặc operator path.
- Kết thúc bằng doctor; exit code chỉ xanh khi doctor `READY`.

## Files

- `zero_mem/commands_wizard.py`
- `zero_mem/cli.py`
- `tests/unit/test_v160_wizard_onboarding.py`
- `docs/v1.6.0/ONBOARDING.md`

## Rollback

Gỡ parser wiring và module wizard không làm thay đổi canonical format. Storage
đã được `setup` tạo vẫn hợp lệ; integration chỉ được xóa bằng command riêng có
owner validation.
