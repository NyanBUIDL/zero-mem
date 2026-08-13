"""PKG-5 local backup verification and staged canonical restore.

The backup is an inspectable directory.  Only canonical JSONL, canonical corpus
registry/blob files, and Zero-Mem-owned configuration descriptors are captured;
SQLite and every other projection remain disposable and are rebuilt in an
isolated staging root before activation.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from src.access.rebuild import rebuild_policy_state
from src.corpus.contracts import CorpusSourceRecord
from src.corpus.identity import compute_content_identity
from src.corpus.derived_store import rebuild_from_corpus
from src.corpus.blob_store import BlobStoreError
from src.corpus.registry import REGISTRY_FILENAME
from src.m8.projection_store import rebuild_graph
from src.m8.temporal_projection import project_temporal_index
from src.project_memory.rebuild import rebuild_all_project_memory
from src.storage.canonical_replay import CanonicalReplayError
from src.storage.ingest import rebuild_from_jsonl
from src.storage.migrations import CURRENT_SCHEMA_VERSION
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

from .hermes_integration import IntegrationConfig
from .paths import (
    ConfigurationError,
    cache_root,
    config_path,
    config_root,
    data_root,
    derived_db,
    expected_config,
    load_config,
    memory_stream,
    write_config,
)
from .version import __version__

BACKUP_FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
BACKUP_DIRNAME = "backups"


class BackupError(RuntimeError):
    """Sanitized typed backup/restore failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> BackupError:
    return BackupError(code)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_target(path: Path, code: str = "UNSAFE_PATH") -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() or candidate == Path("/"):
        raise _fail(code)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current.is_symlink():
            raise _fail(code)
    return candidate


