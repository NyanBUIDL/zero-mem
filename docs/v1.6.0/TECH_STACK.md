# v1.6.0 Tech Stack

## Runtime

- CPython `>=3.11,<3.14`.
- Standard library là core dependency; không thêm runtime dependency cho Multi-KS.
- SQLite cho derived relational/FTS state; JSONL cho canonical events.
- Public package/CLI trong `zero_mem`; implementation nội bộ trong `src`.

## Test và build

- `pytest` và `PyYAML` qua extra `test`.
- `build` qua extra `ci`.
- GitHub Actions: Ubuntu, Windows, macOS × Python 3.11, 3.12, 3.13.
- Benchmark junction là script stdlib-only tại
  `benchmarks/v160_junction_lookup.py`.

## Lựa chọn có chủ đích

- Junction quan hệ thay vì JSON array trong SQLite để có index và predicate rõ.
- Correlated `EXISTS` thay vì JOIN trực tiếp để không nhân bản event.
- Không thêm ORM, vector database, network service hoặc AI call vào memory path.
- Corpus PDF nâng cao vẫn là extra tooling, không phải core runtime dependency.
