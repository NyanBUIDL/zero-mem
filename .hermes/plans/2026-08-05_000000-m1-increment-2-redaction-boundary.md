# M1 Increment 2 — Redaction Boundary Implementation Plan

> **For Hermes:** Implement only Increment 2 after approval. Use strict TDD: RED, verify failure, GREEN, focused tests, then canonical suite. Do not implement JSONL persistence, retry/dead-letter, deduplication, Hermes hook integration, retrieval, or prompt/context injection in this increment.

**Goal:** Add a project-owned deterministic redaction boundary that recursively sanitizes event payloads before hashing or persistence, rejects never-store content, emits sanitized audit metadata, preserves input immutability, and fails closed without leaking secrets.

**Architecture:** Increment 2 sits between the Increment 1 normalizer and all future storage/integration code. It is pure/local and independent of Hermes private modules. It returns sanitized content plus a redaction audit or raises a sanitized policy error; it does not persist, log, retry, call an LLM, or mutate Hermes objects.

**Tech Stack:** Python 3.11 standard library, existing Increment 1 contract types, pytest in project `.venv`. No new runtime dependencies.

---

## 1. Scope and boundaries

### In scope

- Deterministic redaction API.
- `never_store` rejection behavior.
- Recursive mappings and lists, including nested tool results and mixed scalar values.
- Approved secret pattern families from M0 policy.
- Sanitized redaction audit schema.
- Fail-closed behavior and sanitized exceptions/diagnostics.
- Payload immutability.
- Hash-after-redaction API boundary and tests.
- Contract-compatible output for the Increment 1 envelope.

### Explicitly out of scope

- JSONL writes or dead-letter persistence.
- Retry, deadlines, deduplication, capture-rate harness.
- Hermes lifecycle/plugin hook registration.
- SQLite/index scanning.
- Prompt/context/message/tool mutation or injection.
- LLM calls or generated summaries.
- Obsidian, MCP, retrieval, graph, corpus ingestion.
- Importing Hermes private redaction modules at runtime.

The M1 Increment 1 event contract remains unchanged. The redactor consumes a copied payload and returns sanitized data for a later adapter/storage increment.

## 2. Existing contracts and binding decisions

- M0 `never_store`: `api_keys`, `bearer_tokens`, `oauth_secrets`, `passwords`, `private_keys`, `unredacted_credentials`.
- M0 pattern families: bearer authorization headers, API-key assignments, private-key blocks, password assignments, OAuth client secrets, credential URL userinfo.
- Sensitivity `secret` means redact/reject before persist; retention `never_store` is memory-only.
- ADR-M1-004 requires: copy → normalize → redact/reject → hash sanitized content → validate → persist.
- ADR-M1-007 requires no original secret in raw/dead-letter/audit/logs/exceptions/temp artifacts/snapshots; SQLite/index scanning is deferred to M2.
- Increment 1 established `sanitized_content`, `sanitized_content_hash`, `sensitivity`, `retention`, and `redaction_audit` envelope fields.

## 3. Proposed API

Create `src/redaction/redactor.py` with a project-owned API similar to:

```python
@dataclass(frozen=True)
class RedactionAudit:
    applied: bool
    rule_ids: tuple[str, ...]
    field_paths: tuple[str, ...]
    event_id: str | None
    trace_id: str | None
    observed_at: str

@dataclass(frozen=True)
class SanitizedPayload:
    content: object
    audit: RedactionAudit
    content_hash: str

class RedactionRejected(ValueError):
    """Raised when never-store or fail-closed policy forbids persistence."""


def redact_payload(
    payload: object,
    *,
    event_id: str | None = None,
    trace_id: str | None = None,
    observed_at: str | None = None,
) -> SanitizedPayload:
    """Return sanitized content and metadata, never mutate payload or log secrets."""
```

The exact public names may be adjusted during RED if tests expose a simpler interface, but the behavior and output fields are binding. `content_hash` must be computed from deterministic canonical JSON of the sanitized output only. No API may accept an already-hashed pre-redaction value as authoritative.

## 4. Redaction and rejection semantics

### Recursive traversal

- Mapping keys are treated as field-name context and sanitized values are traversed recursively.
- Lists/tuples are traversed by index with paths such as `payload.items[0].token`.
- Sets and arbitrary objects are not silently serialized as raw text; unsupported values produce a sanitized fail-closed error unless an explicitly safe scalar representation is defined.
- Cyclic structures are rejected with a generic sanitized diagnostic.
- Empty/null values remain empty/null.
- Original mappings, sequences, and nested objects are never mutated.

