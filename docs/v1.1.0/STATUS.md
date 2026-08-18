# Zero-Mem v1.1.0 Release Status

| Field | Current value |
|---|---|
| Target | v1.1.0 |
| Source HEAD under preparation | `e6fc96fbe49a2dabac6322877a2ed6d39ae37e2f` before release-prep checkpoint |
| Implementation state | WP-00..WP-22 VERIFIED; Phase A..G VERIFIED |
| Product Runtime | UNTOUCHED by release preparation |
| Supported Python | CPython `>=3.11,<3.14` |
| Locally qualified environment | Linux x86_64, CPython 3.11.16, SQLite 3.53.1 with FTS5 |
| Native Windows | NOT_SUPPORTED |
| Remote publication | NOT_PERFORMED |
| Proposed tag | `v1.1.0` (not created in release preparation) |
| Release decision | Maintainer decision pending final local checkpoint review |

## Release-preparation boundary

Release preparation verifies the current source, package metadata, wheel and sdist
artifacts, clean installation, compatibility claims, migration/backup smoke,
documentation, security scans, and a fresh supported-interpreter regression. It
may correct release metadata and user-facing documentation, but it does not
reopen implementation phases or modify Product Runtime behavior.

Historical planning and acceptance records retain their original version and
lifecycle language where that language describes an earlier state; they are not
current release-status claims.
