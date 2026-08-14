# V1.1.0 Obsidian Knowledge Workspace Contract

**Status:** PROPOSED — normative planning contract

**Owner:** WP-22

## Canonical Sources and Baseline

- `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` §§5.1–5.2, 9.1–9.3, 12.1–12.9, 14.2–14.4, 18 stage 9, 20, and 21.1.
- ADR-008.
- Exact-master M9 projection/runbook and acceptance M9.1–M9.6: safe deterministic one-way projection and human-edit conflict preservation are verified baseline behavior; write-back and Candidate Review were explicitly absent and remain implementation gaps.

## Role and Boundaries

One Obsidian Vault is the primary human workspace for profiles, knowledge spaces, project state, decisions, tasks, curated research, candidates, and conflicts. The managed projection is human-readable without a required plugin. It is not the raw event store, artifact store, retrieval engine, authorization authority, or only copy of canonical knowledge.

Zero-Mem may write only its configured managed subtree after realpath/symlink containment and three-signal ownership checks. `.obsidian/`, human-owned notes, unknown-ownership files, and every path outside the managed subtree remain read-only. Raw secrets, high-volume stdout/stderr, raw event streams, embedding vectors, binary graph indexes, temporary/cache data, and `never_store` content never enter the Vault.

## Required Namespace and Views

The exact folder naming may migrate safely, but one Vault must expose these capabilities:

| Required view | Minimum content | Canonical source |
|---|---|---|
| System Home | capture/derived/projection health, index/projection version, pending review and conflict counts | content-safe WP-15 status plus projection manifest |
| Profile Home | behavior reference, knowledge/memory priorities, access/write/tool policy, privacy ceiling, evidence budget | versioned WP-20/WP-13 profile config |
| Project Home | objective, active requirements, current verified state, next action, source links | canonical project/task/verification traces |
| Decision Log | active, superseded, and conflicted decisions with rationale/provenance | canonical decision traces |
| Task State / Current State | completed, in-progress, blocked, unverified, next step | canonical task-state and verification records |
| Candidate Review | pending/approved/rejected/expired candidates with review provenance | write-back/candidate queue |
| Conflict Queue | source, decision, profile, projection, concurrent, and stale conflicts with resolution status | WP-14 conflict records plus projection conflicts |
| Knowledge Space Index | spaces, sources, entities, topics, and authorized links | canonical metadata and curated research |

## Note and Projection Schema

Every managed note includes stable `note_id`, `note_type`, `source_trace_ids`, source/artifact references, timestamp/time validity, `profile_affinity`, `knowledge_spaces`, project/task relation when present, lifecycle `status`, `verification`, `sensitivity`, `write_scope`, `projection_version`, and canonical/manifest fingerprint. Missing required provenance makes the note ineligible and produces a safe diagnostic; it never produces an untraceable note.

## Projection Lifecycle

1. Select only authorized, sensitivity-eligible, lifecycle-eligible canonical records.
2. Build a deterministic desired projection with provenance and canonical watermark.
3. Classify existing files using manifest listing, physical containment, and managed frontmatter marker.
4. Create/update unchanged managed files idempotently; preserve human/unknown files.
5. Mark stale generated data, authorization revocation, deletion/tombstone, and sensitivity changes explicitly. Retire only provably owned unchanged files; preserve edited files and queue a conflict.
6. Atomically publish the manifest/projection version. Repeating with the same canonical state/configuration performs zero content writes.

Projection triggers are explicit manual/CLI/API request, successful canonical write-back, approved scheduled batch, or rebuild/upgrade. A note edit alone never writes canonical state. Projection can be rebuilt from canonical records, artifacts, approved write-back records, and versioned profile/policy configuration.

## Write-Back and Review Queue State Machine

```text
detected_edit
  -> candidate_created
  -> validating_schema_path_sensitivity
  -> authorizing_write_scope
  -> checking_duplicate_stale_concurrent_conflict
  -> pending_review
  -> approved | rejected | conflicted | expired
  -> approved canonical append/write-back record
  -> canonical validation + derived sync
  -> projection regeneration
```

- The original human bytes remain preserved until an explicit reviewed resolution.
- Approval appends a canonical event/decision/preferences/state transition with reviewer, source note/fingerprint, previous canonical watermark, rationale, timestamp, and verification. It never edits a raw trace in place.
- Rejection records a content-safe audit decision and causes no canonical mutation.
- Duplicate candidates resolve idempotently to the existing candidate/decision; they do not create repeated writes.
- A stale source or concurrent canonical change becomes a conflict and requires rebase/review; last-writer-wins is forbidden.
- Unknown ownership, malformed metadata, unauthorized scope, path escape, or secret-bearing content fails closed before canonical access.
- Review decisions cannot raise the caller's profile, privacy, source, or write authorization.

## Conflict Taxonomy and Ownership

| Conflict type | Detection/authority | Required behavior |
|---|---|---|
| Source conflict | WP-14 canonical conflict rules | Preserve all source traces; show verification/time/source; no silent winner |
| Decision conflict | WP-14 decision lifecycle | Return/display all active positions and resolution record |
| Profile conflict | WP-20 policy/version validation | Fail closed on incompatible scopes/policies; require authorized policy review |
| Projection conflict | WP-22 manifest/ownership comparison | Preserve human note; generate deterministic proposed sibling/diff; queue review |
| Concurrent update | Canonical watermark/idempotency comparison | Reject stale commit, create conflict, require rebase/review |
| Stale information | Time validity/current-state checks | Label stale/superseded; never present as current verified state |

WP-22 presents and routes conflicts; it cannot invent canonical truth or resolve a WP-14 conflict without an approved resolution record.

## Required Acceptance Scenarios

- **Approved change:** valid authorized edit is reviewed, appends exactly one canonical write-back record, becomes retrievable after declared sync, and regenerates a provenance-complete note.
- **Rejected change:** records review outcome, writes no canonical content/state change, and preserves the human edit for audit.
- **Conflict:** human and canonical changes are both preserved; no overwrite; one deterministic conflict record appears in Conflict Queue.
- **Duplicate:** replay/retry creates no duplicate candidate, canonical event, note, or manifest entry.
- **Stale source:** candidate cannot commit against an older watermark; conflict/rebase is required.
- **Concurrent change:** only one compatible commit succeeds; the other becomes an explicit conflict without data loss.
- **Unauthorized write:** fails before canonical mutation and leaks no hidden profile/source data.
- **Malformed edit:** invalid YAML/schema/path/sensitivity fails closed, preserves bytes, and emits a content-safe review error.
- **Delete/tombstone:** approved delete follows retention policy across canonical record, artifact, index, and projection; edited/human-owned notes are never silently deleted.
- **Idempotency/rebuild:** repeated projection makes zero writes; deleting the managed projection and rebuilding reproduces byte-equivalent eligible notes and views.
- **Isolation:** `isolated` and `source_restricted` views contain no out-of-scope note, link, count, conflict, or source locator.
- **Security:** adversarial secrets do not appear in note, manifest, conflict metadata, logs, queue, or temporary output; path/symlink tests cannot escape the managed root.
- **No loops:** projection output is not re-ingested as a new candidate without an actual human change and stable change-origin marker.

## Performance and Operations

WP-16 benchmarks initial build, incremental update, candidate scan, review validation, conflict generation, and clean rebuild by note count and bytes. Projection work is batch/event-important, not every turn. Status exposes projection watermark, pending/failed counts, last success/error, and backlog without note content. Recovery deletes/rebuilds only provably managed derived output; canonical write-back records remain protected by WP-14/WP-17 backup and rollback rules.
