"""V141 — user-local configuration file for Zero-Mem (DEF-012 method A).

Stores operator preferences that are NOT canonical state and NEVER a second
source of truth for authorization data (grants live in the derived projection
of canonical JSONL events; this file only tells the runtime WHERE to find
auxiliary stores such as the corpus-derived.sqlite used by the DEF-004
resolution layer).

Location (XDG, agent-independent):
  $XDG_CONFIG_HOME/zero-mem/config.json   (default ~/.config/zero-mem/config.json)

Precedence in the runtime: explicit arg > env var > this file > unconfigured.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_KNOWN_KEYS = {"corpus-store-path"}


def config_file_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base or not Path(base).is_absolute():
        base = str(Path.home() / ".config")
    return Path(base) / "zero-mem" / "config.json"


def _load() -> dict:
    p = config_file_path()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    p = config_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, p)          # atomic write
    try:
        os.chmod(p, 0o600)      # operator-private
    except OSError:
        pass


def get_corpus_store_path() -> Optional[str]:
    """Return the configured corpus store path, or None when unset."""
    v = _load().get("corpus-store-path")
    return str(v) if v else None


def set_corpus_store_path(path: str) -> None:
    from src.integration.m6.runtime import (
        CorpusStoreConfigError,
        _validate_corpus_store_path,
    )

    p = Path(path)
    # Fail LOUD at set time with a precise reason.
    _validate_corpus_store_path(p)
    data = _load()
    data["corpus-store-path"] = str(p)
    _save(data)


def unset_corpus_store_path() -> bool:
    data = _load()
    if "corpus-store-path" not in data:
        return False
    del data["corpus-store-path"]
    _save(data)
    return True


__all__ = [
    "config_file_path", "get_corpus_store_path",
    "set_corpus_store_path", "unset_corpus_store_path",
    "_KNOWN_KEYS",
]
