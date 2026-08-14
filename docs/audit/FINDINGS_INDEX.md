# Audit Findings Index — Observed Truth

Reconciled against `origin/master` at `78c4bb46b88b8ce9987c6882b24201e08b82a7f0` on 2026-08-14. Detailed baseline evidence, exact-master links, delta reasons, owners, and closure tests are in [FINDINGS_RECONCILIATION.md](FINDINGS_RECONCILIATION.md).

## Evidence Rules

Finding IDs are stable. `Confirmed` is directly demonstrated by source or a reproducible run; `Likely` needs production/scale confirmation; `Architectural concern` identifies a mismatch with the stated reusable-memory goal; `Optimization opportunity` is not a correctness failure. A finding is not implementation authorization.

| Finding | Category | Severity | Evidence | Exact-master location | Primary V1.1.0 WP | Reconciliation status |
|---|---|---:|---|---|---|---|
| F-001 | Integration / Data | P1 | Confirmed | `zero_mem/hermes_integration.py:HermesBoundary.register` | WP-07 | CONFIRMED OPEN |
| F-002 | Data / Architecture / Performance | P1 | Confirmed | `src/integration/capture_adapter.py:adapt_mapped_event`; `src/storage/ingest.py:ingest_file` | WP-04 | CONFIRMED OPEN |
| F-003 | Performance / Scale / Data | P1 | Confirmed | `src/storage/jsonl_capture.py:JsonlCaptureStore._load`; `src/storage/ingest.py:ingest_file` | WP-04 | CONFIRMED OPEN |
| F-004 | Reliability / Data / Scale | P1 | Confirmed | `src/storage/jsonl_capture.py:JsonlCaptureStore.append` | WP-04 | CONFIRMED OPEN |
| F-005 | Portability / Dependencies / Compatibility | P1 | Confirmed | `packaging/install.py:_runtime_python`; `zero_mem/commands_doctor.py:collect` | WP-10 | CONFIRMED OPEN |
| F-006 | Configuration / Integration / Scale | P1 | Confirmed | `src/integration/zero_mem_runtime.py:configure` | WP-13 | CONFIRMED OPEN |
| F-007 | Compatibility / Integration / Configuration | P1 | Confirmed | `zero_mem/hermes_integration.py:IntegrationConfig.from_dict` | WP-07 | CONFIRMED OPEN |
| F-008 | Performance / Scale / Integration | P1 | Confirmed | `src/corpus/retrieval.py:retrieve_corpus` | WP-05 | CONFIRMED OPEN |
| F-009 | Retrieval / Performance / Cost | P2 | Architectural concern | `src/retrieval/search.py:search_text` | WP-05 | CONFIRMED OPEN |
| F-010 | Performance / Cost | P2 | Optimization opportunity | `src/storage/jsonl_capture.py:append`; `src/storage/ingest.py:_commit_outcome` | WP-04 | CONFIRMED OPEN |
| F-011 | Architecture / Integration / Compatibility | P2 | Architectural concern | `zero_mem/__init__.py`; internal `src/*` surface | WP-08 | CONFIRMED OPEN |
| F-012 | Configuration / Portability / Integration | P2 | Architectural concern | `zero_mem/paths.py:data_root`; `src/integration/bridge_config.py:_safe_root` | WP-13 | CONFIRMED OPEN |
| F-013 | Observability / Reliability | P2 | Confirmed | `src/integration/hermes_registration.py`; `zero_mem/commands_doctor.py:collect` | WP-15 | CONFIRMED OPEN |
| F-014 | Performance / Reliability / Sync-Async | P2 | Likely | `src/integration/m7/injection_adapter.py:_make_service`, `process` | WP-11 | NEEDS VERIFICATION |

Full baseline rationale and measurements remain in [SYSTEM_AUDIT.md](SYSTEM_AUDIT.md). Planned responses are in [TRACEABILITY.md](../v1.1.0/TRACEABILITY.md), never in this observed-truth index. The four PKG-7 findings are a separate, resolved namespace and are not reintroduced here.
