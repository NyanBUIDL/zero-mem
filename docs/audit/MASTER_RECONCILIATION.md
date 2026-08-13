# Master Reconciliation — 2026-08-14

## Scope and Result

This record reconciles the existing Zero-Mem v1.1.0 planning layer with the exact upstream state fetched from `https://github.com/NyanBUIDL/zero-mem.git` on 2026-08-14. It is observed/planning evidence only and authorizes no implementation or Git publication.

| Item | Verified value |
|---|---|
| `origin/master` | `78c4bb46b88b8ce9987c6882b24201e08b82a7f0` |
| Annotated tag object | `v1.0.0` at `923bd893f6a21c177ae1043f4122e063c95bb03e` |
| Tagged commit | `79989f34ce3578f275a7b910c8a189896ce9ad57` |
| Merge base | `79989f34ce3578f275a7b910c8a189896ce9ad57` |
| Ahead/behind | master is 1 commit ahead and 0 commits behind the tagged commit |
| Intervening commit | `78c4bb46` — `docs: organize post-v1 repository documentation` |

## Delta Classification

The one-commit delta reports 137 changed paths and 284 insertions/284 deletions. It contains:

- **Documentation/path changes:** acceptance, architecture, audit, plan, runbook, and reference Markdown files move into organized `docs/` subdirectories without content changes; manifests and references point to the new paths.
- **Test/evidence changes:** `project-state.yaml`, `implementation-plan.json`, baseline tests, and comments in focused tests update evidence paths. Historical acceptance results remain historical evidence bound to their recorded commits/environments.
- **Source behavior changes:** no Zero-Mem runtime behavior supporting F-001–F-014 changes. Modified `src/` lines are documentation references in comments/docstrings. `scripts/verify_m0_acceptance.py` changes its input path to the moved architecture file; this is repository verification behavior, not Zero-Mem runtime behavior.
- **Configuration changes:** `config/projection.yaml.example` changes a comment-only plan path.
- **Finding remediation:** none for F-001–F-014. Every source/package blob named by those findings is byte-identical between the tag and master.
- **Previously completed remediation:** PKG-7 dispositions remain resolved by their recorded commits. The documentation reorganization moves `audit-pkg7.md` to `docs/audits/audit-pkg7.md` but does not weaken its closure evidence.

## Finding-Path Identity Evidence

The following audited paths have identical Git blob IDs at `v1.0.0` and exact master: `zero_mem/hermes_integration.py`, `zero_mem/commands_doctor.py`, `zero_mem/paths.py`, `pyproject.toml`, `packaging/install.py`, `src/integration/capture_adapter.py`, `src/storage/ingest.py`, `src/storage/jsonl_capture.py`, `src/integration/zero_mem_runtime.py`, `src/integration/hermes_read_adapter.py`, `src/integration/hermes_registration.py`, `src/corpus/retrieval.py`, `src/retrieval/search.py`, and `src/integration/m7/injection_adapter.py`.

This identity check is sufficient to preserve the baseline code observations on master. It does not replace the closure tests required for each finding; those tests are listed in [FINDINGS_RECONCILIATION.md](FINDINGS_RECONCILIATION.md).

## Governance Reconciliation

Authority is split by subject so that no status file or plan can silently rewrite implementation truth:

1. `Tai_lieu_thong_nhat_Hermes_External_ZeroMem.docx` is the product specification for goals and invariants.
2. Exact-master source, tests, schemas, migrations, packaging, runtime configuration, and Git history are implementation truth.
3. `project-state.yaml`, `implementation-plan.json`, and `docs/acceptance/` are historical milestone/acceptance evidence; their `verified` records do not authorize or complete v1.1.0 WPs.
4. Upstream `docs/audits/` documents historical audit dispositions. PKG-7 remains closed unless regression evidence appears.
5. This planning layer's `docs/audit/` is current observed audit truth; `docs/v1.1.0/` is planned truth.
6. `docs/v1.1.0/STATUS.md` is the operational status authority for v1.1.0.
7. `AGENTS.md` defines the current planning/source-freeze protocol.
8. Only an explicit maintainer authorization naming a WP and exact implementation write scope authorizes implementation.

The upstream `AGENTS.md` says the master DOCX is authoritative and also contains a stale “planning and environment inspection” workflow statement. `project-state.yaml` and `implementation-plan.json` show M10/PKG-7 completion. The reconciliation preserves the DOCX's product authority but treats executable source/evidence and Git history as implementation truth. Historical workflow text cannot override exact-master state, and historical approvals cannot authorize v1.1.0.

Chat history is not project truth. A current maintainer instruction may authorize an action only when its scope is explicit and the corresponding governance/status record is updated.

## Planning Consequences

- Current phase is `V1.1.0 RE-PLANNING`.
- WP-00 is the single active package and is renamed **Baseline Reconciliation and Delta Audit**.
- WP-00 may be at most `READY FOR REVIEW` until maintainer verification.
- WP-01 through WP-19 remain `NOT STARTED` and are not implementation-authorized.
- No new WP or finding is required by the one-commit delta.
- The existing five ADRs remain `PROPOSED`; the delta supplies no basis to approve or reject their target decisions.
- Publication remains `WAITING FOR MAINTAINER APPROVAL`.

## Revalidation Trigger

Before commit/push, fetch `origin/master` and compare it with the SHA above. If it differs, stop publication, inventory the new delta, recheck finding-path blobs and governance evidence, and return any planning-impacting change to maintainer review.
