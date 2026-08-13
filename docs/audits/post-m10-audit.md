# POST-M10 FULL AUDIT

## Baseline

| Field | Result |
| --- | --- |
| Starting HEAD | `167aca14b0cd2d61f6d6ff92693bddea04fa0868` |
| Ending HEAD | `167aca14b0cd2d61f6d6ff92693bddea04fa0868` |
| Branch | `master` |
| Schema | `v10` |
| Canonical start | `3001 passed, 4 skipped, 0 failed` (fresh isolated `HOME`) |
| Canonical end | `3001 passed, 4 skipped, 0 failed` (fresh isolated `HOME`) |
| M10 / M10.7 | `VERIFIED` / `VERIFIED` |
| Feature freeze | `ACTIVE` |
| Post-M10 audit | `STARTED` by this report; no governance state was changed |
| Packaging | `NOT STARTED` |
| M10.8 | `DOES NOT EXIST` |
| M11 | `DOES NOT EXIST / NOT CREATED` |

The starting state was independently reconciled against Git, `project-state.yaml`,
`implementation-plan.json`, `acceptance-m10.7.md`, `plan-m10.md`, the master DOCX,
and the migration/test configuration. The authoritative state agrees with the
requested audit baseline. The repository has eight historical duplicate top-level
state keys; the material divergent one is `m2_current_version` at lines 384 and
403 (`4` versus `6`). This is recorded as AUD-007 and was not changed.

## Scope

M1-M10: capture, canonical and derived persistence, retrieval, project substrate,
policy/authorization, resource-type isolation, router/EvidenceSet/injection,
temporal/graph/calibration, Obsidian projection, Universal Knowledge Corpus,
rebuild/migration/error/concurrency behavior, dependencies, portability, and test
quality.

## Audit Mode

`AUDIT ONLY`

## Model

`GPT-5.6 Luna ONLY`. No model escalation or external model call was used.

## Product Changes

`NONE`. No `src/`, `tests/`, schema, migration, or product configuration file was
modified. The only requested artifact created by this audit is this report.

## Executive Finding Summary

| Severity | Count |
| --- | ---: |
| Critical | 0 |
| High | 2 |
| Medium | 5 |
| Low | 2 |
| **Total unique root findings** | **9** |

Findings were deduplicated by root cause. The canonical suite remains green because
these conditions are outside its current coverage or require a capability/concurrency
state not exercised by the committed tests.

## Architecture Map

### POST-M10 ARCHITECTURE MAP

- **M1 capture / observation:** `src/capture/`, `src/redaction/`,
  `src/storage/jsonl_capture.py`, `src/storage/capture_boundary.py`, and
  `src/integration/capture_adapter.py`. The append-only event JSONL is the raw
  memory trace authority.
- **M2 canonical/derived persistence:** `src/storage/jsonl_capture.py` and
  `src/storage/ingest.py`; SQLite migrations `migrate_1.py` through `migrate_10.py`
  create disposable derived projections, indexes, FTS, lifecycle, provenance,
  artifacts, and ingest state.
- **M3 read-only retrieval:** `src/retrieval/` and the M5 facade. Read helpers expose
  metadata/provenance and do not own write authority.
- **M4 project substrate:** `src/project_memory/{projector,reader,rebuild,contracts}.py`.
  Charter, requirement, decision, state, verification, and artifact projections are
  derived SQLite tables replayed from canonical events.
- **M5 policy:** `src/access/` contains the sole policy authority, persistent grant
  admin/write path, grant-event projection/rebuild, policy audit, linked-resource
  checks, and `AuthorizedReadService`.
- **M6 tools/resource boundaries:** `src/integration/m6/` exposes the fixed read-only
  tool/dispatcher surface and routes calls through M5.
- **M7 router/EvidenceSet:** `src/integration/m7/` contains the runtime gate, router,
  eligibility, deterministic budget, bounded EvidenceSet, hardening, envelope, and
  Hermes pre-LLM hook adapter.
- **M8 graph/temporal/calibration:** `src/m8/` contains derived graph sources and
  projection, bounded authorization-first graph reads, temporal projection/read,
  retrieval metadata, and deterministic calibration. `m8_integration.py` is the M7
  integration boundary and carries DATA-only metadata.
- **M9 Obsidian projection:** `src/projection/` contains M5-authorized read,
  sensitivity eligibility, rendering, links, managed-root path safety, manifest,
  ownership, incremental reconciliation, human-edit conflict handling, and writers.
  Obsidian is a curated projection, not canonical storage.
- **M10 Universal Knowledge Corpus:** `src/corpus/registry.py` and
  `src/corpus/blob_store.py` are canonical corpus registry/blob stores;
  `adapters/`, `extract.py`, `normalize.py`, `dedup.py`, and `versioning.py` form
  the deterministic ingestion boundary; `derived_store.py`, `retrieval.py`,
  `graph.py`, and `enrichment.py` form derived/rebuildable storage and read paths.
  Corpus reads enter through `AuthorizedReadService` and return bounded M7 evidence.

