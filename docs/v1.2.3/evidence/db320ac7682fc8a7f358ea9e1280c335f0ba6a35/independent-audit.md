# R-01 Initial Audit Record

This provisional R-01 evidence is bound to exact source `db320ac7682fc8a7f358ea9e1280c335f0ba6a35`, which includes the bounded in-progress sidecar compatibility implementation but does not claim R-02 closure.

Confirmed by tests: only `zero_mem` is used by the public caller; the factory owns one runtime and one projection coordinator; canonical JSONL capture and derived SQLite reads are real; four read methods return typed results; foreign scope returns no items/provenance; disabled composition creates no runtime root; restart reopens the same durable event; full isolated suite is green.

Open: fresh independent review of this exact tree and final R-01 status update.
