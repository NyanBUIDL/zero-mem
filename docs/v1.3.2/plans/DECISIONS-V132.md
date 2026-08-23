# DECISIONS-V132

## B3 — Điều kiện bắt đầu (user duyệt qua chat 2026-08-23)

> "1. Điều kiện bắt đầu #0.3: CHO PHÉP dựng release/v1.3.2-remediation từ HEAD
> local (07ab93e) dù v1.3.1 chưa publish. Ghi quyết định này vào EVIDENCE.md
> làm bằng chứng điều kiện B3 của checklist."

Trạng thái: APPROVED (verbatim trên). v1.3.1 chưa publish, không có
APPROVE-RELEASE-V131.md → branch v1.3.2 dựng từ HEAD `07ab93e` local.

## WP-3 — Publish v1.3.1 (user duyệt qua chat 2026-08-23)

> "2. WP-3: ghi PENDING vào evidence (WP3-C2a), dừng WP-3 tại đó, các WP khác
> chạy tiếp bình thường. Publish v1.3.1 sẽ làm riêng sau khi user soạn
> APPROVE-RELEASE-V131.md — KHÔNG tự push trong vòng này."

Kết quả: PENDING. Không tag/push/release trong vòng v1.3.2.

## D-01 — is_verified enum alignment

Quyết định: **Phương án A** — align eligibility với enum VerificationStatus thật:
`is_verified = verification in {v.value for v in VerificationStatus} - {"none"}`
(khai báo tường minh tập `{direct_tool_output, user_confirmation,
deterministic_verification, approval}`). Giữ nguyên lifecycle check `"confirmed"`
ở dòng kế tiếp vì nó đúng taxonomy LifecycleStatus. Không đổi enum, không đổi schema.
Rationale: đây là bug logic thật trên đường retrieval quality (mục tiêu cốt lõi);
Option A khôi phục khả năng phân biệt verified qua verification_status mà không
mở lối đi nào mới (tập giá trị đóng theo enum).
Phương án bị loại: B (freeze luôn-False + xoá nhánh chết) — làm mất vĩnh viễn
khả năng phân biệt verified và hợp thức hoá hành vi sai.
Ngày: 2026-08-23. Xem ADR-V132-01-IS-VERIFIED-ALIGNMENT.md.

## D-02 — Machine state consolidation

Quyết định: **Phương án A** — project-state.yaml là machine state DUY NHẤT cho
trạng thái hiện tại + tương lai; implementation-plan.json chuyển vai trò
RECORD-LỊCH-SỬ (frozen, header ghi rõ superseded by project-state.yaml), không
xoá dữ liệu lịch sử. Validator script kiểm tra tính nhất quán cấu trúc đặt ở
scripts/ kèm unit test RED-first.
Phương án bị loại: B (dual-state + validator đối chiếu fail khi lệch) — giữ hai
máy trạng thái sống động là nguồn drift liên tục; validator chỉ phát hiện chứ
không loại bỏ nguyên nhân.
Ngày: 2026-08-23.

## D-03 — Master spec docx ↔ md

Quyết định: **Option A — freeze + hash-anchor**. .docx là authority;
docs/MASTER-SPEC.md là projection có kiểm chứng. SHA-256 của .docx hiện hành
ghi vào ADR-V132-02; scripts/check_master_spec_hash.py + unit test fail-closed
khi hash .docx ≠ hash trong ADR (docx vừa sửa chưa reconcile → chặn merge WP
đụng spec cho đến khi regenerate md). Không sửa nội dung .docx hay md.
Phương án bị loại: đổi authority sang md — trái AGENTS.md hiện hành, cần
spec amendment riêng ngoài phạm vi.
Ngày: 2026-08-23.

## D-04 / GATE-W9 — Venv strategy (user duyệt qua chat 2026-08-23)

> "3. D-04 = Phương án A: giữ .venv-v124 đến hết v1.3.x; tạo
> zero-mem-dev-data/venvs/ ngay; mọi venv tương lai (v1.4+) đặt ở đó;
> cập nhật WORKSPACE-POLICY.md phần Legacy exception phản chiếu quyết định
> (đây là GATE-W9 đã duyệt qua tin nhắn này — trích dẫn nguyên văn khi commit)."

Quyết định: **A**, GATE-W9 = APPROVED (verbatim trên). Edit WORKSPACE-POLICY.md
phần Legacy exception được phép theo gate này; mốc chuyển đổi: từ v1.4.0.
