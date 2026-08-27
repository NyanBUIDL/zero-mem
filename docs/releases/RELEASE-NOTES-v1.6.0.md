# RELEASE NOTES — Zero-Mem v1.6.0

**Trạng thái:** CANDIDATE — chưa tạo tag/release; cần CI 9-cell xanh trên SHA phát hành.

## Điểm chính

- Canonical capture hỗ trợ tùy chọn `knowledge_space_ids: list[str]`, giữ thứ tự đầu tiên và tương thích producer cũ.
- Migration v13 thêm junction derived `zm_event_spaces`; `zm_meta.knowledge_space_id` tiếp tục giữ PRIMARY-KS để tương thích.
- Structured read, `get_event`, trace read và FTS dùng cùng ranh giới authorization qua junction với UNION semantics, không nhân bản event.
- `list_knowledge_space`, M8 graph và projection frontmatter phản ánh membership Multi-KS.
- Corpus unit vẫn có một `knowledge_space_id`; đây là ranh giới được ghi rõ, không âm thầm đổi schema corpus.
- PKG-2 nhận diện và quản lý an toàn cả symlink lẫn Windows junction (DEF-037).
- Guided `zero-mem wizard` gộp setup, Hermes tùy chọn và doctor; có interactive
  mode, non-interactive JSON, validation-before-mutation và không echo identity.

## Tương thích và rollback

- Canonical cũ với `knowledge_space_id` singular vẫn ingest và backfill junction.
- Migration v13 chỉ thêm derived table/index; rollback bỏ junction, không sửa hay xóa canonical JSONL.
- Cursor được ràng buộc với tập Knowledge-Space đã chuẩn hóa; client nên bắt đầu lại từ trang đầu sau khi nâng cấp major query semantics.

## Qualification

- Acceptance C10: capture → canonical → ingest → junction → structured/FTS/grant, gồm cả legacy singular.
- Benchmark chính thức: `benchmarks/v160_junction_lookup.py`.
- Workflow active: `.github/workflows/v1.6.0-qualification.yml` trên Linux/Windows/macOS × Python 3.11/3.12/3.13.
- Core SHA `6433fb2` đã đạt 9/9; exact SHA chứa DX01 phải đạt lại 9/9 trước tag.
