# ADR-007: Profile and Knowledge-Space Access Semantics

**Status:** PROPOSED

## Canonical Source

- `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §§8.1–8.5, 11.2, 12.5, 17.1, 19.2–19.3, 21.1 and Appendix B.
- Exact-master `AGENTS.md` architecture constraints and `docs/architecture/ARCHITECTURE.md` §6.

## Context

Profiles are policies, not physical directories. The canonical default is global read access with profile-first ranking and bounded evidence; explicit union, isolated, global, and source-restricted modes change retrieval scope without changing behavior identity. Existing v1.1.0 planning did not define these modes normatively and WP-12 incorrectly excluded cross-profile retrieval by default.

## Decision

V1.1.0 implements the semantics in `PROFILE_KNOWLEDGE_SPACE_CONTRACT.md`. Authorization determines the maximum readable set before ranking. The access mode then narrows or prioritizes only within that authorized set. `profile_first` may search authorized global/shared data with current-profile priority and bounded fallback; it is not permission escalation. `isolated` and `source_restricted` fail closed and never fall back. Cross-profile writes always require explicit WRITE authorization plus review/verification.

Behavior profile, active profile, target profiles, knowledge spaces, project/session/source filters, privacy ceiling, and evidence budget are separate typed fields. No path, folder, process state, or previous request may infer identity or authorization.

## Consequences

- WP-20 owns mode semantics and policy conformance.
- WP-05 consumes the resolved authorized scope and owns bounded ranking.
- WP-08 exposes the fields without reimplementing policy.
- WP-12 owns physical runtime/process isolation, not retrieval-mode semantics.

## Rejected Alternatives

- Treating each profile as a separate Vault or filesystem root by definition.
- Making isolated retrieval the default.
- Allowing global fallback from isolated or source-restricted mode.
- Conflating cross-profile read capability with cross-profile write authority.
