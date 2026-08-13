# Zero-Mem Documentation Map

| Purpose | Location | Read when |
|---|---|---|
| Agent rules and write authorization | [`../AGENTS.md`](../AGENTS.md) | First, every session |
| Released v1.0.0 identity and exact-master relationship | [`baseline/`](baseline/) | Before interpreting source or planning changes |
| Audit evidence, exact-master reconciliation, and stable findings | [`audit/`](audit/) | When a task refers to a finding, delta, or uncertainty |
| V1.1.0 planning, status, ADRs, and WPs | [`v1.1.0/`](v1.1.0/) | When selecting or executing planning work |

Start with [`baseline/V1.0.0_BASELINE.md`](baseline/V1.0.0_BASELINE.md), then [`v1.1.0/STATUS.md`](v1.1.0/STATUS.md). The current delta record is [`audit/MASTER_RECONCILIATION.md`](audit/MASTER_RECONCILIATION.md), and finding-level dispositions are in [`audit/FINDINGS_RECONCILIATION.md`](audit/FINDINGS_RECONCILIATION.md).

Do not merge truth types: exact-master source and executable evidence are implementation truth, `audit/` is observed truth, and `v1.1.0/` is planned truth. Historical acceptance/status artifacts do not authorize v1.1.0 implementation.
