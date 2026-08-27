# Evidence DX01

- RED: test collection lỗi vì `zero_mem.commands_wizard` chưa tồn tại.
- GREEN focused: `tests/unit/test_v160_wizard_onboarding.py` — `10 passed`.
- Adjacent packaging/setup/Hermes regression — `82 passed`.
- Full unit/integration suite — `3628 passed, 38 skipped, 0 failed`.
- Compile + master-spec hash gate — PASS.
- Installed-wheel acceptance gọi trực tiếp wizard từ CLI shim trong bundle.
- Assertions gồm standalone, interactive Hermes, automation, rerun-preserve,
  validation-before-mutation, help surface và output không lộ ID/path.
- Remote run [33045453992](https://github.com/NyanBUIDL/zero-mem/actions/runs/33045453992)
  tại exact wizard SHA `68bdf29` — **9/9 PASS** trên Ubuntu/Windows/macOS ×
  Python 3.11–3.13.
