# v1.6.0 Architecture

## Luồng dữ liệu

```text
Hermes/public adapter
  -> validated envelope (knowledge_space_ids optional)
  -> canonical append-only JSONL
  -> deterministic ingest/rebuild
  -> zm_meta (PRIMARY-KS compatibility)
  -> zm_event_spaces (full Multi-KS membership)
  -> structured / FTS / list / projection / graph
```

Canonical JSONL là nguồn sự thật. SQLite, FTS, graph, projection và junction đều
là derived state có thể xóa và dựng lại; không dùng derived repair để viết ngược
canonical.

## Storage semantics

- `knowledge_space_ids`: danh sách canonical mới, deduplicate nhưng giữ thứ tự.
- `knowledge_space_id`: field singular legacy được chấp nhận khi list không có.
- `zm_event_spaces(event_id, knowledge_space_id)`: primary key tổng hợp và index
  theo KS, lưu đầy đủ membership.
- `zm_meta.knowledge_space_id`: PRIMARY-KS, tức phần tử đầu tiên; giữ tương thích
  và phục vụ consumer singular.

## Authorization và retrieval

Structured query và FTS dùng correlated `EXISTS` trên junction để tránh duplicate
row. Request nhiều KS có semantics UNION. Space grant chỉ authorize event khi có
giao giữa grant và junction membership; junction thiếu thì fail closed.

`list_knowledge_space` đọc junction. Projection frontmatter xuất danh sách đầy
đủ. Graph giữ PRIMARY-KS theo ADR. Corpus store tiếp tục singular và không được
diễn giải như Multi-KS event storage.

## Tương thích và rollback

Migration v13 additive, backfill từ singular metadata hợp lệ và có downgrade bỏ
junction/index. Canonical cũ không cần rewrite. Rebuild là đường sửa derived state
chuẩn. Rollback code không được xóa canonical hoặc silently coarsen authorization.
