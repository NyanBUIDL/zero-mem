# Zero-Mem — Báo cáo đánh giá toàn diện (v1.3.4)
> **Người review:** GLM 5.3 (Hermes Agent, Nous Research) · **Ngày:** 2026-08-23
> **Cơ sở:** HEAD `670dbfa`, tag v1.3.4 (RELEASED_PUBLISHED trên `NyanBUIDL/zero-mem`), suite **3479 passed / 7 skipped / 0 failed** (Py 3.13.15, isolated HOME), defect registry `docs/defects/DEFECT-REGISTRY.md` (DEF-001..009).
> **Phương pháp:** đọc trực tiếp source + project-state.yaml + git log; mọi claim lỗi đều được grep/xác minh trên tree, không suy đoán.

---

# PHẦN I — TỔNG QUAN

## 1. Hệ thống là gì

Zero-Mem là **external memory sidecar cho AI agent**: một tiến trình bên cạnh Hermes lưu trữ, redact, index, truy xuất và chấm điểm bằng chứng — rồi tiêm một EvidenceSet **giới hạn biên (bounded)** vào context trước khi LLM cuối phản hồi. Không phải app độc lập; là hạ tầng nhớ.

## 2. Kiến trúc (đã xác minh qua MODULE-MAP + cây src)

```
Hermes Agent ──hook──► Zero-Mem Sidecar
   M1 capture/redact → JSONL canonical (append-only)
   M2 SQLite/FTS5 derived (rebuildable)          ← mọi thứ dưới đều derived
   M3 read-only retrieval (mode=ro + query_only)
   M4 project memory / M5 authorization-first
   M7 router → EvidenceSet (5 primary + 3 supporting, deterministic)
   M8 graph/temporal/calibration (DATA-only metadata)
   M9 Obsidian projection (human-owned)
  ◄──bounded evidence envelope──► Final LLM
```

Bốn bất biến xuyên suốt (đều có test bảo vệ): **JSONL là nguồn truth duy nhất**; **zero-LLM memory ops**; **authorization trước mọi query/mutation**; **fail-closed mọi cổng**.

## 3. Trạng thái hoàn thành

| Thành phần | Trạng thái |
|---|---|
| Hạ tầng M1–M10 | ✅ VERIFIED toàn bộ |
| Releases | v1.3.0 → v1.3.1 → v1.3.2 → v1.3.3 → **v1.3.4** tất cả RELEASED_PUBLISHED |
| Defect registry | 9 defects đăng ký: 7 CLOSED/FIXED, 3 OPEN-deferred (004/005/009) |
| Schema | v12 (zm_verifications provenance vừa bổ sung ở v1.3.3) |
| Scale thực tế đã chứng minh | 601 PDF / 1.4GB corpus, 26K units, p95 retrieval 21ms |

**Kết luận mức vĩ mô:** hệ thống đã đi qua giai đoạn "xây hạ tầng" và đang ở giai đoạn đầu "chứng minh giá trị sản phẩm". Nợ kỹ thuật tồn đọng được quản lý tập trung trong registry thay vì lan tràn — đây là trạng thái khỏe.

---

# PHẦN II — ĐÁNH GIÁ CHI TIẾT THEO TIÊU CHÍ

## 2.1 Logic hệ thống — 9.5/10

**Mạnh:** ranh giới module cứng (mỗi milestone một package, contract frozen trước implement); single machine state (`project-state.yaml`) được validator fail-closed bảo vệ; master spec freeze bằng SHA-256 hash — ba lớp chống "drift" mà hầu như không dự án cá nhân nào có.

**Ghi nhận:** logic authorization trải qua 4 tầng precedence (base policy → grants compose → resource-type isolation → defensive post-validation). Không thấy redundancy thực sự — mỗi tầng giải một mối đe dọa khác nhau — nhưng đây là nơi phức tạp tập trung nhất của hệ thống; bất kỳ thay đổi tương lai nào ở đây bắt buộc phải đọc ADR-V132 trước.

## 2.2 Logic thuật toán — 9/10

**Mạnh (đã verify code):**
- Content-hash SHA-256 canonical JSON cho identity/dedup/cursor-fingerprint.
- Keyset pagination `(sort_col, id)` thay OFFSET — đúng cho dataset lớn.
- Two-phase FTS: AND trước, OR fallback chỉ khi 0 kết quả — precision cao.
- FTS injection đã bị chặn: `_quote_fts_term()` double-quote từng term theo FTS5 phrase rule → caller text **không thể** inject operator OR/AND/NOT/NEAR/column-filter (ngược với lo ngại của báo cáo model ngoài — tôi đã đọc code xác minh).