### AUDIT SURFACE INVENTORY

| Surface | Authority / entry point | Derived or external boundary |
| --- | --- | --- |
| Memory traces | event JSONL; `JsonlCaptureStore` | SQLite M2-M9 projections; M3/M5 reads |
| Policy/grant history | canonical policy/grant JSONL events | `zm_access_grants`, `zm_policy_audit` |
| Project substrate | canonical events plus committed governance artifacts | six M4 SQLite tables; M9 notes |
| Corpus source identity | `corpus_sources.jsonl`; `CorpusSourceRegistry` | `zm_corpus_sources` |
| Corpus source bytes | `CorpusBlobStore` content-addressed blobs | extraction/normalization/units/FTS |
| Corpus derived state | `project_corpus` / `rebuild_from_corpus` | v10 `zm_corpus_*` tables |
| Policy evaluation | `AuthorizedReadService` / M5 policy | consumed by M6-M10; no parallel authorizer found |
| Evidence construction | `build_evidence_set` → M8 integration → M7 hardening/envelope | final bounded Hermes context |
| Graph | M8/M10 projection writers and bounded read facades | `zm_graph_*`, `zm_corpus_relations` |
| Obsidian | `project_to_vault` / reconcile / manifest | managed-root Markdown + manifest; noncanonical |
| Runtime configuration | explicit args, selected env vars, optional config roots | no product absolute operator path found |
| External filesystem | corpus root, blob root, Obsidian managed root | containment and symlink checks reviewed |

## Canonical Store Inventory

| Store | Authority | Writer | Reader | Format / mutation | Derived consumers | Rebuild role | Authorization role |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Memory/policy/project event stream | Canonical trace history | `JsonlCaptureStore`, M5 grant/audit writers | M2 ingest, M4 rebuild, M5 policy rebuild, project readers | Append-only JSONL; no normal rewrite | M2-M9 SQLite/projections | Source for derived replay | M5 gates reads/writes; event domains retain provenance |
| `corpus_sources.jsonl` | Canonical corpus source registry | `register_source`; `_update_record` binds `blob_ref` | `CorpusSourceRegistry`, corpus rebuild | Append plus atomic whole-file rebind rewrite | v10 corpus source/unit/graph tables | Replay source metadata and versions | Registry itself delegates authorization to callers; M5 gates corpus reads |
| Corpus blob store | Canonical source bytes | `CorpusBlobStore.put` with `.part` + `os.replace` | extraction and corpus rebuild | Content-addressed files; immutable/idempotent intent | extracted/normalized/derived corpus | Re-extract all units from bytes | Raw bytes do not enter normal read/evidence path |
| `project-state.yaml` | Committed governance state | state-binding commits | baseline tests, operators, audit | YAML rewrite in Git; duplicate keys possible | no runtime product projection | not rebuildable; manually reconciled | Governs allowed next actions, not data authorization |
| `implementation-plan.json` and acceptance evidence | Committed governance/evidence authority | evidence/state commits | baseline tests and operators | JSON/Markdown committed artifacts | no runtime product projection | not runtime-rebuildable | governance/evidence only |

Obsidian notes and its manifest are explicitly **projection artifacts**, not canonical
stores. SQLite, FTS, graph, temporal, calibration, corpus-unit, and M9 manifest data
are derived/disposable or projection state.

## Persistence Blind-Spot Matrix

| STORE | WRITER | READER | APPEND TEST | REWRITE TEST | CLOSE/REOPEN TEST | NEW INSTANCE TEST | REBUILD TEST | CORRUPTION TEST | ATOMICITY TEST | STATUS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Memory event JSONL | `JsonlCaptureStore.append` | M2/M4/M5 readers/rebuilders | PASS | N/A | PASS | PASS | PASS | PASS for malformed/partial lines | PASS for per-event SQLite projection; no power-loss simulation | PASS — no finding |
| Policy/grant JSONL events | M5 grant/audit writers | `access/rebuild.py` | PASS | N/A | GAP for malformed source replay | GAP for malformed source replay | FINDING: malformed lines silently omitted | GAP: no explicit malformed-policy canonical failure | GAP: caller-owned transaction only | FINDING — AUD-003 |
| `corpus_sources.jsonl` | `register_source`, `_update_record` | `CorpusSourceRegistry` | PASS | PASS; M10.7 blank-line regression fixed | PASS; M10.7 reopen regression | FINDING under same-instance concurrency | PASS for normal canonical rebuild | PASS: loader rejects malformed lines | GAP: no crash/power-loss proof; race is separately reproduced | FINDING — AUD-005 |
| Corpus blob store | `CorpusBlobStore.put` | extraction/rebuild | N/A | N/A by content-addressed design | PASS by filesystem reopen | PASS for normal new store | PASS through corpus rebuild | FINDING: invalid empty digest is accepted by `exists` and leaks raw OS error in `get` | GAP: atomic rename tested, directory durability not simulated | FINDING — AUD-009 |
| Governance YAML/JSON | Git/state-binding writers | baseline/operator readers | N/A | PASS as committed history | GAP: duplicate-key parse semantics are not universally enforced | GAP | N/A | FINDING: divergent duplicate state key | N/A | FINDING — AUD-007 |

