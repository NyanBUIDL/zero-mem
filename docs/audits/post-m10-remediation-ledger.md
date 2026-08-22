# Post-M10 Audit — Remediation Ledger

**Purpose:** Authoritative governance ledger reconciling the nine unique root
findings (`AUD-001`..`AUD-009`) from `post-m10-audit.md` against the current
source tree. Each row records the fix commit (full SHA), the permanent
regression, and the disposition.

**Source of truth:** `docs/audits/post-m10-audit.md` (audit findings) and the
current working tree (`git rev-parse HEAD` = the tree inspected for this
reconciliation). Fix SHAs are full object IDs, source-bound and independently
re-derivable via `git show <sha>`.

**Reconciliation date:** 2026-08-22.
**Authority:** Governance-only. This ledger changes no product source, schema,
migration, runtime, test expectation value, or release history. It is
verification evidence, not a new authorization.

## Disposition legend

- `CLOSED` — the specific defect anti-pattern is removed and the fix is present
  in the current tree; a permanent regression exists.
- `VERIFIED` — `CLOSED` plus the fix commit is an ancestor of the release SHA
  (`fa803b6` / `547cb7d`) and the focused regression passes on the current tree.
- `OPEN` — not remediated.

All nine findings are `CLOSED`/`VERIFIED`. No finding remains `OPEN`.

## Ledger

| Finding | Severity | Fix commit (full SHA) | Fix commit message | Permanent regression (test) | Disposition |
| --- | --- | --- | --- | --- | --- |
| AUD-001 | MEDIUM | `00887e0f08ca95d867a697c17d83d4cbb76678f1` | `fix(corpus): make corpus root config dependency-free` | `test_root_resolution_valid_config_without_yaml_module` (test_m10_1_corpus_registry) | VERIFIED |
| AUD-002 | MEDIUM | `c75ec456248f5c75bdf5990351925d94b3cc9af6` | `fix(corpus): separate logical source and content version identity` | `test_registry_changed_bytes_keep_logical_source_and_supersede`; `test_renamed_same_bytes_share_content_only`; `test_changed_source_creates_new_version_with_supersedes` | VERIFIED |
| AUD-003 | HIGH | `f2cce27daafed18b838db3c3a2e617aff033cc3e` | `fix(rebuild): fail closed on malformed canonical replay` | `test_full_rebuild_malformed_json_blocks_and_preserves_prior_state`; `test_replay_failure_restores_prior_m4_state` | VERIFIED |
| AUD-004 | HIGH | `c2faa6ca14538e32bdbc9c991720afb605f9bc17` | `fix(corpus): provide deterministic retrieval without FTS5` | `test_fts5_unavailable_uses_authorized_lexical_fallback`; `test_fts5_unavailable_hidden_candidate_has_zero_influence` | VERIFIED |
| AUD-005 | MEDIUM | `c75ec456248f5c75bdf5990351925d94b3cc9af6` | `fix(corpus): separate logical source and content version identity` | `test_same_instance_concurrent_registration_is_atomic_through_reopen` (added `3c6f24e0daeafc62cc9743cd9cb9015cfa96e570`) | VERIFIED |
| AUD-006 | MEDIUM | `01fdd2cb92ef86bdbc3cfcef5da8cb255368aa38` | `fix(integration): preserve and harden current evidence envelope fields` | `test_role_marker_neutralized`; `test_conflict_with_malicious_content_escaped`; `test_sanitization_preserves_evidence_count` (test_m7_5_hardening) | VERIFIED |
| AUD-007 | LOW | `7e0e90e8dd774a407819f59c8c6b9a31d2b1eb53` | `fix(governance): remove duplicate M2 version declaration` | `test_project_state_has_one_m2_current_version`; `test_project_state_has_no_unexpected_top_level_duplicate_keys` | VERIFIED |
| AUD-008 | MEDIUM | `204a006e70dc0f3a1def3a16a12d4d2dd9493234` | `test(portability): remove machine-specific checkout roots` | `test_tracked_tests_reject_audited_checkout_root` (test_project_artifacts) | VERIFIED |
| AUD-009 | LOW | `6d8472bc7603148656b5886736df7a13501945c4` | `fix(corpus): validate blob references before filesystem access` | `test_blob_store_rejects_invalid_digest_references`; `test_blob_store_valid_missing_digest_has_distinct_semantics` | VERIFIED |

AUD-009 also carries a companion integrity fix `d0852249588d3c0b5ce8d877bc7601dc58bfe3b2`
(`fix(corpus): verify canonical blob payload integrity`) that closes the
related PKG-7 tamper boundary; both are ancestors of the release SHA.

## AUD-007 note

`AUD-007` was the material divergent duplicate governance key. The M2 duplicate
was resolved by `7e0e90e` (at the time of the audit). The remaining seven
duplicate top-level keys (`m1_increment_4_2_status`, `m1_increment_4_3_status`,
`m1_increment_4_4_status`, `m1_increment_4_4_evidence`, `m1_increment_4_status`,
`m3_increment_1_plan_commit`, `m1_increment_4_4_plan`) — including the divergent
`m1_increment_4_status: in_progress` vs `verified` — were resolved in the
post-M10 governance cleanup (see the state-cleanup handoff), and the baseline
`KNOWN_HISTORICAL_DUPLICATES` inventory is now empty. The whole-file
duplicate-key gate therefore enforces zero duplicate top-level keys.

## Verification basis

- Each fix commit is an ancestor of both `fa803b6` (v1.2.4 tested product SHA)
  and `547cb7d` (release tag target), confirmed via
  `git merge-base --is-ancestor <fix> <ref>`.
- Focused regression run on the current tree (isolated HOME/TMPDIR):

  ```
  316 passed, 2 skipped
  ```

  covering `tests/baseline`, `test_m9_1_security`, `test_m4_rebuild`,
  `test_m10_5_retrieval`, `test_m10_1_corpus_registry`, `test_m10_3_normalize`,
  `test_m7_5_hardening`, and `test_m10_2_ingestion`.

## Open items

`NONE`.