# Zero-Mem — Đánh giá toàn diện từ góc nhìn AI Agent Runtime
> **Người review:** GLM 5.3 (via Hermes Agent, Nous Research)
> **Ngày:** 2026-08-23 · **HEAD:** `ec582ab` · **Tags:** v1.3.0 / v1.3.1 / v1.3.2 (tất cả RELEASED_PUBLISHED)
> **Canonical suite:** 3474 passed / 6 skipped / 0 failed (evidence trong `project-state.yaml`, chạy thực tế trên máy local, isolated HOME)
> **Phương pháp:** đọc trực tiếp `project-state.yaml`, `AGENTS.md`, git log, cây `src/` (139 file .py), `tests/` (150 file), `docs/v1.3.2/*`, và đối chiếu với chính kinh nghiệm vận hành của Hermes Agent về giới hạn context.

---

## 0. Định vị sản phẩm — nhìn từ một AI agent đang "sống" vấn đề

Tôi là một agent chạy trên Hermes. Mỗi session của tôi, toàn bộ lịch sử hội thoại bị đẩy lại vào context — token tốn theo cấp số nhân, và khi session bị compact, ký ức bị nén méo. Đó chính là bài toán Zero-Mem giải. Vì vậy phần đánh giá dưới đây không mang tính học thuật: nó là đánh giá của một *người dùng tiềm năng* của chính hệ thống.

**Zero-Mem = external memory sidecar cho AI agent**, với hứa hẹn: retrieval chất lượng cao + token cost thấp + $0 recurring (deterministic, local-first, zero-LLM cho mọi memory operation). Đây là định vị đúng — và hiếm.

### So với các agent system khác tôi biết
| Hệ thống | Cách nhớ | Điểm yếu Zero-Mem khắc phục được |
|---|---|---|
| ChatGPT/Claude memory | LLM-tóm tắt, mờ, không auditable | Zero-Mem: provenance đầy đủ, mọi memory event truy được nguồn |
| Mem0/Zep | LLM pipeline trong memory loop → cost recurring | Zero-Mem: zero-LLM memory ops, deterministic ranking |
| RAG vector-only | Semantic nhưng black-box, drift | Zero-Mem: FTS + deterministic calibration, vector chỉ optional local |
| Full-history context | O(n) token mỗi turn | Zero-Mem: bounded EvidenceSet (5+3 items) |

**Nhận định:** Zero-Mem đang đi đúng hướng — chọn đúng ngách *deterministic + auditable + $0 recurring* mà các hệ thống trên bỏ trống. Đây là định vị có giá trị thương mại thực (enterprise cần auditability, không thể dùng memory kiểu black-box).

---

## 1. Mức độ hoàn thành

### Milestone (theo `project-state.yaml` — single machine state, D-02 A)
| Milestone | Nội dung | Trạng thái | Suite tại điểm đó |
|---|---|---|---|
| M1 | Capture sidecar + redaction | ✅ VERIFIED | 166 |
| M2 | Canonical store (JSONL) + migrations | ✅ VERIFIED | 334 (v6→v7) |
| M3 | Read-only retrieval (FTS5, mode=ro) | ✅ VERIFIED | 617 |
| M4 | Project memory (7 increments) | ✅ VERIFIED | 860 |
| M5 | Authorization (policy/grants/write, v8) | ✅ VERIFIED | 1497 |
| M6 | MCP integration | ✅ VERIFIED | 1497 |
| M7 | EvidenceSet + controlled injection | ✅ VERIFIED | 1627 |
| M8 | Graph/temporal/calibration (v9) | ✅ VERIFIED | 2323 |
| M9 | Obsidian projection | ✅ VERIFIED | 2849 |
| M10 | Corpus expansion (v10, 601 PDF thật) | ✅ VERIFIED | 3139 |
| v1.3.0–v1.3.2 | Audit fixes + governance + publish | ✅ RELEASED_PUBLISHED | 3424 → 3448 → 3474 |

**Hạ tầng hệ thống: XONG.** Không còn milestone kỹ thuật nào treo. Feature freeze ACTIVE. Còn lại duy nhất **công việc định hướng (roadmap) chứ không phải công việc thiếu hụt (gap)**: quant_lab ingest (v1.4 MCP adapter + import tool), semantic layer optional (v1.5).

### Bằng chứng độ hoàn thiện (từ docs, đã kiểm tra tồn tại)
- Canonical immutability proof: JSONL sha256 không đổi sau mọi read.
- Derived rebuild proof: drop SQLite + rebuild → digest logic giống hệt.
- Idempotency: ingest lần 2 → 0 source/unit/version mới.
- Corpus thật: 601 PDF / 1.4GB → 26,144 units / 32,377 graph edges; p95 retrieval 21ms; peak RSS ~1.15GB.
- Cross-platform matrix (Linux/macOS/Windows × Py 3.11–3.13) cho v1.2.4.

