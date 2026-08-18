# WP Tracker — V1.1 Durable Roadmap

Source: `artifacts/tasks/task-manifest.json` and planning ref `2f1763f1335326b83bf90f263cada5c3715f21eb`.

| WP | Title | Phase | Dependencies | Current durable state |
|---|---|---:|---|---|
| WP-00 | Baseline Reconciliation and Delta Audit | A | — | VERIFIED |
| WP-01 | Architecture | A | WP-00 | VERIFIED |
| WP-02 | Core Boundaries | A | WP-01 | VERIFIED (implementation checkpoint `cfcb1f0`; Phase A closure verified) |
| WP-03 | Performance | B | WP-04 | VERIFIED |
| WP-04 | Storage Freshness Retention Delete | B | WP-13, WP-02 | VERIFIED |
| WP-05 | Retrieval | C | WP-04 | NOT_STARTED |
| WP-06 | Context Efficiency | C | WP-05, WP-20, WP-08 | NOT_STARTED |
| WP-07 | Hermes Integration | E | WP-06, WP-08, WP-15, WP-20, WP-21 | NOT_STARTED |
| WP-08 | Agent-Agnostic API | B | WP-04, WP-02 | VERIFIED |
| WP-09 | Compatibility | C | WP-08 | NOT_STARTED |
| WP-10 | Installation Packaging | F | WP-07, WP-09, WP-17, WP-21, WP-22 | NOT_STARTED |
| WP-11 | Sync Async | C | WP-08 | NOT_STARTED |
| WP-12 | Multi Agent Process | C | WP-11 | NOT_STARTED |
| WP-13 | Configuration | B | WP-02 | VERIFIED |
| WP-14 | Reliability Recovery Conflict | D | WP-04, WP-08, WP-12 | NOT_STARTED |
| WP-15 | Observability | D | WP-14 | NOT_STARTED |
| WP-16 | Testing Benchmarks | G | all implementation/consumer WPs | NOT_STARTED |
| WP-17 | Migration v1.0 to v1.1 | F | WP-07, WP-09, WP-14, WP-20, WP-21, WP-22 | NOT_STARTED |
| WP-18 | Documentation DX | F | WP-07, WP-08, WP-10, WP-20, WP-21, WP-22 | NOT_STARTED |
| WP-19 | Release Readiness | G | WP-16, WP-17, WP-18, WP-20, WP-21, WP-22 | NOT_STARTED |
| WP-20 | Profiles Knowledge Spaces | C | WP-05, WP-08 | NOT_STARTED |
| WP-21 | Local Sidecar MCP | E | WP-08, WP-12, WP-14, WP-15 | NOT_STARTED |
| WP-22 | Obsidian Workspace Writeback | E | WP-04, WP-14, WP-20 | NOT_STARTED |

**Count:** 23 WPs, 23 unique IDs, no invented WP.
**Next incomplete WP:** WP-05
**Implementation authorization:** Phase C bounded scopes require materialization.
