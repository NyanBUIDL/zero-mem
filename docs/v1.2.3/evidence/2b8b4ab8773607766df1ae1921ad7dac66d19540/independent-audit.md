# R-01 Initial Audit Record

This is a provisional R-01 evidence record. The implementation is source-bound to `2b8b4ab8773607766df1ae1921ad7dac66d19540`; final R-01 closure requires a fresh exact-tree independent review.

Confirmed by tests: only `zero_mem` is used by the public caller; the factory owns one runtime and one projection coordinator; canonical JSONL capture and derived SQLite reads are real; four read methods return typed results; foreign scope returns no items/provenance; disabled composition creates no runtime root; restart reopens the same durable event.

Open: independent review and final R-01 status update.
