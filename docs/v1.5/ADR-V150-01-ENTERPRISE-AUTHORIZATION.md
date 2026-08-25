# ADR-V150-01 — Cụm ủy quyền enterprise v1.5: granular space-grant, derived-state trong authorization, registry scale (DEF-009 / DEF-010 / DEF-011)

**Trạng thái:** DRAFT — chờ maintainer chọn phương án tại GATE-V150-1
**Ngày:** 2026-08-25 · **Liên quan:** DEF-009, DEF-010, DEF-011 (+ admin CLI đa-agent từ ADR-V141-01)
**Phạm vi quyết định:** thiết kế kiến trúc v1.5 — KHÔNG kèm code trong ADR này.

## Bối cảnh (đã xác minh trên tree v1.4.1 @ 8d981c3)

Ba deferred defect tạo thành MỘT cụm duy nhất: **authorization granularity + độ tin cậy
dữ liệu feed vào authorization + hiệu năng lớp registry**. Cả ba cùng chặn tier
enterprise và đều nằm quanh ranh giới canonical/derived (ADR-009):

### DEF-009 — Corpus registry O(n)/update + tên field sai

`src/corpus/registry.py:244` `_update_record()` đọc TOÀN BỘ JSONL registry mỗi lần
update (`read_bytes().splitlines()`) rồi ghi lại toàn bộ. Bottleneck khi registry vượt
~10k records. Kèm `(b)`: `authorized_read.py` gán nhầm `profile_id=project_filter`
trong `fp_request` (behavior-neutral — chỉ feed cursor fingerprint; scope thật nằm
trong `eff_text`) nhưng gây nhiễu audit.

### DEF-010 — Space-grant coarsening (grant space ≡ grant project)

DEF-004 Option B resolve space → tập `(profile_id, project_id)` sở hữu resource trong
space đó (`knowledge_space_resolver.py`, đọc `zm_corpus_sources`/`zm_corpus_units`),
rồi authorize MỌI event row thuộc cặp đó (`_scope_allows`). Hệ quả: grant đọc 1
knowledge_space hẹp thực tế cấp quyền đọc toàn bộ events của (profile, project) đó.
Fail-closed đúng; chấp nhận được tier cá nhân; KHÔNG đạt granular ủy quyền doanh nghiệp.

### DEF-011 — Authorization phụ thuộc derived state

Kết quả space-grant giờ đọc từ corpus projection thay vì canonical. Lần đầu tiên
derived data tham gia lớp bảo mật:
- Projection stale/thiếu → deny oan (an toàn nhưng khó chịu).
- Projection sai ownership → over-authorize (**security-relevant**): ai ghi được
  projection gián tiếp ảnh hưởng kết quả ủy quyền mà không đụng grants/policy.

### Liên quan: admin CLI đa-agent (backlog từ ADR-V141-01 Option A)

Grant CLI bị thu hồi ở v1.4.1 vì không nối control-plane thật. Nhu cầu quản trị grant
đa-agent sẽ quay lại cùng WP này nếu maintainer chọn mở rộng bề mặt ủy quyền.

## Phương án

### Phương án A — Minimal hardening (không đổi semantics)

1. **DEF-009a:** registry giữ JSONL canonical; thêm in-memory index + flush
   append-only (KHÔNG tạo SQLite index thứ hai); O(n)→O(1) amortized/update.
   Rebuildable từ canonical như mọi derived state.
2. **DEF-009b:** rename biến `fp_request` (fix thuần naming + test pin).
3. **DEF-011:** quy tắc vận hành bắt buộc: verify digest của corpus projection trước
   khi tin kết quả space-grant authorization (digest so với canonical replay);
   mismatch → fail-closed DENY + diagnostic.
4. **DEF-010:** chấp nhận coarsening, ghi documented limitation chính thức
   (MODULE-MAP + doctor INFO) — tier cá nhân vẫn dùng tốt.

