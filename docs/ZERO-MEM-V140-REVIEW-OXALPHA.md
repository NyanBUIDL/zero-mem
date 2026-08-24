# Zero-Mem V1.4.0 — Báo cáo review chuyên sâu (logic / hệ thống / tương thích / thuật toán)

> **Người review:** ox-alpha (Hermes Agent) · **Ngày:** 2026-08-25
> **Phạm vi:** diff `v1.3.4..v1.4.0` (52 files, +2810/-37) + các đường giao với core hiện có
> **Phương pháp:** đọc trực tiếp source tại tag v1.4.0 (`src/corpus/retrieval.py`, `query_planner.py`,
> `src/access/authorized_read.py`, `knowledge_space_resolver.py`, `src/integration/m6/*`,
> `scripts/corpus_*`, `benchmarks/v140_04_retrieval_bench.py`, tests); chạy lại packaging suite
> (27/27 PASS) và benchmark (đã chạy ở phiên trước, reproducible=true). Không suy đoán từ docs.

---

## ĐIỂM TỔNG HỢP THEO TIÊU CHÍ

| # | Tiêu chí | Điểm | Nhận xét ngắn |
|---|---|---|---|
| 1 | Logic hệ thống | 9/10 | Authorization-before-influence được thi hành đúng ở mọi điểm vào; trừ 1 gap wiring (F1) |
| 2 | Logic nghiệp vụ v1.4 | 8.5/10 | Resolver đúng nhưng chưa được đấu nối vào bất kỳ caller production nào (F1) |
| 3 | Thuật toán | 7.5/10 | Scoring thuần TF không IDF/không chuẩn hóa độ dài + FTS chỉ-AND không fallback (F5, F6) |
| 4 | Bảo mật | 9/10 | Không tìm thấy lỗ hổng mới; fail-closed giữ vững; sanitized output kiểm chứng qua test |
| 5 | Tương thích | 7.5/10 | 1 test hardcode path máy cá nhân (F2); MCP protocolVersion đóng cứng (F3) |
| 6 | Portability | 8/10 | Server nhận store-path qua argv/env tốt; trừ F2 |
| 7 | Hiệu năng | 8/10 | FTS discovery không LIMIT + metadata-only quét full bảng 217k units (F7) |
| 8 | Code quality | 8.5/10 | Docstring load-bearing rõ, helper lặp nhẹ (_scored/_fused/_lexical_only/_with_combined copy 15 dòng ×4) |
| 9 | Version hygiene | 8/10 | Bump sạch có suite xanh; nhưng lại sinh 1 hardcode version mới (F3b) |

**Tổng kết: 8.2/10** — chất lượng release cao hơn trung bình dự án ở kỷ luật thực thi,
thấp hơn ở chỗ: tính "generic" chưa trọn vẹn và một số quyết định thuật toán để nợ cho v1.5 mà chưa ghi thành debt chính thức.

---

## PHÁT HIỆN CHI TIẾT

### 🔴 F1 (quan trọng nhất) — DEF-004 Option B: resolver CHƯA được gọi bởi bất kỳ caller production nào

**Bằng chứng:** `grep -rn "corpus_conn" src/ examples/` → chỉ tồn tại trong
`src/access/authorized_read.py` (định nghĩa) + tests. Các điểm dựng service trong production:

- `src/integration/m6/handlers.py:96` — `AuthorizedReadService(store, profile, grant_conn=store.conn)` → **không có `corpus_conn`**
- `src/integration/m7/injection_adapter.py:284` — không có
- `src/integration/zero_mem_runtime.py:358` — không có
- `src/integration/m7/m8_integration.py:200` — không có

**Hệ quả phân tích theo từng path:**

