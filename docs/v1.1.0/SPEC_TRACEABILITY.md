# V1.1.0 Canonical Specification Traceability

**Status:** IN REVIEW

**Canonical source:** `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` at exact reconciliation point `78c4bb46b88b8ce9987c6882b24201e08b82a7f0`; SHA-256 `85b66cbfd380a756eba9266ec8021b331dfee232ab95bd030f287766ba628b9a`.

**Purpose:** Map each normative product requirement to one owning v1.1.0 planning location, testable acceptance, and release gate. Stable IDs below are references only; they do not rewrite the canonical requirement.

**Status vocabulary:** `COVERED`, `PARTIAL`, `MISSING`, `CONFLICT`, `DEFERRED`. `DEFERRED` is used only where DOCX §13.2 explicitly says “Sau MVP.”

## Architecture and Product Boundaries

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-ARCH-001 | §§1, 2.3, 3.1 | Zero-Mem is an external memory substrate, not only PDF retrieval | §§1, 4 | WP-01 | Target component ownership and full agent lifecycle | Generic project/task/research E2E | COVERED |
| REQ-ARCH-002 | §§2.3, 5.1 | Hermes remains orchestration/final action; sidecar owns memory operations | §§3–4 | WP-02, WP-07 | Core imports no Hermes; adapter-only mapping | Import graph + Hermes E2E | COVERED |
| REQ-ARCH-003 | §§3.2, 4.1, 13.1, 21.2 | Sidecar-first; minimize Hermes-core changes | §§3, 4.2 | WP-07 | Hermes core unchanged absent exact authorization | Source hash/import regression | COVERED |
| REQ-ARCH-004 | §§3.3, 5.1, 15 | Deterministic/local memory operations; routine LLM calls = 0 | §§3, 10 | WP-05, WP-06, WP-16 | All normal memory paths prove zero LLM/network | Static/runtime call guards | COVERED |
| REQ-ARCH-005 | §§2.3, 3.1, 5.1 | Core is agent-agnostic; Hermes is one adapter/client | §§4.1–4.2 | WP-02, WP-08, WP-21 | Generic client replaces Hermes without core rewrite | Generic/Hermes conformance | COVERED |
| REQ-ARCH-006 | §§3.3, 5, 9, 12 | Canonical, index, context, and Obsidian projection roles remain separate | §§3–4 | WP-01, WP-04, WP-22 | State owner/rebuild table is enforced | Delete-derived/rebuild + import tests | COVERED |
| REQ-ARCH-007 | §§3.3, 11.4, 15 | Global access remains bounded; only minimum evidence enters context | §§3, 10 | WP-05, WP-06, WP-20 | Candidate/evidence/token ceilings never widen | Budget/candidate/token benchmarks | COVERED |

## Trace, Provenance, Lifecycle, and Conflict

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-TRACE-001 | §6.1 | Preserve the canonical trace taxonomy | §3 | WP-04 | All trace types versioned/migratable | Schema/envelope fixtures | COVERED |
| REQ-TRACE-002 | §6.2, Appendix A | Every trace carries required provenance envelope fields | §§3, 9 | WP-04, WP-08 | 100% returned/persisted evidence has required provenance | Provenance completeness gate | COVERED |
| REQ-TRACE-003 | §6.3 | Assistant claim cannot become active fact without evidence | §3 | WP-05, WP-14 | Claim/evidence/verification transition is explicit | Negative activation fixtures | COVERED |
| REQ-TRACE-004 | §7.2 | Updates append and link replace/supersede; raw trace is not overwritten | §§3, 8 | WP-04, WP-14 | No canonical record silently rewritten | Hash/replay/supersession tests | COVERED |
| REQ-TRACE-005 | §§6.1, 7.2 | Derived summaries retain source trace IDs and are rebuildable | §§3–4 | WP-05, WP-22 | Summary/projection without source IDs is ineligible | Provenance/rebuild tests | COVERED |
| REQ-LIFE-001 | §7.1 | Support raw/observed/candidate/confirmed/active/superseded/conflicted/archived/deleted | §§3, 11 | WP-04, WP-14 | Lifecycle/state machine is complete and versioned | Transition matrix | COVERED |
| REQ-LIFE-002 | §7.2 | Active state is unique per entity+scope+key unless multi-value | §4.4 | WP-14 | Concurrent active conflict is preserved, not overwritten | Uniqueness/concurrency tests | COVERED |
| REQ-LIFE-003 | §§7.2–7.3 | Preserve all source/decision conflicts and resolution records | §§3, 4.4 | WP-14 | All positions/provenance remain visible | Source/decision conflict suite | COVERED |
| REQ-LIFE-004 | §§7.3, 11.4–11.5 | Unresolved conflict returns conflict set; no silent winner | §§3, 11 | WP-05, WP-14 | Retrieval/API returns explicit conflict set | Ranking/envelope conflict tests | COVERED |
| REQ-LIFE-005 | §§12.6, 20 | Distinguish projection, concurrent update, and stale conflicts | §4.4 | WP-14, WP-22 | Each conflict type has owner and outcome | Write-back/conflict matrix | COVERED |
| REQ-LIFE-006 | §§14.3–14.4 | Retention/delete spans raw, artifact, index, and projection with tombstone/versioning | §§3, 8–9 | WP-04, WP-14, WP-17 | Authorized delete leaves no orphan and preserves required audit | Retention/delete/recovery tests | COVERED |

