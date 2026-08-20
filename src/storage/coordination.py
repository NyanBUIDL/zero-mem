"""Storage coordination compatibility API backed by the platform contract."""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator, Literal

from .platform import (
    DEFAULT_TIMEOUT as DEFAULT_COORDINATION_TIMEOUT,
    coordinated as _coordinated,
    file_identity,
    locked as _locked,
    open_parent_dir,
    read_bytes,
)

LockMode = Literal["shared", "exclusive"]


def read_regular_bytes(path: Path) -> bytes:
    return read_bytes(path)


def regular_identity(path: Path) -> tuple[int, int]:
    identity = file_identity(path)
    return identity.device, identity.inode


@contextlib.contextmanager
def locked(path: Path, *, mode: LockMode = "exclusive", timeout: float | None = None, deadline: float | None = None) -> Iterator[None]:
    with _locked(path, mode=mode, timeout=timeout, deadline=deadline):
        yield


@contextlib.contextmanager
def coordinated(canonical: Path, derived: Path, *, mode: LockMode = "exclusive", timeout: float | None = None, deadline: float | None = None) -> Iterator[None]:
    with _coordinated(canonical, derived, mode=mode, timeout=timeout, deadline=deadline):
        yield


__all__ = ["coordinated", "locked", "open_parent_dir", "read_regular_bytes", "regular_identity", "DEFAULT_COORDINATION_TIMEOUT"]