1. **Corpus path (MCP `corpus_search`, M7 evidence fusion):** HOẠT ĐỘNG với space grant mà KHÔNG cần resolver — vì `corpus_unit_search` đọc trực tiếp `scope.allowed_knowledge_space_ids` và `zm_corpus_units` có sẵn cột `knowledge_space_id`. Không phải nhờ Option B.
2. **Event path (`_scope_allows`, lý do DEF-004 tồn tại):** vẫn non-authorizing khi chạy thật, vì `_space_members_for()` trả `None` khi `self._corpus_conn is None` → nhánh fail-closed từ chối. Giống hệt hành vi TRƯỚC khi fix.

**Kết luận:** DEF-004 được đánh giá FIXED dựa trên test unit (tự dựng service với `__new__` + gán tay `_corpus_conn`) — test đúng nhưng **không ai gọi code đó theo cách đó ngoài test**. Đây là dạng lỗi "wired-in-tests-only". Registry entry DEF-004 nên được mở lại hoặc ghi chú "FIXED (library-level); production wiring pending".

**Sửa đề xuất:** `_open_facade` (handlers.py) và các constructor runtime mở thêm connection read-only tới corpus-derived DB (path đã có sẵn trong runtime config) — ~10 dòng, kèm 1 test integration khẳng định space-grant event read hoạt động QUA handler chứ không qua constructor tay.

---

### 🟠 F2 — Test v140-03 hardcode đường dẫn máy cá nhân

`tests/unit/test_v140_03_mcp_corpus.py:24-26`:
```python
CORPUS_DB = Path("/home/lenovo/Hermes Workspace/zero-mem-dev-data/corpus-quant-lab/corpus-derived.sqlite")
```
Vi phạm trực tiếp nguyên tắc portability của dự án ("never assume a specific username/home").
Trên máy khác (bao gồm cross-platform matrix Linux/macOS/Windows đã quảng bá), test này sẽ
error thay vì skip — không có guard `pytest.skip` như các test archive trước đây đã học.
Suite "3425 passed" chỉ tái tạo được trên máy này.

**Sửa đề xuất:** env var `ZERO_MEM_CORPUS_DB` + `pytest.skip` khi thiếu, hoặc fixture build store tạm từ dữ liệu nhỏ synthetic.

---

### 🟠 F3 — Hardcode version + protocolVersion trong MCP server (tái phát pattern DEF-002/006)

- `src/integration/m6/mcp_server.py`: `"serverInfo": {"name": "zero-mem-m6", "version": "1.4.0"}` — chuỗi đóng cứng thay vì import `zero_mem.version`. Lần bump kế tiếp sẽ lệch状态 lần nữa — đây là lần thứ BA pattern này xuất hiện (DEF-002, DEF-006, giờ F3).
- `"protocolVersion": "2024-11-05"` — chấp nhận được cho POC (server trả version nó support là hợp spec), nhưng nên ghi chú: client MCP đời mới negotiate version; nếu sau này cần hỗ trợ tính năng protocol mới thì đây là điểm chạm đầu tiên.

**Sửa đề xuất:** `from zero_mem.version import __version__` — 1 dòng.

---

### 🟠 F4 — Pipeline "generic" chưa generic trọn vẹn: identity corpus bị hardcode

`scripts/corpus_generic_ingest.py:108,123`:
```python
profile_id="quant-lab-profile", project_id="quant-lab-corpus", ...
```
CLI nhận `--source-dir/--ks-name/--adapter` (đúng GATE-0-ADDENDUM) nhưng **không có
`--profile-id/--project-id`**. Người dùng import corpus KHÁC sẽ có tài liệu của họ gắn mác
`quant-lab-profile` — sai provenance ngay từ lúc ingest, và authorization theo profile sẽ
rối về sau (dữ liệu user A mang định danh của sample).

**Sửa đề xuất:** thêm 2 flag bắt buộc (hoặc default = suy từ `--root` dirname), cập nhật README example. Nhỏ nhưng làm trước khi corpus thứ hai được nạp.

---

### 🟡 F5 — Thuật toán scoring: TF thô, không IDF, không chuẩn hóa độ dài (và vì sao điều này là có chủ đích)

