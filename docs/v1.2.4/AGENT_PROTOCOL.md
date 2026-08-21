# Agent Delivery Protocol v1.2.4

## State machine

```text
PLANNED → APPROVED → IN_PROGRESS → IMPLEMENTED → IMPLEMENTED_VERIFIED
                         └──────────────────────► BLOCKED
IMPLEMENTED_VERIFIED → RELEASE_QUALIFIED (chỉ tại V124-05)
```

## Step-by-step

### 1. Establish scope

- Xác nhận branch là `release/v1.2.4`.
- Ghi exact baseline SHA và `git status --short`.
- Phân loại mọi dirty path; không chạm file unrelated/user data.
- Chọn đúng một V124 package có dependency đã đạt.

### 2. Read authority and current code

- Đọc master DOCX section liên quan, `AGENTS.md`, ADR-009 và tài liệu package này.
- Dùng code search để chứng minh call path hiện tại.
- Ghi assumption; assumption không được biến thành verified fact.

### 3. Lock the contract

- Viết input/output/status/failure semantics.
- Xác định backward compatibility và migration.
- Xác định owner của lifecycle/resource.
- Nếu thay đổi public semantics vượt patch-level, dừng xin version decision.

### 4. Tests before implementation

Tối thiểu phải có:

- happy path;
- disabled/off path;
- malformed/bounded input;
- duplicate/retry;
- authorization denial;
- partial failure/restart;
- secret redaction khi xử lý content;
- platform variant nếu có filesystem/process behavior.

### 5. Implement smallest vertical slice

- Không tạo parallel implementation của cùng contract.
- Không bypass canonical writer, authorization hoặc platform abstraction.
- Không thêm network service/vector DB/LLM call nếu package không yêu cầu.
- Giữ callback observation non-interfering: không mutate host payload/return/exception.

### 6. Validate

- Focused tests của file thay đổi.
- Dependency/integration tests của upstream và downstream boundary.
- Negative/security/concurrency tests liên quan.
- `compileall`, `git diff --check`, link/path validation cho docs.
- Full suite/platform matrix tại release gate; không gọi full-suite green nếu collection/error còn lỗi.

### 7. Evidence and review

Record phải có:

- package ID, baseline SHA, tested SHA;
- OS/Python/tool versions;
- exact sanitized commands;
- pass/fail/skip/error counts;
- raw log paths và checksums;
- known limitations;
- independent review result.

### 8. Git/GitHub

- Đọc [`GITHUB-POLICY.md`](../governance/GITHUB-POLICY.md) trước mutation.
- Stage từng path đã phân loại; không `git add .`.
- Không force push/rebase/tag/release nếu chưa được phép.
- Push branch không đồng nghĩa release; release cần gate và SHA invariant riêng.

## Definition of done

Package chỉ là `IMPLEMENTED_VERIFIED` khi code, tests, negative paths, documentation và evidence đều khớp. “Code đã viết”, “test hẹp pass” hoặc “Agent báo xong” không đủ.

