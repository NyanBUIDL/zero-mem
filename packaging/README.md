# PKG-2 installer acceptance bundle

This release-layer bundle installs the Zero-Mem wheel into a versioned,
user-local virtual environment. It is offline after bundle acquisition:
`pip` is invoked with `--no-index`, `--no-deps`, and a bundle-local
`--find-links` directory.

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

This is a **PKG-3 SETUP + DOCTOR ACCEPTANCE BUNDLE**, not the final v1.0.0
release artifact. It does not provide status, rebuild, integration, backup,
restore, upgrade, rollback, service, or GitHub publication commands.
