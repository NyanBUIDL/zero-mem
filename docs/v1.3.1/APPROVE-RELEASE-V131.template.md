# APPROVE-RELEASE-V131 — template (KHÔNG tự tạo bởi Builder)

> File này phải do USER tạo/fill để phê duyệt release v1.3.1.
> Không có file này: KHÔNG tag, KHÔNG push, KHÔNG GitHub Release.

## Release identity

- Version: 1.3.1
- Branch: `release/v1.3.1-remediation`
- Base: master `8264711`
- Head (điền khi duyệt): `<commit-sha>`
- Proposed tag: `v1.3.1`

## Preconditions đã đạt

- [x] WP-1..7 CLOSED, WP-8 analysis xong (OPEN QUESTION chờ quyết riêng)
- [x] Final suite ≥ baseline (`zero-mem-dev-data/evidence/v131/final-suite.log`)
- [x] `docs/v1.3.1/CLOSURE.md` + `EVIDENCE.md` + release notes draft
- [x] ADR-V131-01 (D-01) ghi nhận

## Open question (không block release)

- [ ] WP-8 `is_verified` enum mismatch: Option A / Option B / Defer → ______

## Approval

- [ ] APPROVE tag `v1.3.1` local
- [ ] APPROVE push branch + tag tới canonical remote `NyanBUIDL/zero-mem` (theo GITHUB-POLICY)
- [ ] APPROVE GitHub Release

**Signed:** ______________ **Date:** ____________
