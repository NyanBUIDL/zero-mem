# POST-M10 FIX PLAN

> **Mode:** PLAN ONLY. This document authorizes no implementation, remediation,
> schema change, migration, packaging, installation, backup/restore work, M10.8,
> or M11.

## Baseline

| Field | Value |
| --- | --- |
| Product baseline HEAD | `167aca14b0cd2d61f6d6ff92693bddea04fa0868` |
| Audit artifact HEAD | `975aaaac4057d8faf2b135c344488aabcbcb90db` (`docs(audit): record post-M10 full audit`) |
| Fix-plan HEAD | Uncommitted while this plan is authored; if committed, record the exact resulting HEAD externally and do not claim a canonical run there unless one occurs |
| Schema | `v10` |
| Canonical product evidence | `3001 passed, 4 skipped, 0 failed` at product baseline `167aca14b0cd2d61f6d6ff92693bddea04fa0868` |
| Canonical at audit artifact HEAD | Not run and not claimed; audit artifact commit changed documentation only |
| Feature freeze | `ACTIVE` |
| Post-M10 audit | `COMPLETED — FINDINGS IDENTIFIED` |
| Product code changed during audit | `NO` |
| Packaging | `NOT STARTED` |
| M10.8 | `DOES NOT EXIST` |
| M11 | `DOES NOT EXIST / NOT CREATED` |

The audit artifact was read in full before planning. The audit commit contains only
`post-m10-audit.md`; no `src/`, `tests/`, schema, migration, or project-state file
changed in that commit.

## Audit Summary

| Severity | Count |
| --- | ---: |
| Critical | 0 |
| High | 2 |
| Medium | 5 |
| Low | 2 |
| **Total unique root findings** | **9** |

Findings:

- **AUD-001:** undeclared dependency/config-file portability failure.
- **AUD-002:** M10.1 source identity conflicts with M10.3 dedup/version-chain assumptions.
- **AUD-003:** M4/M5 rebuild silently skips malformed canonical events.
- **AUD-004:** FTS5 capability absence breaks core corpus lexical retrieval.
- **AUD-005:** same-instance concurrent registry registration can append duplicates.
- **AUD-006:** M7 EvidenceSet hardening/envelope loses current fields and leaves scope strings unescaped.
- **AUD-007:** divergent duplicate `m2_current_version` governance key.
- **AUD-008:** 16 tests embed the current absolute checkout path.
- **AUD-009:** blob store accepts malformed/empty digest references and leaks raw filesystem errors.

## Planning Rules

1. **PLAN ONLY.** No source patch, test patch, schema change, migration,
   configuration change, product behavior change, packaging, installation,
   backup/restore, real corpus mutation, or real-vault mutation occurs while
   authoring this plan.
2. Remediation increments are `R1`-`R9`; they are not milestones and must not be
   named M10.8 or M11.
3. Each AUD finding has exactly one primary closure owner below.
4. Every implementation increment must add a permanent regression and preserve
   existing tests; no test expectation may be weakened.
5. Every canonical/persistence change must prove:
   `WRITE → FLUSH → CLOSE → NEW INSTANCE → REOPEN → READ → REBUILD when applicable → COMPARE`.
6. M5 remains the sole authorization authority. M6.6 resource-type isolation,
   hidden-candidate, hidden-graph, and authorization-before-influence regressions
   remain mandatory and untouched.
7. Evidence remains DATA. EvidenceSet remains `primary <= 5`,
   `supporting <= 3`, `total <= 8`; no second unbounded evidence channel may be
   introduced.
8. SQLite remains derived/disposable. No SQLite schema migration is planned.
9. No fix is considered closed by source inspection alone. The focused regression
   must fail against the pre-fix behavior where feasible and pass after the fix.
10. No self-referential final HEAD is written into an acceptance/state artifact.

## Finding Dependency Graph

```text
AUD-003 ───────────────────────────────────────────────┐
                                                       ├─ final remediation audit
AUD-004 ───────────────────────────────────────────────┤
                                                       │
AUD-002 ──► AUD-005 ──► corpus registry integration ───┤
   │                                                   │
   └──────► M10.3/M10.4 identity and rebuild checks ────┤
                                                       │
AUD-006 ─────────────────► M7/M8/M10 hook checks ───────┤
AUD-009 ─────────────────► corpus extraction/rebuild ───┤
AUD-001 ─────────────────► future packaging precondition
AUD-008 ─────────────────► clean-checkout verification
AUD-007 ─────────────────► governance-only closure
```

### Verified ordering dependencies

- **R1/AUD-003 precedes final security acceptance.** An incomplete M5 policy
  projection can invalidate otherwise-green authorization observations.
- **R2/AUD-004 is independent of AUD-001.** FTS capability behavior must be
  resolved in retrieval/storage contracts, not hidden behind dependency setup.
- **R3/AUD-002 precedes R5/AUD-005.** Both touch corpus registry semantics; the
  identity contract must be frozen before the concurrency correction is verified.
- **R6/AUD-009 follows the corpus contract decisions.** Digest validation must
  preserve the selected identity/content-addressing model.
- **R8/AUD-008 follows product remediation tests.** All newly added permanent
  regressions must themselves be location-independent.
- **R9/AUD-007 is independent and governance-only, but should be performed after
  the plan is approved so no plan-phase state edit obscures the audit baseline.**

## Contract Decisions Required

### AUD-002 identity contract — selected plan decision

The remediation will use five explicit axes:

1. **Content identity:** a domain-separated digest of the actual source bytes only.
   Scope, external reference, and operator metadata are excluded. The existing
   blob SHA-256 content address is the physical-content reference; the source
   record content identity must not change when only location or scope metadata
   changes.
2. **Logical source identity:** a stable digest of the operator-visible logical
   source descriptor: external reference, kind, stable custom identity metadata,
   and explicit authorization scope. It does not include source bytes.
3. **Location/external reference:** persisted provenance describing where the
   logical source was observed. A changed `external_ref` is a new logical source
   by default; an implicit rename/relocation must not merge authorization objects.
   An explicit relocate operation is out of scope for this remediation.
4. **Authorization identity:** profile/project/knowledge-space scope remains a
   separate authorization coordinate. Same bytes across scopes may share content
   identity, but source/version/unit IDs remain distinct by scope.