## Profiles and Knowledge Spaces

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-PROF-001 | §8.1 | Profile is policy, not a directory | §4.3 | WP-20 | Profile model is independent of physical layout | Config/model tests | COVERED |
| REQ-PROF-002 | §8.2 | Profile covers behavior, priorities, access, tools, privacy, evidence, write policy | §§3, 4.3 | WP-13, WP-20 | Machine-readable schema covers all fields | Schema/precedence gate | COVERED |
| REQ-PROF-003 | §§8.3, 8.5, 12.5 | `profile_first` searches authorized global data with current-profile priority and bounded fallback | §§3, 4.3 | WP-20, WP-05 | Positive/fallback/no-leak scenarios pass | Mode conformance | COVERED |
| REQ-PROF-004 | §§8.3, 12.5 | `explicit_union` combines only named authorized profiles/spaces | §4.3 | WP-20 | All-or-nothing auth, dedupe, ranking, provenance | Union order/leak tests | COVERED |
| REQ-PROF-005 | §§8.3, 12.5, 17.1 | `isolated` uses only selected scope and has no global fallback | §§3, 4.3 | WP-20 | No cross-profile content/identifier/influence | Positive + negative isolation | COVERED |
| REQ-PROF-006 | §§8.3, 8.5 | `global` searches all caller-authorized scopes while remaining bounded | §4.3 | WP-20, WP-05 | Global does not raise privacy/authorization | Global-mode tests | COVERED |
| REQ-PROF-007 | §§8.3, 12.5 | `source_restricted` uses only explicit file/project/session/source scope | §§3, 4.3 | WP-20 | No neighbor/dense/graph escape or fallback | Source-restriction suite | COVERED |
| REQ-PROF-008 | §8.4, Appendix B | Behavior profile and knowledge scope are separate | §4.3 | WP-20, WP-08 | Independent typed fields and provenance | Cross-combination tests | COVERED |
| REQ-PROF-009 | §§8.5, 21.1 | Default is general profile, global access, profile-first, global fallback, bounded budget | §§3, 4.3, 10 | WP-13, WP-20 | Default config matches canonical behavior | Default-config conformance | COVERED |
| REQ-PROF-010 | §§8.2, 14.4 | Cross-profile writes require explicit authority and review | §§3, 4.3–4.4 | WP-20, WP-22 | Read never implies write; unauthorized edit fails closed | Write authorization tests | COVERED |

