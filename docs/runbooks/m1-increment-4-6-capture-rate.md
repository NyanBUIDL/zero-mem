# M1 Increment 4.6 Capture-Rate Benchmark Runbook

- The benchmark is controlled: temporary HERMES_HOME, temporary capture root,
  synthetic project/profile IDs, synthetic payloads and secrets, no network,
  no LLM, no real Hermes-home writes, no installed-source modification.
- Drive only the 8 operationally supported hooks once each (unique logical
  events), then replay a subset as duplicates to confirm accepted-duplicate
  semantics and no extra records.
- Conditional (8) and deferred (10) hooks are driven as negative fixtures and
  reported separately; they are excluded from the capture-rate denominator.
- Capture rate = accounted / expected_supported * 100, threshold >= 99%.
- Each logical event counts at most once: an appended valid record OR a
  confirmed accepted-duplicate result. Duplicate replays must not add records
  or advance the committed sequence.
- Malformed negative-test inputs are kept outside the valid denominator.
- Secret scanning is performed across JSONL, adapter/bridge results, metrics,
  diagnostics, and reports; no original synthetic secret may appear anywhere.
- The real JsonlCaptureStore (versioned, validating, append-only, dedup) is
  used as the store under test — failure isolation is provided by the bridge
  adapter, which swallows all observation-side exceptions.

## Verification

    .venv/bin/python -m pytest tests/integration/test_m1_capture_rate.py -q
    .venv/bin/python -m pytest tests/integration/test_m1_final_acceptance.py -q
    .venv/bin/python -m pytest tests/ -q
