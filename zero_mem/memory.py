"""Shared-memory library: one local, zero-LLM memory for many agents on the Hermes authorization pipeline.

``Memory.open(profile_id)`` pins ONE profile; every operation runs as that profile and no method accepts another.
Everything (persona, workflow, skill, devlog, fact, ingested files) is a corpus source typed by
``external_ref="mem://<type>/<id>"`` (files: ``file://<name>``) and ``custom_meta.memory_type``.

Every write follows one path:

    closed-schema validation + byte caps
      -> ``authorize_write`` (private = own profile; shared = WRITE grant on ks-shared; devlog/project = WRITE grant
         on the project)                                              [audited through ``src.access.audit``]
      -> secret pre-scan of the bytes AND of the extracted text BEFORE anything is registered (reject, never store)
      -> ``corpus_write_lock`` -> ``register_source_with_blob`` (lifecycle ``observed``, provenance channel)
      -> ``project_source`` -> commit

Reads go through ``AuthorizedReadService.corpus_unit_search`` only: ``recall`` merges the implicit request (own
rows) with the ``ks-shared`` request (design section 3), deduplicates and returns typed hits. ``forget`` appends a
lifecycle ``deleted`` tombstone version (DEF-057): excluded from retrieval and projection, raw blobs kept.

Zero runtime dependencies, no network, no LLM. Nothing here raises for a denied / rejected / invalid request:
see :mod:`zero_mem.memory_results`.
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Union
from urllib.parse import quote

from .memory_layout import Layout, LayoutError
from .memory_results import (
    ContextBundle,
    ForgetResult,
    IngestReport,
    RecallHit,
    RecallResult,
    WriteResult,
    build_ingest_report,
)
from .provisioning import (
    SHARED_SPACE,
    OperatorApprovalLookup,
    append_canonical_event,
    valid_id,
)

MEMORY_TYPES = ("persona", "workflow", "skill", "devlog", "fact", "file")
SCOPES = ("shared", "private", "project")
#: Text kinds ``add`` may store (structure comes from the markdown/plain adapters).
TEXT_KINDS = ("txt", "md")
_DEFAULT_KIND = {"persona": "md", "workflow": "md", "skill": "md"}

MAX_TEXT_BYTES = 256 * 1024
MAX_INGEST_BYTES = 16 * 1024 * 1024
MAX_NAME_CHARS = 128
MAX_REF_NAME_CHARS = 400
MAX_QUERY_CHARS = 1000
MAX_RECALL_LIMIT = 200
MAX_CONTEXT_CHARS = 200_000
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024

# One or more "/"-separated segments of ref-safe characters; "." and ".." segments are never allowed.
_SEGMENT = r"[A-Za-z0-9._:~+@%-]+"
_NAME_RE = re.compile(rf"^(?!(?:.*/)?\.{{1,2}}(?:/|$)){_SEGMENT}(?:/{_SEGMENT})*$")
_DEVLOG_REF_RE = re.compile(r"^mem://devlog/([^/]+)/(\d{4}-\d{2}-\d{2})(?:/|$)")
_WORD_RE = re.compile(r"[^\W_]", re.UNICODE)  # alphanumeric: "_" is a separator for the retriever
_WORDS_RE = re.compile(r"\w+", re.UNICODE)
#: Function words dropped from natural-language questions before retrieval (never when nothing else is left).
_STOPWORDS = frozenset(
    "a an and are as at be but by did do does for from had has have how i if in is it its me my of on or our "
    "so than that the their them then there these they this to us was we were what when where which who whom "
    "why will with would you your".split()
)
_PROVENANCE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_PROVENANCE_KEYS = 8
MAX_PROVENANCE_VALUE_CHARS = 200

_SCOPE_FIELDS = {  # scope -> (uses project, uses shared space)
    "private": (False, False),
    "shared": (False, True),
    "project": (True, False),
}
_CONTEXT_SECTIONS = (  # (title, memory_type, share of the budget)
    ("Persona", "persona", 0.35),
    ("Workflow", "workflow", 0.25),
    ("Skills", "skill", 0.20),
    ("Recent devlog", "devlog", 0.20),
)


class MemoryConfigError(ValueError):
    """``Memory.open`` could not set up or validate the storage layout / profile."""


class _Invalid(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _scope_of(profile_id: Optional[str], project_id: Optional[str], space: Optional[str], shared_space: str) -> str:
    if space == shared_space:
        return "shared"
    if project_id is not None:
        return "project"
    if profile_id is None and space is None:
        return "global"
    return "private"


def _file_identity(path: Path) -> Optional[tuple]:
    """``(device, inode)`` of ``path`` (None when it does not exist): changes when the file is replaced."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return info.st_dev, info.st_ino