`_lexical_score` = tổng term-frequency trên text của unit, cap 1M. Không IDF, không length-norm
→ unit dài tự nhiên thắng unit ngắn cùng độ liên quan; từ hiếm (discriminative) và từ phổ biến
(stopword) đóng góp bằng nhau.

**Điểm tinh tế đáng ghi nhận:** docstring giải thích việc TỪ BỎ corpus-wide IDF là có chủ đích —
IDF toàn cục sẽ để unauthorized documents ảnh hưởng lên score của authorized results, phá
invariant *authorization-before-influence*. Đây là trade-off bảo mật > chất lượng, đúng ưu tiên
của dự án.

**Nhưng:** vẫn còn phương án hợp pháp — **IDF tính trên tập authorized subset** (deterministic
per-scope, không rò rỉ ảnh hưởng từ ngoài scope). Đây là cải tiến rẻ, nâng precision đáng kể mà
không đụng ranh giới bảo mật. Nên ghi thành backlog item chính thức thay vì để nuốt vào "v1.5 semantic".

---

### 🟡 F6 — Corpus retrieval thiếu OR-fallback: cơ chế một phần giải thích precision@1 = 0.095

`_fts_safe_query` nối mọi token bằng AND. M3 event-retrieval có two-phase (AND trước, OR fallback
khi 0 kết quả) — **corpus path không có**. Với held-out query 14 từ, ground-truth unit chỉ cần
thiếu 1 token là rơi khỏi candidate set hoàn toàn → miss tuyệt đối, không cứu được bằng ranking.
Benchmark đo được phần lớn là hiện tượng này cộng dồn với exact-unit matching khắc khe.

**Ý nghĩa:** một phần con số 0.095@1 là *artifact của thiết kế query planner*, không hẳn khả năng
retrieval. Trước khi chi tiền/tokens cho semantic adapter v1.5, OR-fallback (copy pattern M3, ~20
dòng) có thể nâng recall rõ rệt với chi phí gần bằng 0. Nên đo lại baseline sau khi thêm — nếu
không, v1.5 sẽ "ăn điểm" trên nền hạ vốn sửa được không tốn gì.

---

### 🟡 F7 — Hiệu năng: hai đường không có trần ứng viên

1. **FTS discovery không LIMIT** (`retrieval.py:366-373`): query phổ biến trên 217k units có thể
   materialize hàng trăm nghìn row vào Python list trước khi filter/rank → memory spike + latency.
   Benchmark dùng từ khóa đặc thù nên không chạm; người dùng thật gõ "risk" thì có.
2. **Metadata-only path quét full bảng** (`_read_all_units`): SELECT * không WHERE trên zm_corpus_units.

Cả hai đều fail-safe về authorization (filter diễn ra sau, đúng invariant) nhưng là rủi ro
DoS-kiểu-tai-nạn khi MCP server mở cho client ngoài. Đề xuất: cap ứng viên discovery (vd
LIMIT plan.limit × hệ số 50) + document rằng ranking chỉ trên capped set.

---

### ⚪ Nhỏ / hygiene

- `retrieval.py`: 4 helper `_scored/_fused/_lexical_only/_with_combined` lặp 15 dòng dataclass-copy
  — dùng `dataclasses.replace(h, ...)` sẽ gọn còn 4 dòng mỗi cái.
- `test_v140_02_ks_resolution.py:71-72`: assertion có nhánh "sqlite may yield None as None" hơi
  mơ hồ — nên ép kiểu ở fixture thay vì nhượng bộ ở assert.
- `mcp_server.serve()` xử lý tuần tự từng request — đúng scope read-only POC; ghi chú nếu sau này
  concurrent clients thì cần redesign.
- `generic_ingest` dry-run đếm `dirs` khác ngữ nghĩa với apply-mode (dry-run không tính skip-list)
  — thống kê hai mode không so sánh trực tiếp được, dễ gây hiểu lầm khi audit output.

---

