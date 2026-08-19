# WP-34 Evidence

- WP: WP-34 Profiles / Knowledge / Obsidian
- Baseline SHA: `7d871a95017c250f2d27a6e284ccfc6ad6f3c02e`
- Dependencies: WP-29 VERIFIED; WP-32 VERIFIED; WP-33 VERIFIED.
- Scope: qualification/reconciliation of existing M9.1–M9.6 projection.
- Implementation correction: `src/projection/reconcile.py` now validates physical managed-root containment immediately after target construction and before any target existence, symlink, ownership-marker, or content probe. This is a minimal fail-closed boundary correction; no architecture or schema changed.
- Existing implementation: `src/projection/*`; controlled CLI `scripts/project_to_obsidian.py`.
- Focused command: `.venv/bin/python -m pytest tests/unit/test_m9_*.py tests/unit/test_wp29_authorization.py tests/unit/test_wp32_context.py --basetemp=/home/lenovo/pytest-wp34-fix -q`.
- Focused result: `502 passed in 4.10s`.
- Full isolated command: `.venv/bin/python -m pytest tests/ --ignore=tests/baseline/test_project_artifacts.py --basetemp=/home/lenovo/pytest-wp34-final -q` with isolated HOME/XDG directories.
- Full result: `3219 passed, 5 skipped in 67.94s`.
- Verified boundaries: M5 authorization before projection/render; explicit profile/project scope; honest knowledge-space limitation where current views do not expose it; canonical JSONL/SQLite unchanged; deterministic identity/render/reconcile; path, symlink, traversal, `.obsidian`, ownership, human-edit, and secret-baseline protection; no write-back, LLM, network, embedding, or real-vault apply.
- Final Graphify: `7248 nodes, 21399 edges, 193 communities`; disposable output `/home/lenovo/graphify-zero-mem-v1.2-wp34-final-2`.
- Independent fail-closed review: `passed: true`; `security_concerns: []`; `logic_errors: []`.
- Review note: residual writer TOCTOU is non-blocking under the approved local single-writer threat model; descriptor-relative hardening is recommended only if that threat model expands.

- Historical review record: an earlier independent review reopened WP-34 after identifying reconcile probe-before-containment, writer directory-creation TOCTOU, and combined project plus unsupported knowledge-space scope-widening risks. At that historical point the state was `VERIFYING`; the final requalification below supersedes that result without rewriting it.

## Limitations

- Knowledge-space projection is only qualified where the existing authorized contract exposes that field. No schema or fallback was invented for absent knowledge-space data.
- The known historical baseline artifact wording mismatch remains excluded from isolated regression by prior governance evidence.

## Final WP-27-dependent requalification — 2026-08-19

- Dependency WP-27 is now `VERIFIED` under the frozen contract.
- Fresh WP-34 focused suite: `502 passed in 2.34s`.
- No WP-34 source path changed in the WP-27 closure; runtime-root/recovery
  changes preserve the existing projection boundary and canonical/derived
  semantics.
- Final disposition: `VERIFIED`.
