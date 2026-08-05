# M0 Acceptance-Criteria Verification

**Milestone:** M0 — Policy & Architecture
**Verification status:** FULLY VERIFIED
**Authority:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx`

| Criterion | Exact requirement | Status | Verification method | Evidence | Remaining action |
|---|---|---|---|---|---|
| M0-A | “Tạo ARCHITECTURE.md làm source of truth từ tài liệu này.” / architecture decisions recorded | PASS | `python3 scripts/verify_m0_acceptance.py` | Exit code `0`; output `M0-A: PASS`; artifact `ARCHITECTURE.md` | None |
| M0-B | “Chốt taxonomy trace, provenance envelope và lifecycle state”; “Viết danh sách dữ liệu never_store và redaction patterns.” | PASS | `python3 scripts/verify_m0_acceptance.py` | Exit code `0`; output `M0-B: PASS`; artifacts `config/schemas/m0-contracts.yaml` and `config/policies/m0-security-retention.yaml` | None |
| M0-C | “Tạo 30-50 scenario benchmark, ưu tiên task continuation và stale-state.” | PASS | `python3 scripts/verify_m0_acceptance.py` | Exit code `0`; output `M0-C: PASS`; artifact `benchmark-plan.json` contains 30 unique scenarios, required classes, gold fields, and evaluation metrics | None |
| M0-D | “Chưa ingest toàn bộ 600 PDF; chỉ dùng corpus nhỏ khi test research route.” | PASS | Repository file inspection | No corpus files found; no full-corpus ingestion performed | None |
| M0-E | Baseline verification evidence is recorded | PASS | `.venv/bin/python -m pytest tests/ -q` and focused verification | Canonical: `.venv/bin/python -m pytest tests/ -q` → `3 passed in 0.00s`; focused: `PASS`, `exit_code=0`, `cleaned=True`; criterion verifier: `python3 scripts/verify_m0_acceptance.py` → `M0-A: PASS`, `M0-B: PASS`, `M0-C: PASS`, `exit_code=0` | None |

## Criterion-specific verifier

File: `scripts/verify_m0_acceptance.py`

Its assertions directly verify:

- M0-A: required architecture decision markers in `ARCHITECTURE.md`.
- M0-B: required schema, provenance, lifecycle, sensitivity, retention, redaction, and write-back policy sections.
- M0-C: 30–50 unique scenarios, including `task_continuation` and `stale_state`, plus required gold fields and evaluation metrics.

Command:

```text
python3 scripts/verify_m0_acceptance.py
```

Result:

```text
M0-A: PASS
M0-B: PASS
M0-C: PASS
exit_code=0
```

The artifact inspection command also returned `M0 artifact inspection: PASS` and confirmed all M0-A/M0-B/M0-C evidence files were present and non-empty.

## Incident record

A previous temporary verification script failed because `PosixPath` was emitted without the required import. This was a test-script generation error, not a product-code failure. The temporary script was cleaned up, corrected, and rerun successfully. The incident is resolved and non-product-related.

## Verification boundary

This verifies M0 policy and architecture artifacts only. It does not implement or verify M1 capture, storage runtime, retrieval, routing, profile enforcement, MCP, injection, graph, or Obsidian runtime behavior.