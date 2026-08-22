# MASTER-SPEC-RECONCILIATION — v1.3.0

**Nguồn:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` → extracted text tại
`zero-mem-dev-data/evidence/v130-phase-b/master-spec-extracted.md` (42.702 chars / 844 dòng,
extract bằng stdlib zipfile+regex trên `word/document.xml`, không cài package).
**Ngày đối chiếu:** 2026-08-22. **Phạm vi:** 4 chủ đề theo Điều kiện 1 của Gate A.

| # | Invariant | Master spec (dòng extracted) | AGENTS.md / ADR chain | Kết luận |
|---|---|---|---|---|
| 1 | Scope enforcement / knowledge-space | L148: *"Một trace có thể thuộc nhiều knowledge space nhưng chỉ có một source-of-record"*; L263: profile ưu tiên nhiều space, vẫn có global access; L407: một note thuộc nhiều space (Obsidian ngữ cảnh) | zm_meta hiện single-value; corpus/graph/access đều single-value ks; D-2026-08-22-01 chọn cột đơn | **KHÁC (cần lưu ý, không chặn):** spec nói *trace* có thể thuộc nhiều ks. Nhưng: (a) spec không quy định biểu diễn vật lý trên `zm_meta`; (b) toàn bộ derived schema đã duyệt (migrate_8/9/10) dùng ks single-value; (c) authorization scope (`src/corpus/retrieval.py`) là single-value. Cột đơn `zm_meta.knowledge_space_id` + quan sát đa-space ở tầng khác (zm_scopes đã ghi mọi ks quan sát được) là biểu diễn tương thích; multi-trace-ks nếu cần thật sẽ là NEEDS DECISION riêng. Ghi vào spec V130-02 mục "Spec note". |
| 2 | Global default read | L51: *"Default có thể truy cập toàn cục nhưng retrieval luôn profile-first và giới hạn evidence budget"*; L293: profile_first; config mẫu global_fallback: true | AGENTS.md: reads global by default, profile-first | **KHỚP.** Chính sách NULL ks = unscoped = visible theo global-default-read được master spec ủng hộ; deny-by-default KHÔNG có trong spec → đúng như D-2026-08-22-03. |
| 3 | Evidence promotion (assistant_claim/verified/state) | L194-230: bảng độ tin cậy theo type; L230: *"Không nâng assistant_claim thành active fact nếu không có tool observation, user confirmation hoặc deterministic verification"* | AGENTS.md: verified state outranks self-report; PromotionBlockedError guards (`src/project_memory/contracts.py`) | **KHỚP.** P1-03 Option A chỉ nâng state ĐÃ active + eligible trong PROJECT route lên primary role — không tạo verified_state mới, không đụng assistant_claim guard. Tương thích. |
| 4 | Retrieval ordering & determinism | L52: không gọi LLM cho retrieval/routing; L114: deterministic before generative; L377: evidence score tham chiếu (multiplicative weights — ghi là "tham chiếu", không bắt buộc công thức); budget 5/3/6000 tokens (L301) | M7 deterministic ordering `(role, state_rank, verified, lifecycle, created_at, evidence_id)`; budget 5/3/8 | **KHỚP về nguyên tắc** (zero-LLM, deterministic). Spec đưa score formula ở mức tham chiếu; implementation hiện dùng rank-based deterministic — giữ nguyên, không đổi sang score. FTS OR-fallback (V130-01) vẫn zero-LLM, deterministic → hợp lệ. |
| 5 | Temporal read | L156 (paraphrase từ sơ đồ ASCII kiến trúc — không phải quote nguyên văn: sơ đồ chứa `[Temporal Index]` như một derived index chuẩn); L372: *"Temporal view ưu tiên session/project state đúng thời điểm"*; conflict rule L260: preserve all source traces, return conflict_set, no silent overwrite | M8.4 temporal_read verified (authorization-first, bounded ≤20, no recency-truth); P1-04 Option A annotation-only | **KHỚP.** Annotation-only đúng "preserve all source traces / no silent selection"; as-of không chọn truth by recency. |

## Verdict

- **0 mâu thuẫn hard** giữa master spec và authority chain cho scope 5 WP.
- **1 điểm lệch mức vật lý (ks multi-vs-single)** — xử lý bằng Spec Note trong V130-02 + giữ D-2026-08-22-01; không phải STOP RULE 4 vì spec không định nghĩa storage representation và derived-schema đã duyệt là single-value. Nếu user muốn strict multi-ks trên zm_meta → NEEDS DECISION, dừng V130-02.
- Không tự chọn phía nào ngoài phạm vi này.

## Bằng chứng tái tạo

```bash
cd zero-mem-v123-engineering
.venv-v124/bin/python - <<'EOF'
import zipfile, re
z = zipfile.ZipFile('Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx')
xml = z.read('word/document.xml').decode('utf-8')
paras = re.split(r'</w:p>', xml)
out = []
for p in paras:
    texts = re.findall(r'<w:t[^>]*>([^<]*)</w:t>', p)
    line = ''.join(texts).strip()
    if line: out.append(line)
open('/home/lenovo/Hermes Workspace/zero-mem-dev-data/evidence/v130-phase-b/master-spec-extracted.md','w').write('\n'.join(out))
EOF
```