The matrix distinguishes a passing normal lifecycle from untested crash durability
and from reproduced logical defects. The prior M10.7 registry blank-line defect is
not counted again; its reopen regression is present and passes.

## Security Boundary Matrix

| BOUNDARY | RESOURCE TYPES | AUTHORIZATION ENTRY | AUTH BEFORE INFLUENCE | FAIL CLOSED | HIDDEN-INFLUENCE TEST | CROSS-SCOPE TEST | READ-ONLY | STATUS |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Memory retrieval | event, decision, requirement, verification, charter, artifact | M5 `AuthorizedReadService` | PASS | PASS | PASS | PASS | PASS | PASS — no finding |
| Artifact access | artifact / project artifact | M5 + M6 artifact whitelist | PASS | PASS | PASS | PASS | PASS | PASS — no finding |
| Corpus retrieval | corpus_source / corpus_unit | M5 `AuthorizedReadService.corpus_unit_search` | PASS in code/tests | PASS | PASS hidden-candidate regression | PASS | PASS | PASS — aside from AUD-004 capability failure |
| Memory graph | M8 registered memory resource types | M5 seed and neighbor checks | PASS before graph expansion | PASS | PASS hidden-graph regression | PASS | PASS | PASS — no finding |
| Corpus graph | corpus_source / corpus_unit | M5 `_gate` plus endpoint authorization | PASS before path/budget | PASS | PASS hidden-graph regression | PASS | PASS | PASS — no finding |
| EvidenceSet | memory and corpus_unit items | M5 results → M7 eligibility/budget | PASS before selection | PASS | PASS hidden-candidate composition | PASS | PASS | FINDING — AUD-006 hardening/envelope boundary |
| Obsidian projection | M4/project note resources | M5-authorized projection engine | PASS before render | PASS | PASS authorized/withheld tests | PASS | NO — approved projection writes | PASS — no finding |

Targeted regression evidence after audit probes: corpus retrieval/graph `52 passed`;
M6 hardening + M7 hardening `149 passed`; M4 rebuild + M5 policy rebuild `33 passed`.
The fresh full canonical suite passed independently at both audit boundaries.

## Findings

### AUD-001

**SEVERITY:** MEDIUM  
**CONFIDENCE:** HIGH  
**CATEGORY:** Undeclared dependency / configured-root portability  
**AFFECTED MILESTONES:** M10.1, M10.2  
**AFFECTED COMPONENTS:** `CorpusSourceRegistry`, `CorpusBlobStore`, corpus config-root resolution  
**LOCATION:** `src/corpus/registry.py:78-88`; `src/corpus/blob_store.py:51-61`  
**INVARIANT:** The documented explicit → environment → `config/corpus.yaml` root resolution must work on a clean machine without an undeclared mandatory runtime dependency, or fail with an explicit capability state rather than silently disabling an explicitly configured corpus.  
**OBSERVED:** Both resolvers perform a local `import yaml` and catch every exception as “unconfigured.” The project has no tracked dependency manifest and `.venv/bin/python3 -c 'import yaml'` is unavailable. A temporary valid config fixture was resolved as `resolved=None`.  
**ROOT CAUSE:** The config-file branch depends on PyYAML while the project declares no PyYAML dependency and deliberately treats its absence as a silent safe fallback.  
**REPRODUCTION:** In an isolated temporary directory, write `corpus_root: <tmp>/data` to `corpus.yaml`, call `_resolve_root(None, config_path=cfg)` with the project venv; result: `None`.  
**EVIDENCE:** `src/corpus/registry.py:80` and `src/corpus/blob_store.py:53` import `yaml`; AST dependency scan found only these two YAML imports; no `pyproject.toml`, `requirements*.txt`, `setup.py`, `Pipfile`, or `uv.lock` is tracked.  
**IMPACT:** A clean installation using the documented config-file path silently becomes unavailable even though the operator supplied a valid root. Explicit argument/env operation still works.  
**CROSS-MILESTONE IMPACT:** M10.1 root availability → M10.2 blob persistence → M10.4 corpus rebuild/configured deployment.  
**CANONICAL DATA RISK:** NO  
**SECURITY RISK:** NO  
**PORTABILITY RISK:** YES  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Make the config parser dependency-free or declare and provision the dependency as part of an explicit supported install; do not silently convert a valid configured root into “unavailable.”  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-002