5. **Version identity:** immutable digest of stable logical `source_id`, content
   identity, explicit scope, and normalization version. Changed bytes at the same
   logical source produce a new version that explicitly supersedes the previous
   version. Unchanged re-ingest is idempotent.

Consequences:

- `docs/a.txt` with changed bytes retains its logical `source_id`; it receives a
  new `source_version_id` with `supersedes` and predecessor content provenance.
- Identical bytes at `docs/a.txt` and `docs/renamed.txt` share content identity
  but receive distinct logical source IDs unless an explicit relocation contract
  is later approved.
- Identical bytes in different authorization scopes share physical content only;
  no source/version/unit authorization identity collapses.
- The current persisted registry values encode content plus descriptor in
  `content_hash`/`source_id`, so existing canonical records cannot be silently
  reinterpreted as the new axes. A compatibility/data migration is therefore
  required for existing corpus history if it must participate in corrected
  version chains. This is **not** a SQLite schema migration. It must be staged on
  an isolated canonical copy, preserve legacy IDs as provenance, rebuild all
  derived state, and remain owner-gated before any real corpus mutation.

### AUD-004 FTS capability contract — selected plan decision

Select **Direction A: deterministic lexical fallback**.

When FTS5 is unavailable, corpus text retrieval will use a deterministic full
candidate read from `zm_corpus_units`, apply authorization and metadata filtering
before scoring, compute the existing lexical score over the authorized subset,
and apply the existing deterministic limit/order. This is an explicit O(N)
fallback, not a hidden FTS emulation or semantic path. FTS5 remains an optional
performance capability; absence must not make core canonical corpus data
unusable or leak raw `OperationalError`.

The fallback must preserve authorization-before-influence: no unauthorized row
may affect candidate truncation, scoring, tie-breaking, semantic fusion, or the
returned EvidenceSet. Semantic retrieval remains optional and independent.

## Remediation Order

| Order | Increment | Primary finding | Theme | Dependency |
| ---: | --- | --- | --- | --- |
| 1 | R1 | AUD-003 | Fail-closed canonical replay/rebuild | None; highest integrity/security risk |
| 2 | R2 | AUD-004 | FTS5 capability-safe retrieval | Independent of R1/AUD-001 |
| 3 | R3 | AUD-002 | Identity contract and existing-data compatibility gate | Must precede registry concurrency verification |
| 4 | R4 | AUD-006 | Complete EvidenceSet DATA boundary | Independent; security-sensitive |
| 5 | R5 | AUD-005 | Same-instance registry check/append atomicity | After R3 contract freeze |
| 6 | R6 | AUD-009 | Strict blob-reference validation | After corpus identity/content contract |
| 7 | R7 | AUD-001 | Dependency-free corpus config parsing | Independent; packaging prerequisite only |
| 8 | R8 | AUD-008 | Test checkout portability | After product regression additions |
| 9 | R9 | AUD-007 | Governance duplicate-key correction | Governance-only, after owner approval |

---

## R1 — Fail-Closed Canonical Replay and Rebuild Integrity

**Findings:** AUD-003  
**Severity:** HIGH  

### Why first

AUD-003 can make M4/M5 derived state incomplete while reporting a successful
rebuild. Incomplete M5 policy state can invalidate security conclusions and must
be corrected before accepting later authorization-sensitive remediation.

### Invariant

Malformed canonical input must never be silently omitted from a full replay that
publishes derived state. A rebuild must either complete from a valid canonical
snapshot or return a typed blocked/incomplete result while preserving the prior
published derived state.

M2's intentionally tolerant per-line ingestion/dead-letter behavior remains a
separate contract. R1 must not weaken or redesign M2.

### Expected files

- `src/project_memory/rebuild.py`
- `src/access/rebuild.py`
- Prefer an existing replay/parser utility if present; otherwise a narrowly scoped
  canonical replay preflight helper under `src/storage/`, not a general persistence
  framework.
- `tests/unit/test_m4_rebuild.py`
- `tests/unit/test_m5_policy_rebuild.py`
- A focused new failure test may be added only if the existing files cannot express
  the shared contract cleanly.

### Forbidden/unrelated files

- `src/storage/migrations/`
- SQLite schema definitions and migration ledger
- M2 ingestion semantics in `src/storage/ingest.py`, except documentation or a
  shared parser contract proven necessary
- M5 authorization decision semantics
- M6/M7/M8/M9/M10 product features
- `project-state.yaml` and `implementation-plan.json` during implementation

### Contract change

Full M4/M5 replay first validates the complete canonical input relevant to the
replay. Malformed JSON, partial records, or invalid top-level canonical records
produce a typed blocked/incomplete result before destructive derived reset. On
successful validation, projection remains transactional and deterministic. On
failure, the previous derived state remains readable and no success summary is
returned.

### Implementation direction

Use a strict preflight/read snapshot followed by the existing projection
transaction. If the existing M4/M5 APIs cannot preserve the prior state on a
replay failure, stage the new projection in a transaction or temporary derived
connection and publish only after the full replay succeeds. Do not silently
continue after malformed authoritative input.

### Permanent regression

- Malformed line after valid M4 event: rebuild blocks and preserves prior M4 rows.
- Malformed line before valid M4 event: same result; no partial publication.
- Malformed policy/grant event: rebuild blocks and preserves prior grant/policy rows.
- Valid mixed-domain canonical stream: unrelated valid events remain skippable by
  domain classification, but malformed framing is never silently skipped.
- Rebuild success: close store, open a new instance, read, and compare logical state.

### Focused verification

Run the existing M4/M5 rebuild suites plus the new malformed-input tests. Add a
mutation/negative check that disables the preflight or restores the old
`except: continue` path and proves the new tests fail.

### Relevant regression

- M2 canonical/rebuild regression suite, without changing M2 expectations.
- M5 authorization/grant/revocation and M6.6 resource isolation suites.
- M7 hidden-candidate and hidden-graph regressions because their input policy
  state must be complete.

### Canonical

Mandatory. Run fresh isolated-HOME canonical before acceptance and again on the
final R1 commit. This is a HIGH canonical-integrity/security remediation.

### Security invariants

M5 remains the sole authorizer; no partial policy state may be treated as a valid
policy decision. No malformed canonical data may gain authority or alter visible
authorization results.

### Rollback / failure risk