**Cần theo dõi:**
- `CorpusSourceRegistry._update_record` O(n)/update (DEF-009a, deferred) — chỉ thành vấn đề >10k records.
- Calibration là nhân tử 8-factor thuần deterministic — tốt cho audit, nhưng không có semantic signal; paraphrase query sẽ yếu (chờ v1.5 semantic adapter).

## 2.3 Bảo mật — 9/10 (điểm trừ duy nhất là độ phủ, không phải lỗ hổng mở)

**Đã kiểm chứng:** redaction fail-closed (marker-abuse hardened v1.3.2, exact-format only); path safety chống traversal/symlink (`O_NOFOLLOW`); secret never persisted (hash-only); read-only thật ở connection level (`mode=ro` + `PRAGMA query_only=ON` — mutation fail ngay tại driver); DATA-only injection envelope (không thể biến thành instruction); resource-type isolation (grant artifact không đọc được event).

**Lưu ý nhỏ:** 11 chỗ `except Exception` trong retrieval layer đều chuyển hóa thành `QueryError("query_failed")` kèm `from exc` — không nuốt lỗi, nhưng mã hoá thô; khi debug production cần bật log gốc. Đây là trade-off chấp nhận được (không leak nội dung DB ra error message).

**Không tìm thấy lỗ hổng bảo mật mới trong lần review này.**

## 2.4 Lỗi code — tính cả nhỏ nhất

Trạng thái hiện tại sau v1.3.4 (tất cả đã commit + publish):

| # | Lỗi | File | Trạng thái |
|---|---|---|---|
| DEF-001 | `verified_rank` so tuple không khớp enum → verified-priority ranking chết hoàn toàn | `budget.py:51` | ✅ FIXED v1.3.3 |
| DEF-002+006 | version drift 1.3.1 vs tag + 8 pin hardcode còn sót (manifest gate từ chối bundle mới) | `version.py`, `release_common.py:127`... | ✅ FIXED v1.3.3 |
| DEF-007 | `zm_verifications` thiếu provenance columns → verification evidence bị calibration loại nhầm `excluded_unauthorized_scope` + lifecycle non-enum | migrate_7, projector, reader | ✅ FIXED v1.3.3 (migration v12) |
| DEF-008 | dead code 2 dòng unreachable trong `make_relation_fingerprint` | `cursor.py:99-100` | ✅ FIXED v1.3.4 |
| DEF-003 | chưa có crash/power-loss proof | durability | ✅ CLOSED v1.3.4 (SIGKILL harness + torn-tail test, 5/5 stable) |
| DEF-009a | registry O(n) update | `registry.py:244` | 🟡 OPEN v1.4.x (cần ADR) |
| DEF-009b | `fp_request profile_id=project_filter` naming sai (behavior-neutral, chỉ feed fingerprint versioning) | `authorized_read.py:343` | 🟡 OPEN v1.4.x |
| DEF-004 | knowledge-space grant non-authorizing (fail-closed đúng nhưng feature chưa work) | `_scope_allows()` | 🟡 OPEN v1.4.x (cần ADR schema) |
| DEF-005 | enrichment adapter viết xong chưa wire | `enrichment.py` | ⚪ backlog |
| mới | `except Exception` mã hoá thô trong retrieval | 11 chỗ | ⚪ ghi nhận, không fix ngay |

**Không còn lỗi OPEN nào ở mức cấp bách.**

## 2.5 Hiệu suất — 8.5/10

**Chứng minh bằng số liệu:** p95 retrieval 21ms trên 26K units; peak RSS 1.15GB full ingest 1.4GB corpus; WAL mode; bounded queue chống memory explosion; optional deps đúng chính sách.

**Điểm trừ:** registry O(n) (deferred, có ADR plan); ingest từng transaction một (an toàn > nhanh — đúng lựa chọn cho memory sidecar, không phải throughput system); AuthorizedReadService materialize kết quả đồng thời (chấp nhận được vì bounded budget 5+3). Chưa có Rust hot-path — **đừng làm**, p95 21ms chưa phải bottleneck.

## 2.6 Truy suất / Provenance — 9.5/10

Immutable event IDs + content-hash chain + tombstone với prior-state + redaction audit không giữ giá trị gốc + source_event_id liên kết về trace. Temporal validity có M8.4 as-of/history authorization-first. Sau DEF-007, verification records giờ cũng mang đầy đủ provenance giống mọi bảng M4 khác. Đây là điểm mạnh bán được tiền nhất của sản phẩm.

## 2.7 Tính liền mạch & modular — 9/10