**SEVERITY:** MEDIUM  
**CONFIDENCE:** HIGH  
**CATEGORY:** Cross-milestone source identity / version-chain contract mismatch  
**AFFECTED MILESTONES:** M10.1, M10.3, M10.4  
**AFFECTED COMPONENTS:** source registry identity, dedup identity, version chain, corpus rebuild  
**LOCATION:** `src/corpus/identity.py:69-106`; `src/corpus/registry.py:176-187`; `src/corpus/versioning.py:133-170`; `src/corpus/dedup.py:6-35`  
**INVARIANT:** Content identity, logical source identity, and authorization identity must remain distinct. A changed source must produce a new version linked by `supersedes`; renamed copies must follow the declared content-dedup contract without silently defeating source/version history.  
**OBSERVED:** The registry computes `content_hash` from source bytes **plus** a descriptor containing `external_ref` and scope, then derives `source_id` from that hash. Registering changed bytes under the same external reference creates a new `source_id`; `build_version_chain` groups by `source_id`, so it creates two one-version chains with no `supersedes`. Registering identical bytes under a renamed external reference creates a different content hash and source ID, contrary to the M10.3 dedup module's declared renamed-copy/content-hash contract.  
**ROOT CAUSE:** M10.1 source identity combines content and logical descriptor, while M10.3 versioning assumes `source_id` remains stable across content changes and dedup assumes a scope-independent content identity at the source boundary.  
**REPRODUCTION:** Isolated registry probe with `v1` and `v2` under `docs/a.txt`, then `v1` under `docs/renamed.txt`, returned: `changed_source_ids=True`, `version_counts=1 1`, `supersedes_new=None`, `renamed_same_content_hash=False`, `renamed_same_source_id=False`.  
**EVIDENCE:** `src/corpus/versioning.py` explicitly documents “changed content under the same source_id”; `src/corpus/dedup.py` documents renamed-copy same content hash/source identity; the live registry probe contradicts both behaviors. Existing M10.3 tests manually construct records with stable source IDs and do not exercise registry → version-chain integration.  
**IMPACT:** Changed source ingests are not represented as an explicit historical version chain; renamed or relocated logical sources are not deduplicated at the declared source-content boundary. Rebuild preserves the resulting disconnected identities rather than recovering the intended relation.  
**CROSS-MILESTONE IMPACT:** M10.1 identity → M10.3 version/dedup → M10.4 rebuild → M10.5/M10.6 provenance and version selection.  
**CANONICAL DATA RISK:** NO  
**SECURITY RISK:** NO  
**PORTABILITY RISK:** NO  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Freeze one explicit source/content/logical identity model and make registry, dedup, versioning, and rebuild consume the same axes; add an end-to-end registry-to-chain contract before any code change.  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-003

**SEVERITY:** HIGH  
**CONFIDENCE:** HIGH  
**CATEGORY:** Canonical-to-derived rebuild silently drops malformed authoritative events  
**AFFECTED MILESTONES:** M4, M5  
**AFFECTED COMPONENTS:** project-memory rebuild and policy-state rebuild  
**LOCATION:** `src/project_memory/rebuild.py:215-227`; `src/access/rebuild.py:50-63,80-95`  
**INVARIANT:** A malformed canonical line must fail closed or produce an explicit blocked/incomplete rebuild result. A rebuild must never clear derived state, silently skip authoritative input, and report success as if the state were complete.  
**OBSERVED:** `rebuild_project_memory` catches every JSON parsing exception, increments `skipped`, and returns success. `iter_canonical_policy_events` catches `JSONDecodeError` and continues; `rebuild_policy_state` then clears policy tables and rebuilds only the remaining parseable events. A temporary JSONL containing `{not-json}\n` produced `{'projected': 0, 'skipped': 1, 'by_domain': {}}` and left an empty derived project schema without an error.  
**ROOT CAUSE:** The M4/M5 custom replay loops use permissive `continue` handling instead of the strict canonical-store corruption contract used by M1 JSONL loading and M10 registry loading.  
**REPRODUCTION:** Create a temporary SQLite store, ensure schema, write one malformed line to a temporary canonical JSONL, call `rebuild_project_memory(store, path)`. The call returns normally with `skipped=1` and no projected state. The M5 iterator has the same skip branch.  
**EVIDENCE:** Direct probe output above; source lines; M2 has a separate, explicitly tested per-line invalid-record policy, but that policy is not documented or enforced by the M4/M5 full rebuild contracts.  
**IMPACT:** A rebuild after canonical corruption can silently produce an incomplete project/policy view. Authorization, project-state reads, Obsidian projection, or downstream EvidenceSet selection may operate on missing derived facts while the operator sees a successful rebuild summary.  
**CROSS-MILESTONE IMPACT:** Canonical event stream → M4/M5 derived state → M6/M7/M8/M9 consumers.  
**CANONICAL DATA RISK:** YES  
**SECURITY RISK:** YES (incomplete policy projection can affect authorization state)  
**PORTABILITY RISK:** NO  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Establish one explicit corruption policy for full replays and make M4/M5 fail closed with a typed incomplete result or abort before publishing cleared derived state.  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-004