The primary risk is preserving the old destructive reset behavior on an exception.
Rollback must leave the previous derived store intact. No canonical JSONL is
rewritten by R1.

### Acceptance

- Malformed full replays fail closed with a typed/incomplete result.
- Existing derived state is preserved on failed preflight/replay.
- Valid replays remain deterministic and rebuild-equivalent.
- All focused/security/regression tests pass.
- Isolated-HOME canonical passes with no deselection and no unexplained skip change.

### Commit

One implementation/test commit only, e.g.
`fix(rebuild): fail closed on malformed canonical replay`.
No governance state binding in this increment.

---

## R2 — FTS5-Independent Core Corpus Retrieval

**Findings:** AUD-004  
**Severity:** HIGH  

### Why this order

This is the second HIGH finding and has a clear capability contract independent
of the identity work. It must be resolved before packaging prerequisites are
considered, but it does not require a dependency installation or schema change.

### Invariant

FTS5 absence is a supported capability state. Corpus retrieval must either use a
correct deterministic fallback or return a clear typed capability result; raw
SQLite table errors must not escape normal public retrieval.

### Expected files

- `src/corpus/retrieval.py`
- `src/corpus/derived_store.py` only if capability metadata needs a narrow read
  contract update
- `src/access/authorized_read.py` only if the public facade must translate the
  capability result; M5 policy logic must remain unchanged
- `tests/unit/test_m10_5_retrieval.py`
- `tests/unit/test_m10_4_storage.py`
- A focused FTS-capability test fixture/helper if needed

### Forbidden/unrelated files

- No SQLite migration or schema change
- No semantic adapter implementation
- No cloud/network dependency
- No changes to M5 scope composition or authorization policy
- No EvidenceSet budget change
- No packaging files in R2

### Implementation direction

When FTS5 is available, retain the existing path. When unavailable, select the
same corpus-unit columns through a deterministic non-FTS query, apply
`_authorize_and_filter` and metadata filters before lexical scoring, then use the
same score/tie-break/limit path. Keep the fallback explicit in capability
metadata and avoid reading or ranking an unauthorized truncated candidate set.

### Permanent regression

- FTS5 available: current lexical retrieval behavior and deterministic ordering
  remain unchanged.
- FTS5 unavailable: text query returns authorized lexical results without raw
  `OperationalError`.
- Unauthorized high-ranking candidate cannot change authorized results in fallback.
- Metadata-only retrieval remains unchanged.
- Public M5 corpus facade returns the same typed result shape in both capability
  states.

### Focused verification

Controlled migration capability probe with FTS5 enabled and disabled; assert
presence/absence of the table, then exercise the real retrieval facade. Mutation:
force the fallback to rank before authorization or reintroduce the unconditional
FTS join and prove hidden-candidate tests fail.

### Relevant regression

- M10.4 derived-storage/migration tests.
- M10.5 retrieval and real facade regressions.
- M6.6 resource-type isolation.
- Hidden-candidate and authorization-before-influence tests.
- M7 mixed memory/corpus EvidenceSet budget tests.

### Canonical

Mandatory. This is HIGH and changes a core M10 retrieval path. Run isolated-HOME
canonical before and after R2.

### Security invariants

Unauthorized corpus rows must have zero influence on fallback ranking, top-k,
calibration, graph selection, or EvidenceSet contents. M5 remains the sole
authorization authority.

### Rollback / failure risk

The fallback may be O(N) over derived units and must be bounded by existing
result limits after authorization. If performance is unacceptable on the committed
corpus benchmark, retain the capability contract but record the measured risk; do
not replace it with a cloud dependency or weaken authorization ordering.

### Acceptance

- Both FTS capability states are explicit and tested.
- No raw missing-table exception leaks from public retrieval.
- Hidden candidate remains non-influential.
- Existing FTS-enabled results remain stable.
- Canonical passes with no unexplained skip change.

### Commit

One implementation/test commit, e.g.
`fix(corpus): provide deterministic retrieval without FTS5`.

---

## R3 — Freeze and Correct Corpus Identity, Versioning, and Compatibility

**Findings:** AUD-002  
**Severity:** MEDIUM; architecture-sensitive and prerequisite to R5  

### Why this order

The registry, dedup, and versioning modules currently encode incompatible
identity models. Registry concurrency must not be verified against semantics that
will immediately change. R3 therefore freezes the contract first.

### Invariant

Content, logical source, location, authorization, and immutable version identity
are independent. A changed logical source creates a superseding version, not a
new disconnected source. A renamed copy does not silently merge authorization
objects. Rebuild preserves all provenance and scope boundaries.

### Expected files

- `src/corpus/identity.py`
- `src/corpus/contracts.py`
- `src/corpus/registry.py`
- `src/corpus/dedup.py`
- `src/corpus/versioning.py`
- `src/corpus/derived_store.py` only if the derived projection must consume the
  corrected version/source axes
- `tests/unit/test_m10_1_corpus_registry.py`
- `tests/unit/test_m10_3_normalize.py`
- `tests/unit/test_m10_4_storage.py`
- A focused registry-to-version-chain integration test may be added if existing
  files cannot preserve the contract clearly

### Forbidden/unrelated files

- No SQLite schema migration or `migrate_11.py`.
- No M10.8/M11 module.
- No memory JSONL changes or `source_event_id` aliases.
- No cross-scope authorization changes.
- No real 601-PDF corpus mutation during remediation.

### Contract change

Use the selected five-axis model from **Contract Decisions Required**. In
particular, source bytes alone define content identity; logical source identity is
stable across content changes; external reference is provenance/location; scope is
an independent authorization coordinate; version identity includes content and
normalization version and carries explicit supersession.

A changed source at the same logical descriptor must return the existing logical
source ID and produce a new version. Same-content renamed copies share physical
content identity but remain separate logical source objects by default.

### Existing canonical data and migration proof

A SQLite schema migration is **not required**. A canonical-registry compatibility
migration **is required for existing corpus histories** if those histories are to
participate in corrected version chains, because the persisted current IDs and
hashes include descriptor/content combinations and cannot be reinterpreted
without losing identity meaning.

The future implementation must first run an isolated preflight over a copy of
canonical registry/blob fixtures and the documented M10.7-shaped corpus fixture:

1. derive new logical IDs/content hashes;
2. preserve every old record and old ID as historical provenance;
3. create linked corrected records or an append-first compatibility representation;
4. rebuild versions, units, and derived corpus state;
5. compare source count, bytes, scope, provenance, content sharing, and version
   chains before/after;