def _contained(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise _fail("UNSAFE_PATH")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise _fail("UNSAFE_PATH")
    return relative


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        # Directory fsync is an additional durability measure, not a reason to
        # expose platform-specific errors after the file protocol completed.
        return


def _atomic_bytes(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(temporary, mode)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _iter_regular_files(root: Path) -> Iterator[tuple[Path, str]]:
    if not root.exists():
        return
    if root.is_symlink() or not root.is_dir():
        raise _fail("UNSAFE_PATH")
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise _fail("UNSAFE_PATH")
        if path.is_dir():
            continue
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise _fail("UNSAFE_PATH")
        yield path, path.relative_to(root).as_posix()


def _copy_payload(source: Path, destination: Path, relative: str, category: str) -> dict[str, Any]:
    relative_path = _safe_relative(relative).as_posix()
    destination_path = destination / relative_path
    if not _contained(destination, destination_path):
        raise _fail("UNSAFE_PATH")
    destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        shutil.copyfile(source, destination_path)
    except OSError:
        raise _fail("BACKUP_CREATE_FAILED") from None
    if os.name != "nt":
        os.chmod(destination_path, 0o600)
    return {
        "category": category,
        "path": relative_path,
        "size": destination_path.stat().st_size,
        "sha256": _sha256(destination_path),
    }


def _copy_entry(source: Path, destination: Path, backup_path: str, category: str) -> dict[str, Any]:
    relative_path = _safe_relative(backup_path).as_posix()
    destination_path = destination / relative_path
    if not _contained(destination, destination_path):
        raise _fail("UNSAFE_PATH")
    destination_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        shutil.copyfile(source, destination_path)
    except OSError:
        raise _fail("BACKUP_CREATE_FAILED") from None
    if os.name != "nt":
        os.chmod(destination_path, 0o600)
    return {
        "category": category,
        "path": relative_path,
        "size": destination_path.stat().st_size,
        "sha256": _sha256(destination_path),
    }


def _configuration_payload() -> bytes:
    load_config()
    value = expected_config()
    # The runtime config contains absolute machine paths.  Backups retain the
    # semantic contract and regenerate those paths for the restore target.
    portable = {
        "schema_version": value["schema_version"],
        "version": value["version"],
        "capture_mode": value["capture_mode"],
        "canonical_memory_root": "data/memory",
        "derived_store": "data/derived/memory.sqlite3",
        "capture_stream": "data/memory/traces/events-v1.jsonl",
    }
    return (json.dumps(portable, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _load_json_bytes(payload: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError):
        raise _fail(code) from None
    if not isinstance(value, dict):
        raise _fail(code)
    return value


def _validate_memory_file(path: Path) -> None:
    try:
        data = path.read_bytes()
    except OSError:
        raise _fail("MISSING_PAYLOAD") from None
    if data and not data.endswith(b"\n"):
        raise _fail("INVALID_MANIFEST")
    for raw in data.splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (UnicodeError, ValueError):
            raise _fail("INVALID_MANIFEST") from None
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("event_id"), str)
            or not record.get("event_id")
            or not isinstance(record.get("event_type"), str)
            or not record.get("event_type")
        ):
            raise _fail("INVALID_MANIFEST")


def _validate_corpus_root(root: Path) -> None:
    registry = root / REGISTRY_FILENAME
    if not registry.is_file() or registry.is_symlink():
        raise _fail("MISSING_PAYLOAD")
    try:
        lines = registry.read_bytes().splitlines()
    except OSError:
        raise _fail("MISSING_PAYLOAD") from None
    if registry.read_bytes() and not registry.read_bytes().endswith(b"\n"):
        raise _fail("INVALID_MANIFEST")
    for line_number, raw in enumerate(lines, start=1):
        try:
            raw_record = json.loads(raw.decode("utf-8"))
            record = CorpusSourceRecord.from_dict(raw_record)
        except Exception:
            raise _fail("INVALID_MANIFEST") from None
        if not isinstance(record, CorpusSourceRecord):
            raise _fail("INVALID_MANIFEST")
        if record.blob_ref is None:
            continue
        digest = record.blob_ref
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise _fail("INVALID_MANIFEST")
        blob = root / "blobs" / digest[:2] / digest
        if blob.is_symlink() or not blob.is_file() or not _contained(root, blob):
            raise _fail("MISSING_PAYLOAD")
        try:
            content = blob.read_bytes()
        except OSError:
            raise _fail("MISSING_PAYLOAD") from None
        if _sha256_bytes(content) != digest:
            raise _fail("CHECKSUM_MISMATCH")
        if record.content_hash != compute_content_identity(content):
            raise _fail("INVALID_MANIFEST")


def _validate_manifest(manifest: object) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise _fail("INVALID_MANIFEST")
    if manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION:
        raise _fail("UNSUPPORTED_BACKUP_VERSION")
    if manifest.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise _fail("SCHEMA_INCOMPATIBLE")
    if not isinstance(manifest.get("zero_mem_version"), str) or not isinstance(manifest.get("created_at"), str):
        raise _fail("INVALID_MANIFEST")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise _fail("INVALID_MANIFEST")
    seen: set[str] = set()
    folded: set[str] = set()
    required_memory = False
    has_corpus = False
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"category", "path", "size", "sha256"}:
            raise _fail("INVALID_MANIFEST")
        category = entry["category"]
        if category not in {"canonical", "configuration"}:
            raise _fail("INVALID_MANIFEST")
        relative = _safe_relative(entry["path"])
        normalized = relative.as_posix()
        if normalized in seen or normalized.casefold() in folded:
            raise _fail("INVALID_MANIFEST")
        seen.add(normalized)
        folded.add(normalized.casefold())
        if not isinstance(entry["size"], int) or entry["size"] < 0:
            raise _fail("INVALID_MANIFEST")
        digest = entry["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise _fail("INVALID_MANIFEST")
        if normalized == "canonical/memory/events-v1.jsonl":
            required_memory = True
        if normalized.startswith("canonical/corpus/"):
            has_corpus = True
    if not required_memory:
        raise _fail("MISSING_PAYLOAD")
    manifest["_normalized_files"] = seen
    manifest["_has_corpus"] = has_corpus
    return manifest


def verify_backup(backup: Path) -> dict[str, Any]:
    """Read-only verification of manifest structure, paths, payloads, and domains."""
    root = _safe_target(Path(backup), "UNSAFE_PATH")
    if root.is_symlink() or not root.is_dir():
        raise _fail("INVALID_MANIFEST")
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise _fail("INVALID_MANIFEST")
    try:
        manifest = _load_json_bytes(manifest_path.read_bytes(), "INVALID_MANIFEST")
    except OSError:
        raise _fail("INVALID_MANIFEST") from None
    manifest = _validate_manifest(manifest)
    files = manifest["files"]
    listed = {entry["path"] for entry in files}
    actual: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise _fail("UNSAFE_PATH")
        if path.is_dir():
            continue
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise _fail("UNSAFE_PATH")
        actual.add(path.relative_to(root).as_posix())
    if MANIFEST_NAME not in actual:
        raise _fail("INVALID_MANIFEST")
    if actual - {MANIFEST_NAME} != listed:
        raise _fail("INVALID_MANIFEST")
    for entry in files:
        payload = root / entry["path"]
        if payload.is_symlink() or not payload.is_file() or not _contained(root, payload):
            raise _fail("MISSING_PAYLOAD")
        try:
            size = payload.stat().st_size
            digest = _sha256(payload)
        except OSError:
            raise _fail("MISSING_PAYLOAD") from None
        if size != entry["size"]:
            raise _fail("CHECKSUM_MISMATCH")
        if digest != entry["sha256"]:
            raise _fail("CHECKSUM_MISMATCH")
    _validate_memory_file(root / "canonical/memory/events-v1.jsonl")
    config = root / "configuration/config.json"
    if not config.is_file():
        raise _fail("MISSING_PAYLOAD")
    config_value = _load_json_bytes(config.read_bytes(), "INVALID_MANIFEST")
    if (
        config_value.get("schema_version") != 1
        or config_value.get("version") != manifest["zero_mem_version"]
        or config_value.get("capture_mode") != "observation_only"
        or config_value.get("canonical_memory_root") != "data/memory"
        or config_value.get("derived_store") != "data/derived/memory.sqlite3"
        or config_value.get("capture_stream") != "data/memory/traces/events-v1.jsonl"
        or set(config_value) != {
            "schema_version", "version", "capture_mode", "canonical_memory_root", "derived_store", "capture_stream"
        }
    ):
        raise _fail("INVALID_MANIFEST")
    corpus_root = root / "canonical/corpus"
    if manifest["_has_corpus"]:
        _validate_corpus_root(corpus_root)
    hermes = root / "configuration/hermes-integration.json"
    if hermes.exists():
        try:
            IntegrationConfig.from_dict(_load_json_bytes(hermes.read_bytes(), "INVALID_MANIFEST"))
        except Exception:
            raise _fail("INVALID_MANIFEST") from None
    return {
        "status": "VALID",
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "files": len(files),
        "has_corpus": bool(manifest["_has_corpus"]),
    }


def _backup_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"zero-mem-backup-{stamp}-{uuid.uuid4().hex[:8]}"


def create_backup(output: Path | None = None) -> Path:
    """Snapshot authoritative sources into a staged, finalized backup directory."""
    load_config()
    source_data = _safe_target(data_root(), "UNSAFE_PATH")
    source_memory = memory_stream()
    if not source_memory.is_file() or source_memory.is_symlink():
        raise _fail("MISSING_PAYLOAD")
    output_path = Path(output).expanduser() if output is not None else cache_root() / BACKUP_DIRNAME / _backup_name()
    if not output_path.is_absolute():
        raise _fail("UNSAFE_PATH")
    output_path = output_path.resolve()
    if _contained(source_data, output_path):
        raise _fail("BACKUP_CREATE_FAILED")
    if output_path.exists() or output_path.is_symlink():
        raise _fail("BACKUP_CREATE_FAILED")
    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if parent.is_symlink():
        raise _fail("UNSAFE_PATH")
    staging = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.", suffix=".partial", dir=str(parent)))
    try:
        (staging / "canonical/memory").mkdir(parents=True, mode=0o700)
        (staging / "configuration").mkdir(parents=True, mode=0o700)
        files: list[dict[str, Any]] = []
        files.append(_copy_payload(source_memory, staging, "canonical/memory/events-v1.jsonl", "canonical"))
        _validate_memory_file(staging / "canonical/memory/events-v1.jsonl")
        _atomic_bytes(staging / "configuration/config.json", _configuration_payload())
        files.append({
            "category": "configuration",
            "path": "configuration/config.json",
            "size": (staging / "configuration/config.json").stat().st_size,
            "sha256": _sha256(staging / "configuration/config.json"),
        })

        integration = config_root() / "hermes-integration.json"
        if integration.exists():
            if integration.is_symlink() or not integration.is_file():
                raise _fail("UNSAFE_PATH")
            try:
                IntegrationConfig.from_dict(json.loads(integration.read_text(encoding="utf-8")))
            except Exception:
                raise _fail("INVALID_MANIFEST") from None
            files.append(_copy_payload(integration, staging, "configuration/hermes-integration.json", "configuration"))

        corpus_root_value = os.environ.get("ZERO_MEM_CORPUS_ROOT")
        if corpus_root_value:
            corpus_root = _safe_target(Path(corpus_root_value), "UNSAFE_PATH")
            if not corpus_root.is_dir() or corpus_root.is_symlink():
                raise _fail("MISSING_PAYLOAD")
            corpus_destination = staging / "canonical/corpus"
            for source, relative in _iter_regular_files(corpus_root):
                if relative.endswith(".part") or relative.endswith(".tmp"):
                    continue
                files.append(_copy_entry(source, staging, "canonical/corpus/" + relative, "canonical"))
            if not any(item["path"] == "canonical/corpus/" + REGISTRY_FILENAME for item in files):
                raise _fail("MISSING_PAYLOAD")

        manifest = {
            "backup_format_version": BACKUP_FORMAT_VERSION,
            "zero_mem_version": __version__,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "files": sorted(files, key=lambda item: item["path"]),
        }
        _atomic_bytes(
            staging / MANIFEST_NAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        verify_backup(staging)
        os.replace(staging, output_path)
        _fsync_directory(parent)
        return output_path
    except BackupError:
        raise
    except Exception:
        raise _fail("BACKUP_CREATE_FAILED") from None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


@contextmanager
def _temporary_environment(values: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _write_target_runtime_config(target: Path) -> None:
    with _temporary_environment({"ZERO_MEM_DATA_ROOT": str(target)}):
        payload = (json.dumps(expected_config(), indent=2, sort_keys=True) + "\n").encode("utf-8")
        _atomic_bytes(config_path(), payload)


def _restore_configuration(root: Path, manifest: dict[str, Any]) -> None:
    _write_target_runtime_config(root)
    target_integration = config_root() / "hermes-integration.json"
    source_integration = root / "configuration/hermes-integration.json"
    if source_integration.exists():
        _atomic_bytes(target_integration, source_integration.read_bytes())
    elif target_integration.exists():
        if target_integration.is_symlink():
            raise _fail("UNSAFE_PATH")
        target_integration.unlink()


def _snapshot_config() -> dict[str, bytes | None]:
    values: dict[str, bytes | None] = {}
    for path in (config_path(), config_root() / "hermes-integration.json"):
        if path.exists():
            if path.is_symlink() or not path.is_file():
                raise _fail("UNSAFE_PATH")
            try:
                values[str(path)] = path.read_bytes()
            except OSError:
                raise _fail("RESTORE_FAILED") from None
        else:
            values[str(path)] = None
    return values


def _restore_config_snapshot(snapshot: dict[str, bytes | None]) -> None:
    for name, payload in snapshot.items():
        path = Path(name)
        if payload is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        else:
            _atomic_bytes(path, payload)


def _rebuild_staged_derived(stage_root: Path, corpus_stage: Path | None) -> None:
    staged_db = stage_root / "data/derived/memory.sqlite3"
    staged_stream = stage_root / "data/memory/traces/events-v1.jsonl"
    staged_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    store = SQLiteStore(SQLiteStoreConfig(path=staged_db))
    try:
        conn = store._conn
        if conn is None:
            raise _fail("REBUILD_FAILED")
        store.ensure_schema()
        rebuild_from_jsonl(store, staged_stream)
        rebuild_all_project_memory(store, staged_stream)
        rebuild_policy_state(conn, staged_stream)
        if corpus_stage is not None:
            from src.corpus.registry import CorpusSourceRegistry
            registry = CorpusSourceRegistry(root=corpus_stage)
            rebuild_from_corpus(conn, registry)
        latest = conn.execute("SELECT MAX(created_at) FROM zm_meta").fetchone()[0]
        if latest:
            rebuild_graph(conn, version="1", built_at=latest, source_cutoff=latest)
            project_temporal_index(conn, source_cutoff=latest, built_at=latest)
        conn.commit()
    except Exception:
        raise _fail("REBUILD_FAILED") from None
    finally:
        store.close()


def restore_backup(
    backup: Path,
    *,
    yes: bool = False,
    target_data_root: Path | None = None,
    target_corpus_root: Path | None = None,
) -> dict[str, Any]:
    """Verify, stage, rebuild, doctor, then safely promote a backup."""
    if not yes:
        raise _fail("CONFIRMATION_REQUIRED")
    root = _safe_target(Path(backup), "UNSAFE_PATH")
    verification = verify_backup(root)
    target = _safe_target(target_data_root or data_root(), "UNSAFE_PATH")
    manifest = _load_json_bytes((root / MANIFEST_NAME).read_bytes(), "INVALID_MANIFEST")
    manifest = _validate_manifest(manifest)
    corpus_target: Path | None = None
    if manifest["_has_corpus"]:
        if target_corpus_root is None:
            raise _fail("CORPUS_TARGET_REQUIRED")
        corpus_target = _safe_target(Path(target_corpus_root), "UNSAFE_PATH")
        if _contained(target, corpus_target) or _contained(corpus_target, target):
            raise _fail("UNSAFE_PATH")

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise _fail("UNSAFE_PATH")
    if corpus_target is not None:
        corpus_target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if corpus_target.exists() and (corpus_target.is_symlink() or not corpus_target.is_dir()):
            raise _fail("UNSAFE_PATH")
    config_snapshot = _snapshot_config()
    staging = Path(tempfile.mkdtemp(prefix=".zero-mem-restore-", suffix=".partial", dir=str(target.parent)))
    corpus_staging: Path | None = None
    rollback: Path | None = None
    corpus_rollback: Path | None = None
    activated = False
    try:
        (staging / "data/memory/traces").mkdir(parents=True, mode=0o700)
        for entry in manifest["files"]:
            relative = entry["path"]
            source = root / relative
            if relative.startswith("canonical/memory/"):
                destination = staging / "data/memory/traces" / relative[len("canonical/memory/") :]
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(source, destination)
                if os.name != "nt":
                    os.chmod(destination, 0o600)
            elif relative.startswith("canonical/corpus/"):
                if corpus_staging is None:
                    corpus_staging = Path(tempfile.mkdtemp(prefix=".zero-mem-corpus-", suffix=".partial", dir=str(target.parent)))
                destination = corpus_staging / relative[len("canonical/corpus/") :]
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(source, destination)
                if os.name != "nt":
                    os.chmod(destination, 0o600)
        _validate_memory_file(staging / "data/memory/traces/events-v1.jsonl")
        if corpus_staging is not None:
            _validate_corpus_root(corpus_staging)
        _rebuild_staged_derived(staging, corpus_staging)
        config_home = staging / "config-home"
        with _temporary_environment({
            "ZERO_MEM_DATA_ROOT": str(staging),
            "XDG_CONFIG_HOME": str(config_home),
            "ZERO_MEM_CORPUS_ROOT": str(corpus_staging) if corpus_staging is not None else None,
        }):
            write_config()
            from .commands_doctor import collect
            report = collect()
            if report["overall"] != "READY":
                raise _fail("DOCTOR_FAILED")
        shutil.rmtree(config_home, ignore_errors=True)

        if target.exists():
            rollback = target.with_name(f".{target.name}.rollback-{uuid.uuid4().hex[:8]}")
            os.replace(target, rollback)
        os.replace(staging, target)
        activated = True
        if corpus_staging is not None and corpus_target is not None:
            if corpus_target.exists():
                corpus_rollback = corpus_target.with_name(f".{corpus_target.name}.rollback-{uuid.uuid4().hex[:8]}")
                os.replace(corpus_target, corpus_rollback)
            os.replace(corpus_staging, corpus_target)
        _restore_configuration(target, manifest)
        if rollback is not None:
            shutil.rmtree(rollback, ignore_errors=True)
        if corpus_rollback is not None:
            shutil.rmtree(corpus_rollback, ignore_errors=True)
        return {"status": "SUCCESS", "verification": verification, "data_root": str(target)}
    except BackupError:
        if activated:
            try:
                if target.exists():
                    shutil.rmtree(target)
                if rollback is not None and rollback.exists():
                    os.replace(rollback, target)
                if corpus_target is not None and corpus_rollback is not None and corpus_rollback.exists():
                    if corpus_target.exists():
                        shutil.rmtree(corpus_target)
                    os.replace(corpus_rollback, corpus_target)
                _restore_config_snapshot(config_snapshot)
            except Exception:
                raise _fail("ROLLBACK_FAILED") from None
        raise
    except Exception:
        if activated:
            try:
                if target.exists():
                    shutil.rmtree(target)
                if rollback is not None and rollback.exists():
                    os.replace(rollback, target)
                if corpus_target is not None and corpus_rollback is not None and corpus_rollback.exists():
                    if corpus_target.exists():
                        shutil.rmtree(corpus_target)
                    os.replace(corpus_rollback, corpus_target)
                _restore_config_snapshot(config_snapshot)
            except Exception:
                raise _fail("ROLLBACK_FAILED") from None
        raise _fail("RESTORE_FAILED") from None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if corpus_staging is not None and corpus_staging.exists():
            shutil.rmtree(corpus_staging, ignore_errors=True)
        if rollback is not None and rollback.exists():
            shutil.rmtree(rollback, ignore_errors=True)
        if corpus_rollback is not None and corpus_rollback.exists():
            shutil.rmtree(corpus_rollback, ignore_errors=True)


__all__ = [
    "BACKUP_FORMAT_VERSION",
    "BackupError",
    "create_backup",
    "verify_backup",
    "restore_backup",
]