**SEVERITY:** HIGH  
**CONFIDENCE:** HIGH  
**CATEGORY:** FTS5 capability guard does not propagate to corpus retrieval  
**AFFECTED MILESTONES:** M10.4, M10.5  
**AFFECTED COMPONENTS:** v10 migration capability detection, corpus lexical retrieval, M5 corpus facade  
**LOCATION:** `src/storage/migrations/migrate_10.py:282-316`; `src/corpus/derived_store.py:175-183`; `src/corpus/retrieval.py:337-359`  
**INVARIANT:** If FTS5 is capability-guarded and absent, core corpus operation must remain absence-safe or fail at a documented capability boundary; retrieval must not unconditionally query a table that the migration intentionally omitted.  
**OBSERVED:** With `_detect_fts5` controlled to return `False`, v10 creation sets `FTS5_AVAILABLE=False` and creates no `zm_corpus_fts` table. A normal text `retrieve_corpus` call then raises `CorpusQueryError("corpus_fts_error: OperationalError")`.  
**ROOT CAUSE:** The migration/projection path guards FTS5 creation and writes, but the text retrieval path unconditionally executes a join against `zm_corpus_fts`; there is no fallback or capability error at the public boundary.  
**REPRODUCTION:** In a temporary store, set the migration detector to false before `ensure_schema`; verify `fts_flag=False` and `fts_table=False`; call `retrieve_corpus(..., build_query_plan("hello"))`; result: `CorpusQueryError corpus_fts_error: OperationalError`.  
**EVIDENCE:** Controlled capability probe; source paths above; the M10 plan describes FTS5 as capability-guarded and core corpus retrieval as available without optional semantic components.  
**IMPACT:** A clean Ubuntu/Python SQLite build without FTS5 cannot perform core lexical corpus retrieval, even though the schema explicitly treats FTS5 absence as a supported state.  
**CROSS-MILESTONE IMPACT:** M10.4 migration → M10.5 retrieval facade → M7 bounded EvidenceSet/corpus path.  
**CANONICAL DATA RISK:** NO  
**SECURITY RISK:** NO  
**PORTABILITY RISK:** YES  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Either provide a deterministic non-FTS lexical fallback or make the capability requirement explicit and fail before corpus availability is advertised; add an actual FTS5-absent facade regression.  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-005

**SEVERITY:** MEDIUM  
**CONFIDENCE:** HIGH  
**CATEGORY:** Same-instance concurrent registry registration violates idempotent append  
**AFFECTED MILESTONES:** M10.1, M10.2, M10.4  
**AFFECTED COMPONENTS:** `CorpusSourceRegistry.register_source`, blob binding, corpus replay  
**LOCATION:** `src/corpus/registry.py:184-215`  
**INVARIANT:** Concurrent registration of the same identity through one registry instance must append at most one canonical record, matching the documented idempotent-by-source identity contract.  
**OBSERVED:** Two threads registering the same bytes, external reference, kind, and project produced one in-memory record but two identical JSONL lines with the same `source_id`.  
**ROOT CAUSE:** The duplicate checks occur before acquiring `self._lock`; the critical section does not repeat the existence check before append. The lock protects the write but not the check-and-append transaction.  
**REPRODUCTION:** Isolated two-thread probe with a temporary registry and a synchronization gate around `_serialize`: `records_in_memory=1`, `jsonl_lines=2`, both returned the same source ID.  
**EVIDENCE:** Direct probe; `registry.py:102` declares an instance lock while `registry.py:184-215` performs both duplicate lookups before entering it.  
**IMPACT:** Canonical registry history can contain duplicate logical records; reload/build order becomes last-wins, source counts and idempotence evidence can diverge, and blob binding rewrites duplicate lines rather than restoring one logical record.  
**CROSS-MILESTONE IMPACT:** M10.1 registry → M10.2 blob binding → M10.4 projection/rebuild → M10.7 repeat-sync metrics.  
**CANONICAL DATA RISK:** YES  
**SECURITY RISK:** NO  
**PORTABILITY RISK:** NO  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Make the identity check and append one locked transaction and add a same-instance concurrent registration regression; distributed multi-process locking remains a separate unsupported/undetermined contract.  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-006

