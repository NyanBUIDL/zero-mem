# M9 Projection — Operation Runbook

Controlled operation of `scripts/project_to_obsidian.py`, the single approved
entry point for projecting authorized Zero-Mem state into an Obsidian vault.

## Safety summary

- **Dry-run by default.** Without `--apply`, nothing is written.
- **`--apply` requires `--yes`.** A real vault is never touched by accident.
- **One project at a time.** `--project` is mandatory; nothing global is
  projected.
- **Only `<vault>/Zero-Mem/` is ever written.** The vault root, `.obsidian/`,
  and every other human note stay read-only.
- **Canonical store is opened read-only.** The projector cannot write to
  canonical memory; there is no write-back.
- **Zero LLM, zero network, no Hermes core change, no new dependency.**

## Preconditions

1. The canonical derived SQLite store exists and is schema-valid (v9).
2. The operator vault root is an existing, writable, non-symlink directory.
3. An explicit M5 READ grant authorizes `<profile>` for `<project>` (or pass
   `--authorize-project` to supply an in-memory grant for a controlled smoke
   against a store without persisted grants).

## Steps

### 1. Dry-run (read-only plan)

```bash
.venv/bin/python3 -m scripts.project_to_obsidian \
  --vault /absolute/path/to/YourVault \
  --store /path/to/canonical.sqlite \
  --project P --profile PR1 --authorize-project
```

- Prints the sanitized plan: managed dir name, notes desired, per-note
  decision (`create` / `update` / `retire` / `skipped_*`).
- Writes **nothing**.

### 2. Review the plan

Confirm the desired notes are exactly the project you intend, and that no
`skipped_*` outcome covers a path outside `<vault>/Zero-Mem/`.

### 3. Apply (single controlled write)

```bash
.venv/bin/python3 -m scripts.project_to_obsidian \
  --vault /absolute/path/to/YourVault \
  --store /path/to/canonical.sqlite \
  --project P --profile PR1 --authorize-project --apply --yes
```

- Writes only into `<vault>/Zero-Mem/`.
- Idempotent: a second identical run performs **zero** writes.

### 4. Verify integrity

Compare `.obsidian/` and every pre-existing vault path byte-for-byte before
and after. A correct run changes only files under `<vault>/Zero-Mem/`.

```bash
# before (pre-snapshot)
find /absolute/path/to/YourVault -type f -exec sha256sum {} \; > before.txt
# after
find /absolute/path/to/YourVault -type f -exec sha256sum {} \; > after.txt
diff before.txt after.txt
# expect: only Zero-Mem/ entries differ; .obsidian/ and human notes identical
```

## Rollback

The projection is a **derived, disposable** view. To roll back:

```bash
rm -rf /absolute/path/to/YourVault/Zero-Mem
```

Then re-run the projection from canonical state if desired. Canonical memory
(JSONL + SQLite) is never affected by projection or its removal.

## Failure handling

- **Unconfigured vault** → `UNAVAILABLE`, writes nothing, creates no directory.
- **Read-only / unavailable managed root** → fails closed; the run completes
  with `manifest_stored=False` and the vault is left consistent. The next
  reconcile re-derives the manifest.
- **Any non-managed path would be touched** → the operation refuses (path-safety
  invariant). Halt and investigate; do not force.