- ✅ Nhỏ, đảo ngược được, không migration, không schema change.
- ✅ Khắc phục rủi ro bảo mật thật (DEF-011 over-authorize) bằng digest gate.
- ❌ Không mở khóa tier enterprise (granularity vẫn coarse).
- ❌ Digest gate thêm một lần replay/verify khi có space-grant (chi phí O(corpus),
  có thể cache theo mtime+size với rủi ro chấp nhận được).

### Phương án B — Enterprise authorization đúng nghĩa (granular mapping)

1. Tất cả nội dung A, cộng:
2. **DEF-010 thật:** ánh xạ event↔knowledge-space cấp row. Hai con đường kỹ thuật:
   - **B-schema:** migration additive thêm `knowledge_space_id` (hoặc bảng liên kết
     `zm_event_spaces`) vào event store, đi qua ingest/capture path — mapping trở thành
     canonical-side data, authorization không còn phụ thuộc projection.
   - **B-derived:** giữ resolution layer nhưng nâng lên unit-level (event_id ← unit
     source_ref) thay vì (profile, project)-level; kèm digest gate của A.
3. Admin CLI đa-agent wire vào control-plane thật (thiết kế lifecycle/lock/replay theo
   phương án B của ADR-V141-01).
4. Định vị rõ: đây là nền tảng tier enterprise post-v1.5 (commercial), tách gói
   kiểm thử + acceptance riêng.

- ✅ Giải triệt để cả ba defect; mở đường commercial enterprise tier.
- ✅ B-schema đưa mapping về canonical — khôi phục tinh thần ADR-009.
- ❌ Scope lớn: migration mới (schema version bump), chạm capture/ingest/access,
  acceptance riêng, gần như chắc chắn nhiều increment.
- ⚠️ B-derived rẻ hơn nhưng vẫn giữ derived-state trong authorization (chỉ thu hẹp,
  không loại trừ, rủi ro DEF-011).

### Phương án C — Tách tier: core cá nhân giữ A, enterprise = module riêng

Giữ Zero-Mem core tối giản (phương án A) và thiết kế authorization enterprise như
module/plug-in tách biệt (adapter boundary như ADR-002), không ép người dùng cá nhân
chở mã enterprise. Cần ADR con về contract giữa core ↔ module.

- ✅ Bảo vệ triết lý local-first/nhẹ cho tier cá nhân; doanh thu enterprise không
  làm phình core.
- ❌ Nhiều quyết định con (contract, packaging, licensing) — cần thiết kế trước khi
  hứa hẹn lịch.
- ⚠️ Rủi ro double-maintenance nếu contract không đóng băng sớm.

## So sánh theo tiêu chí Decision Style của dự án

| Tiêu chí | A (hardening) | B (granular) | C (tách tier) |
|---|---|---|---|
| Compliant spec/biên | ✅ | ✅ nếu B-schema | ✅ cần ADR con |
| Nhỏ nhất / dễ review | ✅ | ❌ | ⚠️ |
| Loại rủi ro DEF-011 | ✅ (digest gate) | ✅ nếu B-schema | ✅ |
| Granularity enterprise | ❌ | ✅ | ✅ (qua module) |
| Token/storage/runtime cost | thấp nhất | trung bình | trung bình |
| Đảo ngược được | ✅ | ⚠️ migration | ⚠️ |

## Khuyến nghị

**Lộ trình 2 bước:** chọn **A cho v1.5.0** (hardening + digest gate + documented
limitation — nhỏ, an toàn, đóng rủi ro security-relevant ngay), đồng thời phê duyệt
**khảo sát B-schema** (spike: chi phí migration event↔ks mapping, kích thước index,
ảnh hưởng ingest latency) làm đầu vào GATE tiếp theo trước khi cam kết B đầy đủ.
Phương án C chỉ mở khi B chứng minh chi phí chấp nhận được mà vẫn muốn tách product tier.

## Quyết định GATE-V150-1 (maintainer)

☐ CHỌN A — hardening-only cho v1.5.0
☐ CHỌN B — granular enterprise authorization trong v1.5
☐ CHỌN A + spike B-schema (khuyến nghị)
☐ CHỌN C — tách tier module riêng (cần ADR con)
☐ Khác: ………