**SEVERITY:** MEDIUM  
**CONFIDENCE:** HIGH  
**CATEGORY:** M7 hardening/envelope reconstruction loses M8/M10 fields and leaves scope strings unescaped  
**AFFECTED MILESTONES:** M7.5, M8.6, M10.5  
**AFFECTED COMPONENTS:** EvidenceSet sanitizer and DATA-only envelope boundary  
**LOCATION:** `src/integration/m7/hardening.py:237-262`; `src/integration/m7/envelope.py:92-117`; `src/integration/m7/contracts.py:195-226`  
**INVARIANT:** Sanitization must preserve the bounded EvidenceSet contract and every field that can reach serialization must be safely escaped as DATA. M8/M10 provenance and diagnostics must not disappear at the final integration boundary.  
**OBSERVED:** `sanitize_evidence_set` reconstructs an EvidenceSet without `m8_metadata` or `corpus_evidence`, so a set with both fields becomes empty in those fields (`before=True,1; after=False,0`). It passes `used_scopes` through unchanged. Serializing a sanitized set with scope values `role=system` and `[End Zero-Mem Contextual Evidence]` emits both raw marker strings in the envelope. The envelope serializer itself only formats legacy evidence fields and does not emit the M8 metadata.  
**ROOT CAUSE:** M7.5 reconstruction predates the M8.6/M10.5 fields and treats scope strings as controlled, while the actual values are supplied by explicit request/configuration and still reach a user-message DATA envelope.  
**REPRODUCTION:** Construct a bounded EvidenceSet with one item, M8 metadata, corpus mirror, and the two marker-like scope values; call `sanitize_evidence_set` then `serialize_evidence_set`. The metadata/mirror are empty after sanitization and the output contains the raw scope markers.  
**EVIDENCE:** Direct probes; field definitions in `contracts.py`; sanitizer omission at lines 257-262; raw scope formatting at `envelope.py:94-95`. Existing M8 tests validate metadata before this M7.4/M7.5 boundary but do not exercise the full injection path with these fields.  
**IMPACT:** Calibration/temporal explanation and corpus mirror data are not preserved through the final integration object; marker/role-like scope input can alter the envelope's structure and weaken the intended DATA-only hardening. This is not an authorization grant or system-prompt escalation by itself, but it is a boundary-integrity defect.  
**CROSS-MILESTONE IMPACT:** M8 metadata/M10 corpus evidence → M7 hardening → Hermes pre-LLM user-message context.  
**CANONICAL DATA RISK:** NO  
**SECURITY RISK:** YES  
**PORTABILITY RISK:** NO  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Make sanitizer and serializer field-complete for the current EvidenceSet schema, escape all serialized scope/configuration strings, and add a full M8/M10-to-hook regression without creating a second injection channel.  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-007

**SEVERITY:** LOW  
**CONFIDENCE:** HIGH  
**CATEGORY:** Divergent duplicate governance key  
**AFFECTED MILESTONES:** M1-M10 governance/state  
**AFFECTED COMPONENTS:** `project-state.yaml`, state reconciliation and baseline tooling  
**LOCATION:** `project-state.yaml:384` and `project-state.yaml:403`  
**INVARIANT:** Each effective top-level governance key must have one authoritative value, and parsed state must not depend on YAML last-wins behavior.  
**OBSERVED:** `m2_current_version: 4` and `m2_current_version: 6` both exist. A last-wins top-level parser reads `6`; textual/substitution consumers can observe `4` or both. The current M10 state remains correctly reconciled, but the artifact is structurally ambiguous.  
**ROOT CAUSE:** Historical state-binding append/reconciliation left a divergent M2 key; the hardened duplicate-key check is scoped to the M9 binding surface and intentionally deferred this unrelated key to the full audit.  
**REPRODUCTION:** Stdlib column-0 scan reports eight duplicate top-level keys, including `m2_current_version`; the two values are `4` and `6`.  
**EVIDENCE:** Direct state scan; current baseline assertions do not reject this key because it is outside their M9-scoped structural gate.  
**IMPACT:** Future generic YAML readers or operators can make inconsistent decisions about historical schema/state, reducing governance auditability. No current M10 product path was found to consume this key.  
**CROSS-MILESTONE IMPACT:** M2 historical state → project governance → future state reconciliation.  
**CANONICAL DATA RISK:** NO  
**SECURITY RISK:** NO  
**PORTABILITY RISK:** NO  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Resolve the duplicate in a dedicated governance-only correction after the audit, with a structural whole-file state check that does not alter product semantics.  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-008

**SEVERITY:** MEDIUM  
**CONFIDENCE:** HIGH  
**CATEGORY:** Test-suite checkout-path portability blocker  
**AFFECTED MILESTONES:** M4, M5, M8, M9 test gates  
**AFFECTED COMPONENTS:** static/security/integration tests using repository-root constants  
**LOCATION:** 16 test files, including `tests/unit/test_m4_read.py:11`, `test_m5_access_policy.py:21`, `test_m8_3_helpers.py:27`, and `test_m9_6_hardening.py:41`  
**INVARIANT:** Tests must derive the repository root from the test location or Git/runtime context, not embed the current operator's absolute checkout path.  
**OBSERVED:** Sixteen tracked test files contain `ROOT = Path("/home/brian-nguyen/Hermes Workplace/Zero-mem")`. The current checkout passes because that path exists; a clean checkout at another path leaves those tests pointed at a nonexistent/stale tree.  
**ROOT CAUSE:** Test fixtures/static scanners were authored against the current spaced checkout and the canonical suite has not been exercised from a different repository location.  
**REPRODUCTION:** Static search finds 16 absolute-root constants. Copying/checking out the repository at a different path would make those constants resolve outside the active source tree; no runtime product path contains this operator path.  
**EVIDENCE:** `search_files` over tracked tests; product-source scan found no operator path except the intentional path-token rejection list in `project_memory/contracts.py`.  
**IMPACT:** Clean-machine verification and packaging acceptance cannot rely on the current test suite from a different checkout location; failures can be false test failures or scans of the wrong tree.  
**CROSS-MILESTONE IMPACT:** M4/M5/M8/M9 static and integration gates → final portability/clean-machine acceptance.  
**CANONICAL DATA RISK:** NO  
**SECURITY RISK:** NO  
**PORTABILITY RISK:** YES  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Replace test-only absolute roots with dynamic repository discovery or `Path(__file__)`-relative roots, then exercise the canonical suite from a different checkout path.  
**PERMANENT REGRESSION NEEDED:** YES

