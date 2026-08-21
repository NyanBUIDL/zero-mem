# Zero-Mem v1.2.3 Task Board

| Row | Status | Current evidence / gate |
|---|---|---|
| R-00 | VERIFIED | Wiring, public verifier behavior, source-bound evidence, clean detached worktree, and independent review PASS at HEAD `32575eb5999401bb1a8fb55399c57cd5a7493ac7` |
| R-01 | NOT_STARTED | Blocked until R-00 verified |
| R-02 | NOT_STARTED | Blocked until R-01 verified |
| R-03 | NOT_STARTED | Blocked until R-02 verified |
| R-04 | NOT_STARTED | Ordered after R-03; Linux available, hosted platform evidence absent |
| R-05 | NOT_STARTED | Blocked until R-00…R-04 gates are satisfied |
| Final audit | NOT_STARTED | Requires exact final tree and fresh read-only review |

## Allowed status vocabulary

`NOT_STARTED` · `IN_PROGRESS` · `VERIFIED` · `BLOCKED` · `DEFERRED`

A row is not `VERIFIED` without wiring, black-box behavior, provenance, and independent review.