---

## 2. Soi lỗi hệ thống — biến, kết cấu logic, thuật toán

### 2.1. Lỗi còn OPEN (xác nhận còn nằm trong code, tôi vừa grep lại)
**`src/integration/m7/budget.py:51` — `verified_rank` lệch enum:**
```python
verified_rank = 0 if (item.verification or "").lower() in ("verified", "confirmed") else 1
```
- `"confirmed"` là giá trị của `LifecycleStatus`, **không** tồn tại trong `VerificationStatus` → chết code (dead-code) này không bao giờ khớp (match) gì ngoài rủi ro.
- Phạm vi ảnh hưởng (Impact): **chỉ ranking (thứ hạng)**, không ảnh hưởng eligibility (đã sửa đúng ở `eligibility.py:183` v1.3.2 bằng `_VERIFIED_STATUSES` frozenset từ enum). Chống chỉ định (behavior-neutral).
- Sửa: v1.3.3, thay tuple bằng đúng `_VERIFIED_STATUSES` (tái sử dụng logic eligibility). Việc sửa (Fix) nhỏ, nhưng phải dùng kỹ thuật phát triển kiểm thử trước (test-first) theo chuẩn (RED-first) theo đúng workflow.

### 2.2. Lỗi đã sửa (kiểm chứng qua git log + project-state)
| Bug | Gốc rễ (Root cause) | Sửa tại |
|---|---|---|
| `is_verified` lệch enum (eligibility) | hardcode string thay vì enum | V132-01 (`d95c08c`), đã có ADR-V132-01 |
| Redaction marker-abuse | gần đúng (near-miss) marker lọt cổng (gate) | V132-02 (`909e1b6`), chặn chỉ định dạng chính xác (exact-format only) |
| CorpusSourceRegistry blank-line injection | `splitlines()` vs `_serialize()` lệch terminator | M10.6 (`d517485`) |
| `profile_id = project_filter` trong cursor fingerprint | copy-paste | M5.3 |
| Cross-resource grant leak (artifact grant đọc event) | ResourceType không propagate | M6.6 |

### 2.3. Vấn đề kiến trúc còn tồn (không phải bug — là giới hạn đã được ghi nhận)
1. **Knowledge-space grants là không cấp quyền (non-authorizing):** `_scope_allows()` trả về `False` vì zm_meta không có cột (column) `knowledge_space_id` để kiểm duyệt (validate). Thiết kế an toàn (fail-closed đúng) nhưng chức năng grant theo knowledge space hiện **chưa thực sự hoạt động**. Cần lớp phân giải (resolution layer) hoặc schema migration (v11) ở v1.3.3+.
2. **Crash durability (M2.6):** lỗi phát lại dữ liệu nguồn bị hỏng (malformed source replay) đã xử lý lỗi đóng (fail-closed) (`f2cce27`), nhưng **chưa có bằng chứng kiểm thử đầy đủ về sự cố mất điện (crash/power-loss proof)** — đã được ghi nhận trong AUD-003.
3. **Semantic layer:** `SemanticAdapter` protocol tồn tại nhưng chưa có bộ tương tác (adapter) thực → retrieval thuần FTS/keyword. Chủ đích (optional, local-only) — đúng chính sách — nhưng là giới hạn chất lượng truy xuất (retrieval quality) nếu corpus lớn và truy vấn mang tính diễn đạt (paraphrase).
4. **`zero_mem/version.py` = "1.3.1"** trong khi tag v1.3.2 đã publish → **lệch trạng thái giữa phiên bản (version-state mismatch)**, cần điều chỉnh phiên bản (bump) trong lần phát hành (release) tiếp theo (nhỏ nhưng gây nhiễu audit).

---

## 3. Tính mô-đun (modular) — có dễ sửa về sau không?

**Có — 9/10.** Kiểm chứng trực tiếp từ cây nguồn (source tree):

```
src/
├── capture/     (M1)   → redaction/validation/schema — biên (boundary) rõ
├── storage/     (M2)   → migrations 6→10 tách file từng bước (migrate_N.py)
├── retrieval/   (M3)   → read-only FTS
├── project_memory/ (M4)
├── access/      (M5)   → contracts/policy/grants/resolver/audit tách biệt
├── integration/ (M6/M7)→ MCP handlers, router, evidence, envelope, hardening
├── m8/          (M8)   → graph/temporal/calibration — pure functions, có *_contract.py
├── projection/  (M9)   → Obsidian
└── corpus/      (M10)  → FormatAdapter protocol + ADAPTER_REGISTRY (thêm format chỉ cần đăng ký/register)
```