### AUD-009

**SEVERITY:** LOW  
**CONFIDENCE:** HIGH  
**CATEGORY:** Blob-reference input validation / typed failure gap  
**AFFECTED MILESTONES:** M10.1, M10.2, M10.4  
**AFFECTED COMPONENTS:** `CorpusBlobStore` digest path API and corpus projection error boundary  
**LOCATION:** `src/corpus/blob_store.py:92-128`; `src/corpus/contracts.py` blob reference field  
**INVARIANT:** A blob reference must be a valid content address; malformed references must fail closed with the domain error and must never be treated as an existing blob.  
**OBSERVED:** With a valid temporary blob root, `CorpusBlobStore.exists("")` returns `True` because the computed target is the existing `blobs/` directory. `get("")` raises raw `IsADirectoryError` rather than `BlobStoreError`.  
**ROOT CAUSE:** `_path_for` and `_assert_within_root` enforce containment but do not validate digest syntax/non-empty input; `exists` checks filesystem existence without requiring a regular blob file.  
**REPRODUCTION:** Temporary store probe returned `exists_empty=True` and `get_empty=IsADirectoryError [Errno 21] Is a directory`.  
**EVIDENCE:** Direct probe and source lines above. Path traversal itself is rejected, but empty/malformed digest handling is not closed.  
**IMPACT:** Corrupt or malformed canonical `blob_ref` metadata can produce false existence and an uncaught OS exception during extraction/rebuild instead of a stable classified failure.  
**CROSS-MILESTONE IMPACT:** Registry blob binding → corpus extraction → derived rebuild/error reporting.  
**CANONICAL DATA RISK:** NO  
**SECURITY RISK:** NO  
**PORTABILITY RISK:** NO  
**TEST BLIND SPOT:** YES  
**REMEDIATION NEEDED:** YES  
**PROPOSED FIX DIRECTION:** Validate the closed digest format before path construction and require a regular file for existence/read operations; add malformed-reference and rebuild-error regressions.  
**PERMANENT REGRESSION NEEDED:** YES

## Cross-Milestone Contradictions

**FINDINGS:**

- AUD-002: M10.1 source identity and M10.3 version/dedup assumptions disagree at
  the registry-to-chain boundary.
- AUD-003: M2's malformed-line ingestion policy is intentionally tolerant, while
  M4/M5 full rebuilds silently skip malformed canonical events without publishing
  an incomplete status; the same canonical authority has inconsistent corruption
  semantics across derived consumers.
- AUD-006: M8.6/M10.5 added EvidenceSet fields after M7.5 reconstruction and
  envelope logic; the final integration boundary does not preserve the full current
  contract.
- AUD-007: governance history contains a divergent duplicate state key even though
  the current M10 effective state is reconciled.

## Test Blind Spots

- Full canonical execution is green at both boundaries, but the suite does not
  cover valid `config/corpus.yaml` resolution in a dependency-clean environment,
  FTS5-absent corpus retrieval, registry same-instance concurrent registration,
  registry-to-version-chain changed-source integration, M4/M5 malformed canonical
  full-rebuild behavior, full M8/M10 EvidenceSet hook serialization, empty blob
  references, or a different checkout path.
- Existing M10.3 version tests manually construct stable `source_id` records, which
  bypasses the M10.1 registry identity behavior.
- Existing M8.6 tests verify `m8_metadata` on the intermediate EvidenceSet, not the
  M7.5 sanitizer plus M7.4 envelope boundary.
- The M1 event JSONL path has close/reopen and malformed-line coverage; that coverage
  did not generalize to the M4/M5 custom replay loops.

## Canonical / Derived Risks

- **AUD-003 HIGH:** malformed canonical events can be absent from rebuilt M4/M5
  state without a blocking result.
- **AUD-005 MEDIUM:** a same-instance concurrent registry race can append duplicate
  canonical records.
- The v10 `zm_corpus_*` tables, FTS, graph relations, temporal/calibration data,
  and M9 manifest remain derived/rebuildable by design; normal projection/rebuild
  parity and committed M10.7 real-corpus evidence were not contradicted in the
  normal lifecycle.

## Authorization / Security Risks

- **AUD-003:** incomplete policy rebuild can make derived authorization state
  incomplete after malformed canonical input.
- **AUD-006:** current EvidenceSet hardening is not field-complete at the final
  serialization boundary; raw marker-like scope values remain structurally active.