6. prove rollback leaves the original canonical copy unchanged.

Only after that proof and explicit owner approval may a real canonical migration be
executed. No live corpus or real blob root is touched by plan authoring or by this
future implementation unless separately authorized. The migration must not be a
silent in-place overwrite; old IDs remain traceable.

### Implementation direction

Implement the smallest compatible identity representation that lets old records
remain readable while new records use the corrected axes. If an additive
identity-version/provenance marker is required in JSONL, it must be backward-safe
and not a SQLite schema change. Keep `source_event_id` semantically separate from
corpus source IDs.

### Permanent regression

- Same external reference/scope, changed bytes: same logical source ID, two
  source versions, second explicitly supersedes first.
- Same content, same logical descriptor: idempotent version re-ingest.
- Same bytes, renamed external reference: shared content identity but distinct
  logical source IDs and provenance.
- Same bytes, different scopes: shared physical content only; distinct source,
  version, unit, and authorization identities.
- Registry → version chain → derived rebuild preserves logical state after close,
  new instance, and derived rebuild.
- Legacy compatibility fixture preserves old IDs/provenance and produces a
  deterministic corrected chain.

### Focused verification

Run the existing M10.1/M10.3 identity tests and new registry-to-version tests.
Mutation: restore descriptor+bytes hashing or group versions only by the new
content ID and prove changed-source supersession tests fail.

### Relevant regression

- M10.2 ingestion/blob binding.
- M10.4 derived storage/rebuild and downgrade tests.
- M10.5 retrieval provenance and hidden-candidate tests.
- M10.6 corpus graph provenance/scope tests.
- M5/M6.6 resource-type and cross-scope isolation.

### Canonical

Mandatory. This changes canonical corpus identity semantics and requires isolated
fixture replay plus full isolated-HOME canonical before acceptance. A real corpus
migration is not part of the plan phase.

### Security invariants

Content sharing never grants access. Profile/project/knowledge-space scope remains
explicit. `corpus_source` and `corpus_unit` remain distinct resource types. No
corpus identity is presented as a memory `source_event_id`.

### Rollback / failure risk

The highest risk is losing historical source identity or scope during compatibility
conversion. Use append-first linked records or a staged copy, never destructive
rewrite without a verified rollback snapshot and owner authorization. No backup /
restore execution occurs in this plan phase.

### Acceptance

- Contract is documented in code/contracts/tests.
- Changed-source chains explicitly supersede.
- Renamed/cross-scope identity behavior is deterministic and non-collapsing.
- Existing data compatibility proof passes on isolated fixtures.
- No SQLite schema/migration change is introduced.
- Canonical and relevant cross-milestone security suites pass.

### Commit

Use separate commits if the compatibility proof requires distinct code/test and
canonical-data tooling. Never commit a real-data conversion as part of ordinary
product remediation. The implementation commit must not contain governance state
or a self-referential final hash.

---

## R4 — Complete EvidenceSet DATA Sanitization and Existing Envelope Boundary

**Findings:** AUD-006  
**Severity:** MEDIUM; security-sensitive  

### Why this order

This is an integration/security boundary independent of corpus identity. It is
placed before later corpus registry work so the final remediation audit has a
stable DATA envelope for M8/M10 evidence.

### Invariant

The current EvidenceSet schema remains bounded and field-complete through:

`M8/M10 generation → M7 sanitizer → existing M7 envelope → Hermes pre-LLM hook`.

M8 metadata, corpus provenance, and diagnostic fields remain DATA only. No field
can create system/developer/tool/policy authority. There is exactly one bounded
context envelope, not parallel evidence channels.

### Expected files

- `src/integration/m7/contracts.py`
- `src/integration/m7/hardening.py`
- `src/integration/m7/envelope.py`
- `src/integration/m7/injection_adapter.py` only if the existing hook boundary
  needs a narrow field-complete pass-through
- `src/integration/m7/m8_integration.py` only if current metadata shape requires
  a compatibility adjustment
- `tests/unit/test_m7_5_hardening.py`
- `tests/unit/test_m7_4_injection_adapter.py`
- `tests/unit/test_m7_6_end_to_end.py`
- `tests/unit/test_m8_6_integration.py`
- `tests/unit/test_m10_5_retrieval.py`

### Forbidden/unrelated files

- No second injection/context channel.
- No Hermes core changes.
- No M5 policy changes or authorization inference.
- No EvidenceSet budget increase.
- No changes to M8 authority semantics, calibration, graph bounds, or temporal
  meaning.

### Contract change

Sanitizer reconstruction must preserve all current EvidenceSet fields. The existing
single envelope will serialize one bounded selected-evidence list plus a bounded
DATA-only metadata/provenance section keyed only to selected evidence IDs. The
`corpus_evidence` mirror must not become a second list of injectable evidence; if
serialized, it is a bounded identity/provenance mirror and cannot add items.

Every string reaching the envelope, including `used_scopes`, reason/configuration
strings, metadata values, provenance, summaries, IDs, and marker-like content,
receives the same deterministic DATA escaping. Escaping must break structural
markers such as `role=system`, `role=developer`, `role=user`, and
`[End Zero-Mem Contextual Evidence]`, not merely wrap them.

### Implementation direction

Inventory `EvidenceSet.to_dict`, sanitizer reconstruction, serializer fields, and
hook return shape before editing. Reuse the existing envelope and local recursive
sanitization; do not import a second authorizer or add a new context surface.
Preserve `primary/supporting` roles and all M6.6 `resource_type` values verbatim.

### Permanent regression

- Full M8/M10 EvidenceSet survives sanitize/serialize with metadata and required
  provenance present.
- `primary <= 5`, `supporting <= 3`, `total <= 8` before and after sanitization.
- Corpus mirror cannot add an item outside primary/supporting.
- Scope/configuration strings containing role markers and envelope terminators are
  escaped in the final hook output.
- Corpus text containing instruction-like strings remains DATA.
- M5 authorization and resource-type isolation cannot be changed by metadata.
- Hermes hook returns the same single bounded context contract.

### Focused verification

Run the full end-to-end path, not only intermediate EvidenceSet assertions:
construct M8/M10 evidence, sanitize, serialize, invoke the real hook adapter, and
inspect the returned user-message context. Mutation: bypass `used_scopes` escaping,
drop metadata, or append a second corpus list and prove the new tests fail.

