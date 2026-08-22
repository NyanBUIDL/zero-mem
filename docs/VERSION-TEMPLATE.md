# Zero-Mem — VERSION TEMPLATE (docs/vX.Y.Z/)

Khung bắt buộc cho mỗi version phát triển. Copy toàn bộ file này thành từng file
trong `docs/vX.Y.Z/` và điền nội dung **trước khi code**. Xoá dòng ghi chú `<!-- -->`.

---

## README.md (index version)

```markdown
# Zero-Mem vX.Y.Z — <tên ngắn>

**Status:** `PLANNING | IN_PROGRESS | RELEASED_QUALIFIED | RELEASED_PUBLISHED | CLOSED`
**Branch:** `release/vX.Y.Z`
**Purpose:** <1-2 câu: version này giải quyết gì>

## Đọc theo thứ tự
1. ROADMAP.md — lộ trình
2. ARCHITECTURE.md — kiến trúc
3. TECH_STACK.md — công nghệ
4. DEVELOPMENT.md — cách phát triển
5. EVIDENCE.md — bằng chứng

## Work packages
| ID | Nội dung | Status |
|---|---|---|
| VXYZ-01 | ... | PLANNED/APPROVED/IMPLEMENTED_VERIFIED |
```

---

## ROADMAP.md (lộ trình)

```markdown
# vX.Y.Z — Lộ trình

## Mục tiêu version
- <mục tiêu chính>

## Phạm vi
- Trong phạm vi: ...
- Ngoài phạm vi: ... (ghi rõ, kể cả thứ đã từng đề xuất nhưng bị hoãn)

## Nguyên tắc / invariant không được phá
- <dẫn AGENTS.md + ADR; liệt kê ràng buộc bất biến>

## Work-packages (dependency order)
| ID | Tên | Depends on | Trạng thái | Gate |
|---|---|---|---|---|
| VXYZ-01 | ... | — | PLANNED | G1 |

## Milestone / gate
- G0 Contract → G1 Unit → G2 Integration → G3 Security/Failure → G4 Platform → G5 Packaging → G6 Release

## Open questions
- <câu hỏi cần quyết định; mỗi câu có owner + deadline>
```

---

## ARCHITECTURE.md (kiến trúc)

```markdown
# vX.Y.Z — Kiến trúc

## Component topology
<diagram text>

## Ownership boundaries
| Component | Owner | State authority |

## Interaction protocols
| Boundary | Protocol | Quyết định |

## State and failure semantics
<CURRENT/STALE/UNAVAILABLE/DENIED/EMPTY ...>

## Quyết định kiến trúc version này
- ADR/SPEC-AMENDMENT mới (nếu có): link.
```

---

## TECH_STACK.md (công nghệ)

```markdown
# vX.Y.Z — Technology Stack

## Approved stack
| Layer | Technology | Usage | Constraint |

## Deliberately not used
| Technology | Decision | Reason |

## Performance/cost budgets
- Zero LLM calls cho capture/classify/redact/project/retrieve/health.
- Capture append synchronous qua durability receipt; projection decoupled.
- Benchmark phải ghi corpus size, repeats, platform, Python version, seed.
```

---

## DEVELOPMENT.md (cách phát triển)

```markdown
# vX.Y.Z — Cách phát triển

## Quy trình (bắt buộc)
1. Chọn đúng work-package; kiểm tra dependency.
2. Ghi baseline SHA + dirty paths.
3. Đọc authority (`AGENTS.md`, master spec, ADR) + code map.
4. Viết/điều chỉnh acceptance test trước (RED).
5. Sửa vertical slice nhỏ nhất (GREEN).
6. Focused + negative + integration tests; security gate nếu xử lý content.
7. Ghi evidence (log/hash/verdict) vào `evidence/`.
8. Cập nhật trạng thái package; không bắt đầu package sau khi predecessor chưa xong.

## Gate bắt buộc
- G0..G6 (xem ROADMAP); mỗi gate có lệnh chạy thật + log + checksum.

## Điều kiện dừng (BLOCKED)
- Hành vi host không khớp contract fixture.
- Cần sửa sâu Hermes core thay vì sidecar/plugin boundary.
- Phải đổi schema/public semantics mà chưa có migration/version decision.
- Canonical và derived không chứng minh cùng topology.
- Test cần bỏ qua security gate để pass.
- Dirty path không xác định hoặc cần rewrite lịch sử Git.
- Không chạy được gate bắt buộc trên platform được tuyên bố hỗ trợ.

## Template work-package
<tham chiếu docs/v1.2.4/WORK_PACKAGE_TEMPLATE.md hoặc bản copy của version này>
```

---

## EVIDENCE.md (chỉ mục bằng chứng)

```markdown
# vX.Y.Z — Chỉ mục bằng chứng

## Tested SHA
- Product SHA: `<40 hex>` (CI-tested)
- Branch head: `<40 hex>`

## Matrix
| Gate | Kết quả | Lệnh | Log/Checksum |

## Work-package evidence
| WP | Evidence | Verdict |

## Verifier
- Independent verifier verdict: PASS/FAIL — link artifact.

## Git protocol
- Commits: chỉ stage exact paths; `git diff --check` sạch; không `git add .`.
- Release invariant: `MASTER_SHA = RELEASE_BRANCH_SHA = TAG_TARGET = ARTIFACT_SOURCE_SHA`.

## Known limitations
- <ghi trung thực: thứ chưa chạy, thứ bị skip có lý do, platform chưa test>
```