- M5 policy, M6.6 resource-type isolation, authorization-before-influence,
  hidden-candidate, hidden-graph, sensitivity/redaction, graph adjacency, and
  prompt-injection-as-DATA controls passed the targeted/full checks otherwise.

## Concurrency / Recovery Risks

- **AUD-005:** registry check/append race is reproduced.
- M10 registry rewrite uses an atomic replacement and the prior blank-line defect is
  fixed; a power-loss fsync-directory proof was not run.
- M4/M5 replay behavior is the larger recovery concern: **AUD-003** clears/rebuilds
  from an incomplete parseable subset while reporting a normal summary.
- Distributed multi-process writer semantics are not claimed by the project and were
  not inflated into a separate finding.

## Portability Blockers

1. **AUD-001:** valid `config/corpus.yaml` roots silently fail without undeclared
   PyYAML.
2. **AUD-004:** FTS5 absence breaks core corpus lexical retrieval despite the
   capability guard.
3. **AUD-008:** 16 test gates embed the current checkout path.

No hard-coded operator path was found in product code; the one product match is an
intentional path-token rejection list. Runtime corpus and Obsidian roots remain
explicit/configured rather than inferred from the current machine.

## Packaging Blockers

1. Packaging is explicitly `NOT STARTED`; the repository has no tracked package
   metadata or dependency manifest from which a clean Ubuntu machine could recreate
   the tested environment. This is recorded as a release/portability blocker, not
   remediated or counted as a product finding.

## Dead / Duplicate / Drift Candidates

- **AUD-007** is the only material governance duplicate confirmed: divergent
  `m2_current_version` values.
- No high-confidence dead product path was filed. The M10 optional semantic and
  enrichment boundaries are intentionally absence-safe; M9/M10 deferred corpus
  Obsidian projection is explicitly absent.
- Security-critical authorization/path/sensitivity implementations were inspected
  for duplication; no additional mismatch was proven beyond AUD-002 and AUD-006.
- Migration sequence v1-v10 is contiguous in source, and the v10 downgrade is
  derived-only by inspection and existing migration tests.

## Performance Risks

- No new performance finding was filed. The committed M10.7 measurements remain the
  only large-corpus evidence: first ingest ~22 minutes, peak RSS ~1.15 GiB, 26,144
  units, retrieval median 4.885 ms/p95 21.214 ms, and rebuild ~755 s on that machine.
- Source inspection confirms metadata-only and lexical retrieval scan/filter work is
  bounded in returned results but not proven at larger-than-committed corpus scale.
  This remains **DEFERRED / NOT PROVEN**, not an inflated defect.

## No-Finding Areas

PASS — no finding for the normal M1 event JSONL append/reopen/redaction boundary.

PASS — no finding for M5 policy precedence, explicit requester identity, cross-scope
read/write grants, deny precedence, and M6.6 resource-type isolation under targeted
regressions.

PASS — no finding for normal M8 temporal separation of transaction/valid time,
closed lifecycle/resource vocabularies, graph bounds (2/20/40/80), graph read-only
behavior, or calibration-as-ordering-only semantics.

PASS — no finding for M7 routing/master switch behavior, ordinary bounded 5/3/8
EvidenceSet selection, corpus authorization-before-influence, hidden candidate/graph
regressions, or prompt-injection text remaining DATA in the normal tested path.

PASS — no finding for M10.2 TXT/PDF adapter boundary, optional parser absence
contract, normalization determinism, unit logical/provenance separation, normal
blob path containment/symlink defenses, or normal v10 derived rebuild parity.

PASS — no finding for M9 managed-root containment, three-signal ownership, human
sibling/.obsidian preservation, secret ceiling/backstop, manifest validation, and
normal idempotent projection behavior.

## Deferred / Not Proven

- Actual power-loss/interrupted-process durability and directory-fsync behavior for
  atomic replacements was not simulated; no additional finding is claimed.
- A real alternate Ubuntu SQLite build without FTS5 was not installed; AUD-004 is
  validated with the product's own capability flag and absent-table controlled probe.
- Multi-process/distributed writers are outside the claimed deployment contract; the
  reproduced AUD-005 is same-instance concurrency only.
- The 601-PDF corpus was not re-ingested during this audit; committed M10.7 evidence
  was treated as historical evidence, not rerun evidence for this audit.
- Real Obsidian vault mutation was not performed; existing read-only/committed smoke
  evidence and isolated tests were reviewed.
- Packaging, clean-machine installation, backup/restore, and release engineering
  remain explicitly unstarted.
- No remediation plan or fix ordering was created.

## AI Usage / Cost

The audit used the configured GPT-5.6 Luna reasoning session with deterministic/local
inspection first and compact evidence-driven reasoning. No separate model/API call
was made and no external API spend was exposed; best estimate of incremental
external model spend is `$0`.

## Remediation

`NOT STARTED`

## Packaging

`NOT STARTED`

## M11

`NOT CREATED`
