# PKG-2 installer acceptance bundle

This release-layer bundle installs the Zero-Mem wheel into a versioned,
user-local virtual environment. It is offline after bundle acquisition:
`pip` is invoked with `--no-index`, `--no-deps`, and a bundle-local
`--find-links` directory.

Release-wheel builds use the standard reproducible-build input
`SOURCE_DATE_EPOCH=315532800`. This fixes ZIP metadata timestamps, so repeated
builds from the same committed source and build toolchain are byte-identical.

The tested interpreter policy is existing CPython `>=3.11,<3.14`. The
installer does not install Python, require root, contact PyPI, use Git, or
modify a system interpreter.

Runtime defaults to `${XDG_DATA_HOME:-$HOME/.local/share}/zero-mem`; the
CLI shim defaults to `${XDG_BIN_HOME:-$HOME/.local/bin}/zero-mem`. Runtime
configuration/state/cache roots remain the product's XDG-controlled paths.
Default uninstall removes only the managed runtime and owned CLI shim. It
preserves Memory, Corpus, artifacts, configuration, state, and backups.

After installation, `zero-mem setup` initializes an empty, user-local
observation-only runtime and prints `READY`. `zero-mem doctor` performs
non-mutating runtime, configuration, canonical Memory, derived SQLite, and
optional-integration checks. Hermes, Corpus, Obsidian, and AI APIs are optional;
their absence does not prevent first-run readiness.

The optional PKG-4 branch is explicit and identity-bound:

```text
zero-mem integrate hermes --check
zero-mem integrate hermes --project-id PROJECT --profile-id PROFILE
zero-mem integrate hermes --remove
```

It does not run during installation, setup, or doctor. It writes only the
Zero-Mem-owned integration descriptor below the configured XDG config root and
uses the existing external Hermes plugin-context boundary. Hermes is not a
runtime dependency of the Zero-Mem wheel.

This is a local release-layer acceptance bundle, not a public v1.0.0 release
artifact. It does not provide status, a manual rebuild command, rollback,
service, GitHub publication, or data-purge commands.

PKG-6 extends the installed lifecycle with `zero-mem upgrade --check` and
`zero-mem upgrade`. The compatibility check is read-only. Upgrade refreshes
only disposable derived SQLite/FTS/graph/temporal state through sibling staging
and atomic activation; it never rewrites canonical Memory JSONL, corpus
registry/blobs, artifact payloads, profiles/grants, or configuration. A failed
staged refresh leaves the previously active derived state usable. Application
uninstall remains separate from user-data deletion: the supplied uninstaller
removes managed runtime code and the owned shim only. No data-purge command is
provided by this release layer.
