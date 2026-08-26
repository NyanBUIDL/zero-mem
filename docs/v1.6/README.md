# Zero-Mem v1.6.0 — Multi-Knowledge-Space

**Trạng thái:** `IN_PROGRESS / BLOCKED_QUALIFICATION`

**Branch phát triển:** `v160/multi-ks`

**Phiên bản package hiện tại:** `1.5.1` — chưa bump lên `1.6.0`

**Phạm vi chính:** hoàn thiện hỗ trợ một event thuộc nhiều Knowledge Space (Multi-KS), từ capture đến truy xuất, phân quyền, projection và release qualification.

> v1.6.0 chưa phải bản phát hành. Không được tuyên bố `release-ready`, tạo tag
> `v1.6.0`, hoặc cập nhật phiên bản package cho đến khi C1–C10 và toàn bộ release
> gate được nghiệm thu bằng bằng chứng thực thi.

## 1. Mục tiêu

v1.6.0 giải quyết giới hạn mỗi event chỉ có một `knowledge_space_id`. Canonical
event mới có thể mang `knowledge_space_ids: list[str]`, trong khi dữ liệu cũ vẫn
được đọc và nâng cấp theo quy tắc tương thích đã phê duyệt.

Kết quả mong muốn:

- capture bảo toàn danh sách Knowledge Space của từng event;
- SQLite tạo lại được junction `zm_event_spaces` từ canonical JSONL;
- structured query và FTS có cùng semantics Multi-KS;
- phân quyền đọc theo union và grant theo từng row, mặc định fail-closed;
- graph/temporal dùng PRIMARY-KS theo quyết định kiến trúc;
- list API và projection thể hiện Knowledge Space đúng dữ liệu;
- dữ liệu legacy, migration, rollback và rebuild tiếp tục hoạt động;
- release chỉ được mở khi acceptance, benchmark và full qualification đạt gate.

## 2. Nguồn quyết định và thứ tự đọc

Đọc tài liệu theo thứ tự sau trước khi triển khai một commit C5–C10:

1. [`AGENTS.md`](../../AGENTS.md) — authority, invariant và delivery protocol.
2. [`ADR-V160-01-MULTI-KS-PROPOSAL.md`](ADR-V160-01-MULTI-KS-PROPOSAL.md) — quyết định kiến trúc Multi-KS đã được chấp thuận.
3. [`V160-MULTI-KS-REMEDIATION-PLAN.md`](V160-MULTI-KS-REMEDIATION-PLAN.md) — thứ tự C1–C10, phạm vi và test gate.
4. [`DEFECT-REGISTRY.md`](../defects/DEFECT-REGISTRY.md) — trạng thái defect và quy trình RED-first.
5. [`GITHUB-POLICY.md`](../governance/GITHUB-POLICY.md) — bắt buộc trước mọi thao tác làm thay đổi Git/GitHub.

Khi tài liệu có khác biệt, authority và quyết định mới hơn có ghi rõ supersede
được ưu tiên. `project-state.yaml` là trạng thái máy hiện hành;
`implementation-plan.json` chỉ là historical record đã đóng băng.

## 3. Các invariant không được phá

- Canonical JSONL là nguồn sự thật append-only cho memory event và trace.
- SQLite, FTS, graph, temporal index và junction là derived state, phải rebuild được.
- Không rewrite hoặc xóa canonical history để sửa derived state.
- `knowledge_space_ids` được lưu theo event; trace-level KS là union dẫn xuất của các event trong trace.
- Junction `zm_event_spaces` là nguồn dẫn xuất chính cho Multi-KS authorization, structured query và FTS.
- `zm_meta.knowledge_space_id` chỉ giữ PRIMARY-KS để tương thích ngược và phục vụ graph/temporal; không phải source of truth.
- Event không có KS không được tự động mở quyền bằng space grant; quyền đọc còn phụ thuộc profile, project và global policy.
- Mọi thay đổi phải RED-first, commit nhỏ, có focused test, adjacent test và full-suite evidence.
- Không được đóng defect hoặc tuyên bố release dựa trên suy đoán môi trường.

