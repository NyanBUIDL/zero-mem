# Contributing to Zero-Mem

Thank you for contributing. Keep changes small, reviewable, and consistent with
the repository's local-first and fail-closed boundaries.

Before changing code or release documentation:

1. Read `AGENTS.md` and the relevant master-spec section.
2. Register confirmed defects in `docs/defects/DEFECT-REGISTRY.md` before fixing
   them.
3. Add a failing regression test first, then make the smallest complete fix.
4. Run focused tests and the applicable full suite.
5. Read `docs/governance/GITHUB-POLICY.md` before any Git or GitHub mutation.

Do not include secrets, user data, generated clutter, or machine-specific paths.
Do not rewrite published history, move release tags, or publish releases without
explicit maintainer authorization.

For a pull request, describe the scope, defect or decision reference, changed
files, tests run, and remaining risks. Product behavior, schema, authorization,
or canonical-storage changes require the corresponding approved design and
acceptance evidence.
