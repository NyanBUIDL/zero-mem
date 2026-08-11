"""M10.1 — focused unit tests: corpus source registry + authorization boundary.

Scope: registry append/idempotence/checkpoint, deterministic identity, closed
contract, M5 resource-type registration, M8 mirror equality, M6.6 isolation for
corpus_source vs corpus_unit/event/artifact, and portable config-root resolution.

No ingestion, no normalization, no FTS, no embeddings, no graph, no migrate_10.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.access.contracts import _VALID_RESOURCE_TYPES
from src.access.grants import AuthorizedReadGrant, compose_effective_scope
from src.capture.event_types import LifecycleStatus
from src.corpus import (
    CorpusSourceRegistry,
    compute_source_hash,
    derive_source_id,
)
from src.corpus.contracts import (
    CORPUS_SOURCE_RESOURCE_TYPE,
    CorpusSourceRecord,
    SourceSensitivity,
    ValidationError,
)
from src.m8.vocabulary import RESOURCE_TYPES


# ---------------------------------------------------------------------------
# 1. registry append is append-first and idempotent
# ---------------------------------------------------------------------------
def _tmp_root() -> Path:
    return Path(tempfile.mkdtemp(prefix="m10_1_"))


def test_register_appends_and_is_idempotent_by_content_and_scope():
    root = _tmp_root()
    reg = CorpusSourceRegistry(root=root)
    assert reg.available
    content = b"%PDF-1.4 fake finance doc"
    desc = dict(profile_id="p1", project_id="proj-x", external_ref="s3://bucket/a.pdf", kind="pdf")

    r1 = reg.register_source(
        content=content, external_ref=desc["external_ref"], kind=desc["kind"],
        profile_id=desc["profile_id"], project_id=desc["project_id"],
    )
    # identical (content, scope) => same id, no second append
    r2 = reg.register_source(
        content=content, external_ref=desc["external_ref"], kind=desc["kind"],
        profile_id=desc["profile_id"], project_id=desc["project_id"],
    )
    assert r1.source_id == r2.source_id
    assert r1.content_hash == r2.content_hash
    assert len(reg.all_records()) == 1

    # a different scope => distinct source version (append, not overwrite)
    r3 = reg.register_source(
        content=content, external_ref=desc["external_ref"], kind=desc["kind"],
        profile_id="p2", project_id=desc["project_id"],
    )
    assert r3.source_id != r1.source_id
    assert len(reg.all_records()) == 2


def test_registry_persists_across_reload(tmp_path):
    reg = CorpusSourceRegistry(root=tmp_path)
    reg.register_source(
        content=b"hello world", external_ref="file:///a.txt", kind="txt",
        profile_id="p1", project_id="proj-x",
    )
    # new instance over same root reloads from disk (append-first durability)
    reg2 = CorpusSourceRegistry(root=tmp_path)
    assert len(reg2.all_records()) == 1
    rec = reg2.get_by_external_ref_first("file:///a.txt")
    assert rec is not None


def test_unconfigured_root_is_safe_and_silent(monkeypatch):
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    reg = CorpusSourceRegistry(root=None, config_path=Path("/nonexistent/corpus.yaml"))
    assert reg.available is False
    with pytest.raises(ValidationError):
        reg.register_source(content=b"x", external_ref="e", kind="txt")


# ---------------------------------------------------------------------------
# 2. deterministic identity
# ---------------------------------------------------------------------------
def test_source_hash_deterministic_and_unchanged_source_detection():
    content = b"same bytes"
    desc = dict(external_ref="r", kind="pdf", profile_id="p1", project_id="pr")
    h1 = compute_source_hash(content, desc)
    h2 = compute_source_hash(content, desc)
    assert h1 == h2
    # different content => different hash
    assert compute_source_hash(b"different", desc) != h1
    # deterministic source_id
    assert derive_source_id(h1, desc) == derive_source_id(h1, desc)


def test_source_id_changes_when_scope_changes():
    content = b"same bytes"
    desc_a = dict(external_ref="r", kind="pdf", profile_id="p1", project_id="pr")
    desc_b = dict(external_ref="r", kind="pdf", profile_id="p2", project_id="pr")
    h = compute_source_hash(content, desc_a)
    assert derive_source_id(h, desc_a) != derive_source_id(h, desc_b)


# ---------------------------------------------------------------------------
# 3. closed contract fails closed
# ---------------------------------------------------------------------------
def test_record_rejects_unknown_lifecycle():
    with pytest.raises(ValidationError):
        CorpusSourceRecord(
            source_id="s", content_hash="c", external_ref="e", kind="pdf",
            created_at="2026-01-01T00:00:00+00:00", lifecycle_status="bogus",
        )


def test_record_rejects_wrong_resource_type():
    with pytest.raises(ValidationError):
        CorpusSourceRecord(
            source_id="s", content_hash="c", external_ref="e", kind="pdf",
            created_at="2026-01-01T00:00:00+00:00", resource_type="corpus_unit",
        )


def test_record_rejects_unknown_sensitivity():
    with pytest.raises(ValidationError):
        CorpusSourceRecord(
            source_id="s", content_hash="c", external_ref="e", kind="pdf",
            created_at="2026-01-01T00:00:00+00:00", sensitivity="topsecret",
        )


def test_record_blob_ref_stays_none_in_m10_1():
    rec = CorpusSourceRecord(
        source_id="s", content_hash="c", external_ref="e", kind="pdf",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert rec.resource_type == CORPUS_SOURCE_RESOURCE_TYPE
    assert rec.blob_ref is None  # no bytes stored in M10.1


# ---------------------------------------------------------------------------
# 4. M5 resource-type registration
# ---------------------------------------------------------------------------
def test_m5_resource_types_include_corpus_source_and_unit():
    assert "corpus_source" in _VALID_RESOURCE_TYPES
    assert "corpus_unit" in _VALID_RESOURCE_TYPES


def test_m5_rejects_unregistered_resource_type():
    from src.access.contracts import AccessRequest
    with pytest.raises(ValueError):
        AccessRequest(
            operation="READ", requesting_profile_id="p1",
            resource_type="corpus_zzz_not_real",
        ).validate()


# ---------------------------------------------------------------------------
# 5. M8 mirror equality (existing regression must stay green)
# ---------------------------------------------------------------------------
def test_m8_resource_type_mirror_includes_corpus():
    assert RESOURCE_TYPES == frozenset(_VALID_RESOURCE_TYPES)
    assert "corpus_source" in RESOURCE_TYPES
    assert "corpus_unit" in RESOURCE_TYPES


# ---------------------------------------------------------------------------
# 6. M6.6 isolation: corpus_source grant must NOT authorize corpus_unit/event/artifact
# ---------------------------------------------------------------------------
def _grant(resource_types):
    return AuthorizedReadGrant(
        grant_id="g1", subject_profile="p1", operation="READ",
        target_type="project", target_id="proj-x",
        resource_types=resource_types, lifecycle_status="active",
    )


def _req(profile, projects, resource_type=None):
    from src.access.contracts import AccessRequest

    return AccessRequest(
        operation="READ", requesting_profile_id=profile,
        project_ids=list(projects), resource_type=resource_type,
    )


def _resource_allowed(eff, request):
    """Exercise the REAL M6.6 enforcement point (facade._resource_allowed).

    compose_effective_scope only *records* grant_resource_types; the per-type
    denial is applied by AuthorizedReadService._resource_allowed when a corpus
    read is gated. The store is never touched here.
    """
    from src.access.authorized_read import AuthorizedReadService

    svc = AuthorizedReadService(store=object(), requesting_profile_id="p1")
    return svc._resource_allowed(eff, request)


def test_corpus_source_grant_does_not_authorize_corpus_unit():
    eff = compose_effective_scope(
        _req("p1", ["proj-x"], resource_type="corpus_unit"),
        grants=[_grant(["corpus_source"])],
    )
    # The grant covers corpus_source only; corpus_unit must be denied by the
    # real M6.6 enforcement point (grant_resource_types restricts).
    assert _resource_allowed(eff, _req("p1", ["proj-x"], resource_type="corpus_unit")) is False


def test_corpus_source_grant_allows_corpus_source_only():
    eff = compose_effective_scope(
        _req("p1", ["proj-x"], resource_type="corpus_source"),
        grants=[_grant(["corpus_source"])],
    )
    assert _resource_allowed(eff, _req("p1", ["proj-x"], resource_type="corpus_source")) is True


def test_corpus_unit_grant_does_not_authorize_corpus_source():
    eff = compose_effective_scope(
        _req("p1", ["proj-x"], resource_type="corpus_source"),
        grants=[_grant(["corpus_unit"])],
    )
    assert _resource_allowed(eff, _req("p1", ["proj-x"], resource_type="corpus_source")) is False


def test_corpus_grant_does_not_authorize_event_or_artifact():
    for rt in ("event", "artifact", "project_artifact"):
        eff = compose_effective_scope(
            _req("p1", ["proj-x"], resource_type=rt),
            grants=[_grant(["corpus_source"])],
        )
        assert _resource_allowed(eff, _req("p1", ["proj-x"], resource_type=rt)) is False, rt


# ---------------------------------------------------------------------------
# 7. portable config-root resolution
# ---------------------------------------------------------------------------
def test_root_resolution_explicit_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(tmp_path / "env"))
    explicit = tmp_path / "explicit"
    reg = CorpusSourceRegistry(root=explicit)
    assert reg.available
    assert reg.path.parent == explicit


def test_root_resolution_env_used_when_no_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("ZERO_MEM_CORPUS_ROOT", str(tmp_path / "from_env"))
    reg = CorpusSourceRegistry(root=None)
    assert reg.available
    assert reg.path.parent == (tmp_path / "from_env")


def test_root_resolution_unconfigured_is_none(monkeypatch):
    monkeypatch.delenv("ZERO_MEM_CORPUS_ROOT", raising=False)
    reg = CorpusSourceRegistry(root=None, config_path=Path("/no/corpus.yaml"))
    assert reg.available is False


# ---------------------------------------------------------------------------
# 8. zero-LLM guarantee: no network/LLM import in src.corpus
# ---------------------------------------------------------------------------
def test_corpus_module_has_no_llm_or_network_import():
    import ast
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parents[2] / "src" / "corpus"
    banned = ("openai", "anthropic", "requests", "httpx", "urllib.request", "llm")
    for py in pkg.glob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not any(b in alias.name for b in banned), alias.name
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or not any(
                    b in node.module for b in banned
                ), node.module


# ---------------------------------------------------------------------------
# 9. canonical JSONL stays replayable after blob_ref rebinding (M10.7 defect)
# ---------------------------------------------------------------------------
def _blob_bound_registry(root: Path, count: int) -> CorpusSourceRegistry:
    """Register ``count`` sources WITH blobs, which triggers _update_record."""
    from src.corpus.blob_store import CorpusBlobStore

    blob = CorpusBlobStore(root=root)
    reg = CorpusSourceRegistry(root=root)
    for index in range(count):
        reg.register_source_with_blob(
            content=f"canonical replay doc {index}".encode(),
            external_ref=f"label/doc{index}.txt",
            kind="txt",
            blob_store=blob,
            profile_id="p1",
            project_id="P",
        )
    return reg


def test_registry_jsonl_has_no_blank_lines_after_blob_rebind():
    """PERMANENT REGRESSION (M10.7) — canonical registry must stay parseable.

    ``_update_record`` rewrites the registry to bind ``blob_ref``. It read lines
    via ``splitlines()`` (unterminated) but re-inserted records via
    ``_serialize`` (already newline-terminated), then re-joined with "\\n" --
    injecting one BLANK line per rebound record. The canonical
    ``corpus_sources.jsonl`` was therefore written in a state its own loader
    rejects with ``malformed_historical_line``, so any reload/rebuild from
    canonical failed. Registering N sources with blobs produced N blank lines.
    """
    root = _tmp_root()
    _blob_bound_registry(root, 3)
    raw = (root / "corpus_sources.jsonl").read_bytes()

    # Exactly one trailing terminator, and no interior blank lines.
    assert raw.endswith(b"\n")
    assert b"\n\n" not in raw, "canonical registry JSONL contains a blank line"
    lines = raw.split(b"\n")[:-1]
    assert len(lines) == 3, f"expected 3 record lines, got {len(lines)}"
    assert all(lines), "canonical registry JSONL contains an empty record line"


def test_registry_reloads_from_canonical_after_blob_rebind():
    """The registry must replay its own canonical JSONL (rebuild precondition)."""
    root = _tmp_root()
    first = _blob_bound_registry(root, 3)
    original = {r.source_id: r.blob_ref for r in first.all_records()}
    assert all(ref is not None for ref in original.values())

    reloaded = CorpusSourceRegistry(root=root)  # must not raise
    assert {r.source_id: r.blob_ref for r in reloaded.all_records()} == original