### Approved secret patterns

Implement only deterministic patterns derived from M0 policy:

1. Bearer authorization headers, including case-insensitive `Authorization: Bearer ...` and bearer-like mapping values.
2. API-key assignments such as `api_key=`, `api-key:`, provider key names, and configured M0 `api_keys` field context.
3. PEM/private-key blocks such as `-----BEGIN ... PRIVATE KEY-----` through matching end marker.
4. Password assignments such as `password=`, `passwd:`, and password field context.
5. OAuth client secrets and token/secret assignments in OAuth context.
6. Credential URL userinfo where a credential appears before `@` in a supported URL form.

Pattern identifiers must be stable, sanitized labels, for example:

- `bearer_authorization`
- `api_key_assignment`
- `private_key_block`
- `password_assignment`
- `oauth_secret`
- `credential_url_userinfo`

Do not broaden patterns into generic PII detection or redact ordinary web URLs without an approved credential shape. If a value is ambiguous and may be secret, fail closed rather than persist it.

### Never-store behavior

- Explicit `sensitivity=secret` or `retention=never_store` context rejects the payload or the affected field before hashing/persistence.
- A recognized private key, password, bearer token, API key, OAuth secret, or credential URL is replaced with a stable marker only when the surrounding event can safely retain a sanitized representation; otherwise the whole payload is rejected.
- Rejection errors contain only rule ID, field path, event/trace ID, and generic failure class. They must not include the matched value, a raw payload repr, or an exception string derived from the secret.
- Audit metadata never contains original values or pre-redaction content.

The precise replacement-versus-reject decision must be encoded in tests and documented in the module; no later storage layer may see the original value.

## 5. Audit schema

The audit must be JSON-serializable and deterministic:

```json
{
  "applied": true,
  "rule_ids": ["bearer_authorization"],
  "field_paths": ["payload.headers.authorization"],
  "event_id": "event-id-or-null",
  "trace_id": "trace-id-or-null",
  "observed_at": "RFC3339-UTC-Z",
  "original_values_included": false
}
```

Requirements:

- `rule_ids` and `field_paths` are sorted/deduplicated.
- `original_values_included` is always `false` and is tested.
- `event_id`, `trace_id`, and timestamp are optional metadata only; missing IDs remain null.
- Audit serialization must not include raw payload, regex match text, secret fragments, or exception text.
- No logging belongs inside the pure redaction function; callers may log only sanitized diagnostics.

## 6. Fail-closed and diagnostics

- Invalid detector configuration, unsupported cyclic/unsafe object, malformed credential structure, or internal redactor exception must return/raise a sanitized `RedactionRejected` failure.
- The public exception message is a stable generic class plus safe identifiers/path/rule labels only.
- A helper such as `sanitize_diagnostic(exc)` may be added only if it guarantees that exception text and reprs are not exposed; prefer fixed diagnostic codes over exception text.
- The redactor must never print, log, write a temp file, or call the network.
- The redactor must never call an LLM.

## 7. Hash-after-redaction rule

The redaction API must make the safe order obvious:

```text
copy input
  -> recursively sanitize/reject
  -> produce audit
  -> canonicalize sanitized content
  -> compute sha256
  -> return SanitizedPayload
```

Tests must demonstrate that changing a secret changes neither persisted output nor any pre-redaction hash path, and that the returned hash equals the sanitized content hash. Increment 2 does not write the envelope; later code will place this hash into `sanitized_content_hash` only after redaction succeeds.

## 8. Files to create or modify

### Create

- `src/redaction/__init__.py`
- `src/redaction/redactor.py`
- `tests/unit/test_m1_redaction.py`
- Optional `tests/fixtures/m1_secret_payloads.json` only if fixture contents are safe to store and contain no real credentials; use clearly synthetic values.
- Optional `runbooks/m1-redaction.md` if implementation introduces operational diagnostics that need durable documentation.

### Modify

- `implementation-plan.json` only to record Increment 2 plan approval/status; do not mark it verified before tests pass.
- `project-state.yaml` only to record planning/implementation status and evidence after verification.
- `acceptance-m1-criteria.md` only if the exact Increment 2 criterion mapping needs a clarification; current approved scope already defines the relevant requirements.

### Do not modify

