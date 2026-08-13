# M1 Increment 4.4 Registration Runbook

- The registration adapter is project-local and disabled by default.
- It registers only the verified supported hook registry.
- It does not modify the installed Hermes source or real Hermes home.
- Failures are sanitized and fail open to Hermes control flow.
- Disable with `RegistrationAdapter.shutdown()`; existing JSONL records are preserved.
- Conditional and deferred hooks remain unregistered.

Rollback: disable the bridge, revert the Increment 4.4 commit, and rerun the canonical suite. Never delete or rewrite existing raw traces.

# End
