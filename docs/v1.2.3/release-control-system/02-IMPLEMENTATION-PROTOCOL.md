# 02 — Implementation protocol for an agent

## Step 1: open one package record

Copy [05-WORK-PACKAGE-TEMPLATE.md](05-WORK-PACKAGE-TEMPLATE.md) into `docs/v1.2.3/work-packages/R-XX-<slug>/`. Record baseline SHA, audit ID, permitted paths, public contract, platform scope and rollback plan.

## Step 2: write black-box tests first

Start with the user-visible failure. Examples:

- R-01: only `import zero_mem`; create supported local composition; capture fixture; all four public methods return real typed results.
- R-02: invoke sidecar by its advertised capability list; compare normalized response to direct API.
- R-03: invoke a host fixture through the published factory; do not instantiate internal adapters in the test setup.
- R-04: invoke real storage API from a spawned process on the target operating system.

Mock/unit tests are supplementary. A package cannot be verified from a mocked service alone.

## Step 3: implement the smallest complete slice

Only modify the ledger row’s owner paths and test/evidence files. Keep resource ownership singular:

```text
public factory → one runtime → one canonical writer + one projection coordinator
               → authorized read service → public/sidecar/Hermes adapters
```

Do not add a second query implementation, global runtime writer, direct SQL call in public API, or transport-specific authorization logic.

## Step 4: run the verification ladder

1. New focused unit and black-box E2E tests.
2. Direct dependency tests from the code owner.
3. Redaction, denial-before-discovery, stale/recovery and restart failure tests.
4. Affected Windows/Linux/macOS rows.
5. Full isolated suite only after the focused layer is green.

Record complete commands and raw logs before changing package status. A repeated pass count without raw-log SHA is not evidence.

## Step 5: independent close review

The reviewer asks only:

1. Can a consumer reach this through the advertised public boundary?
2. Does the implementation call the one authorized/canonical owner?
3. Does the exact tag contain and verify evidence for this result?

Any “no” returns the row to `PARTIAL` or `OPEN` with a reproduction. The reviewer does not repair or downgrade a failing test inside the review.
