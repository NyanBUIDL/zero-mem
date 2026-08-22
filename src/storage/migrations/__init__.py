"""M2 migration registry.

Mutations are numbered and applied in deterministic ascending order. Each entry
is a module exposing `up(conn, note)` and `down(conn, note)`. The registry is
the single source of migration ordering for the SQLite store.
"""
from __future__ import annotations

from . import migrate_1
from . import migrate_2
from . import migrate_3
from . import migrate_4
from . import migrate_5
from . import migrate_6
from . import migrate_7
from . import migrate_8
from . import migrate_9
from . import migrate_10
from . import migrate_11

# Deterministic ordering keyed by integer schema version.
MIGRATIONS: dict[int, object] = {
    1: migrate_1,
    2: migrate_2,
    3: migrate_3,
    4: migrate_4,
    5: migrate_5,
    6: migrate_6,
    7: migrate_7,
    8: migrate_8,
    9: migrate_9,
    10: migrate_10,
    11: migrate_11,
}

CURRENT_SCHEMA_VERSION: int = max(MIGRATIONS.keys()) if MIGRATIONS else 0


__all__ = ["CURRENT_SCHEMA_VERSION", "MIGRATIONS"]
