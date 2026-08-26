# v1.6.0 — Canonical Evidence Index

Đây là chỉ mục evidence chính thức cho Multi-KS v1.6.0. Chỉ mục không di chuyển,
đổi tên hoặc sửa raw evidence lịch sử; nó tạo một đường dẫn ổn định để audit.

## Work-package index

| WP | Implementation | Evidence |
|---|---|---|
| C01 | Capture list contract | [evidence/C01](evidence/C01/README.md) |
| C02 | Migration/junction | [evidence/C02](evidence/C02/README.md) |
| C03 | Rebuild | [evidence/C03](evidence/C03/README.md) |
| C04 | Structured authorization | [evidence/C04](evidence/C04/README.md) |
| C05 | FTS parity | [evidence/C05](evidence/C05/README.md) |
| C06 | Graph PRIMARY-KS | [evidence/C06](evidence/C06/README.md) |
| C07 | Knowledge-Space listing | [evidence/C07](evidence/C07/README.md) |
| C08 | Projection parity | [evidence/C08](evidence/C08/README.md) |
| C09 | Corpus boundary | [evidence/C09](evidence/C09/README.md) |
| C10 | Acceptance/release gates | [evidence/C10](evidence/C10/README.md) |
| DEF-037/038 | Windows junction + crash-test portability | [evidence/DEF-037](evidence/DEF-037/README.md) |

## Vị trí lịch sử được giữ nguyên

- C2–C4 raw logs: [audit/evidence-v160-c2](../../audit/evidence-v160-c2/).
- DEF-037 probe/checksum: [audit/evidence-v160-def037](../../audit/evidence-v160-def037/).
- Probe DEF-034 ban đầu: [docs/v1.6/probes](../v1.6/probes/).
- Acceptance milestone trước v1.6: [docs/acceptance](../acceptance/).
- Evidence/handoff lịch sử khác: [artifacts/evidence](../../artifacts/evidence/)
  và [artifacts/handoffs](../../artifacts/handoffs/).

Tên `audit/evidence-v160-c2` chứa cả C3/C4 là di sản đã nghiệm thu. Không rename.

## Qualification local cuối

- Platform: Windows; CPython 3.12.13.
- Machine state + compile: PASS.
- C1–C10 focused: `66 passed`.
- PKG-2 Windows: `13 passed`.
- Full unit/integration: **3618 passed, 38 skipped, 0 failed**.
- Benchmark: covering primary-key index; median 10.3 / 10.2 / 14.0 µs ở
  1k / 10k / 100k event trên máy qualification.
- Remote run 1: [GitHub Actions 32999483909](https://github.com/NyanBUIDL/zero-mem/actions/runs/32999483909)
  đạt 7/9 cell; Windows 3.11 phát hiện junction detection thiếu fallback trước
  Python 3.12 và DEF-036 timing test; Windows 3.13 phát hiện cùng timing test.
  Hai lỗi đã được sửa bằng reparse-attribute detection và blocking barrier;
  follow-up 9-cell run là gate hiện hành.

## Quy tắc cập nhật

Evidence mới ghi vào thư mục WP tương ứng. Raw CI sau push phải ghi run URL, exact
SHA và verdict; không thay local verdict bằng claim remote khi workflow chưa xong.