## 4. Trạng thái triển khai

| Commit | Nội dung | Trạng thái | Gate chính |
|---|---|---|---|
| C1 | Capture contract `knowledge_space_ids` | DONE | Validation, adapter và legacy mapping |
| C2 | Migration v13 + `zm_event_spaces` + PRIMARY-KS | DONE | Upgrade, downgrade, backfill và batch memory |
| C3 | Rebuild junction từ canonical | DONE | Rebuild loại stale row và tái tạo faithful |
| C4 | Structured authorization qua junction | DONE về kỹ thuật | Union read, per-row grant và fail-closed |
| C5 | FTS parity qua junction | PENDING | FTS Multi-KS hit và grant filtering |
| C6 | Graph/temporal PRIMARY-KS | PENDING | Primary scope và trade-off fail-closed |
| C7 | `list_knowledge_space` parity | PENDING | Trả KS rows từ junction |
| C8 | Projection parity | PENDING | Projection render danh sách KS |
| C9 | Corpus singular limitation | PENDING | Giữ schema hiện tại và document limitation |
| C10 | Compatibility, acceptance và release gates | PENDING | E2E, legacy, benchmark, docs và qualification |

### Trạng thái qualification

- C4 đã có bằng chứng kỹ thuật cho đường đọc có cấu trúc.
- DEF-037 đang `REOPENED / INVESTIGATING` và root cause cụ thể chưa được xác nhận.
- Full qualification hiện bị chặn; chưa authorize bắt đầu C5 theo remediation plan hiện hành.
- Trước khi mở C5 phải có quyết định/record mới xác nhận blocker đã được xử lý hoặc phạm vi được maintainer cho phép tiếp tục.

## 5. Phạm vi C5–C10

### C5 — FTS parity

- Cập nhật `src/retrieval/search.py` và `authorized_read.search_text` để lọc candidate qua junction.
- Dùng cùng correlated `EXISTS` semantics với structured authorization ở C4.
- Chứng minh FTS Multi-KS trả đúng hit và space grant không làm lộ row ngoài quyền.

### C6 — Graph và temporal

- Graph/temporal tiếp tục dùng `zm_meta.knowledge_space_id` làm PRIMARY-KS.
- Event-derived graph node không được mặc định `knowledge_space_id=None` khi canonical có KS.
- Ghi rõ limitation: event `[A, B]` được biểu diễn trong graph dưới primary `A`; grant `B` có thể đọc event qua structured/FTS nhưng graph vẫn fail-closed theo primary.

### C7 — List Knowledge Space

- Sửa `src/retrieval/relations.py` để đọc Knowledge Space từ junction.
- Loại bỏ hành vi hardcode trả danh sách rỗng.
- Có behavioral test cho dữ liệu multi, singular legacy và unscoped.

### C8 — Projection parity

- Sửa `src/projection/render.py` để render `knowledge_spaces` từ dữ liệu event.
- Không giữ hardcode rỗng của projection cũ.
- Kiểm tra output ổn định, escape an toàn và tương thích fixture.

### C9 — Corpus

- Giữ `zm_corpus_units.knowledge_space_id` ở dạng singular trong v1.6.0.
- Không mở migration corpus Multi-KS trong phạm vi này.
- Document limitation và chuyển Multi-KS corpus unit thành increment/version riêng nếu cần.

### C10 — Compatibility và release qualification

