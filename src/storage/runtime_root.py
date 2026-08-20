"""Runtime-owned storage root using the internal platform contract."""
from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

from .platform import PlatformErrorCode, PlatformStorageError, ensure_private_directory, validate_directory


@dataclass(frozen=True)
class RuntimeStorageRoot:
    """Controlled root whose descendants are the only production domains."""

    root: Path

    @property
    def canonical(self) -> Path:
        return self.root / "canonical"

    @property
    def derived(self) -> Path:
        return self.root / "derived"

    @property
    def recovery(self) -> Path:
        return self.root / "recovery"

    @property
    def locks(self) -> Path:
        return self.root / "locks"

    @property
    def metadata(self) -> Path:
        return self.root / "metadata"

    @classmethod
    def open(cls, root: Path) -> "RuntimeStorageRoot":
        if not isinstance(root, Path) or not root.is_absolute():
            raise ValueError("storage root must be absolute")
        root = root.expanduser()
        if root == Path.home() or Path.home() in root.parents:
            raise ValueError("storage root must not be inside the real home directory")
        for ancestor in (root, *root.parents):
            if ancestor.is_symlink():
                raise ValueError("storage root symlink is not allowed")
        try:
            ensure_private_directory(root)
            for name in ("canonical", "derived", "recovery", "locks", "metadata"):
                child = root / name
                if child.exists() or child.is_symlink():
                    validate_directory(child)
                else:
                    ensure_private_directory(child)
        except PlatformStorageError as exc:
            if exc.code is PlatformErrorCode.UNSAFE_PATH:
                raise ValueError("storage root path is unsafe") from None
            raise
        return cls(root)


__all__ = ["RuntimeStorageRoot"]
