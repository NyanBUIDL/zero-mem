"""PKG-3 deterministic first-run setup command."""
from __future__ import annotations

from .config import load_effective_config
from .memory_layout import setup_lock
from .paths import (
    ConfigurationError,
    SetupError,
    cache_root,
    config_root,
    data_root,
    derived_db,
    derived_root,
    ensure_corpus_root,
    ensure_empty_memory_stream,
    ensure_private_dir,
    load_config,
    state_root,
    write_config,
)


def run() -> int:
    # Validate an existing file before creating or changing any application path.
    try:
        load_effective_config()
        load_config(required=False)
    except ConfigurationError:
        raise
    # T8: everything below runs under the exclusive first-run lock, so simultaneous `zero-mem setup` / `add` /
    # `serve` processes on a fresh install cannot trip over each other's directory, config or schema creation.
    with setup_lock(data_root()):
        for path, label in (
            (data_root(), "data directory"),
            (config_root(), "configuration directory"),
            (state_root(), "state directory"),
            (cache_root(), "cache directory"),
            (derived_root(), "derived directory"),
        ):
            ensure_private_dir(path, label)
        write_config()
        ensure_empty_memory_stream()
        ensure_corpus_root()

        try:
            from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

            store = SQLiteStore(SQLiteStoreConfig(path=derived_db()))
            try:
                store.ensure_schema()
            finally:
                store.close()
        except SetupError:
            raise
        except Exception:
            raise SetupError("unable to initialize derived store") from None
    return 0