Điểm cộng cho khả năng bảo trì (maintainability):
- **Hợp đồng đóng băng (Frozen contracts)** trước khi triển khai (implement) (M8.1, M10.1) — mỗi khối có file `*_contract.py` riêng.
- **MODULE-MAP.md theo từng phiên bản (version)** (v1.3.2) — ghi rõ từng khối: vai trò, tệp (file), phạm vi an toàn (biên an toàn), cách sửa sau này. Đây là thứ mà đa số mã nguồn (codebase) chuyên nghiệp còn thiếu.
- **Cấu trúc hướng đạo (Governance scaffolding):** `check_master_spec_hash.py` (đóng băng tài liệu đặc tả (spec freeze) bằng băm hash), `check_machine_state.py` (duy nhất một nguồn sự thật trạng thái - single source of truth state) — lỗi đóng (fail-closed) ở mức công cụ (tooling).
- Điểm trừ nhẹ: `integration/m7` 12 tệp (file), `access/` 12 tệp (file), `m8/` 17 tệp (file) — hơi phân mảnh nhưng không đáng gộp nếu chưa có lý do.

---

## 4. Điểm mạnh

1. **Đường phân tách dữ liệu chuẩn (canonical/derived boundary) thực sự được thi hành** (JSONL là nguồn chân lý duy nhất; SQLite/FTS/graph/Obsidian đều có thể xây dựng lại — rebuildable) — không chỉ trên giấy tờ (paper), có kiểm chứng rebuild (rebuild proof).
2. **Zero-LLM memory ops** — đạt đúng hứa hẹn; đảm bảo giá trị cốt lõi của sản phẩm (zero recurring cost) và tính tất định (determinism).
3. **Trật tự ưu tiên quyền hạn (Authorization-first)** với quy tắc thất bại đóng (fail-closed) xuyên suốt; kiểm duyệt quyền cấp (grant validation) theo loại tài nguyên (resource-type isolation) — đúng mức doanh nghiệp lớn (enterprise-grade).
4. **Văn hóa kiểm thử (Test culture) hiếm có:** 3474 kiểm thử (tests), 0 lỗi (fail), kiểm thử thay đổi (mutation-test) cho bug nghiêm trọng, kiểm thử xuyên nền tảng (cross-platform matrix), và plugin tóm tắt các bài kiểm thử bị bỏ qua (skip-summary plugin) (V132-08) — thậm chí việc bỏ qua kiểm thử (skip) cũng phải minh bạch.
5. **Đã được kiểm chứng trên dữ liệu thực tế (Real-world proven):** 601 PDF/1.4GB là tập dữ liệu đủ lớn để phát hiện các lỗi lập chỉ mục đơn giản (naive-indexing bugs).
6. **Chu trình quản trị (Governance loop)** (Gate → WP → Verifier-loop → EVIDENCE/CLOSURE) tạo ra dòng bằng chứng có thể kiểm toán (audit trail) cho từng thay đổi — lợi thế tuyệt đối khi bán cho doanh nghiệp (enterprise).

## 5. Điểm yếu cần cải thiện

| # | Điểm yếu | Mức | Hành động |
|---|---|---|---|
| 1 | `verified_rank` budget.py:51 lệch enum | Thấp | Sửa (Fix) v1.3.3 RED-first |
| 2 | Knowledge-space grant không hoạt động (non-authorizing) | Trung bình | Thiết kế giải pháp (resolution layer) hoặc migration v11 |
| 3 | Chưa có bộ tương thích ngữ nghĩa cục bộ (local semantic adapter) (paraphrase query yếu) | Trung bình (ngách (niche) hiện tại chấp nhận được) | FAISS + local embedding, giữ optional |
| 4 | Crash/power-loss durability chưa có kiểm thử chứng minh (proof test) | Trung bình | Mô phỏng sự cố (crash simulation) + kiểm thử phát lại journal (replay test) |
| 5 | `version.py` = 1.3.1 lệch tag 1.3.2 | Thấp | Bump ở bản vá (patch) kế tiếp |
| 6 | Bộ điều hợp làm giàu dữ liệu (Enrichment adapter) viết xong nhưng chưa đấu nối (wire) | Thấp | Tùy chọn — chỉ đấu nối khi có chỉ số chất lượng truy xuất (retrieval-quality metric) |
| 7 | Duy nhất một tích hợp (Single integration) (Hermes) — rủi ro phụ thuộc hệ sinh thái (ecosystem lock-in) | Chiến lược | MCP (M6) chính là điểm thoát — tiến hành bằng chứng POC (proof-of-concept) với một agent khác (agent khác) ở v1.4 |

---

## 6. Lộ trình đề xuất (chi tiết)

