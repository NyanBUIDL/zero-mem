"""Shared fixtures for the T3 (paths + retrieval) corpus tests.

Builds a real derived store from registry sources through the production
projection, then queries it through the authorized facade.  Not collected by
pytest (no ``test_`` prefix).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from src.access import AccessRequest, AuthorizedReadService
from src.corpus.blob_store import CorpusBlobStore
from src.corpus.derived_store import project_corpus
from src.corpus.registry import CorpusSourceRegistry
from src.retrieval.db import open_readonly
from src.storage.sqlite_store import SQLiteStore, SQLiteStoreConfig


def doc(text: str, *, ref: Optional[str] = None, profile: str = "p1",
        project: Optional[str] = None, space: Optional[str] = None,
        kind: str = "txt", meta: Optional[Mapping[str, Any]] = None) -> dict:
    return {"content": text.encode("utf-8"), "ref": ref, "profile": profile,
            "project": project, "space": space, "kind": kind, "meta": meta}


def build_store(tmp_path: Path, docs: Iterable[dict], *, tag: str = "t3"):
    """Register + project ``docs`` and return a read-only store handle."""
    uid = uuid.uuid4().hex[:8]
    root = tmp_path / f"corpus_{tag}_{uid}"
    root.mkdir(parents=True, exist_ok=True)
    registry = CorpusSourceRegistry(root=root)
    blobs = CorpusBlobStore(root=root)
    db_path = tmp_path / f"db_{tag}_{uid}.sqlite"
    writer = SQLiteStore(SQLiteStoreConfig(path=db_path))
    writer.ensure_schema()
    writer._conn.execute("PRAGMA journal_mode=DELETE")
    for index, item in enumerate(docs):
        registry.register_source_with_blob(
            content=item["content"],
            external_ref=item["ref"] or f"file://{tag}-{index}.txt",
            kind=item["kind"],
            profile_id=item["profile"],
            project_id=item["project"],
            knowledge_space_id=item["space"],
            custom_meta=item["meta"],
            blob_store=blobs,
        )
    project_corpus(writer._conn, registry, blob_store=blobs)
    writer._conn.commit()
    writer.close()
    return open_readonly(db_path)


def search(ro, text: str, *, profile: str = "p1", limit: Optional[int] = None,
           metadata: Optional[Mapping[str, Any]] = None, **request_kwargs: Any):
    """Authorized corpus search as ``profile`` (implicit own-profile read)."""
    service = AuthorizedReadService(ro, requesting_profile_id=profile, grant_conn=ro.conn)
    request = AccessRequest(
        operation="READ",
        requesting_profile_id=profile,
        resource_type="corpus_unit",
        **request_kwargs,
    )
    return service.corpus_unit_search(request, text, metadata=metadata, limit=limit)


def texts(result) -> list[str]:
    return [hit.normalized_text for hit in result.items]