10 package biên rõ, contracts frozen per-milestone, FormatAdapter registry mở rộng không đụng core, MODULE-MAP.md per-version ghi biên sửa an toàn từng block. Điểm trừ nhỏ: `integration/m7` 12 file hơi phân mảnh; `authorized_read.py` 850 dòng import chéo nhiều package (tight coupling chấp nhận được vì nó là facade trung tâm của M5).

## 2.8 Token efficiency — 9/10

Zero-LLM memory ops (chi phí $0 recurring — lợi thế cốt lõi); metadata-only retrieval; snippet-only FTS; bounded EvidenceSet 5+3; DEFAULT_LIMIT=50/MAX_LIMIT=500. **Thiếu duy nhất:** token estimation trước injection — caller không biết EvidenceSet tốn bao nhiêu token trước khi tiêm. Đã ghi nhận, nên làm cùng v1.5 semantic layer (cần metric để tune budget).

## 2.9 Lộ trình phát triển

| Giai đoạn | Nội dung | Ghi chú |
|---|---|---|
| **v1.4.x** (kế tiếp) | quant_lab ingest (600 .md + 471 PDF primary-pdf) + MCP adapter/import tool + DEF-004/009 (cùng chạm access layer, làm 1 lượt theo ADR) | mục tiêu kép: nạp corpus showcase + chứng minh agent-independence qua MCP client khác |
| **v1.5** | Local semantic adapter (FAISS, rebuildable) + token estimation + retrieval-quality benchmark (precision@k trên QA set từ quant data) | chuyển từ "hạ tầng vững" sang "sản phẩm đo được" |
| **Sau v1.5** | Multi-corpus (legal-vn, research-insight pipeline) → enterprise tier (multi-tenant, RBAC chi tiết, on-prem) | định vị thương mại: auditable memory — ngách Mem0/Zep bỏ trống |

---

# PHẦN III — DANH SÁCH FIX THEO ĐỘ ƯU TIÊN

## Cấp bách (P0): **RỖNG**
Không có item nào. Mọi lỗi ảnh hưởng correctness/security đã đóng trong v1.3.3/v1.3.4.

## Cần làm sớm (P1 — gói v1.4.x)
1. **ADR knowledge-space resolution** (DEF-004): chọn (A) thêm column + migration v13 hay (B) resolution layer ánh xạ space→resource ids. Quyết định kiến trúc, cần bạn duyệt phương án trước khi code.
2. **Registry index ADR** (DEF-009a): chỉ làm khi quant_lab đẩy registry vượt ~10k sources; nếu làm thì SQLite derived index rebuildable từ JSONL, không đổi canonical format.
3. **fp_request rename** (DEF-009b): 5 phút, làm cùng lúc chạm `authorized_read.py`.

## Theo dõi (P2 — backlog có điều kiện)
4. Token estimation trong QueryRequest (v1.5, kèm benchmark).
5. Enrichment wiring (DEF-005) — chỉ khi có retrieval-quality metric chứng minh lợi ích.
6. Crash-durability mở rộng: test kill giữa lúc *canonical append* (hiện mới kill giữa *ingest*; append-side đã có torn-tail test bọc phần lớn rủi ro).
7. Semantic adapter FAISS (v1.5) — giữ optional local-only, không bao giờ thành dependency bắt buộc.

---

# PHẦN IV — NHẬN XÉT KẾT LUẬN

**Điểm số tổng hợp: 9.1/10.**

Zero-Mem thuộc nhóm hiếm các hệ thống memory cho AI agent mà tôi đánh giá được: (1) hứa hẹn zero-LLM/$0-recurring là thật, kiểm chứng bằng code chứ không phải marketing; (2) canonical/derived boundary được thi hành bằng tooling (hash freeze, machine-state validator) chứ không phải quy ước; (3) văn hoá defect-registry + RED-first + evidence-based closure tạo audit trail mà enterprise customer trả tiền để mua; (4) crash-safety giờ đã có proof test thay vì lời khẳng định.

**Điểm yếu lớn nhất không nằm trong code mà trong vị thế sản phẩm:** hệ thống đã rất chắc nhưng mới có duy nhất một integration (Hermes). Giá trị "agent-independent" cần được chứng minh bằng POC từ một MCP client thứ hai ở v1.4 — đó là bước chuyển từ "dự án kỹ thuật tốt" sang "sản phẩm có thị trường".

**Khuyến nghị hành động ngay tiếp theo:** bắt đầu v1.4 theo `CORPUS-QUANT-LAB-PROMPT.md`; trong WP đầu tiên, soạn luôn 2 ADR (knowledge-space + registry index) để tôi duyệt phương án trước khi code.

---
*Ký: GLM 5.3 · Mọi số liệu lấy trực tiếp từ tree `670dbfa` + GitHub release v1.3.4 tại thời điểm review.*