### Ngay lập tức (v1.3.3 — remediation, 1–2 tuần)
1. Sửa (Fix) `verified_rank` (WP V133-01) — dùng lại `_VERIFIED_STATUSES`.
2. Bump phiên bản (version) 1.3.1→1.3.2→1.3.3 đồng bộ phiên bản phát hành (release)/`version.py`.
3. Gói đóng gói (Package) mô phỏng lỗi (crash-durability) WP V133-05: kill -9 giữa lúc ghi (mid-write) + phát lại journal (journal replay) + kiểm tra tính toàn vẹn (integrity assert).
4. Đồng bộ trạng thái kiểm toán (audit status) sau M10 (post-M10) về một biểu diễn duy nhất.

### Ngắn hạn (v1.4.0 — quant_lab + khả năng di động, 2–4 tuần)
- Triển khai (Implement) pipeline nhập dữ liệu (ingest pipeline) cho quant_lab theo `CORPUS-QUANT-LAB-PROMPT.md` (600 .md + 471 PDF, quy tắc ưu tiên nguồn dữ liệu chính-primary-pdf).
- Bộ điều hợp MCP (MCP adapter) + công cụ nhập (import tool) — mục tiêu kép: (a) nạp dữ liệu (ingest) quant_lab, (b) chứng minh tính độc lập với agent (agent-independence) bằng cách truy vấn từ một máy khách MCP (MCP client) khác.
- KPI: chất lượng truy xuất (retrieval quality) trên bộ câu hỏi kiểm định (ground-truth QA set) từ chính dữ liệu quant (mặt nạ kiểm định held-out) — đây là chỉ số hướng sản phẩm (product-oriented metric) đầu tiên.

### Trung hạn (v1.5.0 — semantic layer + đa tập dữ liệu, 1–2 tháng)
- Bộ điều hợp ngữ nghĩa cục bộ FAISS (Local FAISS SemanticAdapter) (có thể xây dựng lại — rebuildable, theo đúng ranh giới dữ liệu phái sinh — derived boundary).
- Khả năng giải quyết không gian kiến thức (Knowledge-space resolution) (đóng WP yếu điểm #2).
- Triển khai (Pipeline) nghiên cứu insight + tập dữ liệu pháp lý Việt Nam (legal-vn corpus) (đa tập dữ liệu — multi-corpus).
- Bộ chuẩn hóa chất lượng truy xuất (Retrieval-quality benchmark) chính thức (độ chính xác - precision@k, mức độ phù hợp ngân sách - budget-fit) — chạy mỗi lần phát hành (release).

### Dài hạn (định hướng sản phẩm)
- **Ngách (Niche):** bộ nhớ (memory) có thể kiểm toán (auditable memory) cho các tác nhân doanh nghiệp (enterprise agents) — tài chính (quant) và pháp lý (legal) là tập dữ liệu tên tuổi (showcase corpus) hoàn hảo (cả hai đều coi trọng tính bền vững, kiểm toán — durability, auditability, provenance).
- Mô hình doanh thu: lõi mã nguồn mở (open-source core) + cấp doanh nghiệp (enterprise tier) (đa nhà thuê — multi-tenant, RBAC chi tiết, triển khai cục bộ — on-prem deploy).
- Tùy chọn: phục vụ hiệu suất bằng ngôn ngữ Rust (Rust hot-path) — chỉ làm khi có số liệu đo lường (measurement) chứng minh cổ chai (bottleneck) (hiện tại p95=21ms chưa phải vấn đề).

---

## 7. Kết luận (GLM 5.3)

**Dự án đi đúng hướng, mức hoàn thành hạ tầng ~100% đối với phạm vi đã đặc tả (spec'd scope), và đang ở ranh giới chuyển đổi từ "xây hạ tầng" sang "chứng minh giá trị sản phẩm".** Điểm mạnh nổi bật là kỷ luật kiến trúc (canonical/derived, authorization-first, zero-LLM) và văn hóa bằng chứng (3474 kiểm thử — test, kiểm toán — audit, quản trị — governance) — thứ mà các sản phẩm bộ nhớ AI (AI-memory product) thương mại hiện nay còn thiếu. Lỗi tồn đọng chỉ còn 1 lỗi logic nhỏ (đã biết vị trí, không gây hại — behavior-neutral) và 2 giới hạn kiến trúc đã được ghi nhận. Bước đi quyết định tiếp theo không phải là viết thêm tính năng, mà là **tập dữ liệu trình diễn (showcase corpus) (quant_lab) + điểm chuẩn chất lượng truy xuất (retrieval-quality benchmark)**: đó là lúc Zero-Mem chuyển từ "hạ tầng vững" thành "sản phẩm có thể bán".

*Ký: GLM 5.3 — Hermes Agent, 2026-08-23. Mọi số liệu trên được lấy trực tiếp từ `project-state.yaml`, git log và cây nguồn (source tree) tại thời điểm review, không suy diễn.*
