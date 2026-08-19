# Zero-Mem v1.2 Work Packages

This index scaffolds WP-24 through WP-35. It does not authorize implementation or advance any work-package state.

| WP | Name | Dependencies | Status | Path |
|---|---|---|---|---|
| WP-24 | Correctness Backport | none | `VERIFIED` | [wp-24-correctness-backport](./wp-24-correctness-backport/) |
| WP-25 | Runtime Ownership | WP-24 | `VERIFIED` | [wp-25-runtime-ownership](./wp-25-runtime-ownership/) |
| WP-26 | Projection | WP-25 | `VERIFIED` | [wp-26-projection](./wp-26-projection/) |
| WP-27 | Recovery | WP-25, WP-26 | `VERIFIED` | [wp-27-recovery](./wp-27-recovery/) |
| WP-28 | Public API | WP-25, WP-26 | `VERIFIED` | [wp-28-public-api](./wp-28-public-api/) |
| WP-29 | Authorization | WP-28 | `VERIFIED` | [wp-29-authorization](./wp-29-authorization/) |
| WP-30 | Sidecar | WP-28, WP-29 | `VERIFIED` | [wp-30-sidecar](./wp-30-sidecar/) |
| WP-31 | Hermes | WP-25, WP-29, WP-30 | `VERIFIED` | [wp-31-hermes](./wp-31-hermes/) |
| WP-32 | Context | WP-29, WP-31 | `VERIFIED` | [wp-32-context](./wp-32-context/) |
| WP-33 | Retrieval Evolution | WP-32 | `VERIFIED` | [wp-33-retrieval-evolution](./wp-33-retrieval-evolution/) |
| WP-34 | Profiles/Knowledge/Obsidian | WP-29, WP-32, WP-33 | `VERIFIED` | [wp-34-profiles-knowledge-obsidian](./wp-34-profiles-knowledge-obsidian/) |
| WP-35 | Release Qualification | all required previous WPs | `VERIFIED` | [wp-35-release-qualification](./wp-35-release-qualification/) |

## State machine

```text
NOT_STARTED
→ PLANNING
→ READY
→ IMPLEMENTING
→ VERIFYING
→ VERIFIED
```

Additional states may be used when evidenced:

```text
BLOCKED
FAILED_VERIFICATION
```

State transitions require explicit repository evidence and the applicable authorization, planning, implementation, and verification gates. This scaffolding task leaves every WP at `NOT_STARTED`; no state transition is implied by v1.1 history, the Master Plan, or the existence of these files.