### Relevant regression

M7 hardening/injection/end-to-end, M8.6 integration, M10.5 retrieval, hidden
candidate/graph, M6.6 isolation, sensitivity/redaction, and no-real-Hermes-home
write tests.

### Canonical

Mandatory. This is security-sensitive and changes the final integration boundary.
Run isolated-HOME canonical before and after R4.

### Rollback / failure risk

The risk is accidentally treating metadata as authority or widening context. Keep
metadata explicitly DATA-only and fail closed if malformed fields exceed bounds.
Rollback is the prior single-envelope implementation; do not preserve a partial
new serializer.

### Acceptance

- Current fields survive where the contract requires.
- All envelope strings are structurally escaped.
- One bounded envelope remains.
- No authority, authorization, budget, provenance, or secret boundary regresses.
- Full hook-path security tests and canonical pass.

### Commit

One implementation/test commit, e.g.
`fix(integration): preserve and harden current evidence envelope fields`.

---

## R5 — Atomic Same-Instance Registry Registration

**Findings:** AUD-005  
**Severity:** MEDIUM  

### Why this order

R3 freezes the source identity contract first. R5 then fixes only the reproduced
same-instance race and does not expand into unsupported distributed locking.

### Invariant

For one `CorpusSourceRegistry` instance, concurrent identical registration calls
perform one check-and-append transaction and yield one logical canonical record.
The result remains correct after close, new instance, reopen, and blob rebind.

### Expected files

- `src/corpus/registry.py`
- `tests/unit/test_m10_1_corpus_registry.py`
- `tests/unit/test_m10_2_ingestion.py`
- `tests/unit/test_m10_4_storage.py` only if the reopen/rebuild assertion belongs there

### Forbidden/unrelated files

- No distributed/multi-process locking framework.
- No schema/migration changes.
- No identity-contract changes beyond the R3 interface it consumes.
- No blob path or M5 authorization redesign.

### Contract change

The duplicate lookup, source identity derivation, append, and in-memory index
publication become one instance-lock-protected transaction. A second check under
the lock is mandatory even if an optimistic pre-check remains.

### Implementation direction

Move or repeat all identity-map checks inside `self._lock`; ensure exceptions do
not publish in-memory state ahead of the durable append. Preserve append flush/
fsync behavior and `_update_record` canonical newline normalization.

### Permanent regression

Two synchronized threads registering the same content/ref/kind/scope return the
same source identity, produce exactly one canonical line, close, reopen a new
registry instance, and rebuild one logical source. Add a blob-bound concurrent
case to ensure `blob_ref` rebind does not duplicate lines.

### Focused verification

Use a deterministic barrier around the append boundary. Mutation: restore the
pre-lock check-only behavior and prove duplicate-line assertion fails.

### Relevant regression

M10.1 registry, M10.2 ingestion/blob binding, M10.4 derived rebuild, and R3
identity/version integration tests.

### Canonical

Required before final remediation acceptance; a focused isolated regression is
required for R5. If R5 changes only corpus product/tests, run the full canonical
before accepting the increment because canonical persistence is affected.

### Rollback / failure risk

Avoid holding the lock across unrelated blob I/O. The lock must cover registry
identity publication; blob persistence/rebind remains separately failure-safe.
No cross-process guarantee is added.

### Acceptance

- One logical append under synchronized same-instance concurrency.
- In-memory and on-disk state agree after reopen.
- Existing idempotence, blob binding, newline, and rebuild tests pass.
- No distributed locking or schema change added.

### Commit

One implementation/test commit, e.g.
`fix(corpus): make registry check-and-append atomic per instance`.

---

## R6 — Strict Corpus Blob Digest Validation

**Findings:** AUD-009  
**Severity:** LOW  

### Why this order

R6 is a narrow corpus input-boundary correction after the identity/content
contract is frozen and before portability/packaging prerequisites are evaluated.

### Invariant

The accepted blob digest remains the current 64-character lowercase SHA-256
hexadecimal content address. Empty, short, non-hex, path-like, or otherwise
malformed input fails with `BlobStoreError` before filesystem path construction.
`exists` only reports regular blob files, never the blob directory itself.

### Expected files

- `src/corpus/blob_store.py`
- `src/corpus/contracts.py` only if a shared blob-reference validator belongs in
  the current contract layer
- Corpus extraction/rebuild caller only where raw OS errors must be translated
- `tests/unit/test_m10_2_ingestion.py`
- `tests/unit/test_m10_4_storage.py`
- `tests/unit/test_m10_1_corpus_registry.py` if registry-level malformed refs are
  covered there

### Forbidden/unrelated files

- No new content-addressing scheme.
- No schema/migration changes.
- No path-safety weakening or symlink behavior changes.
- No memory JSONL or M5 authorization changes.

### Contract change

`put` continues to derive the existing SHA-256 digest. `get` and `exists` reject
invalid digest syntax before `_path_for`; missing valid digests return the existing
domain error; directory/non-regular targets cannot count as blobs; filesystem
read errors are translated to stable domain errors without content leakage.

### Implementation direction

Add one closed validator at the blob-store boundary and preserve containment checks
as defense in depth. Ensure extraction/rebuild callers classify `BlobStoreError`
predictably rather than leaking `IsADirectoryError`.

### Permanent regression

- Empty digest rejected.
- Short digest rejected.
- Non-hex digest rejected.
- Path-like digest rejected.
- Valid existing digest reads successfully.
- Valid missing digest returns typed missing-blob error.
- `exists("")` is false or raises the typed validation error, never true.
- Valid blob survives close/new store/reopen.

### Focused verification

Run corpus ingestion/storage tests and a mutation that removes the validator or
restores directory-based `exists`; prove the negative tests fail.

### Relevant regression

M10.1 registry, M10.2 ingestion, M10.4 rebuild, path/symlink safety, and R3
identity/content tests.

### Canonical

Focused and relevant corpus regressions are required. Full canonical is required
at the final remediation gate; run it per increment if the caller/error-boundary
change crosses the public corpus path.

### Rollback / failure risk

Do not reject valid existing lowercase SHA-256 blob refs or alter existing blob
layout. A failed validation must not mutate registry or derived state.

### Acceptance

