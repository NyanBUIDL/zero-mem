# Evidence DEF-037 / DEF-038

DEF-037 được xác nhận là lỗi Windows junction của PKG-2 và đã sửa tại commit
`ff694ad`. DEF-038 là lỗi portability của test crash durability, được đóng bằng
retry Windows-only cho đúng lỗi `disk I/O error` trong một cửa sổ tối đa 1 giây.

- Raw probe/checksum giữ nguyên: [`audit/evidence-v160-def037`](../../../../audit/evidence-v160-def037/).
- Defect narrative/addenda: [`docs/defects/DEFECT-REGISTRY.md`](../../../defects/DEFECT-REGISTRY.md).
- PKG-2 focused: `13 passed`.
- DEF-003: `2 passed`, sau đó hard-kill test `1 passed` ×2.
- Full suite: `3618 passed, 38 skipped, 0 failed`.

Không xóa các addendum cũ dù root cause ban đầu bị supersede; registry giữ lịch
sử điều tra và closure mới là kết luận hiện hành.
