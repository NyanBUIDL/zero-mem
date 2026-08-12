# Zero-Mem

Zero-Mem is a local-first evidence and memory sidecar. The PKG-1 distribution
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
