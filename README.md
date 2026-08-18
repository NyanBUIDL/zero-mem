# Zero-Mem

Zero-Mem v1.1.0 is a local-first evidence and memory sidecar. The PKG-1 distribution
provides the installable package and release CLI foundation.

```text
zero-mem --help
zero-mem --version
zero-mem version
```

The optional `pdf` extra enables PDF extraction through `pypdf`; the core
runtime has no mandatory third-party dependencies.

PKG-2 provides an offline, user-local acceptance bundle builder in
`packaging/build_bundle.py`, plus `install.sh` and `uninstall.sh`. The
The installer accepts only bundled wheels, creates a versioned managed runtime
under `${XDG_DATA_HOME:-$HOME/.local/share}/zero-mem`, and exposes the CLI
under `${XDG_BIN_HOME:-$HOME/.local/bin}/zero-mem`. It never requires root or
network access after the bundle is obtained. Default uninstall removes only
owned runtime components and preserves user data.

PKG-3 adds the non-destructive first-run commands:

```text
zero-mem setup
zero-mem doctor
zero-mem doctor --json
```

`setup` creates private XDG data/config/state/cache directories, an empty
canonical Memory JSONL stream, and the derived SQLite schema. It finishes with
`READY` and does not require Hermes, Corpus, Obsidian, an AI API, network access,
or a repository checkout. `doctor` is read-only and reports stable PASS/WARN/
OPTIONAL/FAIL checks; absent optional integrations are warnings or optional
capabilities, not setup failures.

PKG-4 adds an explicit, optional Hermes integration workflow:

```text
zero-mem integrate hermes --check
zero-mem integrate hermes --project-id PROJECT --profile-id PROFILE
zero-mem integrate hermes --remove
```

Integration is never enabled by `setup`, `doctor`, or normal startup. The
project and profile identifiers are mandatory and are never inferred from the
working directory, repository name, HOME, session text, or branch. The command
stores only a Zero-Mem-owned descriptor under the configured XDG config root;
it does not edit Hermes files, install Hermes, contact the network, or expose
write/admin/raw-storage tools. `ZERO_MEM_ENABLED` remains the sole master
switch, and Hermes remains operational when Zero-Mem is unavailable.

## Upgrade and data lifecycle

Application code and user data have separate lifecycles. Reinstalling or
uninstalling the managed runtime does not remove canonical Memory JSONL, the
canonical corpus registry and blobs, artifacts, profiles/grants, configuration,
or backups. The PKG-2 default uninstaller removes only the managed runtime and
its owned CLI shim.

PKG-6 provides a local, no-network upgrade lifecycle:

```text
zero-mem upgrade --check --json
zero-mem upgrade --json
```

`upgrade --check` is read-only. It reports installed package/data format and
SQLite schema compatibility, canonical readability, backup readiness, and
doctor readiness. A future derived schema is refused; Zero-Mem never silently
downgrades data. For the current v10 schema, a compatible installation reports
`NO_MIGRATION_REQUIRED`.

`upgrade` validates canonical data, builds disposable SQLite/FTS/graph/temporal
state in a sibling staging directory, and activates it only after the staged
rebuild and doctor checks succeed. Canonical JSONL, corpus registry/blobs,
artifact payloads, profiles/grants, and configuration are never migrated or
rewritten by this operation. A staging failure leaves the prior active derived
state in place. Create and verify a local PKG-5 backup before a significant
upgrade when recovery assurance is desired:

```text
zero-mem backup create --output /absolute/backup-directory
zero-mem backup verify /absolute/backup-directory --json
```

There is intentionally no `zero-mem data remove` command in PKG-6. Persistent
data deletion is a separate, explicitly authorized lifecycle operation; OS
package removal is not data deletion.