## Storage, Capture, and Ingestion

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-STORE-001 | §§1, 4.1, 9.1, 16.1, 21.1 | Canonical trace contract is SQLite + append-first JSONL | §§3–4 | WP-04, ADR-003 | Composite roles/commit outcomes/replay are explicit | Migration/replay/freshness suite | COVERED |
| REQ-STORE-002 | §§5.1, 9.1 | Large artifacts are separate, immutable/versioned, provenance-linked | §§3–4 | WP-04 | Artifact identity/version/source survives migration | Artifact/replay tests | COVERED |
| REQ-STORE-003 | §9.3 | FTS, dense, graph, and other retrieval indexes rebuild from canonical state | §§3, 8, 12 | WP-04, WP-14 | Deleting derived indexes loses no canonical data | Full rebuild equivalence | COVERED |
| REQ-STORE-004 | §§9.1, 9.3, 12 | Obsidian projection rebuilds from canonical+approved write-back | §§3, 4.4 | WP-22 | Clean projection rebuild is byte-equivalent | Projection rebuild gate | COVERED |
| REQ-STORE-005 | §§14.4, 16.4 | Schema migration is versioned and rollback-capable | §§8, 12 | WP-17 | Interrupted migration resumes/rolls back | Migration matrix | COVERED |
| REQ-STORE-006 | §§4.2, 19 | Backup/restore/rebuild/delete runbooks and verification exist | §§8, 12 | WP-14, WP-17, WP-18 | Backup verifies before mutation; restore/rebuild pass | Lifecycle gate | COVERED |
| REQ-CAP-001 | §§10.1–10.2 | Initial capture is observation-only and does not auto-inject | §§3, 4.2 | WP-07 | Capture does not mutate prompt/action | Non-interference tests | COVERED |
| REQ-CAP-002 | §§2.2, 10.1 | Capture messages, sessions, tools, files, skills, tasks, decisions/artifacts/verification where observable | §4.2 | WP-07 | Each class maps to verified hook/fallback/unavailable diagnostic | Hook coverage matrix | COVERED |
| REQ-CAP-003 | §§10.2, 14.2 | Redact/reject secrets before persistence | §§3, 9 | WP-04, WP-07 | Secret appears in no persistent/exposure boundary | Adversarial secret scan | COVERED |
| REQ-CAP-004 | §§6.2, 10.2, 10.4 | Validate schema, hash/dedupe, append, metadata, provenance | §§3–4 | WP-04 | Stable IDs/idempotency/provenance under retry/concurrency | Capture/replay tests | COVERED |
| REQ-CAP-005 | §§4.3, 10.3 | Document chunks retain page/section/offset/checksum and source version | §§3–4 | WP-04, WP-05 | Corpus evidence resolves to exact source locator | Corpus provenance tests | COVERED |
| REQ-CAP-006 | §§3.2, 10.1 | Do not turn every event into permanent memory | §§3, 4.4 | WP-14, WP-22 | Candidate/review gates separate raw from curated | Candidate lifecycle tests | COVERED |

## Retrieval, Routing, Evidence, and Token Budget

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-RETR-001 | §11.1 | Deterministic routes cover no/session/project/user/research/global/external-current | §§3, 10 | WP-06 | Route precedence/default/ambiguity documented and tested | Router conformance | COVERED |
| REQ-RETR-002 | §11.2 | Lexical/FTS handles exact terms, names, paths, dates, numbers | §4 | WP-05 | Exact/gold evidence is retrieved within bounded candidates | Retrieval quality gate | COVERED |
| REQ-RETR-003 | §§11.2, 16.1 | Local dense retrieval supports semantic mismatch without mandatory remote service | §§3, 4, 10 | WP-05 | Local adapter/auth/fallback/capability behavior tested | Dense/lexical comparison | COVERED |
| REQ-RETR-004 | §11.2 | Temporal view respects valid/current state | §§3–4 | WP-05, WP-14 | Stale/superseded cannot masquerade as current | Temporal fixtures | COVERED |
| REQ-RETR-005 | §11.2 | Relational/hierarchy view links entity, decision, task, artifact, parent/neighbor | §4 | WP-05 | Expansion remains authorized and bounded | Link/graph/neighbor tests | COVERED |
| REQ-RETR-006 | §11.2 | Profile/access filters run before final fusion | §§3, 9 | WP-05, WP-20 | Unauthorized content has zero influence | Influence/leakage tests | COVERED |
| REQ-RETR-007 | §11.3 | Ranking documents profile, verification, source quality, time, provenance, conflict factors | §4 | WP-05 | Versioned deterministic score/tie-break contract | Gold set + determinism | COVERED |
| REQ-RETR-008 | §§11.4, 15.2 | Injection is gated and bounded by primary/support/token budgets | §§3, 10 | WP-06 | Bounds cannot be raised by request/injected text | Budget/prompt-injection tests | COVERED |
| REQ-RETR-009 | §§11.4–11.5, Appendix C | Envelope includes route/scopes/evidence/provenance/conflicts/insufficiency/omitted/version/latency | §§4.1, 11 | WP-08 | Common response contract is complete across transports | Schema/conformance tests | COVERED |
| REQ-RETR-010 | §§7.3, 11.4–11.5 | Conflict/insufficient/stale/empty states are explicit | §§3, 11 | WP-05, WP-08, WP-14 | Distinct typed states; no silent fallback/winner | Error/envelope matrix | COVERED |

