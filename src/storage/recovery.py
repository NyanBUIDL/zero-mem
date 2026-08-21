"""Bounded, coordinated recovery for disposable derived SQLite state."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from pathlib import Path


from src.storage.coordination import coordinated, read_regular_bytes
from src.storage.platform import (
    PlatformStorageError,
    FileIdentity,
    atomic_promote,
    close_handle,
    handle_info,
    fsync_handle,
    is_regular_info,
    is_symlink_info,
    list_relative,
    open_parent_dir,
    open_relative,
    paths_alias,
    read_all,
    rename_relative,
    stat_relative,
    unlink_relative,
    validate_path,
    write_all,
)
from src.storage.ingest import rebuild_from_jsonl
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig
from src.storage.runtime_root import RuntimeStorageRoot
from zero_mem.recovery import FailureClass, diagnose as diagnose_derived


DEFAULT_RECOVERY_TIMEOUT = 5.0


class RecoveryStatus(str, Enum):
    CURRENT = "CURRENT"
    MISSING = "MISSING"
    STALE = "STALE"
    CORRUPT = "CORRUPT"
    INCOMPATIBLE = "INCOMPATIBLE"
    INTERRUPTED = "INTERRUPTED"
    REBUILT = "REBUILT"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class RecoveryResult:
    status: RecoveryStatus
    source_id: str
    canonical_sequence: int
    derived_sequence: int | None
    diagnostic_code: str


@dataclass(frozen=True)
class _CanonicalIdentity:
    device: int
    inode: int
    size: int
    mtime_ns: int
    digest: str


class _PromotionFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _CleanupFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_FAILURE_MAP = {
    FailureClass.READY: RecoveryStatus.CURRENT,
    FailureClass.DERIVED_MISSING: RecoveryStatus.MISSING,
    FailureClass.DERIVED_STALE: RecoveryStatus.STALE,
    FailureClass.DERIVED_CORRUPT: RecoveryStatus.CORRUPT,
    FailureClass.SCHEMA_INCOMPATIBLE: RecoveryStatus.INCOMPATIBLE,
    FailureClass.CANONICAL_MISSING: RecoveryStatus.UNAVAILABLE,
    FailureClass.CANONICAL_MALFORMED: RecoveryStatus.UNAVAILABLE,
    FailureClass.DERIVED_UNAVAILABLE: RecoveryStatus.UNAVAILABLE,
}


def _validate_path(path: Path, *, allow_missing: bool = False) -> None:
    try:
        validate_path(path, allow_missing=allow_missing)
    except PlatformStorageError as exc:
        raise ValueError("path symlink or unsafe") from exc


def _strict_identity(value: object) -> bool:
    return type(value) is int and value >= 0


def _valid_canonical_identity(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"device", "inode", "size", "mtime_ns", "digest"}:
        return False
    return (
        _strict_identity(value["device"])
        and _strict_identity(value["inode"])
        and _strict_identity(value["size"])
        and _strict_identity(value["mtime_ns"])
        and isinstance(value["digest"], str)
        and len(value["digest"]) == 64
        and all(character in "0123456789abcdef" for character in value["digest"])
    )


def _validate_domain_path(path: Path, domain: Path, *, allow_missing: bool = False) -> None:
    try:
        path.absolute().relative_to(domain.absolute())
    except ValueError as exc:
        raise ValueError("path outside runtime storage domain") from exc
    _validate_path(path, allow_missing=allow_missing)



def _identity(path: Path) -> _CanonicalIdentity:
    _validate_path(path)
    parent = open_parent_dir(path)
    try:
        fd = open_relative(parent, path.name, access="read")
        try:
            info = handle_info(fd)
            if not is_regular_info(info):
                raise OSError("canonical_not_regular")
            raw = read_all(fd)
            return _CanonicalIdentity(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, hashlib.sha256(raw).hexdigest())
        finally:
            close_handle(fd)
    finally:
        close_handle(parent)


def _remove_owned(path: Path, marker: Path, token: str, *, directory_fd: int | Path | None = None) -> None:
    owned_directory = directory_fd is None
    if directory_fd is None:
        directory_fd = open_parent_dir(path)
    build_fd: int | None = None
    sidecar_fds: list[int] = []
    try:
        marker_fd = open_relative(directory_fd, marker.name, access="read")
        try:
            data = json.loads(read_all(marker_fd).decode("utf-8"))
        finally:
            close_handle(marker_fd)
        expected_build = data.get("build_identity")
        if (
            data.get("token") != token
            or data.get("build") != str(path)
            or not isinstance(expected_build, dict)
            or set(expected_build) != {"device", "inode"}
            or not _strict_identity(expected_build["device"])
            or not _strict_identity(expected_build["inode"])
        ):
            return
        build_fd = open_relative(directory_fd, path.name, access="read", nonblocking=True)
        info = handle_info(build_fd)
        if not is_regular_info(info) or expected_build != {"device": info.st_dev, "inode": info.st_ino}:
            return
        close_handle(build_fd)
        build_fd = None
        for suffix in ("-wal", "-shm"):
            sidecar_name = path.name + suffix
            try:
                sidecar_fd = open_relative(directory_fd, sidecar_name, access="read", nonblocking=True)
            except PlatformStorageError:
                continue
            sidecar_info = handle_info(sidecar_fd)
            if not is_regular_info(sidecar_info):
                close_handle(sidecar_fd)
                return
            close_handle(sidecar_fd)
            unlink_relative(directory_fd, sidecar_name)
        unlink_relative(directory_fd, path.name)
        unlink_relative(directory_fd, marker.name)
    except (OSError, PlatformStorageError, ValueError, json.JSONDecodeError, TypeError) as exc:
        raise _CleanupFailure("owned_cleanup_failed") from exc
    finally:
        if build_fd is not None:
            close_handle(build_fd)
        for sidecar_fd in sidecar_fds:
            close_handle(sidecar_fd)
        if owned_directory:
            close_handle(directory_fd)



class RecoveryCoordinator:
    """One bounded, coordinated recovery operation per derived store."""

    def __init__(self, storage_root: RuntimeStorageRoot, canonical_path: Path, derived_path: Path) -> None:
        if not isinstance(storage_root, RuntimeStorageRoot):
            raise ValueError("storage_root is required")
        _validate_domain_path(canonical_path, storage_root.canonical)
        _validate_domain_path(derived_path, storage_root.derived, allow_missing=True)
        if canonical_path.absolute() == derived_path.absolute():
            raise ValueError("canonical_path and derived_path must differ")
        self.storage_root = storage_root
        self.canonical_path = canonical_path.absolute()
        self.derived_path = derived_path.absolute()
        if paths_alias(self.canonical_path, self.derived_path):
            raise ValueError("canonical_path and derived_path alias")
        self.source_id = self.canonical_path.name
        self._lock = threading.Lock()
        self._active_worker: threading.Thread | None = None
        self._terminal_failure = False
        self._cancel_event = threading.Event()
        self._commit_started = False

    def _diagnose_unlocked(self) -> RecoveryResult:
        diagnosis = diagnose_derived(
            canonical_path=self.canonical_path,
            derived_path=self.derived_path,
            source_id=self.source_id,
            _coordination_held=True,
        )
        status = _FAILURE_MAP[diagnosis.status]
        return RecoveryResult(
            status=status,
            source_id=self.source_id,
            canonical_sequence=max(-1, diagnosis.canonical_records - 1),
            derived_sequence=diagnosis.derived_records,
            diagnostic_code=diagnosis.status.value.lower(),
        )

    def diagnose(self) -> RecoveryResult:
        try:
            with coordinated(self.canonical_path, self.derived_path, mode="shared", timeout=5.0):
                self._reject_canonical_derived_alias()
                return self._diagnose_unlocked()
        except Exception:
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, "coordination_unavailable")

    def recover(self, timeout: float | None = None) -> RecoveryResult:
        if timeout is not None and (
            not isinstance(timeout, Real) or isinstance(timeout, bool)
            or not math.isfinite(float(timeout)) or timeout < 0
        ):
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, "invalid_timeout")
        effective_timeout = DEFAULT_RECOVERY_TIMEOUT if timeout is None else float(timeout)
        deadline = time.monotonic() + effective_timeout
        with self._lock:
            try:
                with coordinated(self.canonical_path, self.derived_path, mode="exclusive", deadline=deadline):
                    return self._recover_locked(deadline)
            except _CleanupFailure as exc:
                return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, exc.code)
            except (TimeoutError, OSError, ValueError):
                return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, "coordination_unavailable")

    def _recover_locked(self, deadline: float | None) -> RecoveryResult:
        if self._terminal_failure:
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, "terminal_failure")
        if self._active_worker is not None and self._active_worker.is_alive():
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, "recovery_in_progress")
        if self._deadline_expired(deadline):
            return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, -1, None, "recovery_deadline_exceeded")
        try:
            self._reject_canonical_derived_alias()
            self._reject_unsafe_derived_artifacts()
        except ValueError:
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, "canonical_derived_alias")
        except OSError:
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, -1, None, "unsafe_derived_artifact")
        before = self._diagnose_unlocked()
        if before.status is RecoveryStatus.CURRENT:
            return before
        if before.status is RecoveryStatus.UNAVAILABLE:
            return before
        if self._deadline_expired(deadline):
            return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "diagnosis_deadline_exceeded")
        snapshot = _identity(self.canonical_path)
        self._cancel_event.clear()
        self._commit_started = False
        error: list[BaseException] = []
        token = f"{os.getpid()}-{threading.get_ident()}-{time.time_ns()}"
        build_path = self.derived_path.with_name(self.derived_path.name + f".recovery-building.{token}")
        marker = Path(str(build_path) + ".owner")
        snapshot_path = self.canonical_path.with_name(self.canonical_path.name + f".recovery-snapshot.{token}")
        self._create_snapshot(snapshot_path, snapshot)
        if self._deadline_expired(deadline):
            self._safe_unlink_snapshot(snapshot_path)
            return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "snapshot_deadline_exceeded")
        self._reserve_owned_build(build_path, marker, token, snapshot)
        if self._deadline_expired(deadline):
            _remove_owned(build_path, marker, token)
            self._safe_unlink_snapshot(snapshot_path)
            return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "build_deadline_exceeded")

        def run_rebuild() -> None:
            try:
                self._build_default(snapshot_path, build_path, marker, token)
                if self._cancel_event.is_set():
                    _remove_owned(build_path, marker, token)
            except BaseException as exc:
                error.append(exc)
                try:
                    _remove_owned(build_path, marker, token)
                except _CleanupFailure as cleanup_error:
                    error.append(cleanup_error)
            finally:
                try:
                    self._safe_unlink_snapshot(snapshot_path)
                except _CleanupFailure as exc:
                    error.append(exc)

        worker = threading.Thread(target=run_rebuild, name="zero-mem-recovery", daemon=True)
        self._active_worker = worker
        worker.start()
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        worker.join(timeout=remaining)
        if worker.is_alive():
            self._cancel_event.set()
            return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "rebuild_deadline_exceeded")
        self._active_worker = None
        if error:
            self._terminal_failure = True
            diagnostic_code = next(
                (exc.code for exc in error if isinstance(exc, _CleanupFailure)),
                "rebuild_failed",
            )
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, before.canonical_sequence, None, diagnostic_code)
        if deadline is not None and time.monotonic() >= deadline:
            self._cancel_event.set()
            _remove_owned(build_path, marker, token)
            return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "promotion_deadline_exceeded")
        try:
            if self._cancel_event.is_set() or _identity(self.canonical_path) != snapshot:
                _remove_owned(build_path, marker, token)
                self._terminal_failure = True
                return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "canonical_generation_changed")
            self._promote_owned(build_path, marker, token, snapshot, deadline)
        except TimeoutError:
            _remove_owned(build_path, marker, token)
            if not self._commit_started:
                return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "promotion_deadline_exceeded")
            self._terminal_failure = True
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, before.canonical_sequence, None, "committed_promotion_failed")
        except Exception as exc:
            _remove_owned(build_path, marker, token)
            self._terminal_failure = True
            diagnostic_code = exc.code if isinstance(exc, _PromotionFailure) else "rebuild_promotion_failed"
            return RecoveryResult(RecoveryStatus.UNAVAILABLE, self.source_id, before.canonical_sequence, None, diagnostic_code)
        if self._deadline_expired(deadline) and not self._commit_started:
            return RecoveryResult(RecoveryStatus.INTERRUPTED, self.source_id, before.canonical_sequence, before.derived_sequence, "diagnosis_deadline_exceeded")
        after = self._diagnose_unlocked()
        if after.status is RecoveryStatus.CURRENT:
            return RecoveryResult(RecoveryStatus.REBUILT, after.source_id, after.canonical_sequence, after.derived_sequence, "rebuild_verified")
        self._terminal_failure = True
        return RecoveryResult(RecoveryStatus.UNAVAILABLE, after.source_id, after.canonical_sequence, after.derived_sequence, "committed_post_diagnosis_failed")

    @staticmethod
    def _deadline_expired(deadline: float | None) -> bool:
        return deadline is not None and time.monotonic() >= deadline

    @staticmethod
    def _safe_unlink_snapshot(path: Path) -> None:
        try:
            parent = open_parent_dir(path)
            try:
                unlink_relative(parent, path.name)
            finally:
                close_handle(parent)
        except (OSError, PlatformStorageError):
            raise _CleanupFailure("snapshot_cleanup_failed") from None

    def _reject_canonical_derived_alias(self) -> None:
        if not paths_alias(self.canonical_path, self.derived_path):
            return
        canonical_parent = open_parent_dir(self.canonical_path)
        derived_parent = open_parent_dir(self.derived_path)
        canonical_fd = derived_fd = None
        try:
            canonical_fd = open_relative(canonical_parent, self.canonical_path.name, access="read")
            derived_fd = open_relative(derived_parent, self.derived_path.name, access="read")
            canonical_info = handle_info(canonical_fd)
            derived_info = handle_info(derived_fd)
            if (canonical_info.st_dev, canonical_info.st_ino) == (derived_info.st_dev, derived_info.st_ino):
                raise ValueError("canonical_derived_alias")
        finally:
            if canonical_fd is not None:
                close_handle(canonical_fd)
            if derived_fd is not None:
                close_handle(derived_fd)
            close_handle(canonical_parent)
            close_handle(derived_parent)

    def _reject_unsafe_derived_artifacts(self) -> None:
        """Reject hostile legacy/build artifacts through one pinned parent handle."""
        parent = open_parent_dir(self.derived_path)
        try:
            prefix = self.derived_path.name + ".recovery-building."
            names = list_relative(parent)
            fixed = {self.derived_path.name + "-wal", self.derived_path.name + "-shm"}
            for name in names:
                if name.endswith(".owner"):
                    if name[:-len(".owner")] not in names:
                        raise OSError("orphan_recovery_owner")
                    continue
                if ".recovery-old." in name or name == self.derived_path.name + ".recovery-building":
                    raise OSError("unknown_recovery_artifact")
                if name not in fixed and not name.startswith(prefix):
                    continue
                info = stat_relative(parent, name)
                if is_symlink_info(info) or not is_regular_info(info):
                    raise OSError("unsafe_derived_artifact")
                if name in fixed:
                    continue
                marker_name = name + ".owner"
                try:
                    marker_info = stat_relative(parent, marker_name)
                except PlatformStorageError:
                    raise OSError("unowned_recovery_build") from None
                if is_symlink_info(marker_info) or not is_regular_info(marker_info):
                    raise OSError("unowned_recovery_build")
                marker_fd = open_relative(parent, marker_name, access="read")
                try:
                    owner = json.loads(read_all(marker_fd).decode("utf-8"))
                except (OSError, ValueError, UnicodeError, json.JSONDecodeError):
                    raise OSError("malformed_recovery_owner") from None
                finally:
                    close_handle(marker_fd)
                candidate = self.derived_path.parent / name
                marker = self.derived_path.parent / marker_name
                expected_build = owner.get("build_identity")
                if (owner.get("build") != str(candidate) or owner.get("destination") != str(self.derived_path)
                        or not isinstance(owner.get("token"), str) or not _valid_canonical_identity(owner.get("canonical"))
                        or not isinstance(expected_build, dict) or set(expected_build) != {"device", "inode"}
                        or not _strict_identity(expected_build["device"]) or not _strict_identity(expected_build["inode"])):
                    raise OSError("recovery_owner_mismatch")
                _remove_owned(candidate, marker, owner["token"], directory_fd=parent)
        finally:
            close_handle(parent)


    def _create_snapshot(self, snapshot_path: Path, identity: _CanonicalIdentity) -> None:
        raw = read_regular_bytes(self.canonical_path)
        if _identity(self.canonical_path) != identity:
            raise ValueError("canonical_generation_changed")
        parent = open_parent_dir(snapshot_path)
        fd = open_relative(parent, snapshot_path.name, access="readwrite", create=True, exclusive=True)
        try:
            try:
                write_all(fd, raw)
                if handle_info(fd).st_size != len(raw):
                    raise OSError("snapshot_size_mismatch")
                fsync_handle(fd)
            except Exception as snapshot_error:
                try:
                    unlink_relative(parent, snapshot_path.name)
                except Exception as cleanup_error:
                    raise _CleanupFailure("snapshot_cleanup_failed") from cleanup_error
                raise snapshot_error
        finally:
            close_handle(fd)
            close_handle(parent)

    def _reserve_owned_build(self, building_path: Path, marker: Path, token: str, identity: _CanonicalIdentity) -> None:
        directory = open_parent_dir(building_path)
        try:
            build_fd = open_relative(directory, building_path.name, access="readwrite", create=True, exclusive=True)
            build_info = handle_info(build_fd)
            close_handle(build_fd)
            marker_fd = open_relative(directory, marker.name, access="write", create=True, exclusive=True)
            owner = {"token": token, "build": str(building_path), "build_identity": {"device": build_info.st_dev, "inode": build_info.st_ino}, "pid": os.getpid(), "canonical": {"device": identity.device, "inode": identity.inode, "size": identity.size, "mtime_ns": identity.mtime_ns, "digest": identity.digest}, "destination": str(self.derived_path)}
            try:
                write_all(marker_fd, json.dumps(owner, sort_keys=True).encode("utf-8"))
                fsync_handle(marker_fd)
            finally:
                close_handle(marker_fd)
        finally:
            close_handle(directory)

    def _build_default(self, snapshot_path: Path, building_path: Path, marker: Path, token: str) -> None:
        store = None
        try:
            store = SQLiteStore(SQLiteStoreConfig(path=building_path))
            store.ensure_schema()
            reports = rebuild_from_jsonl(store, [snapshot_path], source_ids=[self.source_id], synchronous_full=True)
            report = reports.get(self.source_id)
            if report is None or report.stopped:
                raise RuntimeError("recovery_ingest_stopped")
        finally:
            if store is not None:
                store.close()

    def _promote_owned(self, building_path: Path, marker: Path, token: str, identity: _CanonicalIdentity, deadline: float | None) -> None:
        directory = open_parent_dir(self.derived_path)
        build_fd: int | None = None
        try:
            marker_fd = open_relative(directory, marker.name, access="read")
            try:
                data = json.loads(read_all(marker_fd).decode("utf-8"))
            finally:
                close_handle(marker_fd)
            expected_owner = {"device": identity.device, "inode": identity.inode, "size": identity.size, "mtime_ns": identity.mtime_ns, "digest": identity.digest}
            if data.get("token") != token or data.get("build") != str(building_path) or data.get("destination") != str(self.derived_path) or data.get("canonical") != expected_owner:
                raise RuntimeError("recovery_owner_mismatch")
            build_fd = open_relative(directory, building_path.name, access="read", nonblocking=True)
            build_info = handle_info(build_fd)
            expected_build = data.get("build_identity")
            if (not is_regular_info(build_info) or not isinstance(expected_build, dict) or set(expected_build) != {"device", "inode"}
                    or not _strict_identity(expected_build["device"]) or not _strict_identity(expected_build["inode"])
                    or expected_build != {"device": build_info.st_dev, "inode": build_info.st_ino}):
                raise RuntimeError("recovery_build_identity_mismatch")
            try:
                destination_info = stat_relative(directory, self.derived_path.name)
            except PlatformStorageError:
                destination_info = None
            if destination_info is not None and not is_regular_info(destination_info):
                raise RuntimeError("derived_destination_unsafe")
            if self._deadline_expired(deadline):
                raise TimeoutError("promotion_deadline_exceeded")
            self._commit_started = True
            quarantined: list[tuple[str, str]] = []
            try:
                for suffix in ("-wal", "-shm"):
                    sidecar_name = self.derived_path.name + suffix
                    try:
                        sidecar_info = stat_relative(directory, sidecar_name)
                    except PlatformStorageError:
                        continue
                    if not is_regular_info(sidecar_info):
                        raise RuntimeError("derived_sidecar_unsafe")
                    quarantine = sidecar_name + f".recovery-old.{token}"
                    rename_relative(directory, sidecar_name, quarantine)
                    quarantined.append((sidecar_name, quarantine))
                atomic_promote(
                    building_path,
                    self.derived_path,
                    expected_source=FileIdentity(build_info.st_dev, build_info.st_ino, build_info.st_size, build_info.st_mtime_ns, ""),
                )
                unlink_relative(directory, building_path.name)
            except Exception as promotion_error:
                rollback_errors: list[OSError] = []
                for sidecar_name, quarantine in reversed(quarantined):
                    try:
                        rename_relative(directory, quarantine, sidecar_name)
                    except (OSError, PlatformStorageError) as rollback_error:
                        rollback_errors.append(rollback_error)
                if rollback_errors:
                    raise _PromotionFailure("promotion_rollback_failed") from rollback_errors[0]
                raise promotion_error
            try:
                unlink_relative(directory, marker.name)
            except (OSError, PlatformStorageError):
                raise _CleanupFailure("promotion_marker_cleanup_failed") from None
        finally:
            if build_fd is not None:
                close_handle(build_fd)
            close_handle(directory)


__all__ = ["RecoveryCoordinator", "RecoveryResult", "RecoveryStatus"]