- `src/capture/event_types.py`, `src/capture/adapter.py`, or `src/capture/validation.py` unless a test-proven contract compatibility correction is required.
- Installed Hermes source or real `~/.hermes` state.
- JSONL/storage/retry/integration modules; those are later increments.

## 9. Test plan

Write tests before production code and observe RED for each behavior group.

### API and immutability

- Public API returns a sanitized payload and audit for safe scalar/mapping/list input.
- Nested mappings and lists are copied recursively.
- Original payload remains byte/value-equivalent after redaction.
- `None`, empty mappings, empty lists, booleans, numbers, and safe strings remain stable.
- Cyclic/unsupported objects fail closed with no secret in the exception.

### Secret pattern coverage

- Bearer authorization header.
- API-key assignment and key-name context.
- Private-key PEM block.
- Password assignment/context.
- OAuth client secret/token context.
- Credential URL userinfo.
- Nested mappings, lists, and mixed tool-result structures.
- Multiple secrets produce sorted/deduplicated rule IDs and field paths.

### Never-store and fail-closed

- Explicit secret sensitivity rejects or sanitizes according to the documented policy.
- `never_store` retention rejects.
- Malformed detector/configuration path rejects without raw data.
- Exceptions contain no synthetic secret values, fragments, or raw repr.
- No logs/temporary files are created by the redactor.

### Audit and hash

- Audit includes event/trace IDs and UTC timestamp when supplied/generated.
- Audit always says `original_values_included: false`.
- Audit contains rule IDs/field paths but no values.
- Hash is computed after redaction and is stable under mapping key order.
- Hash differs for different sanitized content and never exposes the original secret.

### Contract compatibility

- Returned sanitized content can be placed in Increment 1 `sanitized_content`.
- Returned audit shape is accepted by the Increment 1 optional `redaction_audit` field.
- No Increment 1 event type or validation behavior changes.

## 10. Focused and canonical commands

Focused command to add and run after implementation:

```bash
.venv/bin/python -m pytest tests/unit/test_m1_redaction.py -q
```

Canonical regression command:

```bash
.venv/bin/python -m pytest tests/ -q
```

Do not claim Increment 2 acceptance from the generic suite alone. Record both exact outputs against the final Increment 2 commit. Remove `.pytest_cache`, `__pycache__`, temporary files, and synthetic output artifacts before committing.

## 11. Acceptance criteria

| Criterion | Required evidence |
|---|---|
| Recursive deterministic redaction | Focused tests pass for mappings/lists and all approved M0 secret pattern families |
| Never-store rejection | Explicit secret/never-store cases fail closed with sanitized diagnostics |
| Audit safety | Audit schema has identifiers/rules/paths/timestamp and never original values/pre-redaction payload |
| Payload immutability | Nested input remains unchanged after success and failure |
| Hash-after-redaction | Test proves returned hash is over sanitized content only and deterministic |
| Exception/diagnostic safety | Secret values do not appear in exceptions/log captures/temp artifacts/snapshots |
| Contract compatibility | Increment 1 contract tests continue passing; no hook/storage/integration behavior added |

Increment 2 is not M1-complete. It verifies only the redaction boundary and remains independent of persistence and Hermes integration.

## 12. Rollback strategy

- Create a Git checkpoint before implementation.
- Keep the redactor project-local and unregistered from Hermes until later integration approval.
- If a pattern causes false positives or leaks, revert the Increment 2 commit without touching M0 contracts or Increment 1 code.
- Preserve no real credentials in fixtures; remove generated synthetic outputs after tests.
- Verify the Increment 1 focused and canonical suites after rollback or any contract correction.
- Do not delete or rewrite canonical raw traces; Increment 2 has no persistence and therefore no data migration.

## 13. Open implementation decisions

The binding decisions resolve the architecture, but one policy detail must be made explicit during RED/GREEN and documented before GREEN:

- **Replacement versus whole-event rejection:** for each recognized secret pattern, decide whether the field is replaced with a stable marker or the entire payload is rejected. Conservative default: replace clearly isolated secret fields with a marker; reject explicit `secret`/`never_store` payloads and ambiguous/unsafe structures. This is an implementation-level interpretation of ADR-M1-004 and must be covered by tests, not silently varied by pattern.

No other blocker is identified for Increment 2 planning.

**Increment 2 plan: READY FOR APPROVAL**

Do not implement Increment 2 until approved.