## NHẬN XÉT KIẾN TRÚC (điều tích cực cần giữ)

1. **Authorization-before-influence được thi hành bằng cấu trúc, không bằng kỷ luật con người:**
   FTS chỉ là discovery; filter scope diễn ra TRƯỚC scoring; scoring chỉ dùng nội dung authorized
   (không IDF toàn cục). Chuỗi này nhất quán xuyên suốt retrieval.py và được test phủ. Đây là
   design hiếm thấy và đúng.
2. **Resource-type isolation (corpus_source ≠ corpus_unit)** được enforce 2 lớp (`_gate` +
   check tường minh `resource_type not in (None, "corpus_unit")`) — defense-in-depth đúng chỗ nguy hiểm nhất.
3. **NULL-sentinel semantics** `(None,None,None)` = unowned-only (không phải wildcard) được
   comment rõ và test riêng — bẫy logic kinh điển đã được né.
4. MCP wrapper đúng cam kết "thin transport": 166 dòng, không fork dispatcher, forbidden tools
   unreachable có test.

## ĐỐI CHIẾU CLAIM RELEASE vs THỰC TẾ

| Claim | Thực tế verify | Verdict |
|---|---|---|
| Suite 3425/0 green | Chạy lại packaging subset: 27/27 PASS; full-suite claim hợp lệ trên máy này (xem F2 caveat) | ✅* |
| MCP 11 tools, POC non-Hermes | tools/list trả đúng; sanitizer test có negative assertions | ✅ |
| DEF-004 FIXED | Library-level đúng; production wiring KHÔNG có (F1) | 🟠 một phần |
| Generic pipeline | Parameterized trừ identity (F4) | 🟠 một phần |
| precision@k reproducible | 3-run identical, fingerprint; tôi tự chạy khớp | ✅ |

## DANH SÁCH FIX ƯU TIÊN

| # | Việc | Mức | Khi nào |
|---|---|---|---|
| F1 | Đấu nối `corpus_conn` vào `_open_facade` + runtime constructors (+integration test) | CAO | v1.4.1 hotfix hoặc WP đầu v1.5 |
| F2 | Bỏ hardcode path khỏi test v140-03 (env var + skip guard) | CAO | v1.4.1 |
| F4 | Thêm `--profile-id/--project-id` vào ingest CLI | TRUNG BÌNH | trước khi nạp corpus thứ 2 |
| F3 | Import version thay vì hardcode trong mcp_server | THẤP | v1.4.1 (1 dòng) |
| F6 | OR-fallback cho corpus FTS (pattern M3) + đo lại baseline | TRUNG BÌNH | trước quyết định semantic v1.5 |
| F5 | IDF-on-authorized-subset cho lexical score | TRUNG BÌNH | v1.5 |
| F7 | Candidate cap cho FTS discovery + metadata-only | TRUNG BÌNH | v1.5 (trước khi expose MCP rộng) |
| — | dataclasses.replace cleanup; dry-run/apply stats đồng nhất | THẤP | backlog |

## KẾT LUẬN

v1.4.0 là release đạt chuẩn về kỷ luật thực thi: mọi gate có evidence, metric có reproducibility,
authorization invariant giữ vững qua một thay đổi kiến trúc lớn (corpus path). Hai phát hiện
quan trọng nhất (F1, F2) không làm hỏng dữ liệu hay mở lỗ hổng — hệ thống vẫn fail-closed —
nhưng chúng làm giảm giá trị tuyên bố của release: **DEF-004 chưa thực sự "sống" ở runtime**, và
suite xanh hiện phụ thuộc máy cá nhân. Cả hai đều sửa được trong phạm vi nhỏ, nên làm trước khi
bắt đầu v1.5 để baseline v1.5 đứng trên nền trung thực.

*Ký: ox-alpha · mọi phát hiện trên đều dẫn kèm file:dòng, đọc trực tiếp từ tree tag v1.4.0 ngày 2026-08-25.*
