# Evidence DEF-037 / DEF-038

DEF-037 được xác nhận là lỗi Windows junction của PKG-2 và đã sửa tại commit
`ff694ad`. DEF-038 là lỗi portability của test crash durability, được đóng bằng
retry Windows-only cho đúng lỗi `disk I/O error` trong một cửa sổ tối đa 1 giây.

- Raw probe/checksum giữ nguyên: [`audit/evidence-v160-def037`](../../../../audit/evidence-v160-def037/).
- Defect narrative/addenda: [`docs/defects/DEFECT-REGISTRY.md`](../../../defects/DEFECT-REGISTRY.md).
- PKG-2 focused: `13 passed`.
- DEF-003: `2 passed`, sau đó hard-kill test `1 passed` ×2.
- Full suite: `3618 passed, 38 skipped, 0 failed`.
- Remote run 1 bổ sung compatibility finding: Python 3.11 không có
  `Path.is_junction()`. Follow-up dùng `st_file_attributes` với
  `FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY`, cùng đường code đã
  được probe cục bộ trên junction thật.

Không xóa các addendum cũ dù root cause ban đầu bị supersede; registry giữ lịch
sử điều tra và closure mới là kết luận hiện hành.
