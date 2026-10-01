"""Storage layout + first-run setup shared by :class:`zero_mem.memory.Memory` and the provisioning commands.

Two modes:

* **default** (``data_root=None``): the paths come from ``zero_mem.paths`` (``ZERO_MEM_DATA_ROOT`` / XDG, and
  ``ZERO_MEM_CORPUS_ROOT``), and :meth:`Layout.ensure` runs exactly what ``zero-mem setup`` runs, so ``doctor``,
  ``upgrade`` and ``backup`` agree with the library.
* **explicit** (``data_root=<absolute path>``): an isolated store (tests, benchmarks, tooling). The corpus root
  is ``<root>/data/corpus`` unless ``corpus_root`` is passed (the corpus env override is deliberately ignored: an
  explicit root must never write elsewhere), and the user's configuration directory is never touched.

Zero dependencies, no network.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from . import paths

PathLike = Union[str, Path]


class LayoutError(RuntimeError):
    """Sanitized layout / setup failure (no path or content in the message)."""


@dataclass(frozen=True)
class Layout:
    data_root: Path
    memory_stream: Path
    derived_db: Path
    corpus_root: Path
    explicit: bool

    @classmethod
    def resolve(cls, data_root: Optional[PathLike] = None, corpus_root: Optional[PathLike] = None) -> "Layout":
        try:
            if data_root is None:
                if corpus_root is not None:
                    raise LayoutError("corpus_root requires an explicit data_root")
                return cls(
                    data_root=paths.data_root(),
                    memory_stream=paths.memory_stream(),
                    derived_db=paths.derived_db(),
                    corpus_root=paths.corpus_root(),
                    explicit=False,
                )
            root = Path(data_root).expanduser()
            if not root.is_absolute():
                raise LayoutError("data root must be absolute")
            corpus = Path(corpus_root).expanduser() if corpus_root is not None else root / paths.CORPUS_RELATIVE
            if not corpus.is_absolute():
                raise LayoutError("corpus root must be absolute")
            return cls(
                data_root=root,
                memory_stream=root / paths.MEMORY_STREAM_RELATIVE,
                derived_db=root / paths.DERIVED_DB_RELATIVE,
                corpus_root=corpus,
                explicit=True,
            )
        except paths.ConfigurationError as exc:
            raise LayoutError(str(exc)) from None

    def ensure(self) -> None:
        """Idempotently create private dirs, the empty canonical stream, the corpus root and the schema."""
        try:
            if not self.explicit:
                from .commands_setup import run

                run()
                return
            paths.ensure_private_dir(self.data_root, "data directory")
            paths.ensure_private_dir(self.derived_db.parent, "derived directory")
            paths.ensure_private_dir(self.memory_stream.parent, "canonical memory directory")
            self._ensure_stream()
            self._ensure_corpus()
            self._ensure_schema()
        except LayoutError:
            raise
        except (paths.ConfigurationError, paths.SetupError) as exc:
            raise LayoutError(str(exc)) from None
        except Exception:
            raise LayoutError("setup failed") from None

    # -- explicit-mode helpers (mirror zero_mem.paths without the environment) --------------
    def _ensure_stream(self) -> None:
        import os

        path = self.memory_stream
        paths._reject_symlink(path, "canonical memory stream")
        if not path.exists():
            path.touch(mode=0o600)
        if not path.is_file():
            raise LayoutError("invalid canonical memory stream")
        if os.name != "nt":
            os.chmod(path, 0o600)

    def _ensure_corpus(self) -> None:
        import os

        paths.ensure_private_dir(self.corpus_root, "corpus directory")
        paths.ensure_private_dir(self.corpus_root / "blobs", "corpus blob directory")
        registry = self.corpus_root / paths.CORPUS_REGISTRY_FILENAME
        paths._reject_symlink(registry, "corpus registry")
        if not registry.exists():
            registry.touch(mode=0o600)
        if not registry.is_file():
            raise LayoutError("invalid corpus registry")
        if os.name != "nt":
            os.chmod(registry, 0o600)

    def _ensure_schema(self) -> None:
        from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

        store = SQLiteStore(SQLiteStoreConfig(path=self.derived_db))
        try:
            store.ensure_schema()
        finally:
            store.close()


__all__ = ["Layout", "LayoutError"]
