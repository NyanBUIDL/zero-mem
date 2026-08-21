# Zero-Mem v1.2.3 Task Board

| Row | Status | Current evidence / gate |
|---|---|---|
| R-00 | VERIFIED | Wiring, public verifier behavior, source-bound evidence, clean detached worktree, and independent review PASS at HEAD `32575eb5999401bb1a8fb55399c57cd5a7493ac7` |
| R-01 | VERIFIED | Public factory, real JSONL/SQLite E2E, four reads, denied-scope isolation, disabled lifecycle, restart, evidence verifier, and independent review PASS at HEAD `4e427f102803a67a3a63b0f85e4863a540e77767` |
| R-02 | IN_PROGRESS | Canonical read capability advertisement and sidecar parity implementation green; evidence and independent review pending |
| R-03 | NOT_STARTED | Blocked until R-02 verified |
| R-04 | NOT_STARTED | Ordered after R-03; Linux available, hosted platform evidence absent |
| R-05 | NOT_STARTED | Blocked until R-00…R-04 gates are satisfied |
| Final audit | NOT_STARTED | Requires exact final tree and fresh read-only review |

## Allowed status vocabulary

`NOT_STARTED` · `IN_PROGRESS` · `VERIFIED` · `BLOCKED` · `DEFERRED`

A row is not `VERIFIED` without wiring, black-box behavior, provenance, and independent review.
