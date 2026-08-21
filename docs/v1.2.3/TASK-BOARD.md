# Zero-Mem v1.2.3 Task Board

| Row | Status | Current evidence / gate |
|---|---|---|
| R-00 | VERIFIED | Wiring, public verifier behavior, source-bound evidence, clean detached worktree, and independent review PASS at HEAD `32575eb5999401bb1a8fb55399c57cd5a7493ac7` |
| R-01 | VERIFIED | Public factory, real JSONL/SQLite E2E, four reads, denied-scope isolation, disabled lifecycle, restart, evidence verifier, and independent review PASS at HEAD `4e427f102803a67a3a63b0f85e4863a540e77767` |
| R-02 | VERIFIED | Canonical read advertisement, direct/sidecar parity, EMPTY/DENIED normalization, bounded close truthfulness, verifier, checksums, and independent review PASS at HEAD `94c83b17375d8710547f7e07c1f1862b97534420` |
| R-03 | VERIFIED | Full Hermes host factory, real lifecycle, projection/read success, restart, duplicate hook/tool checks, verifier, checksums, and independent review PASS |
| R-04 | VERIFIED | Real GitHub Actions matrix run `32452599375`: Linux PASS, macOS PASS, Windows PASS; raw logs and checksums captured |
| R-05 | IN_PROGRESS | Release qualification, packaging, final reconciliation, and independent audit pending |
| Final audit | NOT_STARTED | Requires exact final tree and fresh read-only review |

## Allowed status vocabulary

`NOT_STARTED` · `IN_PROGRESS` · `VERIFIED` · `BLOCKED` · `DEFERRED`

A row is not `VERIFIED` without wiring, black-box behavior, provenance, and independent review.