## Obsidian Knowledge Workspace

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-OBS-001 | §12.1 | Obsidian is the main human workspace, not raw store/retrieval engine | §§3, 4.4 | WP-22 | One readable Vault with strict role boundaries | Workspace E2E | COVERED |
| REQ-OBS-002 | §12.2 | Use one Vault with managed namespace | §4.4 | WP-13, WP-22 | Managed root containment; human/.obsidian untouched | Path/real-vault tests | COVERED |
| REQ-OBS-003 | §12.3 | Only eligible candidates become generated/curated projection with approval/verification | §4.4 | WP-22 | Ineligible/unverified/secret records do not project | Eligibility/security suite | COVERED |
| REQ-OBS-004 | §12.4 | Every note has ID/type/source/status/verification/sensitivity/profile/space/project/version metadata | §4.4 | WP-22 | 100% managed notes satisfy schema/provenance | Note-schema audit | COVERED |
| REQ-OBS-005 | §12.5 | Profile/knowledge-space modes apply consistently in the Vault | §§4.3–4.4 | WP-20, WP-22 | Mode conformance includes projection/views | Projection isolation tests | COVERED |
| REQ-OBS-006 | §12.6 | Bidirectional flow uses change queue, validation, authorization, conflict, approved write-back | §4.4 | WP-22 | Full review state machine executes | Write-back matrix | COVERED |
| REQ-OBS-007 | §12.6 | Obsidian edit never directly overwrites raw trace | §§3, 4.4 | WP-04, WP-22 | Only approved append-first record mutates canonical state | Hash/write-boundary tests | COVERED |
| REQ-OBS-008 | §§12.3, 12.6 | Projection is idempotent/versioned and updates without silent history loss | §4.4 | WP-22 | Identical rerun writes zero; stale/edit behavior explicit | Manifest/idempotency tests | COVERED |
| REQ-OBS-009 | §12.7 | Provide System Home, Profile Home, Project Home, Decision Log, Task/Current State, Candidate Review, Conflict Queue, Knowledge Space Index | §4.4 | WP-22 | Every required view exists and is source-backed | Required-view gate | COVERED |
| REQ-OBS-010 | §12.8 | Vault excludes secrets, raw logs/events, vectors/binary indexes, cache/never_store | §§3, 9 | WP-22 | Forbidden-data corpus yields zero occurrences | Vault secret/content scan | COVERED |
| REQ-OBS-011 | §12.9 | Vault rebuilds, avoids duplicate notes/sync loops, and preserves provenance | §§4.4, 11 | WP-22 | Byte-equivalent rebuild; no-loop marker; zero duplicates | Rebuild/no-loop tests | COVERED |
| REQ-OBS-012 | §§7, 12.6–12.9 | Approved/rejected/conflict/duplicate/stale/concurrent/unauthorized/malformed edits are explicit | §§4.4, 11 | WP-14, WP-22 | All outcomes preserve data and audit state | Full negative/positive matrix | COVERED |

## Agent Interface, MCP, and Hermes Access

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-API-001 | §§4.2, 13.1 | Sidecar listens for events and exposes retrieval API with minimal Hermes core change | §§4.1–4.2 | WP-07, WP-21 | Packaged local lifecycle and client activation | Installed E2E | COVERED |
| REQ-API-002 | §§4.2, 13, 16.1 | Interface uses MCP or approved local HTTP/Unix socket; local contract is required | §4.1 | WP-21 | MCP baseline; optional bindings are conformant/local-only | Transport conformance/security | COVERED |
| REQ-API-003 | §13.1 | Tool schema is small/stable and returns structured errors | §4.1 | WP-08, WP-21 | Common versioned request/response/error types | Contract snapshot tests | COVERED |
| REQ-API-004 | §13.2 | `zero_mem.search` is an MVP capability | §4.1 | WP-08, WP-21 | Full purpose/input/output/scope/auth/error/timeout contract | Capability conformance | COVERED |
| REQ-API-005 | §13.2 | `zero_mem.get_trace` is an MVP capability | §4.1 | WP-08, WP-21 | Non-probing authorized trace lookup/expansion | Capability conformance | COVERED |
| REQ-API-006 | §13.2 | `zero_mem.get_task_state` is an MVP capability | §4.1 | WP-08, WP-21 | Verified current state with conflict/stale/provenance | Capability conformance | COVERED |
| REQ-API-007 | §13.2 | `zero_mem.get_decisions` is an MVP capability | §4.1 | WP-08, WP-21 | Active/superseded/conflicted decision contract | Capability conformance | COVERED |
| REQ-API-008 | §13.1 | Read-only retrieval precedes write-back; native memory holds only short config/preferences | §§4.1–4.2 | WP-07, WP-08, WP-22 | Read tools expose no raw/admin/write; write-back is separate reviewed path | Tool-surface/write-boundary tests | COVERED |
| REQ-API-009 | §13.2 “Sau MVP” | Reserve `zero_mem.expand` for bounded expansion after MVP | §4.1 | WP-08 | Typed unavailable until separately authorized | Reserved-name/version test | DEFERRED |
| REQ-API-010 | §13.2 “Sau MVP” | Reserve `zero_mem.propose_memory` for candidate-only proposal after MVP | §4.1 | WP-08, WP-22 | Cannot curate/direct-write; typed unavailable | Reserved-name/write test | DEFERRED |
| REQ-API-011 | §13.2 “Sau MVP” | Reserve `zero_mem.project_to_obsidian` after MVP | §4.1 | WP-08, WP-22 | Cannot bypass projection/review policy; typed unavailable | Reserved-name/policy test | DEFERRED |

