# M1 Increment 2 Acceptance Evidence

**Increment:** Redaction boundary
**Status:** VERIFIED
**Starting commit:** `87b81c3e806fbc4bbcd571737704596f191f980f`
**Implementation commit:** `a2818decfc8e9f1083e4f4cb32d635272c7c9eaa`
**Product-code test state:** `dd36562e35a64f0984fb1acd9a84b88b1a4350f5`
**Current evidence-review HEAD:** `2558c9f1d915e5f7162e5c9c18d3d5d84be8fb85`
**No-op patch incident:** attempted identical old/new patch for `src/redaction/redactor.py`; product impact none; no file change required.
**Fresh verification:** focused tests `14 passed in 0.12s`; canonical suite `30 passed in 0.10s`; focused redaction ad-hoc verification `PASS`, `exit_code=0`, `cleaned=True`.
**Rerun required:** No. Changes after the product-code test state are documentation, plan, acceptance-evidence, and project-state records only; no executable source, tests, redaction policy, schema, or runtime configuration changed.
**Checkpoint:** `checkpoint-m1-increment-2-start` → `87b81c3e806fbc4bbcd571737704596f191f980f`

| Criterion | Status | Objective evidence | Evidence location |
|---|---|---|---|
| Deterministic redaction | PASS | 14 focused tests cover stable markers and deterministic output | `src/redaction/redactor.py`; `tests/unit/test_m1_redaction.py` |
| Recursive nested redaction | PASS | Mapping, list, tuple, nested tool-argument/result tests pass | `tests/unit/test_m1_redaction.py` |
| Supported secret patterns | PASS | Authorization, bearer, API key, OAuth, password, private-key, and credential URL cases pass | `supported_secret_patterns()`; focused tests |
| Never-store rejection | PASS | `sensitivity=secret` and `retention=never_store` reject with sanitized errors | `redact_payload`; focused tests |
| Source immutability | PASS | Success and failure payload snapshots remain unchanged | `test_source_payload_immutable_on_success_and_failure` |
| Fail-closed behavior | PASS | Cyclic, unsupported, malformed private-key, and unsafe values reject | Focused tests and `RedactionRejected` |
| Sanitized audit records | PASS | Audit contains rule IDs, paths, IDs/timestamp, action/count, and `original_values_included=false` | `RedactionAudit`; audit tests |
| Sanitized errors and diagnostics | PASS | Exceptions contain fixed codes/paths/rules only; no raw repr or secret | Focused exception tests |
| Idempotence | PASS | Redacting sanitized output preserves content and hash | `test_output_is_deterministic_and_idempotent` |
| Hash-after-redaction | PASS | SHA-256 is recomputed from canonical sanitized content | `test_hash_is_computed_from_sanitized_content_only` |
| Original-secret absence | PASS | Synthetic secret corpus absent from returned content and audit; ad-hoc scan passed | Focused redaction ad-hoc verification; `acceptance-m1-increment-2.md` |
| No LLM usage | PASS | Pure stdlib redactor has no LLM/network/persistence calls; focused and canonical tests pass | `src/redaction/redactor.py` |
| Future increments remain unimplemented | PASS | No JSONL persistence, retry/dead-letter, deduplication, Hermes hooks, retrieval, SQLite, MCP, Obsidian, or injection code added | Scope boundary; Git commit diff |

## Test evidence

Focused Increment 2 tests:

```text
.venv/bin/python -m pytest tests/unit/test_m1_redaction.py -q
14 passed in 0.12s
```

Canonical regression suite:

```text
.venv/bin/python -m pytest tests/ -q
30 passed in 0.10s
```

Focused redaction ad-hoc verification:

```text
PASS
exit_code=0
cleaned=True
```

The ad-hoc check directly covered source immutability, absence of original secrets from returned content/audit, sanitized hash output, Increment 1 contract compatibility, and `never_store` rejection. It is recorded as ad-hoc evidence, not canonical test evidence.

No temporary files, pytest caches, or generated verification artifacts remain. Overall M1 remains in progress.

**M1 INCREMENT 2: VERIFIED**
