# M1 Increment 4.5 Non-Interference Integration Runbook

- The bridge is a project-local, opt-in observer. Disabled by default.
- Enabling the bridge registers only the verified supported hooks and copies payloads before observation.
- All runtime/integration tests use temporary `HERMES_HOME`, temporary capture roots, and synthetic identities. They never write under the real `~/.hermes`.
- The installed Hermes source is read-only for compatibility; it is never modified by the bridge or its tests.
- Sidecar failures (mapping, redaction, envelope, duplicate, storage, registration, callback) are isolated and sanitized; they never propagate into Hermes or change Hermes-owned values.
- Enabling the bridge does not suppress, replace, or introduce exceptions in the Hermes-owned execution path.
- Secrets are redacted at the boundary; synthetic secret corpus values never appear in captured JSONL, diagnostics, metrics, logs, or temporary artifacts.
- Rollback: disable the bridge, revert only the Increment 4.5 commit, preserve JSONL records, and rerun Increment 1–4.4 focused/canonical suites. Never modify or delete real Hermes state or installed source.

# End of file
