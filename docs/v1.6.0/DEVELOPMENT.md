# v1.6.0 Development Guide

## Trước khi sửa

Đọc `AGENTS.md`, ADR v1.6.0, work-package liên quan, defect registry và
`docs/governance/GITHUB-POLICY.md`. Ghi nhận dirty paths và không stage artifact
ngoài phạm vi.

## Chu trình thay đổi

1. Viết behavioral test RED cho đúng boundary.
2. Sửa nhỏ nhất để GREEN; không rewrite canonical.
3. Chạy focused + adjacent regression.
4. Chạy full unit/integration suite trong môi trường được hỗ trợ.
5. Ghi command, platform, Python, SHA và verdict vào evidence.
6. Commit một work-package có phạm vi rõ; push explicit branch, không force.

## Lệnh local chuẩn

```bash
python -m pip install -e ".[test,ci]"
python scripts/check_machine_state.py
python -m compileall -q zero_mem src scripts release_helpers benchmarks
python -m pytest -q tests/unit tests/integration
python benchmarks/v160_junction_lookup.py
```

## Evidence policy

Evidence C1–C4 đã tồn tại ở các vị trí lịch sử và không di chuyển. Evidence C5+
dùng `docs/v1.6.0/evidence/Cxx/`. Nếu một kết luận cũ sai, thêm addendum/supersede
và giữ raw record cũ. Skip phải có lý do capability rõ; không blanket-skip security.
