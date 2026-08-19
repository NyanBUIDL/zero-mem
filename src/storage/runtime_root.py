"""Runtime-owned production storage root for Linux-qualified Zero-Mem."""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .coordination import open_parent_dir


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
        if root.exists() or root.is_symlink():
            info = root.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("storage root symlink is not allowed")
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("storage root must be a directory")
        else:
            _mkdir_private_no_symlink(root)
        parent_fd = open_parent_dir(root / ".root-probe")
        os.close(parent_fd)
        for name in ("canonical", "derived", "recovery", "locks", "metadata"):
            child = root / name
            if child.exists() or child.is_symlink():
                info = child.lstat()
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError("storage domain symlink is not allowed")
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError("storage domain must be a directory")
            else:
                child.mkdir(mode=0o700)
            child_fd = open_parent_dir(child / ".domain-probe")
            os.close(child_fd)
        if os.name != "nt":
            os.chmod(root, 0o700)
        return cls(root)


def _mkdir_private_no_symlink(path: Path) -> None:
    """Create a missing directory without traversing an existing symlink.

    ``Path.mkdir(parents=True)`` delegates ancestor traversal to the kernel and
    would accept a symlinked ancestor during ordinary bootstrap.  Build the
    missing chain one component at a time and validate every existing component
    before proceeding.  Post-validation hostile replacement is outside the
    trusted-private-root model; this closes the normal bootstrap path only.
    """
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("storage root ancestor symlink is not allowed")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("storage root ancestor must be a directory")
        return
    _mkdir_private_no_symlink(path.parent)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("storage root ancestor is unsafe")


__all__ = ["RuntimeStorageRoot"]
