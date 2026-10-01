"""T13 / DEF-090: Windows-only concurrent-write failures in the corpus store.

Windows raises PermissionError (WinError 5/32) from os.replace / open when another
process holds or is replacing the destination, and Path.resolve() can transiently
disagree about a file that is being replaced.  Simulated here on POSIX.
"""
from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from src.corpus import _fsretry
from src.corpus.blob_store import BlobStoreError, CorpusBlobStore
from src.corpus.contracts import ValidationError
from src.corpus.registry import CorpusSourceRegistry


def _perm(winerror: int) -> PermissionError:
    exc = PermissionError(errno.EACCES, "Access is denied")
    exc.winerror = winerror  # type: ignore[attr-defined]
    return exc


@pytest.fixture
def sleeps(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(_fsretry, "_sleep", calls.append)
    return calls


def _flaky_replace(monkeypatch, failures: int, winerror: int = 5):
    real = os.replace
    state = {"n": 0}

    def fake(src, dst, *a, **k):
        state["n"] += 1
        if state["n"] <= failures:
            raise _perm(winerror)
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", fake)
    return state


def _no_temp(root: Path):
    return [p for p in root.rglob("*") if p.is_file() and (p.suffix in (".part", ".tmp"))]


@pytest.mark.parametrize("winerror", [5, 32])
def test_blob_put_retries_transient_replace_denial(tmp_path, monkeypatch, sleeps, winerror):
    store = CorpusBlobStore(root=tmp_path / "c")
    state = _flaky_replace(monkeypatch, 3, winerror)
    digest = store.put(content=b"hello", source_ref="a")
    assert store.get(digest) == b"hello"
    assert state["n"] == 4 and len(sleeps) == 3
    assert sleeps == sorted(sleeps) and _no_temp(tmp_path) == []


def test_blob_put_persistent_denial_raises_typed_error_bounded(tmp_path, monkeypatch, sleeps):
    store = CorpusBlobStore(root=tmp_path / "c")
    state = _flaky_replace(monkeypatch, 10**6)
    with pytest.raises(BlobStoreError):
        store.put(content=b"hello", source_ref="a")
    assert state["n"] <= 12 and sum(sleeps) < 2.0
    assert _no_temp(tmp_path) == []


def test_blob_put_destination_already_correct_is_success(tmp_path, monkeypatch, sleeps):
    store = CorpusBlobStore(root=tmp_path / "c")
    digest = store._sha256(b"hello")
    target = store._path_for(digest)
    real = os.replace

    def fake(src, dst, *a, **k):
        real(src, dst)  # a competing writer landed identical bytes first
        raise _perm(5)

    monkeypatch.setattr(os, "replace", fake)
    assert store.put(content=b"hello", source_ref="a") == digest
    assert target.read_bytes() == b"hello" and _no_temp(tmp_path) == []


def test_non_transient_oserror_is_not_masked_or_retried(tmp_path, monkeypatch, sleeps):
    store = CorpusBlobStore(root=tmp_path / "c")

    def fake(src, dst, *a, **k):
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(os, "replace", fake)
    with pytest.raises(OSError) as info:
        store.put(content=b"hello", source_ref="a")
    assert info.value.errno == errno.ENOSPC and sleeps == []
    assert _no_temp(tmp_path) == []


def test_blob_read_retries_sharing_violation(tmp_path, monkeypatch, sleeps):
    store = CorpusBlobStore(root=tmp_path / "c")
    digest = store.put(content=b"hello", source_ref="a")
    real = Path.read_bytes
    state = {"n": 0}

    def fake(self):
        state["n"] += 1
        if state["n"] <= 2:
            raise _perm(32)
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", fake)
    assert store.get(digest) == b"hello"
    assert store.put(content=b"hello", source_ref="b") == digest


def test_containment_check_does_not_resolve_the_file_itself(tmp_path, monkeypatch):
    """A transiently odd resolve() of the (being replaced) file must not look like an escape."""
    store = CorpusBlobStore(root=tmp_path / "c")
    digest = store._sha256(b"hello")
    target = store._path_for(digest)
    real = Path.resolve

    def fake(self, *a, **k):
        if self.name == digest:  # file-level resolve returns garbage mid-replace
            return Path("/elsewhere") / digest
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", fake)
    store._assert_within_root(target)
    assert store.put(content=b"hello", source_ref="a") == digest


def test_containment_still_rejects_traversal_and_symlink_parent(tmp_path):
    store = CorpusBlobStore(root=tmp_path / "c")
    digest = store._sha256(b"x")
    with pytest.raises(BlobStoreError, match="path_escape_attempt"):
        store._assert_within_root(store._blob_dir / ".." / ".." / digest)
    with pytest.raises(BlobStoreError, match="path_escape_attempt"):
        store._assert_within_root(store._blob_dir / "not-a-digest")
    outside = tmp_path / "outside"
    outside.mkdir()
    (store._blob_dir / digest[:2]).symlink_to(outside, target_is_directory=True)
    with pytest.raises(BlobStoreError, match="path_escape_attempt"):
        store._assert_within_root(store._blob_dir / digest[:2] / digest)


def test_registry_update_record_retries_replace(tmp_path, monkeypatch, sleeps):
    reg = CorpusSourceRegistry(root=tmp_path / "c")
    rec = reg.register_source(content=b"a\n", external_ref="mem://p/x", kind="txt")
    state = _flaky_replace(monkeypatch, 3, 32)
    reg._update_record(rec)
    assert state["n"] == 4 and _no_temp(tmp_path) == []
    state["n"] = -10**6  # persistent
    with pytest.raises(ValidationError):
        reg._update_record(rec)
    assert sum(sleeps) < 2.0 + 0.5 and _no_temp(tmp_path) == []


def test_registry_append_and_read_retry_sharing_violation(tmp_path, monkeypatch, sleeps):
    reg = CorpusSourceRegistry(root=tmp_path / "c")
    real_open = Path.open
    state = {"n": 0}

    def fake(self, *a, **k):
        if self.name == "corpus_sources.jsonl":
            state["n"] += 1
            if state["n"] <= 2:
                raise _perm(32)
        return real_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", fake)
    reg.register_source(content=b"a\n", external_ref="mem://p/x", kind="txt")
    assert len(CorpusSourceRegistry(root=tmp_path / "c").all_records()) == 1
    assert len(sleeps) == 2


def test_retry_helper_budget():
    assert sum(_fsretry.delays()) < 2.0 and len(_fsretry.delays()) >= 9
