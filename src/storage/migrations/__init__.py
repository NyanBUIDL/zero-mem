"""M2 migration registry.

Mutations are numbered and applied in deterministic ascending order. Each entry
is a module exposing `up(conn, note)` and `down(conn, note)`. The registry is
the single source of migration ordering for the SQLite store.
"""
from __future__ import annotations

from . import migrate_1

# Deterministic ordering keyed by integer schema version.
MIGRATIONS: dict[int, object] = {
    1: migrate_1,
}

CURRENT_SCHEMA_VERSION: int = max(MIGRATIONS.keys()) if MIGRATIONS else 0


__all__ = ["CURRENT_SCHEMA_VERSION", "MIGRATIONS"]