## Security, Privacy, Performance, Migration, and Release

| Requirement ID | Canonical Source | Requirement | MASTER_PLAN | Work Package | Acceptance Criteria | Test/Gate | Status |
|---|---|---|---|---|---|---|---|
| REQ-SEC-001 | §14.1 | Enforce public/internal/private/secret classes | §§3, 9 | WP-13, WP-14 | Privacy ceiling and persistence policy are typed | Sensitivity matrix | COVERED |
| REQ-SEC-002 | §14.2 | Raw secrets never persist; redaction/rejection emits safe audit | §§3, 9 | WP-04, WP-15, WP-22 | Zero secret occurrence across all boundaries | Adversarial scan | COVERED |
| REQ-SEC-003 | §§8, 13–14 | Local API caller is explicitly identified/authorized; local is not trusted | §9 | WP-21 | Unauthorized local callers fail closed | Endpoint threat tests | COVERED |
| REQ-SEC-004 | §§8.3, 17.1, 20 | Profile isolation prevents cross-profile leakage/influence | §§3, 9 | WP-20 | Full leakage matrix passes | Isolation gate | COVERED |
| REQ-SEC-005 | §§8.3, 12.5 | Source restriction is enforced before retrieval/expansion/projection | §§3, 9 | WP-20, WP-22 | No source/link/cache/projection escape | Source-restriction gate | COVERED |
| REQ-SEC-006 | §§12.6, 14, 20 | Data/Vault paths and symlinks remain inside authorized roots | §9 | WP-13, WP-22 | Traversal/symlink/alias tests fail closed | Path-safety gate | COVERED |
| REQ-SEC-007 | §§8.2, 12.6, 14.4 | Write boundaries require authorization, review, audit, and no privilege escalation | §§3, 9 | WP-20, WP-22 | Unauthorized/malformed/concurrent writes do not mutate | Write-boundary gate | COVERED |
| REQ-SEC-008 | §14.4 | Migrations/write-back are versioned, rollback-capable, and audited | §§8–9 | WP-14, WP-17, WP-22 | Audit/recovery/rollback records are safe and complete | Fault/migration tests | COVERED |
| REQ-PERF-001 | §§3.3, 15.1–15.2 | Memory-operation LLM calls = 0 | §§3, 10 | WP-05, WP-06, WP-16 | Runtime/static proof across all normal operations | Zero-LLM gate | COVERED |
| REQ-PERF-002 | §§11.4, 15.2 | Evidence is top-k/token bounded with one controlled expansion | §§3, 10 | WP-06 | Defaults and ceilings are enforced | Token/candidate tests | COVERED |
| REQ-PERF-003 | §§15.3, 17.2 | Measure retrieval p50/p95 and enforce machine-specific local budget | §10 | WP-03, WP-16 | Initial <2 s proposal is measured/approved, not assumed | Benchmark gate | COVERED |
| REQ-PERF-004 | §§15.3, 17.3 | Measure tokens, Recall@K, MRR/nDCG, citation, stale/conflict, continuation | §§10–11 | WP-16 | Gold-evidence benchmark publishes methods/results | Quality benchmark | COVERED |
| REQ-PERF-005 | §17.2 | Supported capture succeeds ≥99% with retry/dead-letter diagnostics | §§10–11 | WP-07, WP-16 | Declared event-class harness meets target | Capture benchmark | COVERED |
| REQ-PERF-006 | §17.2 | Evidence provenance completeness is 100% | §§3, 11 | WP-08, WP-16 | Every evidence item passes schema | Provenance gate | COVERED |
| REQ-PERF-007 | §17.2 | Task continuation succeeds ≥90% of scenarios | §§10–11 | WP-08, WP-16 | New-session state benchmark meets target | Continuation benchmark | COVERED |
| REQ-MIG-001 | §§14.4, 16.4, 19 | V1.0.0→V1.1.0 migration is explicit; clean install is not assumed | §8 | WP-17 | Populated/empty/stale/corrupt fixtures migrate | Migration gate | COVERED |
| REQ-MIG-002 | §§9.3, 16.4 | Existing JSONL/artifacts remain readable and raw hashes preserved | §8 | WP-04, WP-17 | No unapproved canonical rewrite | Hash/replay tests | COVERED |
| REQ-MIG-003 | §9.3 | Existing SQLite/index/projection state is migrated or rebuilt safely | §8 | WP-17 | Logical identities/watermarks match | Rebuild comparison | COVERED |
| REQ-MIG-004 | §§8, 13, 19 | Profiles/grants/config/Hermes/local interface/M9 projection state migrate | §8 | WP-13, WP-17 | No silent path/scope/version change | Compatibility fixture matrix | COVERED |
| REQ-MIG-005 | §§14.4, 16.4 | Migration is idempotent/interruption-safe with backup/rollback | §8 | WP-14, WP-17 | Every checkpoint resumes or rolls back | Fault-injection gate | COVERED |
| REQ-MIG-006 | §§16.4, 18–19 | Backward compatibility/deprecations/removal are documented/tested | §§8, 12 | WP-09, WP-10, WP-17, WP-18 | Exact-wheel upgrade/rollback/uninstall pass | Lifecycle matrix | COVERED |
| REQ-TEST-001 | §16.4 | Every module has schema/migration, unit/failure, logs/metrics, provenance, security, runbook/rollback | §§6, 11 | Every owning WP; WP-16 | WP quality/acceptance inventory complete | Structural + executable gate | COVERED |
| REQ-TEST-002 | §17.1 | Required tests cover capture, redaction, provenance, state, profiles, retrieval, conflict, continuation, token | §11 | WP-16 | All categories have passing evidence | Test inventory gate | COVERED |
| REQ-TEST-003 | §§17.2–17.3 | Acceptance/benchmarks use explicit thresholds and gold evidence | §§10–11 | WP-16 | Raw evidence, repetitions, environment and variance recorded | Benchmark-quality gate | COVERED |
| REQ-TEST-004 | §18 | Delivery follows policy→capture→store→retrieval→routing→profiles→MCP→injection→Obsidian | §7 | WP-01, WP-19 | Dependency graph is acyclic and gates predecessors | Graph/order validation | COVERED |
| REQ-TEST-005 | Appendix D | Before code, canonical/Obsidian/trace/lifecycle/redaction/profiles/benchmarks/events/backup are decided | §§3–7, 13 | WP-00, WP-01 | No implementation authorization before design gate | Governance gate | COVERED |
| REQ-TEST-006 | Appendix E | Controlled injection requires redaction/isolation/continuation/stale/provenance/latency/token/kill-switch gates | §§9–11 | WP-06, WP-07, WP-16 | All pre-injection gates pass | Injection release gate | COVERED |
| REQ-TEST-007 | §§19–20 | Ongoing health/review/conflict/stale/index lag/backup/benchmark/profile audits are planned | §§9–12 | WP-15, WP-18, WP-19 | Operations/runbooks/status support cycles | Operational readiness | COVERED |
| REQ-TEST-008 | Full specification | Release requires complete canonical traceability with no unresolved mandatory gap | §§11–13 | WP-19 | No mandatory MISSING/PARTIAL/CONFLICT | Spec parity NO-GO gate | COVERED |

## Completeness Gate

Planning is not aligned when a mandatory row is `MISSING`, `PARTIAL`, or `CONFLICT`. A future change to the canonical DOCX, exact master, ADR decision, WP owner, acceptance criterion, or release gate must update this file in the same planning change. `TRACEABILITY.md` remains the separate F-001–F-014 implementation-finding map.
