# Zero-Mem

[English](README.md) · [Tiếng Việt](README.vi.md)

Zero-Mem is a local-first evidence and memory sidecar for agent workflows. It
captures durable canonical events, builds disposable query projections, applies
explicit access boundaries, and keeps user data independent from the installed
application runtime.

The core runtime has no mandatory third-party dependencies and does not require
an AI API or network connection.

## Project status

| Line | Status | Notes |
|---|---|---|
| Package `1.6.0` | Current candidate package version | Version declared by `zero_mem/version.py` |
| `master` | Latest stable branch | Stable integration line |
| `v160/multi-ks` | Qualified release candidate | C1–C10 + wizard complete; remote 9-cell CI passed |

v1.6.0 is **not released**. Local and remote qualification are green; tag and
publication remain separate maintainer-approved gates.

See the [v1.6.0 guide](docs/v1.6.0/README.md) for the current scope, gates,
work-package map, and canonical evidence index.

## Core principles

- **Local-first:** normal operation is user-local and offline.
- **Canonical history:** Memory JSONL is append-only canonical event/trace truth.
- **Rebuildable projections:** SQLite, FTS, graph, temporal indexes, and
  Obsidian-style projections are derived state.
- **Explicit identity:** project, profile, and Knowledge Space identities are
  never inferred from a working directory, repository name, branch, HOME, or
  session text.
- **Authorization before retrieval:** scoped reads fail closed and preserve
  profile/project/Knowledge Space boundaries.
- **Non-destructive lifecycle:** upgrade and uninstall do not silently delete or
  rewrite canonical user data.
- **Evidence-backed delivery:** changes use RED-first tests, bounded commits, and
  executable qualification evidence.

## Capabilities

Zero-Mem provides:

- durable event capture with explicit receipts;
- canonical JSONL storage and rebuildable SQLite projections;
- structured and full-text retrieval;
- profile, project, and Knowledge Space access controls;
- project-memory, graph, temporal, corpus, and projection layers;
- a public Python facade and local CLI;
- optional Hermes integration through an explicit boundary;
- verified local backup, restore, diagnosis, and upgrade workflows;
- generic corpus import tooling for user-provided document collections.

Corpus tooling is not tied to the development `quant_lab` sample. Import and
projection commands are parameterized so other domains can use the same
pipeline.

## Repository map

```text
zero_mem/        Public Python API, CLI, configuration, and lifecycle commands
src/             Internal implementation by domain
tests/           Unit, integration, packaging, fixtures, and baselines
docs/            Architecture, plans, decisions, runbooks, releases, and evidence
artifacts/       Historical control, handoff, tracking, and evidence artifacts
audit/           Raw audit and qualification artifacts not yet consolidated
benchmarks/      Performance and retrieval-quality harnesses
config/          Policy and schema examples
examples/        Small integration examples
release_helpers/ Offline bundle, installation, and uninstallation helpers
scripts/         Verification, corpus, maintenance, and projection tools
```

The split between the two Python trees is intentional:

- `zero_mem/` is the supported public and operational surface;
- `src/` contains internal domain implementation.

See the [current module map](docs/v1.6.0/MODULE-MAP.md) before adding a module.

The root management files have different roles:

- `project-state.yaml` is the current machine-readable project state and is the
  only file in this group that should receive new status overlays.
- `implementation-plan.json` is a frozen historical record; do not update it.
- `benchmark-plan.json` defines the original M0 benchmark contract, not current
  release status or current benchmark results.
- `Review V1.1/` is historical review material retained for audit.

For documentation navigation, start with the
[documentation index](docs/README.md). For repository authority and invariants,
read [AGENTS.md](AGENTS.md).

## Development quick start

Requirements: Python 3.11–3.13.

```bash
python -m venv .venv
python -m pip install -e ".[test]"
python -m pytest -q
```

Inspect the CLI without changing user data:

```bash
zero-mem --help
zero-mem --version
zero-mem version
```

The optional PDF extra uses `pypdf`:

```bash
python -m pip install -e ".[pdf]"
```

## Guided onboarding (recommended)

After installing the Zero-Mem wheel, the shortest safe first run is:

```bash
zero-mem wizard
```

The wizard initializes local storage, optionally configures Hermes, and finishes
with a read-only health check. If Hermes is present, it explains and requests two
explicit identifiers; it never guesses identity or reads Hermes secrets.

- **Project ID** is the stable Hermes identifier for the current codebase or
  workspace. It is not a filesystem path.
- **Profile ID** is the Hermes behavior/access identity currently in use. It is
  not the operating-system username.

If either value is unknown, skip Hermes and add it later. Automation can use:

```bash
zero-mem wizard --non-interactive --skip-hermes --json
zero-mem wizard --non-interactive --project-id PROJECT --profile-id PROFILE --json
```

See the [complete onboarding guide](docs/v1.6.0/ONBOARDING.md).

## Manual local setup and health

```bash
zero-mem setup
zero-mem doctor
zero-mem doctor --json
```

`setup` creates private user-local data, config, state, and cache directories,
an empty canonical Memory JSONL stream, and the derived SQLite schema. It does
not require Hermes, Corpus, Obsidian, an AI API, network access, or a repository
checkout.

`doctor` is read-only. Optional integrations that are absent are reported as
optional or warning states rather than setup failures.

## Optional Hermes integration

```bash
zero-mem integrate hermes --check
zero-mem integrate hermes --project-id PROJECT --profile-id PROFILE
zero-mem integrate hermes --remove
```

Integration is never enabled implicitly by `setup`, `doctor`, or startup.
Project and profile identifiers are mandatory. Zero-Mem stores only its own
descriptor and does not edit or install Hermes. `ZERO_MEM_ENABLED` remains the
master switch, and Hermes must remain operational when Zero-Mem is unavailable.

## Backup and upgrade

```bash
zero-mem backup create --output /absolute/backup-directory
zero-mem backup verify /absolute/backup-directory --json
zero-mem backup restore /absolute/backup-directory --yes

zero-mem upgrade --check --json
zero-mem upgrade --json
```

`upgrade --check` is read-only. `upgrade` validates canonical data, rebuilds
disposable derived state in staging, and activates it only after verification.
A staging failure leaves the previous active derived state in place. Future
schema versions are refused rather than silently downgraded.

Application removal is not data deletion. The default uninstaller preserves
canonical Memory JSONL, corpus registry and blobs, artifacts, profiles/grants,
configuration, and backups.

## Documentation entry points

- [Documentation index](docs/README.md)
- [Authoritative repository rules](AGENTS.md)
- [Master specification projection](docs/MASTER-SPEC.md)
- [Architecture](docs/architecture/ARCHITECTURE.md)
- [Defect registry](docs/defects/DEFECT-REGISTRY.md)
- [Release notes](docs/releases/)
- [v1.6.0 Multi-KS guide](docs/v1.6.0/README.md)
- [v1.6.0 architecture decision](docs/v1.6.0/decisions/ADR-V160-01-MULTI-KS.md)
- [v1.6.0 roadmap](docs/v1.6.0/ROADMAP.md)
- [v1.6.0 evidence index](docs/v1.6.0/EVIDENCE.md)

## Contributing safely

Before changing code, read [AGENTS.md](AGENTS.md), the relevant version plan and
ADR, and the defect registry. Before any Git or GitHub mutation, read the
[GitHub governance policy](docs/governance/GITHUB-POLICY.md).

Do not rewrite canonical history, weaken access boundaries, treat derived state
as canonical, commit generated/private data, or claim completion without
executable evidence.