All malformed cases produce stable domain failures; valid content-addressed blobs
remain readable and rebuildable; no raw filesystem error leaks; path containment
regressions remain green.

### Commit

One implementation/test commit, e.g.
`fix(corpus): validate blob references before filesystem access`.

---

## R7 — Dependency-Free Corpus Config Root Parsing

**Findings:** AUD-001  
**Severity:** MEDIUM  

### Why this order

The selected approach avoids introducing a hidden runtime dependency and becomes a
clean-machine/packaging prerequisite without starting packaging itself.

### Invariant

The supported `config/corpus.yaml` contract works on a clean environment using
only declared/available project facilities. Missing optional config remains
absence-safe. A valid config never silently becomes “unconfigured”; malformed or
duplicate config fails explicitly and does not select an unsafe root.

### Expected files

- `src/corpus/registry.py`
- `src/corpus/blob_store.py`
- Prefer a narrow shared parser module only if duplication cannot be avoided;
  otherwise keep the tiny parser local and identical by contract.
- `tests/unit/test_m10_1_corpus_registry.py`
- `tests/unit/test_m10_2_ingestion.py`
- A clean-config fixture under `tests/fixtures/` if existing fixture conventions
  require it

### Forbidden/unrelated files

- No `pyproject.toml`, installer, lockfile, or packaging artifact in R7.
- No PyYAML installation or system-wide package installation.
- No broad YAML implementation.
- No runtime root fallback to `$HOME`, cwd, username, or repository location.

### Contract change

The intentionally tiny config contract supports one top-level `corpus_root`
scalar with documented whitespace/comment/quote handling. Duplicate, nested,
malformed, non-string, or empty values fail explicitly. Explicit argument and
`ZERO_MEM_CORPUS_ROOT` precedence remains unchanged.

### Implementation direction

Use a deterministic stdlib parser for exactly the supported key, shared by registry
and blob store if possible. Remove silent broad `import yaml` fallback. Preserve
safe unavailable behavior only for a genuinely absent optional config file, not a
present malformed/valid config.

### Permanent regression

- Valid config works with a venv where `yaml` is unavailable.
- Missing config remains unavailable without error.
- Malformed config fails with a typed config error.
- Duplicate `corpus_root` fails closed.
- Explicit argument and environment precedence remain deterministic.
- Both registry and blob store resolve the same root.

### Focused verification

Run the config-root tests under a clean temporary `HOME` with no YAML module
available. Mutation: restore `import yaml`/silent exception and prove valid-config
and malformed-config assertions fail.

### Relevant regression

M10.1 registry, M10.2 ingestion/blob, M10.4 rebuild root behavior, and path
containment tests.

### Canonical

Run the focused clean-environment regression and relevant M10 suite. Full canonical
is required before final remediation acceptance; no dependency installation is
allowed to make the test pass.

### Rollback / failure risk

The parser must not become a permissive YAML interpreter or accept a path from
untrusted nested content. Explicit/env root behavior is the rollback baseline.

### Acceptance

No runtime product path imports undeclared YAML. Valid config works dependency-
free; malformed config is explicit; absent config remains safe; no absolute-machine
path is introduced.

### Commit

One implementation/test commit, e.g.
`fix(corpus): make corpus root config dependency-free`.

---

## R8 — Checkout-Independent Test Roots

**Findings:** AUD-008  
**Severity:** MEDIUM  

### Why this order

This is test-only and should include all permanent regressions added by R1-R7.
Doing it after product remediation prevents new tests from reintroducing the same
portability defect.

### Invariant

No tracked test derives the repository root from the current operator username,
`HOME`, current absolute checkout path, or a stale machine-specific constant.

### Expected files

- The 16 audited test files containing
  `/home/brian-nguyen/Hermes Workplace/Zero-mem`
- Use `Path(__file__)`-relative discovery or a clearly scoped test-only helper;
  do not introduce a product runtime helper.
- Any affected static-scan fixtures that assert the source tree location

### Forbidden/unrelated files

- No `src/` changes.
- No changes to product configuration or runtime root resolution.
- No weakening of static/security scans.
- No renaming tests merely to evade terminal guards.

### Contract change

Test roots are derived from the test file/repository location and work from any
checkout path, including a spaced path and a second temporary checkout.

### Implementation direction

Replace each absolute operator-path constant with an OS-safe dynamic path. Keep
static scanners pointed at the active checkout and preserve all test assertions.
Prefer minimal per-file changes over a global helper that could itself hide root
calculation errors.

### Permanent regression

- Affected targeted tests pass from the current checkout.
- The same affected test set passes from a second temporary checkout path.
- No absolute operator path remains in tracked tests.
- Product-source path safety scans remain unchanged and pass.

### Focused verification

Use a temporary copy/checkout at a different path; run the affected static,
security, and integration tests there. Mutation: restore one hard-coded root and
prove the alternate-checkout run fails or scans the wrong tree.

### Relevant regression

All affected M4/M5/M8/M9 gates, M6.6 security checks, M7 hardening checks, and
all new permanent regressions from R1-R7.

### Canonical

Required after test changes. Run current-checkout canonical and the affected test
set from the second checkout; final remediation canonical remains authoritative.

### Rollback / failure risk

The main risk is resolving the wrong parent depth and silently scanning a stale
path. Positive-control assertions must confirm the active source tree is the one
being inspected.

### Acceptance

All 16 hard-coded roots are removed from tracked tests; current and alternate
checkout targeted suites pass; no product code or security expectation is weakened.

### Commit

One test-only commit, e.g.
`test(portability): derive repository roots from checkout location`.

---

## R9 — Governance Duplicate-Key Correction

**Findings:** AUD-007  
**Severity:** LOW; governance-only  

### Why this order

R9 must not alter the audit baseline while the plan is being authored. It is a
separate governance correction after owner approval and after the effective M2
value is confirmed from `m2_increment_7_schema_version: 6` and related evidence.

### Invariant

Every effective top-level governance key has exactly one authoritative value.
State consumers must not depend on YAML last-wins behavior or textual substring
matches.

### Expected files

- `project-state.yaml`, editing the existing `m2_current_version` key in place
- `tests/baseline/test_project_artifacts.py` only if a structural whole-file
  duplicate-key gate is genuinely required by existing convention
- A narrow governance validation test/helper only if current baseline tooling
  cannot prove the invariant