def _clip(text: str, limit: int) -> str:
    """Cut ``text`` to at most ``limit`` chars at a word boundary, marking the cut with an ellipsis."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space >= (limit - 1) // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


class Memory:
    """One agent's pinned view of the shared memory. Use :meth:`open`; close with :meth:`close` / ``with``."""

    SHARED_SPACE = SHARED_SPACE

    def __init__(
        self,
        profile_id: str,
        layout: Layout,
        *,
        channel: str = "library",
        clock: Optional[Callable[[], datetime]] = None,
        shared_space: str = SHARED_SPACE,
    ) -> None:
        self._profile = profile_id
        self._layout = layout
        self._channel = channel
        self._clock = clock
        self._shared = shared_space
        self._lock = threading.RLock()
        self._store = None
        self._registry = None
        self._blobs = None
        self._lookup = OperatorApprovalLookup(layout.memory_stream)
        self._closed = False
        # Read side (T7): one read-only connection reused by recall/context while the database file is the same
        # (opening it fingerprints the whole file twice, which grows with the store); serialized by its own lock.
        self._ro = None
        self._ro_ident: Optional[tuple] = None
        self._read_lock = threading.RLock()

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def open(
        cls,
        profile_id: str,
        data_root: Optional[Union[str, Path]] = None,
        *,
        corpus_root: Optional[Union[str, Path]] = None,
        channel: str = "library",
        clock: Optional[Callable[[], datetime]] = None,
        setup: bool = True,
    ) -> "Memory":
        """Open the memory as ``profile_id``, ensuring first-run setup (private dirs, schema, corpus root).

        ``data_root=None`` uses the standard location (``ZERO_MEM_DATA_ROOT`` / XDG) and the exact setup
        ``zero-mem setup`` performs; an explicit absolute ``data_root`` gives an isolated store.
        """
        if not valid_id(profile_id):
            raise MemoryConfigError("profile_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
        if not isinstance(channel, str) or not valid_id(channel):
            raise MemoryConfigError("channel must be a short identifier")
        try:
            layout = Layout.resolve(data_root, corpus_root)
            if setup:
                layout.ensure()
        except LayoutError as exc:
            raise MemoryConfigError(str(exc)) from None
        return cls(profile_id, layout, channel=channel, clock=clock)

    @property
    def profile_id(self) -> str:
        return self._profile

    @property
    def shared_space(self) -> str:
        return self._shared

    @property
    def layout(self) -> Layout:
        return self._layout

    def close(self) -> None:
        with self._lock:
            if self._store is not None:
                self._store.close()
                self._store = None
            self._registry = None
            self._blobs = None
            self._closed = True
        with self._read_lock:
            self._drop_readonly()

    def __enter__(self) -> "Memory":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ plumbing
    def _now(self) -> datetime:
        return (self._clock() if self._clock else datetime.now(timezone.utc)).astimezone(timezone.utc)

    def _conn(self):
        """Lazy writer connection to the derived store (schema ensured once)."""
        if self._store is None:
            from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig

            store = SQLiteStore(SQLiteStoreConfig(path=self._layout.derived_db))
            store.ensure_schema()
            self._store = store
            self._closed = False
        return self._store._conn

    def _corpus(self):
        if self._registry is None:
            from src.corpus.blob_store import CorpusBlobStore
            from src.corpus.registry import CorpusSourceRegistry

            self._registry = CorpusSourceRegistry(root=self._layout.corpus_root)
            self._blobs = CorpusBlobStore(root=self._layout.corpus_root)
        return self._registry, self._blobs

    def _append_event(self, event: dict) -> None:
        append_canonical_event(self._layout.memory_stream, event)

    # ------------------------------------------------------------------ validation
    @staticmethod
    def _clean_text(text: Any) -> str:
        if not isinstance(text, str):
            raise _Invalid("invalid_text")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise _Invalid("invalid_text") from None
        if "\x00" in text:
            raise _Invalid("invalid_text")
        clean = unicodedata.normalize("NFC", text.strip())
        if not clean:
            raise _Invalid("invalid_text")
        if len(clean.encode("utf-8")) > MAX_TEXT_BYTES:
            raise _Invalid("text_too_large")
        return clean

    @staticmethod
    def _check_provenance(provenance: Any) -> dict:
        """Closed caller provenance: <= 8 short scalar fields. Never part of the source identity."""
        if provenance is None:
            return {}
        if not isinstance(provenance, dict) or len(provenance) > MAX_PROVENANCE_KEYS:
            raise _Invalid("invalid_provenance")
        for key, value in provenance.items():
            if not isinstance(key, str) or not _PROVENANCE_KEY_RE.fullmatch(key):
                raise _Invalid("invalid_provenance")
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                raise _Invalid("invalid_provenance")
            if isinstance(value, str) and len(value) > MAX_PROVENANCE_VALUE_CHARS:
                raise _Invalid("invalid_provenance")
            if isinstance(value, int) and abs(value) > 2 ** 53:
                raise _Invalid("invalid_provenance")
        return dict(provenance)

    @staticmethod
    def _check_name(name: Any, limit: int = MAX_NAME_CHARS) -> Optional[str]:
        if name is None:
            return None
        if not isinstance(name, str) or not name or len(name) > limit or not _NAME_RE.fullmatch(name):
            raise _Invalid("invalid_name")
        return name

    @staticmethod
    def _check_target(memory_type: Any, scope: Any, project_id: Any) -> tuple[str, str, Optional[str]]:
        if not isinstance(memory_type, str) or memory_type not in MEMORY_TYPES:
            raise _Invalid("invalid_memory_type")
        if scope is not None and (not isinstance(scope, str) or scope not in SCOPES):
            raise _Invalid("invalid_scope")
        if memory_type == "devlog":
            if scope not in (None, "project"):
                raise _Invalid("devlog_requires_project_scope")
            scope = "project"
        elif scope is None:
            scope = "private"
        if scope == "project":
            if project_id is None:
                raise _Invalid("project_id_required")
            if not valid_id(project_id):
                raise _Invalid("invalid_project_id")
        elif project_id is not None:
            raise _Invalid("project_id_not_allowed")
        return memory_type, scope, project_id

    def _scope_fields(self, scope: str, project_id: Optional[str]) -> dict:
        return {
            "profile_id": self._profile,
            "project_id": project_id if scope == "project" else None,
            "knowledge_space_id": self._shared if scope == "shared" else None,
        }

    # ------------------------------------------------------------------ authorization
    def _write_request(self, scope: str, project_id: Optional[str]):
        from src.access import AccessRequest

        base = dict(operation="WRITE", requesting_profile_id=self._profile, resource_type="corpus_source")
        if scope == "private":
            return AccessRequest(**base, target_profile_ids=[self._profile])
        if scope == "shared":
            return AccessRequest(**base, knowledge_space_ids=[self._shared])
        return AccessRequest(**base, project_ids=[project_id])

    def _authorize(self, scope: str, project_id: Optional[str]):
        """``authorize_write`` for the whole call, audited (DENY and grant-using ALLOW only, per audit.py)."""
        from src.access.audit import project_policy_decision, record_decision
        from src.access.authorized_write import authorize_write

        conn = self._conn()
        decision = authorize_write(self._write_request(scope, project_id), conn, self._lookup)
        target = f"knowledge_space:{self._shared}" if scope == "shared" else (
            f"project:{project_id}" if scope == "project" else f"profile:{self._profile}")
        try:
            event = record_decision(
                self._append_event, decision, decision_id=f"pd-{uuid.uuid4().hex[:16]}",
                requester=self._profile, target_scope=target, profile_id=self._profile,
                created_at=self._now().strftime("%Y-%m-%dT%H:%M:%SZ"))
            if event is not None:
                project_policy_decision(conn, event)
                conn.commit()
        except Exception:  # audit is best-effort (audit.py contract) and never decides the write
            pass
        return decision

    # ------------------------------------------------------------------ pre-register scan
    def _preflight(self, content: bytes, kind: str, scan_names: Sequence[str]):
        """Return ``(status, reason, rule_ids)`` when the content must NOT be stored, else ``None``."""
        from src.corpus.adapters.registry import select_adapter
        from src.corpus.extract import ExtractionStatus
        from src.corpus.normalize import normalize_extraction
        from src.corpus.redact import scan_extracted_text
        from src.redaction.prescan import looks_like_zip, scan_bytes, scan_text, scan_zip_members

        for text in scan_names:
            verdict = scan_text(text)
            if not verdict.safe:
                return "rejected_secret", "secret_detected", tuple(verdict.rule_ids)
        verdict = scan_bytes(content)
        if not verdict.safe:
            return "rejected_secret", "secret_detected", tuple(verdict.rule_ids)
        if looks_like_zip(content):  # every member (customXml, comments, embeddings, nested zips), not just extracted units
            verdict = scan_zip_members(content)
            if not verdict.safe:
                return "rejected_secret", verdict.reason or "secret_detected", tuple(verdict.rule_ids)
        adapter = select_adapter(kind)
        if adapter is None:
            return "rejected_content", "unsupported_format", ()
        if not adapter.is_available():
            return "rejected_content", "parser_unavailable", ()
        try:
            result = adapter.extract(source_ref="preflight", content=content, kind_hint=kind)
            status = ExtractionStatus.validate(result.status)
        except Exception:
            return "rejected_content", "adapter_failed", ()
        if not status.is_success:
            return "rejected_content", status.value, ()
        normalized = normalize_extraction(result)
        if not normalized.ok:
            return "rejected_content", "empty_source", ()
        for unit in normalized.units:  # compressed containers (docx/xlsx/pptx) are only visible here
            outcome = scan_extracted_text(unit.normalized_text)
            if not outcome.safe:
                return "rejected_secret", "secret_detected", tuple(outcome.rule_ids)
        return None

    # ------------------------------------------------------------------ the write path
    def _external_ref(self, memory_type: str, name: Optional[str], project_id: Optional[str], digest: str) -> str:
        if memory_type == "file":
            return f"file://{name or 'text-' + digest[:12]}"
        if memory_type == "devlog":
            if name:
                return f"mem://devlog/{project_id}/{name}"
            return f"mem://devlog/{project_id}/{self._now().strftime('%Y-%m-%d')}/{digest[:8]}"
        return f"mem://{memory_type}/{name or digest[:12]}"

    def _write_one(
        self,
        *,
        content: bytes,
        kind: str,
        memory_type: str,
        scope: str,
        project_id: Optional[str],
        ref_name: Optional[str],
        display_name: Optional[str] = None,
        provenance: Optional[dict] = None,
    ) -> WriteResult:
        """Preflight -> lock -> register -> project -> commit for ONE already-authorized source."""
        fields = self._scope_fields(scope, project_id)
        digest = _sha256(content)
        external_ref = self._external_ref(memory_type, ref_name, project_id, digest)
        base = dict(name=display_name, external_ref=external_ref, memory_type=memory_type, scope=scope, **fields)
        if len(external_ref) > 512:
            return WriteResult(status="invalid", reason="name_too_long", **base)
        scanned = [external_ref] + [v for v in (provenance or {}).values() if isinstance(v, str)]
        blocked = self._preflight(content, kind, scanned)
        if blocked is not None:
            status, reason, rule_ids = blocked
            return WriteResult(status=status, reason=reason, rule_ids=rule_ids, **base)
        try:
            return self._commit_source(content, kind, memory_type, external_ref, fields, provenance or {}, base)
        except Exception as exc:
            reason = "write_lock_timeout" if "write_lock_timeout" in str(exc) or "LOCK_TIMEOUT" in repr(exc) \
                else f"internal_error:{type(exc).__name__}"
            return WriteResult(status="error", reason=reason, **base)

    def _commit_source(self, content, kind, memory_type, external_ref, fields, provenance, base) -> WriteResult:
        from src.corpus.derived_store import project_source, source_status
        from src.corpus.identity import derive_source_id, source_descriptor
        from src.corpus.registry import corpus_write_lock

        meta = {"memory_type": memory_type}
        prov = {**provenance, "channel": self._channel, "writer": "zero_mem.memory", "profile": self._profile}
        with self._lock:
            registry, blobs = self._corpus()
            conn = self._conn()
            with corpus_write_lock(self._layout.corpus_root):
                registry.refresh()
                sid = derive_source_id(None, source_descriptor(
                    external_ref=external_ref, kind=kind, custom_meta=meta, **fields))
                previous = registry.get_by_source_id(sid)
                record = registry.register_source_with_blob(
                    content=content, external_ref=external_ref, kind=kind, sensitivity="internal",
                    lifecycle_status="observed", custom_meta=meta, provenance=prov, blob_store=blobs, **fields)
                if previous is not None and record.content_hash == previous.content_hash \
                        and record.source_version_id == previous.source_version_id \
                        and previous.lifecycle_status != "deleted":
                    status = "unchanged"
                elif previous is None or previous.lifecycle_status == "deleted":
                    status = "created"
                else:
                    status = "updated"
                base = {**base, "source_id": record.source_id, "version": record.source_version_id}
                row = conn.execute(
                    "SELECT content_hash, lifecycle_status FROM zm_corpus_sources WHERE source_id=?",
                    (record.source_id,)).fetchone()
                projected = row is not None and row[0] == record.content_hash and row[1] == record.lifecycle_status
                if status == "unchanged" and projected:
                    state = source_status(conn, record.source_id)
                else:
                    try:
                        report = project_source(conn, registry, record, blob_store=blobs)
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        return WriteResult(status="error", reason="projection_failed", **base)
                    state = report.source_statuses[0] if report.source_statuses else {}
        return WriteResult(status=status, units=state.get("units"), extraction=state.get("status"), **base)

    # ------------------------------------------------------------------ public: add
    def add(
        self,
        text: str,
        memory_type: str = "fact",
        name: Optional[str] = None,
        scope: Optional[str] = None,
        project_id: Optional[str] = None,
        *,
        kind: Optional[str] = None,
        provenance: Optional[dict] = None,
    ) -> WriteResult:
        """Remember ``text`` as ``memory_type`` in ``scope`` (default private; devlog is always project).

        ``name`` makes the source versionable by name (``mem://<type>/<name>``): adding again with other text is
        a new version. Without a name the id is the content hash (immutable; identical text is a no-op).
        ``provenance`` adds up to 8 short scalar fields (e.g. ``{"imported_from": "notes-v1"}``) to the registry's
        provenance; it is scanned for secrets, is never part of the source identity and cannot override the pinned
        ``channel`` / ``profile`` / ``writer`` / ``tool`` fields.
        """
        invalid_base = {"memory_type": memory_type if isinstance(memory_type, str) else None}
        try:
            memory_type, scope, project_id = self._check_target(memory_type, scope, project_id)
            name = self._check_name(name)
            if kind is not None and kind not in TEXT_KINDS:
                raise _Invalid("invalid_kind")
            extra = self._check_provenance(provenance)
            clean = self._clean_text(text)
        except _Invalid as exc:
            return WriteResult(status="invalid", reason=exc.reason, **invalid_base)
        try:
            with self._lock:
                decision = self._authorize(scope, project_id)
            base = dict(memory_type=memory_type, scope=scope, **self._scope_fields(scope, project_id))
            if not decision.allow:
                return WriteResult(status="denied", reason=decision.reason_code, **base)
            content = clean.encode("utf-8")
            return self._write_one(
                content=content, kind=kind or _DEFAULT_KIND.get(memory_type, "txt"), memory_type=memory_type,
                scope=scope, project_id=project_id, ref_name=name,
                provenance={**extra, "tool": "add"})
        except Exception as exc:
            return WriteResult(status="error", reason=f"internal_error:{type(exc).__name__}", **invalid_base)

    # ------------------------------------------------------------------ public: ingest
    def ingest(
        self,
        source: Union[bytes, bytearray, str, "os.PathLike[str]"],
        filename: Optional[str] = None,
        memory_type: str = "fact",
        scope: Optional[str] = None,
        project_id: Optional[str] = None,
        *,
        name: Optional[str] = None,
        allow_roots: Optional[Sequence[Union[str, Path]]] = None,
        max_files: Optional[int] = None,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> IngestReport:
        """Ingest a file, a directory (recursively) or raw ``bytes`` (needs ``filename`` for the format).

        One authorization decision covers the whole call. Unchanged files are no-ops, changed files become new
        versions, files with a credential / unreadable content are rejected and listed (never stored), and every
        skipped path is reported with its reason.
        """
        from src.corpus.detect_kind import DEFAULT_MAX_FILES, IngestPathError, detect_kind, iter_ingestable

        try:
            memory_type, scope, project_id = self._check_target(memory_type, scope, project_id)
            prefix = self._check_name(name, MAX_REF_NAME_CHARS)
            if isinstance(source, (bytes, bytearray)):
                is_bytes = True
            elif isinstance(source, (str, os.PathLike)):
                is_bytes = False
            else:
                raise _Invalid("invalid_source")
            if not isinstance(max_total_bytes, int) or isinstance(max_total_bytes, bool) or max_total_bytes < 1:
                raise _Invalid("invalid_max_total_bytes")
            if max_files is not None and (not isinstance(max_files, int) or isinstance(max_files, bool) or max_files < 1):
                raise _Invalid("invalid_max_files")
            if is_bytes:
                filename = self._check_filename(filename)
        except _Invalid as exc:
            return self._report("invalid", exc.reason, [], [])
        try:
            with self._lock:
                decision = self._authorize(scope, project_id)
            if not decision.allow:
                return self._report("denied", decision.reason_code, [], [])
            results: list[WriteResult] = []
            skipped: list[dict] = []
            if is_bytes:
                data = bytes(source)
                if len(data) > MAX_INGEST_BYTES:
                    results.append(WriteResult(status="rejected_content", reason="content_too_large",
                                               name=filename, memory_type=memory_type, scope=scope))
                else:
                    ref = prefix or (self._encode_name(filename) if filename else "blob-" + _sha256(data)[:12])
                    kind = detect_kind(filename, data)
                    results.append(self._ingest_one(
                        data, kind, memory_type, scope, project_id, ref, filename or ref, {"tool": "ingest"}))
                return self._report(None, None, results, skipped)
            root = Path(source)
            try:
                walk = iter_ingestable(
                    root, allow_roots=allow_roots, max_bytes=MAX_INGEST_BYTES,
                    max_files=max_files or DEFAULT_MAX_FILES)
            except IngestPathError as exc:
                return self._report("invalid", str(exc) or "invalid_path", [], [])
            is_dir = root.is_dir() and not root.is_symlink()
            base_name = prefix or (self._encode_name(root.resolve().name or "root") if is_dir else None)
            total = 0
            for item in walk:
                rel, _path, kind = item
                try:
                    data = item.read_bytes()
                except Exception as exc:
                    skipped.append({"name": rel, "reason": getattr(exc, "reason", "unreadable")})
                    continue
                total += len(data)
                if total > max_total_bytes:
                    skipped.append({"name": rel, "reason": "max_total_bytes_reached"})
                    break
                encoded = self._encode_name(rel)
                if is_dir:
                    ref = f"{base_name}/{encoded}"
                else:
                    ref = prefix or encoded
                results.append(self._ingest_one(
                    data, kind, memory_type, scope, project_id, ref, rel,
                    {"tool": "ingest", "original_name": rel}))
            skipped = [{"name": s.relative_name, "reason": s.reason} for s in walk.skipped] + skipped
            return self._report(None, None, results, skipped)
        except Exception as exc:
            return self._report("error", f"internal_error:{type(exc).__name__}", [], [])

    def _ingest_one(self, data, kind, memory_type, scope, project_id, ref, display, provenance) -> WriteResult:
        if len(ref) > MAX_REF_NAME_CHARS or not _NAME_RE.fullmatch(ref):
            return WriteResult(status="invalid", reason="name_too_long" if len(ref) > MAX_REF_NAME_CHARS else "invalid_name",
                               name=display, memory_type=memory_type, scope=scope)
        return self._write_one(
            content=data, kind=kind, memory_type=memory_type, scope=scope, project_id=project_id,
            ref_name=ref, display_name=display, provenance={**provenance, "size": len(data)})

    @staticmethod
    def _check_filename(filename: Any) -> Optional[str]:
        if filename is None:
            return None
        if not isinstance(filename, str) or not filename or len(filename) > 255 \
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in filename):
            raise _Invalid("invalid_filename")
        base = posixpath.basename(filename.replace("\\", "/"))
        if base in ("", ".", ".."):
            raise _Invalid("invalid_filename")
        return base

    @staticmethod
    def _encode_name(relative: str) -> str:
        """Reversible, collision-free ref segment(s): NFC + percent-encoding of everything outside the ref alphabet."""
        text = unicodedata.normalize("NFC", relative.replace("\\", "/"))
        return quote(text, safe="/:+@~._-")

    @staticmethod
    def _report(status: Optional[str], reason: Optional[str], results: list, skipped: list) -> IngestReport:
        return build_ingest_report(status, reason, results, skipped)

    # ------------------------------------------------------------------ reads: shared plumbing
    def _drop_readonly(self) -> None:
        ro, self._ro, self._ro_ident = self._ro, None, None
        if ro is not None:
            ro.close()

    def _readonly(self):
        """The reused read-only connection; reopened when the derived database file was replaced (upgrade, restore)."""
        from src.retrieval.db import open_readonly

        path = self._layout.derived_db
        ident = _file_identity(path)
        if self._ro is not None and ident is not None and ident == self._ro_ident:
            return self._ro
        self._drop_readonly()
        ro = open_readonly(path)
        self._ro, self._ro_ident = ro, _file_identity(path)
        return ro

    def _read_requests(self, include_private: bool, project_id: Optional[str]) -> list:
        from src.access import AccessRequest

        out = []
        if include_private:
            out.append(("private", AccessRequest(
                operation="READ", requesting_profile_id=self._profile, resource_type="corpus_unit")))
        out.append(("shared", AccessRequest(
            operation="READ", requesting_profile_id=self._profile, knowledge_space_ids=[self._shared],
            resource_type="corpus_unit")))
        if project_id is not None:
            out.append(("project", AccessRequest(
                operation="READ", requesting_profile_id=self._profile, project_ids=[project_id],
                resource_type="corpus_unit")))
        return out

    def _search(self, requests: list, text: str, metadata: Optional[dict], limit: int):
        """Run every request through the authorized facade; return ``(hits_by_unit_id, notes, errors)``."""
        from src.access import AuthorizedReadService

        merged: dict[str, Any] = {}
        notes: dict[str, str] = {}
        errors: list[str] = []
        with self._read_lock:
            try:
                ro = self._readonly()
                service = AuthorizedReadService(ro, self._profile, grant_conn=ro.conn)
                for label, request in requests:
                    result = service.corpus_unit_search(request, text, metadata=metadata, limit=limit)
                    notes[label] = result.reason_code
                    if result.denied:
                        continue
                    if result.is_downstream_error:
                        errors.append(f"{label}:{result.error}")
                        continue
                    for hit in result.items:
                        best = merged.get(hit.unit_id)
                        if best is None or hit.combined_score > best.combined_score:
                            merged[hit.unit_id] = hit
            except Exception:
                self._drop_readonly()  # never keep a connection that failed mid-call
                raise
        return merged, notes, errors

    def _to_hit(self, hit) -> RecallHit:
        return RecallHit(
            text=hit.normalized_text, score=round(float(hit.combined_score), 6), external_ref=hit.external_ref,
            memory_type=hit.memory_type, source_id=hit.source_id, unit_id=hit.unit_id, unit_kind=hit.kind,
            scope=_scope_of(hit.profile_id, hit.project_id, hit.knowledge_space_id, self._shared),
            profile_id=hit.profile_id, project_id=hit.project_id, knowledge_space_id=hit.knowledge_space_id,
            page=hit.page)

    # ------------------------------------------------------------------ public: recall
    def recall(
        self,
        query: str,
        memory_types: Optional[Iterable[str]] = None,
        limit: int = 8,
        include_private: bool = True,
        project_id: Optional[str] = None,
    ) -> RecallResult:
        """Ranked authorized hits for ``query`` (own rows + the ks-shared space [+ one project]), deduplicated."""
        try:
            if not isinstance(query, str) or not _WORD_RE.search(query):
                raise _Invalid("empty_query")
            if len(query) > MAX_QUERY_CHARS:
                raise _Invalid("query_too_long")
            if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RECALL_LIMIT:
                raise _Invalid("invalid_limit")
            types = self._check_types(memory_types)
            if project_id is not None and not valid_id(project_id):
                raise _Invalid("invalid_project_id")
            if not isinstance(include_private, bool):
                raise _Invalid("invalid_include_private")
        except _Invalid as exc:
            return RecallResult(status="invalid", reason=exc.reason)
        try:
            metadata = {"memory_type": types[0]} if len(types) == 1 else None
            internal = limit if len(types) <= 1 else min(MAX_RECALL_LIMIT * 2, limit * 5)
            merged, notes, errors = self._search(
                self._read_requests(include_private, project_id), self._search_text(query), metadata, internal)
            if errors and not merged:
                return RecallResult(status="error", reason="retrieval_failed", notes=notes)
            if notes and all(code.startswith("DENY") for code in notes.values()):
                return RecallResult(status="denied", reason=next(iter(notes.values())), notes=notes)
            hits = list(merged.values())
            if len(types) > 1:
                hits = [h for h in hits if h.memory_type in types]
            hits.sort(key=lambda h: (-h.combined_score, h.external_ref or "", h.unit_order, h.unit_id))
            out = [self._to_hit(h) for h in hits[:limit]]
            return RecallResult(status="ok" if out else "empty", hits=out, notes=notes)
        except Exception as exc:
            return RecallResult(status="error", reason=f"internal_error:{type(exc).__name__}")

    @staticmethod
    def _search_text(query: str) -> str:
        """The query without English function words ("what is the name of the cat" -> "name cat").

        Deterministic and local. A query made only of function words is searched as written.
        """
        kept = [w for w in _WORDS_RE.findall(query.lower()) if w not in _STOPWORDS]
        return " ".join(kept) if kept else query.strip()

    @staticmethod
    def _check_types(memory_types: Any) -> list[str]:
        if memory_types is None:
            return []
        if isinstance(memory_types, str):
            memory_types = [memory_types]
        try:
            types = list(dict.fromkeys(memory_types))
        except TypeError:
            raise _Invalid("invalid_memory_types") from None
        if any(not isinstance(t, str) or t not in MEMORY_TYPES for t in types):
            raise _Invalid("invalid_memory_types")
        return types

    # ------------------------------------------------------------------ public: context
    def context(self, max_chars: int = 4000, project_id: Optional[str] = None) -> ContextBundle:
        """Deterministic, token-bounded session-start bundle: persona, workflow, skill descriptions, recent devlog."""
        if not isinstance(max_chars, int) or isinstance(max_chars, bool) or not 1 <= max_chars <= MAX_CONTEXT_CHARS:
            return ContextBundle(status="invalid", reason="invalid_max_chars")
        if project_id is not None and not valid_id(project_id):
            return ContextBundle(status="invalid", reason="invalid_project_id", max_chars=max_chars)
        try:
            requests = self._read_requests(True, project_id)
            items: dict[str, list[tuple[str, list[str]]]] = {}
            for _title, mtype, _share in _CONTEXT_SECTIONS:
                merged, _notes, _errors = self._search(requests, "", {"memory_type": mtype}, _res_limit())
                items[mtype] = self._group_sources(merged.values())
            return self._assemble(items, max_chars)
        except Exception as exc:
            return ContextBundle(status="error", reason=f"internal_error:{type(exc).__name__}", max_chars=max_chars)

    @staticmethod
    def _group_sources(hits: Iterable[Any]) -> list[tuple[str, list[Any]]]:
        by_source: dict[str, list[Any]] = {}
        for hit in hits:
            by_source.setdefault(hit.source_id, []).append(hit)
        groups = []
        for source_hits in by_source.values():
            source_hits.sort(key=lambda h: (h.unit_order, h.unit_id))
            groups.append((source_hits[0].external_ref or "", source_hits))
        groups.sort(key=lambda g: (g[0], g[1][0].source_id))
        return groups

    def _assemble(self, items: dict, max_chars: int) -> ContextBundle:
        lines_by_section: dict[str, list[str]] = {}
        refs_by_section: dict[str, list[str]] = {}
        for title, mtype, _share in _CONTEXT_SECTIONS:
            groups = items.get(mtype, [])
            if mtype == "devlog":
                groups = self._newest_first(groups)
            lines, refs = [], []
            for ref, hits in groups:
                if mtype == "skill":
                    lines.append(self._skill_line(ref, hits))
                elif mtype == "devlog":
                    lines.append(self._devlog_line(ref, hits))
                else:
                    lines.append(" ".join(" ".join(h.normalized_text.split()) for h in hits))
                refs.append(ref)
            lines_by_section[mtype] = [ln for ln in lines if ln.strip()]
            refs_by_section[mtype] = refs
        blocks: list[str] = []
        sections: dict[str, int] = {}
        sources: list[str] = []
        truncated = False
        carry = 0
        for title, mtype, share in _CONTEXT_SECTIONS:
            lines = lines_by_section[mtype]
            budget = int(max_chars * share) + carry
            header = f"## {title}"
            room = budget - len(header) - 1
            kept, cut = self._fill(lines, room)
            used = (len(header) + 1 + sum(len(k) + 1 for k in kept)) if kept else 0
            carry = max(0, budget - used) if kept or not lines else budget
            if cut:
                truncated = True
            if kept:
                blocks.append(header + "\n" + "\n".join(kept))
                sections[title] = len(kept)
                sources.extend(refs_by_section[mtype][: len(kept)])
        text = "\n".join(blocks)
        if len(text) > max_chars:  # joins add a few chars; never exceed the bound
            text, truncated = _clip(text, max_chars), True
        status = "ok" if text else "empty"
        return ContextBundle(status=status, text=text, sections=sections, sources=sources,
                             truncated=truncated, max_chars=max_chars)

    @staticmethod
    def _fill(lines: list[str], room: int) -> tuple[list[str], bool]:
        kept: list[str] = []
        used = 0
        for line in lines:
            need = len(line) + 1
            if used + need <= room:
                kept.append(line)
                used += need
                continue
            tail = room - used - 1
            if tail >= 24:
                kept.append(_clip(line, tail))
            return kept, True
        return kept, False

    @staticmethod
    def _newest_first(groups: list) -> list:
        def key(group):
            match = _DEVLOG_REF_RE.match(group[0])
            return (match.group(2) if match else "", group[0])

        return sorted(groups, key=key, reverse=True)

    def _skill_line(self, ref: str, hits: list) -> str:
        name = ref.rsplit("/", 1)[-1] or ref
        description = self._front_matter_description(hits[0].source_id)
        if not description:
            for hit in hits:
                if hit.kind in ("text", "other") and hit.normalized_text.strip():
                    description = " ".join(hit.normalized_text.split())
                    break
        return f"- {name}: {_clip(description, 160)}" if description else f"- {name}"

    def _front_matter_description(self, source_id: str) -> str:
        """``description:`` of a SKILL.md-style front matter, read from the (already authorized) source's blob."""
        try:
            registry, blobs = self._corpus()
            record = registry.get_by_source_id(source_id)
            if record is None or record.blob_ref is None or record.lifecycle_status == "deleted":
                return ""
            head = blobs.get(record.blob_ref)[:16384].decode("utf-8", errors="replace").replace("\r\n", "\n")
        except Exception:
            return ""
        match = re.match(r"\A\ufeff?---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", head, re.S)
        if not match:
            return ""
        lines = match.group(1).split("\n")
        for index, line in enumerate(lines):
            key = re.match(r"(?i)description\s*:\s*(.*)$", line)
            if not key:
                continue
            value = key.group(1).strip()
            if value in (">", "|", ">-", "|-", ">+", "|+"):
                folded = []
                for follow in lines[index + 1:]:
                    if follow[:1] in (" ", "\t"):
                        folded.append(follow.strip())
                    else:
                        break
                value = " ".join(folded)
            return " ".join(value.strip("'\"").split())
        return ""

    @staticmethod
    def _devlog_line(ref: str, hits: list) -> str:
        match = _DEVLOG_REF_RE.match(ref)
        label = f"[{match.group(2)} {match.group(1)}] " if match else f"[{hits[0].project_id or 'devlog'}] "
        body = " ".join(" ".join(h.normalized_text.split()) for h in hits)
        return "- " + label + _clip(body, 300)

    # ------------------------------------------------------------------ public: forget
    def forget(self, source_id: str) -> ForgetResult:
        """Forget one source by appending a lifecycle ``deleted`` tombstone version (DEF-057).

        The source disappears from recall/context and from every projection (a rebuild keeps it gone); the raw
        blobs of earlier versions stay in the canonical corpus (AGENTS.md: raw traces are never deleted).
        ``source_id`` may be the full id, a unique prefix (8+ hex chars) or an exact ``external_ref``.

        Only sources this profile can READ are ever matched (T8): a source that does not exist and one the caller
        cannot read (another profile's private memory, a project or space without a READ grant) answer the same
        ``not_found`` / ``unknown_source``, and an ambiguous reference lists only candidates the caller can read.
        """
        if not isinstance(source_id, str) or not 4 <= len(source_id.strip()) <= 600:
            return ForgetResult(status="invalid", reason="invalid_source_id")
        try:
            with self._lock:
                registry, _blobs = self._corpus()
                registry.refresh()
                record, problem = self._resolve(registry, source_id.strip(), self._reader())
                if record is None:
                    status, reason, candidates = problem
                    return ForgetResult(status=status, reason=reason, candidates=candidates)
                if record.lifecycle_status == "deleted":
                    return ForgetResult(status="already_forgotten", source_id=record.source_id,
                                        external_ref=record.external_ref,
                                        memory_type=(record.custom_meta or {}).get("memory_type"),
                                        version=record.source_version_id)
                scope = _scope_of(record.profile_id, record.project_id, record.knowledge_space_id, self._shared)
                memory_type = (record.custom_meta or {}).get("memory_type")
                if scope == "global":
                    return ForgetResult(status="denied", reason="DENY_GLOBAL_WRITE", source_id=record.source_id,
                                        external_ref=record.external_ref, memory_type=memory_type)
                decision = self._authorize_forget(record, scope)
                if not decision.allow:
                    return ForgetResult(status="denied", reason=decision.reason_code, source_id=record.source_id,
                                        external_ref=record.external_ref, memory_type=memory_type)
                return self._tombstone(record, memory_type)
        except Exception as exc:
            return ForgetResult(status="error", reason=f"internal_error:{type(exc).__name__}")

    def _authorize_forget(self, record, scope: str):
        from src.access import AccessRequest
        from src.access.audit import project_policy_decision, record_decision
        from src.access.authorized_write import authorize_write

        base = dict(operation="WRITE", requesting_profile_id=self._profile, resource_type="corpus_source")
        if record.knowledge_space_id is not None:
            request = AccessRequest(**base, knowledge_space_ids=[record.knowledge_space_id])
            target = f"knowledge_space:{record.knowledge_space_id}"
        elif record.project_id is not None:
            request = AccessRequest(**base, project_ids=[record.project_id])
            target = f"project:{record.project_id}"
        else:
            request = AccessRequest(**base, target_profile_ids=[record.profile_id])
            target = f"profile:{record.profile_id}"
        conn = self._conn()
        decision = authorize_write(request, conn, self._lookup)
        try:
            event = record_decision(
                self._append_event, decision, decision_id=f"pd-{uuid.uuid4().hex[:16]}", requester=self._profile,
                target_scope=target, profile_id=self._profile,
                created_at=self._now().strftime("%Y-%m-%dT%H:%M:%SZ"))
            if event is not None:
                project_policy_decision(conn, event)
                conn.commit()
        except Exception:
            pass
        return decision

    def _reader(self) -> Callable[[Any], bool]:
        """``record -> bool``: may this profile READ the source (its own private rows, global rows, ``ks-shared`` and
        projects it holds a READ grant for)? Exactly the row-level scope ``recall`` retrieves under (the authorized
        read facade's ``corpus_scope``), decided once per project."""
        from src.access import AccessRequest, AuthorizedReadService
        from src.corpus.retrieval import AuthorizedCorpusScope

        service = AuthorizedReadService(None, self._profile, grant_conn=self._conn())
        scopes: dict[Optional[str], Any] = {}

        def scope_for(project_id: Optional[str]):
            if project_id not in scopes:
                base = dict(operation="READ", requesting_profile_id=self._profile, resource_type="corpus_unit")
                requests = [AccessRequest(**base), AccessRequest(**base, knowledge_space_ids=[self._shared])]
                if project_id is not None:
                    requests.append(AccessRequest(**base, project_ids=[project_id]))
                allowed: list = []
                for request in requests:
                    scope = service.corpus_scope(request)
                    if scope is not None:
                        allowed.extend(scope.allowed_scopes)
                scopes[project_id] = AuthorizedCorpusScope(allowed_scopes=tuple(allowed))
            return scopes[project_id]

        def can_read(record) -> bool:
            return scope_for(record.project_id).allows(record.profile_id, record.project_id, record.knowledge_space_id)

        return can_read

    @staticmethod
    def _resolve(registry, ident: str, can_read: Callable[[Any], bool]):
        """Resolve ``ident`` among the sources ``can_read`` accepts; an unreadable source is simply not there."""
        latest: dict[str, Any] = {}
        for rec in registry.all_records():
            latest[rec.source_id] = rec
        if ident in latest:
            return (latest[ident], None) if can_read(latest[ident]) else (None, ("not_found", "unknown_source", ()))
        if "://" in ident:
            matches = [r for r in latest.values() if r.external_ref == ident]
        elif re.fullmatch(r"[0-9a-f]{8,63}", ident):
            matches = [r for r in latest.values() if r.source_id.startswith(ident)]
        else:
            matches = []
        matches = [r for r in matches if can_read(r)]
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, ("ambiguous", "multiple_sources_match", tuple(sorted(m.source_id for m in matches)))
        return None, ("not_found", "unknown_source", ())

    def _tombstone(self, record, memory_type) -> ForgetResult:
        import json

        from src.corpus.derived_store import project_source
        from src.corpus.registry import corpus_write_lock

        registry, blobs = self._corpus()
        conn = self._conn()
        marker = json.dumps({
            "tombstone": True, "forgotten_by": self._profile, "forgotten_at": self._now().isoformat(),
            "forgotten_version": record.source_version_id, "forgotten_content_hash": record.content_hash,
        }, sort_keys=True).encode("utf-8")
        with corpus_write_lock(self._layout.corpus_root):
            registry.refresh()
            latest = registry.get_by_source_id(record.source_id)
            if latest is not None and latest.lifecycle_status == "deleted":
                return ForgetResult(status="already_forgotten", source_id=record.source_id,
                                    external_ref=record.external_ref, memory_type=memory_type,
                                    version=latest.source_version_id)
            tomb = registry.register_source_with_blob(
                content=marker, external_ref=record.external_ref, kind=record.kind,
                profile_id=record.profile_id, project_id=record.project_id,
                knowledge_space_id=record.knowledge_space_id, sensitivity=record.sensitivity,
                lifecycle_status="deleted", custom_meta=dict(record.custom_meta or {}),
                provenance={"channel": self._channel, "writer": "zero_mem.memory", "profile": self._profile,
                            "tool": "forget", "operation": "forget", "forgotten_version": record.source_version_id},
                blob_store=blobs)
            try:
                project_source(conn, registry, tomb, blob_store=blobs)
                conn.commit()
            except Exception:
                conn.rollback()
                return ForgetResult(status="error", reason="projection_failed", source_id=record.source_id,
                                    external_ref=record.external_ref, memory_type=memory_type,
                                    version=tomb.source_version_id)
        return ForgetResult(status="forgotten", source_id=record.source_id, external_ref=record.external_ref,
                            memory_type=memory_type, version=tomb.source_version_id)

    # ------------------------------------------------------------------ public: status
    def status(self) -> dict:
        """Counts, this profile's grants and projection drift (no content)."""
        import json

        with self._lock:
            registry, _blobs = self._corpus()
            registry.refresh()
            conn = self._conn()
            latest: dict[str, Any] = {}
            for rec in registry.all_records():
                latest[rec.source_id] = rec
            derived = {r[0]: (r[1], r[2]) for r in conn.execute(
                "SELECT source_id, content_hash, lifecycle_status FROM zm_corpus_sources")}
            by_type: dict[str, int] = {}
            own = forgotten = drift = 0
            for rec in latest.values():
                if derived.get(rec.source_id) != (rec.content_hash, rec.lifecycle_status):
                    drift += 1
                if rec.lifecycle_status == "deleted":
                    forgotten += 1
                    continue
                mtype = (rec.custom_meta or {}).get("memory_type") or "unknown"
                by_type[mtype] = by_type.get(mtype, 0) + 1
                own += 1 if rec.profile_id == self._profile else 0
            units = conn.execute("SELECT COUNT(*) FROM zm_corpus_units").fetchone()[0]
            grants = []
            can_read = can_write = False
            rows = conn.execute(
                "SELECT operation, target_type, target_id, verification_ref FROM zm_access_grants "
                "WHERE subject_profile=? AND lifecycle_status='active' AND (state IS NULL OR state != 'revoked') "
                "ORDER BY grant_id", (self._profile,)).fetchall()
            for op, tt, tid, ref in rows:
                grants.append({"operation": op, "target_type": tt, "target_id": tid})
                if tt == "knowledge_space" and tid == self._shared:
                    if op == "READ":
                        can_read = True
                    elif op == "WRITE":
                        approval = self._lookup(ref)
                        can_write = approval is not None and approval.verification_status == "verified"
            schema = conn.execute("SELECT MAX(version) FROM zm_migrations").fetchone()[0]
        return json.loads(json.dumps({
            "profile_id": self._profile, "shared_space": self._shared,
            "data_root": str(self._layout.data_root), "corpus_root": str(self._layout.corpus_root),
            "schema_version": schema,
            "sources": {"total": own if False else sum(by_type.values()), "own": own, "forgotten": forgotten,
                        "by_type": dict(sorted(by_type.items()))},
            "units": units,
            "grants": grants, "can_read_shared": can_read, "can_write_shared": can_write,
            "needs_rebuild": drift > 0, "drifted_sources": drift,
        }))


def _res_limit() -> int:
    from src.corpus.query_planner import MAX_RESULT_LIMIT

    return MAX_RESULT_LIMIT


__all__ = [
    "MAX_INGEST_BYTES", "MAX_TEXT_BYTES", "MEMORY_TYPES", "Memory", "MemoryConfigError", "SCOPES", "SHARED_SPACE",
]
