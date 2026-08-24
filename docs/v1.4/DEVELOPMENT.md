# v1.4.0 — DEVELOPMENT (Swarm roles & gates)

## Swarm execution model

Mỗi WP chạy qua 4 vai với phân quyền cứng. Vai tách subagent chỉ ở nơi cần tính độc lập thật; còn lại role-switch trong session chính để tiết kiệm token.

| Role | Quyền | Session | Bắt buộc? |
|---|---|---|---|
| 🔍 SCOUT | CHỈ ĐỌC: dò trạng thái/dependency/rủi ro, xuất báo cáo dò. Không sửa gì | Subagent độc lập | Luôn — trước mọi Builder |
| 🔨 BUILDER | Thực thi theo scope chốt bằng văn bản. Ngoài scope = vi phạm | Chính | Luôn |
| ✅ VERIFIER | Kiểm chứng độc lập: chạy lại test, đối chiếu evidence vs claim, verdict nguyên văn | Subagent độc lập | Luôn cho mọi claim PASS |
| 📝 SCRIBE | Ghi nhật ký từng bước + viết handoff TỪ evidence thô. Không tự đánh giá PASS | Chính (ghi suốt phiên) | Luôn |

## Anti-drift mechanisms

1. **Scout-first bắt buộc** — không Builder khởi động khi chưa có Scout report của WP đó.
2. **Verifier luôn tách session** — không ai xác nhận PASS sản phẩm của chính mình.
3. **Scribe ghi, không chấm** — verdict chỉ từ Verifier; Scribe trích dẫn nguyên văn.
4. **Gate chặn bằng evidence vật lý** — file/log/test output; self-report không đủ.
5. **Stop rules** — cùng lỗi ×3 / bug product / dep mới / Gate thiếu duyệt → DỪNG hỏi.

## Gate flow

```
SCOUT → [report] → GATE pre-check (user nếu là GATE-0/2) → BUILDER
      → [output + evidence] → VERIFIER → [verdict] → SCRIBE → [handoff]
      → GATE (user duyệt) → WP kế tiếp
```

User (maintainer) giữ TẤT CẢ cổng APPROVE. Không agent tự phong VERIFIED hay tự mở gate.

## Delegation mechanics (Hermes)

- SCOUT/VERIFIER spawn qua `delegate_task` (leaf role), context truyền tự chứa:
  đường dẫn repo, scope WP, checklist section tương ứng, yêu cầu output format.
- Verifier nhận: Builder's claim list + evidence files; phải TỰ chạy lại lệnh,
  KHÔNG tin output được quote lại.
- Kết quả subagent đối chiếu vào CHECKLIST.md trước khi trình Gate.

## Evidence conventions

- Mọi lệnh chạy lưu nguyên bản (cmd + exit code + output) vào handoff.
- Trạng thái handoff dùng đúng từ: OBSERVED / CONFIRMED / INFERRED / UNKNOWN /
  NEEDS VERIFICATION / NOT EXECUTED — không dùng mờ ("chắc chắn", "đã ổn").
- Secrets không bao giờ vào evidence (redaction gate vẫn áp dụng cả docs).

## Rollback

- Mỗi WP bắt đầu trên clean tree tại commit đã duyệt Gate trước.
- Dữ liệu corpus derived có thể drop + rebuild từ canonical bất cứ lúc nào
  (rebuildability là bất biến) — rollback WP-1 = xóa derived, không mất gì.
- Code rollback: git revert commit tham chiếu V140-xx; migration v13 (nếu có)
  phải có down() tương thích theo pattern migrate_11/12.