### Forbidden/unrelated files

- No `src/` changes.
- No schema/migrations.
- No historical acceptance rewrite.
- No broad normalization of unrelated same-value historical keys unless required
  by the structural validator.
- No change to product milestone semantics.

### Contract change

The effective value is `6`, matching the verified M2 increment-7/schema-v6
record. The earlier duplicate `m2_current_version: 4` is removed or reconciled
in place without appending a second block. Governance parsing detects duplicate
column-0 top-level keys across the whole file and fails closed on divergent
values.

### Implementation direction

Use a deterministic stdlib structural scan if dependency-free parsing is required;
assert effective values and duplicate counts. Do not use a substring-only check.
Preserve historical evidence as history, but keep one effective state key.

### Permanent regression

- A self-contained shadowed state fixture proves substring-only logic would pass
  while the structural/effective-value gate fails.
- Current project state has one `m2_current_version` key with value `6`.
- Existing M10 state remains unchanged and parses consistently.

### Focused verification

Run governance/baseline tests and a direct structural scan. Mutation: reintroduce
the duplicate and prove the new gate fails.

### Relevant regression

`tests/baseline/test_project_artifacts.py`, state parsing, and all existing
milestone-state consistency checks. No product suite is logically changed, but a
canonical run is required if tracked baseline tests change.

### Canonical

Not required for a pure documentation/state edit if no tests or product files
change; required if the baseline test or tracked state affects canonical
collection/behavior. Do not claim a canonical run at the governance commit unless
one occurs.

### Rollback / failure risk

The risk is selecting an incorrect historical value or creating another duplicate
block. Verify the effective value against M2 increment-7 evidence before editing;
rollback is a governance-only revert.

### Acceptance

Exactly one effective `m2_current_version` exists with value `6`; the whole-file
duplicate guard catches divergent shadowing; no product code/schema/test security
expectation is weakened.

### Commit

One governance-only commit after approval, e.g.
`chore(state): remove divergent duplicate M2 version key`.

---

## Cross-Increment Regression Matrix

Legend: **F** = full suite required for the increment; **R** = relevant regression
required; **T** = targeted verification; **—** = no direct change, but final audit
still checks the invariant.

| Increment | M1/M2 persistence | M4 project rebuild | M5 authorization | M6.6 isolation | M7 EvidenceSet | M8 graph/temporal/calibration | M9 projection | M10 registry | M10 ingestion | M10 retrieval | M10 graph | Path safety | Canonical |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R1 | R/F | R/F | R/F | R | R | R | R | — | — | — | — | — | F |
| R2 | — | — | R | R | R | — | — | — | R | R/F | R | — | F |
| R3 | — | — | R | R | R | R | — | R/F | R/F | R | R/F | — | F |
| R4 | — | — | R | R | R/F | R/F | R | R | R | R | R | R | F |
| R5 | — | — | — | R | — | — | — | R/F | R/F | R | R | — | F or final gate |
| R6 | — | — | — | — | — | — | — | R | R/F | R | R | R | final gate |
| R7 | — | — | — | — | — | — | — | R | R/F | — | — | R | final gate |
| R8 | T | T | T | T | T | T | T | T | T | T | T | R/F | F after test changes |
| R9 | — | — | — | — | — | — | — | — | — | — | — | — | conditional |

## Findings Closure Matrix

Each finding has exactly one primary closure owner.

| Finding | Primary owner | Closure condition |
| --- | --- | --- |
| AUD-001 | R7 | Dependency-free valid config works; malformed config explicit; no silent YAML fallback |
| AUD-002 | R3 | Identity contract, compatibility proof, corrected version chain, and scope/provenance preservation pass |
| AUD-003 | R1 | Malformed replay blocks before publication and prior derived state remains intact |
| AUD-004 | R2 | FTS5-available and FTS5-absent retrieval both have explicit safe behavior; fallback preserves auth-before-influence |
| AUD-005 | R5 | Same-instance synchronized registration yields one canonical line after reopen/rebuild |
| AUD-006 | R4 | Current EvidenceSet fields and required provenance survive the single escaped DATA envelope |
| AUD-007 | R9 | One effective `m2_current_version: 6`; whole-file duplicate detection passes |
| AUD-008 | R8 | All 16 test roots are checkout-independent and alternate-checkout tests pass |
| AUD-009 | R6 | Closed digest validation rejects malformed refs and maps failures to domain errors |

## Permanent Regression Matrix

| Finding | New permanent regression | Failure-before-fix evidence | Pass-after-fix requirement |
| --- | --- | --- | --- |
| AUD-001 | Valid/malformed/missing `corpus.yaml` under no-YAML environment | Current valid config probe returns `None`; `import yaml` unavailable | Valid root resolves; malformed/duplicate config fails explicitly |
| AUD-002 | Registry → version chain for changed, renamed, and cross-scope sources | Current probe yields two one-version chains and no `supersedes` | Stable logical source, explicit supersession, shared physical content only |
| AUD-003 | M4/M5 malformed replay with prior-state preservation | Current rebuild returns success with `skipped=1` and incomplete state | Typed blocked/incomplete result; prior state remains readable |
| AUD-004 | FTS5-enabled/disabled real facade retrieval | Current absent-table probe raises `CorpusQueryError` from missing FTS table | Deterministic fallback, no raw table error, hidden candidate has zero influence |
| AUD-005 | Synchronized same-instance two-thread registration + reopen | Current probe writes two identical JSONL lines | Exactly one canonical record after close/new instance/rebuild |
| AUD-006 | Full M8/M10 EvidenceSet → sanitize → serialize → hook | Current sanitizer drops metadata/mirror and emits raw scope markers | Fields preserved, markers escaped, one bounded DATA envelope |
| AUD-007 | Whole-file duplicate-key shadow fixture and current state scan | Current file has `m2_current_version` values `4` and `6` | Structural gate rejects shadowing; effective value is uniquely `6` |
| AUD-008 | Alternate-checkout affected test run | 16 tests contain current absolute path | Current and second-checkout targeted tests pass; no absolute operator root |
| AUD-009 | Empty/short/non-hex/path-like/valid/missing digest cases | `exists("")=True`; `get("")` leaks `IsADirectoryError` | Typed validation/missing errors; valid blob round-trip remains intact |

## Canonical Strategy

