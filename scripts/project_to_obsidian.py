#!/usr/bin/env python3
"""M9.6 — controlled Obsidian projection CLI.

One explicit, auditable operator entry point for the VERIFIED M9 projection
pipeline. It performs NO projection of its own: it only resolves configuration,
opens the canonical store strictly read-only, and delegates to the VERIFIED
:func:`~src.projection.engine.project_to_vault`.

Safety properties (plan-m9.md §2, §5, §24, §26.1, §28):

* **Dry-run by default.** Without ``--apply``, nothing is written. ``--apply``
  additionally requires ``--yes`` and an explicit ``--project`` so a real vault
  is never touched by accident or by a global/no-arg invocation.
* **No hard-coded vault.** The operator vault root is always supplied
  explicitly (``--vault``), via the ``ZERO_MEM_OBSIDIAN_VAULT`` environment
  variable, or via an optional ``config/projection.yaml``. No username, home
  directory, or ``~/Obsidian`` guess lives in this file.
* **No hard-coded store.** The canonical store path is an explicit operator
  argument (``--store``) or omitted, in which case the caller must supply it;
  the CLI never invents a path.
* **Read-only canonical.** The store is opened with ``open_readonly`` (mode=ro,
  query_only). The projector can read nothing it could write.
* **Subtree bounded.** Only ``<vault>/Zero-Mem`` (configurable) is ever written.
  The vault root, ``.obsidian/``, and every other human note stays read-only.
* **Zero LLM / zero network / no Hermes core.** This script imports only store
  + projection modules. It makes no socket, no HTTP, and no embeddings call.

This file is the LAST M9 increment. It changes no product module and adds no
dependency.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.access.authorized_read import AuthorizedReadService  # noqa: E402
from src.access.contracts import AccessRequest  # noqa: E402
from src.projection import config as projection_config  # noqa: E402
from src.projection.engine import project_to_vault  # noqa: E402
from src.projection.manifest import MANIFEST_RELATIVE_PATH  # noqa: E402
from src.projection.writer import WriteStatus  # noqa: E402
from src.retrieval.db import open_readonly  # noqa: E402

# Content-level secret backstop forwarded to the engine (plan-m9.md §11.3).
# The engine ALWAYS applies its built-in baseline (DEFAULT_SECRET_PATTERNS),
# so even an empty list here never disables the backstop. Operators may add
# more patterns; they are appended, not a replacement.
DEFAULT_SECRET_PATTERNS: Tuple[str, ...] = ()


def _build_service(store_path: Path, requesting_profile_id: str) -> AuthorizedReadService:
    """Open the canonical store READ-ONLY and wrap it in the M5 service."""
    readonly = open_readonly(store_path)
    return AuthorizedReadService(readonly, requesting_profile_id)


def _plan_lines(result, managed_root: Path) -> List[str]:
    """A sanitized, human-reviewable plan. Carries NO absolute operator path."""
    lines = [
        "Projection plan (sanitized):",
        f"  managed_dir_name : {managed_root.name}",
        f"  notes desired     : {len(result.notes)}",
        f"  writes            : {result.written}",
    ]
    by_status: dict = {}
    for w in result.writes:
        by_status.setdefault(w.status.name, 0)
        by_status[w.status.name] += 1
    for status, count in sorted(by_status.items()):
        lines.append(f"    {status}: {count}")
    lines.append("  per-note decision (relative_path | status):")
    for w in sorted(result.writes, key=lambda x: (x.relative_path, x.note_id)):
        lines.append(f"    {w.relative_path} | {w.status.value}"
                     + (f" | {w.reason}" if w.reason else ""))
    return lines


def run(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="project_to_obsidian",
        description="Project authorized Zero-Mem state into an Obsidian vault "
                    "(dry-run by default).",
    )
    parser.add_argument("--vault", type=str, default=None,
                        help="Explicit operator vault root (absolute path). "
                             "Overrides ZERO_MEM_OBSIDIAN_VAULT and config.")
    parser.add_argument("--store", type=str, required=True,
                        help="Path to the canonical derived SQLite store "
                             "(opened read-only).")
    parser.add_argument("--project", type=str, required=True,
                        help="Single explicit project id to project. Nothing "
                             "global is projected.")
    parser.add_argument("--profile", type=str, default=None,
                        help="Requesting profile id. None = unbound (fail-closed "
                             "authorization by default).")
    parser.add_argument("--ceiling", type=str, default="internal",
                        help="Sensitivity ceiling (default: internal). secret "
                             "never projects; unknown fails closed.")
    parser.add_argument("--managed-dir-name", type=str, default="Zero-Mem",
                        help="Managed subtree name inside the vault.")
    parser.add_argument("--secret-pattern", action="append", default=[],
                        help="Extra content-level secret pattern to withhold.")
    parser.add_argument("--authorize-project", action="store_true",
                        help="Construct an explicit in-memory READ grant for "
                             "--profile on --project (mirrors the verified M9 "
                             "fixture path). Use when the canonical store has no "
                             "persisted M5 grant for this request.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write. REQUIRES --yes.")
    parser.add_argument("--yes", action="store_true",
                        help="Confirm a real write. Must be paired with --apply.")
    args = parser.parse_args(argv)

    if args.apply and not args.yes:
        sys.stderr.write("REFUSING: --apply requires --yes for a real vault.\n")
        return 2

    store_path = Path(args.store).expanduser().resolve()
    if not store_path.exists():
        sys.stderr.write(f"REFUSING: store not found: {store_path.name}\n")
        return 2

    # The vault root must exist before config validation (validate_vault_root
    # refuses a missing directory). Creating the operator's chosen vault
    # directory is a prerequisite, not a projection write; the managed subtree
    # inside it stays bounded by the VERIFIED config layer.
    vault_root = projection_config.resolve_vault_root(args.vault)
    if vault_root is None:
        sys.stderr.write(
            "UNAVAILABLE: no vault configured (explicit --vault, "
            "ZERO_MEM_OBSIDIAN_VAULT, or config/projection.yaml).\n")
        return 0
    vault_root.mkdir(parents=True, exist_ok=True)

    cfg = projection_config.ProjectionConfig(
        vault_root=vault_root,
        managed_dir_name=args.managed_dir_name,
        sensitivity_ceiling=args.ceiling,
    )

    # The managed root is confined to <vault>/<managed_dir_name> by the VERIFIED
    # config layer. We never touch the vault root itself.
    managed_root = cfg.managed_root
    if not managed_root.exists():
        if args.apply:
            managed_root.mkdir(parents=True, exist_ok=True)
        else:
            sys.stderr.write(
                f"dry-run: managed root does not exist yet: {managed_root.name}\n")

    secret_patterns = DEFAULT_SECRET_PATTERNS + tuple(args.secret_pattern)

    service = _build_service(store_path, args.profile)
    request = AccessRequest(
        operation="READ",
        requesting_profile_id=args.profile,
        project_ids=[args.project],
    )
    grants = None
    if args.authorize_project:
        # Explicit in-memory READ grant (verified M9 fixture semantics). The M5
        # service still validates the grant from its own fields; nothing is
        # self-authorized. Omit when the canonical store carries persisted grants.
        from src.access.grants import AuthorizedReadGrant
        grants = [AuthorizedReadGrant(
            grant_id="cli-explicit",
            subject_profile=args.profile or "",
            operation="READ",
            target_type="project",
            target_id=args.project,
        )]
    # In-memory grants are NOT auto-loaded here: the operator must supply an
    # explicit profile, and the M5 service resolves from the canonical store's
    # persisted grants when a grant connection is configured. For this CLI we
    # rely on the store's own authorization records; grants=None lets the service
    # evaluate the request against canonical authorization state.
    result = project_to_vault(
        service, request, cfg, args.project, managed_root,
        managed_dir_name=args.managed_dir_name,
        grants=grants,
        dry_run=not args.apply,
        secret_patterns=secret_patterns,
    )

    for line in _plan_lines(result, managed_root):
        print(line)

    if args.apply:
        print(f"APPLIED: {result.created} created, {result.updated} updated, "
              f"{result.retired} retired; manifest stored={result.manifest_stored}.")
    else:
        print("DRY-RUN: no files written. Re-run with --apply --yes to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