- Chứng minh canonical cũ vẫn đọc được sau migration additive.
- Chạy upgrade, downgrade và rebuild tests.
- Chạy E2E: capture → canonical → ingest → junction → structured/FTS/grant.
- Kiểm tra matrix legacy, NULL, unscoped, profile/project/global-read và no-leak.
- Benchmark junction ở quy mô 1k/10k/100k, ghi platform, Python version, seed, latency và memory.
- Chạy full suite trên platform được hỗ trợ; mọi fail/error/skip phải được phân loại bằng evidence.
- Cập nhật MASTER-SPEC projection, ARCHITECTURE, README, release notes và evidence index.

## 6. Quy trình thực hiện mỗi commit

1. Xác nhận predecessor đã đạt gate và không còn blocker cấm mở commit tiếp theo.
2. Ghi baseline SHA, branch và các dirty path; không chạm file ngoài phạm vi.
3. Đọc ADR, remediation plan, defect registry và code/test liên quan.
4. Viết behavioral test nhỏ nhất và lưu kết quả RED.
5. Thực hiện thay đổi production nhỏ nhất để test GREEN.
6. Chạy focused tests, negative/security tests và adjacent regression.
7. Chạy full suite trong môi trường qualification hợp lệ.
8. Lưu raw log, checksum, tested SHA, lệnh chạy và verdict.
9. Cập nhật remediation plan/evidence index bằng dữ liệu thực thi; không overclaim.
10. Chỉ mở commit kế tiếp khi gate hiện tại được đóng rõ ràng.

## 7. Bằng chứng hiện có

| Phạm vi | Vị trí hiện tại |
|---|---|
| C1 | `tests/unit/test_v160_c1_capture_ks.py` và record trong remediation plan |
| C2 | `tests/unit/test_v160_c2_junction.py`, `audit/evidence-v160-c2/` |
| C3 | `tests/unit/test_v160_c3_rebuild_junction.py`, raw logs C3 trong `audit/evidence-v160-c2/` |
| C4 | `tests/unit/test_v160_c4_auth_junction.py`, raw logs C4 trong `audit/evidence-v160-c2/` |
| DEF-037 | `audit/evidence-v160-def037/` và defect registry addendum |

Tên thư mục `audit/evidence-v160-c2/` là di sản và hiện chứa cả C3/C4. Không di
chuyển hoặc sửa evidence đã nghiệm thu chỉ để làm đẹp cấu trúc. `EVIDENCE.md`
của v1.6.0 nên làm chỉ mục ổn định trỏ tới các artifact cũ; evidence mới của
C5–C10 nên đặt theo từng commit/work package.

## 8. Điều kiện hoàn thành v1.6.0

v1.6.0 chỉ được coi là hoàn thành khi đồng thời thỏa mãn:

- C1–C10 đều có trạng thái verified và tested SHA rõ ràng;
- ADR và tài liệu kiến trúc phản ánh đúng implementation cuối;
- Multi-KS E2E và toàn bộ compatibility/security matrix PASS;
- benchmark junction đạt ngân sách đã duyệt;
- full suite và platform qualification không còn lỗi chưa phân loại;
- mọi blocker/defect liên quan đã đóng hoặc có disposition được maintainer chấp thuận;
- version package được bump đúng `1.6.0` ở bước release preparation;
- release SHA invariant được xác minh trước tag và publication.

## 9. Ngoài phạm vi

- Không expose trace-union thành public surface trong v1.6.0.
- Không chuyển corpus unit sang Multi-KS trong version này.
- Không thêm ordinal cho junction nếu chưa có use case truy vấn thứ tự.
- Không thay canonical JSONL bằng SQLite hoặc projection.
- Không rewrite dữ liệu lịch sử để làm migration trông sạch hơn.

## 10. Ghi chú cho người tiếp nhận

Điểm bắt đầu an toàn không phải là viết code C5 ngay. Trước tiên hãy kiểm tra
DEF-037 và qualification record mới nhất. Khi blocker được giải quyết và C5 được
authorize, dùng C4 làm mẫu cho correlated `EXISTS`, viết test parity
structured/FTS trước, rồi mới sửa `src/retrieval/search.py`.