1. **No canonical run is claimed at `975aaaac4057d8faf2b135c344488aabcbcb90db`;**
   that commit records only the audit Markdown.
2. R1 and R2 require full isolated-HOME canonical runs because they are HIGH
   persistence/retrieval fixes.
3. R3 and R4 require full canonical runs because they change corpus identity and
   the security-sensitive final EvidenceSet boundary.
4. R5 requires a full canonical before acceptance because it changes canonical
   registry persistence; at minimum it must be included in the final canonical.
5. R6/R7 require focused and relevant M10 regressions and are included in the
   final canonical; run a per-increment full canonical if public caller behavior
   changes.
6. R8 requires canonical after test changes and alternate-checkout validation.
7. R9 requires canonical only if its governance correction changes a collected
   baseline test or canonical behavior; otherwise targeted governance validation
   is sufficient.
8. After all R increments, run exactly the authoritative command in a fresh
   isolated HOME:

   ```sh
   TEST_HOME="$(mktemp -d)"
   HOME="$TEST_HOME" .venv/bin/python3 -m pytest tests/ -q
   RC=$?
   rm -rf "$TEST_HOME"
   exit "$RC"
   ```

   Requirements: zero failures, no deselection, and any skip-count change must be
   explained by an approved remediation rather than assumed.

## Governance Strategy

- Do not edit `project-state.yaml` or `implementation-plan.json` while authoring
  this plan.
- Do not mark any AUD finding fixed, remediation started, packaging started,
  M10.8 created, or M11 created.
- The audit artifact is preserved at `975aaaac4057d8faf2b135c344488aabcbcb90db`.
- Remediation execution should be recorded through dedicated remediation evidence
  and one effective state block, never by appending duplicate YAML keys.
- The plan itself is the authoritative remediation sequence until owner approval;
  no current project-state field is changed to imply execution.
- Any later state update must use actual tested HEADs and must never embed a
  self-referential future commit hash.
- AUD-007 is a separate governance-only correction owned by R9; it must not be
  hidden in a product remediation commit.

## Packaging Preconditions

Prerequisites only; packaging remains `NOT STARTED`.

Before packaging can begin, the following must be true:

- all nine AUD findings are closed with evidence;
- the final remediation canonical is green under isolated HOME;
- the targeted post-remediation audit is green;
- config/dependency behavior is reproducible without undeclared runtime imports;
- test suite works from a second checkout path;
- no schema or migration change is introduced without a separately approved
  architecture decision;
- working tree is clean apart from any explicitly tracked governance evidence;
- feature freeze is explicitly lifted by the owner.

No `pyproject.toml`, installer, service, Docker image, release artifact, or
clean-machine installation is created by this plan.

## Final Remediation Acceptance

All conditions below are required before packaging may be proposed:

- All 9 findings closed by their assigned primary increment.
- 0 Critical unresolved.
- 0 High unresolved.
- 0 Medium unresolved unless the owner explicitly accepts the residual risk.
- 0 Low unresolved unless the owner explicitly accepts the residual risk.
- Canonical suite green under fresh isolated HOME, zero failures, no deselection.
- Permanent regression matrix green, including hidden-candidate, hidden-graph,
  M6.6 isolation, EvidenceSet 5/3/8, path safety, and no-real-Hermes-home writes.
- Canonical persistence round trips include close/new-instance/reopen/rebuild.
- Targeted post-remediation audit passes all nine root causes and touched
  cross-milestone boundaries.
- Product/test/schema/migration changes are exactly those approved by the R
  increments; no drive-by refactor or feature work.
- Working tree is clean and evidence commits contain no self-referential hashes.
- Feature freeze is preserved until explicit owner direction.

## Post-Remediation Targeted Audit

After R1-R9 are implemented and individually accepted, perform a targeted audit,
not a new full M1-M10 discovery audit. It must re-check:

- AUD-001 config dependency and clean environment;
- AUD-002 identity axes, legacy compatibility, supersession, scope/provenance;
- AUD-003 malformed replay and prior-state preservation;
- AUD-004 FTS capability states and authorization-before-influence;
- AUD-005 same-instance concurrent registry and reopen/rebuild;
- AUD-006 complete M8/M10 EvidenceSet hook DATA boundary;
- AUD-007 whole-file governance duplicate protection;
- AUD-008 alternate-checkout test execution;
- AUD-009 strict blob validation and caller error mapping;
- all touched M1/M2/M4/M5/M6.6/M7/M8/M9/M10 cross-boundaries.

Only after this targeted audit and the final canonical pass may packaging be
considered.

## Explicitly Deferred

- Packaging and release engineering.
- Clean-machine installation.
- Backup/restore implementation or testing.
- Real 601-PDF corpus migration or re-ingestion.
- Real Obsidian vault mutation.
- Any new document format, folder watcher, dashboard, adapter expansion, semantic
  retrieval implementation, enrichment feature, M10.8, or M11.
- Any SQLite schema migration unless a future implementation preflight proves it
  unavoidable and the owner separately authorizes it.
- Distributed/multi-process locking beyond R5's same-instance contract.

## Plan Validation Checklist

Before owner approval, verify deterministically:

- [x] Full `post-m10-audit.md` read from disk.
- [x] AUD-001 through AUD-009 each appear in the plan.
- [x] Each finding has exactly one primary remediation increment.
- [x] AUD-003 is first and specifies fail-closed replay semantics.
- [x] AUD-004 selects the deterministic lexical fallback contract.
- [x] AUD-002 defines content/logical/location/authorization/version axes and
      proves why existing canonical history needs a compatibility/data migration,
      but no SQLite schema migration.
- [x] AUD-005 is limited to same-instance concurrency.
- [x] AUD-006 covers the complete existing hook path with one bounded envelope.
- [x] AUD-007 remains governance-only.
- [x] AUD-008 remains test-only.
- [x] AUD-009 defines strict current SHA-256 digest validation.
- [x] M6.6, hidden-candidate, hidden-graph, EvidenceSet 5/3/8, sensitivity,
      path-safety, and no-real-Hermes-home invariants remain required.
- [x] No M10.8, M11, packaging, installation, backup/restore, schema change, or
      product implementation is started.
- [x] No product code was changed while creating this plan.

## Explicit Stop

This document is PLAN ONLY. Do not start R1 or fix any AUD finding until the owner
explicitly approves `post-m10-fix-plan.md`.
