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
installer accepts only bundled wheels, creates a versioned managed runtime
under `${XDG_DATA_HOME:-$HOME/.local/share}/zero-mem`, and exposes the CLI
under `${XDG_BIN_HOME:-$HOME/.local/bin}/zero-mem`. It never requires root or
network access after the bundle is obtained. Default uninstall removes only
owned runtime components and preserves user data.
