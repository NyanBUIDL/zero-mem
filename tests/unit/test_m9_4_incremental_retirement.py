"""M9.4 focused tests — incremental reconcile, zero-write rerun, safe stale
retirement, three-signal ownership, human-file preservation, and path/symlink
safety. Counterpart to ``test_m9_4_manifest_lifecycle.py``: this file drives the
:func:`~src.projection.reconcile.reconcile` engine directly and through
:func:`~src.projection.engine.project_to_vault`.

Every destructive operation under test runs in an OS-safe ``tmp_path`` vault.
The real operator vault is never touched; the one true-vault check lives in
``test_m9_4_integration_real_vault.py``.
"""

import os
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.projection.identity import content_fingerprint, derive_note_id  # noqa: E402
from src.projection.contracts import NoteStatus, NoteType, ProjectedNote  # noqa: E402
from src.projection.manifest import (  # noqa: E402
    MANIFEST_RELATIVE_PATH,
    ManifestEntry,
    ManifestError,
    ProjectionManifest,
    load_manifest,
    resolve_entry_path,
)
from src.projection.reconcile import reconcile, rebuild  # noqa: E402
from src.projection.writer import WriteStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Note builders (note id always derived, like the renderer)
# ---------------------------------------------------------------------------

def _mk_note(rel, body, *, resource_id, note_type="requirement",
             resource_type="requirement", project_id="P"):
    note_id = derive_note_id(
        note_type=NoteType(note_type), resource_type=resource_type,
        resource_id=resource_id, project_id=project_id, profile_id=None,
    )
    content = (
        "---\n"
        f"zero_mem_managed: true\n"
        f"note_id: {note_id}\n"
        f"note_type: {note_type}\n"
        "---\n"
        f"{body}\n"
    )
    return ProjectedNote(
        note_id=note_id,
        note_type=NoteType(note_type),
        relative_path=rel,
        content=content,
        content_fingerprint=content_fingerprint(content),
        resource_type=resource_type,
        resource_id=resource_id,
        project_id=project_id,
        source_trace_ids=(),
    )


def _cfg_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    return vault


# ---------------------------------------------------------------------------
# Deterministic full rebuild / byte-equivalence
# ---------------------------------------------------------------------------

def test_rebuild_creates_all_desired_notes(tmp_path):
    vault = _cfg_vault(tmp_path)
    notes = [
        _mk_note("requirements/unscoped/a.md", "body a", resource_id="A"),
        _mk_note("decisions/unscoped/s.md", "body s", resource_id="S",
                  note_type="decision", resource_type="decision"),
    ]
    result = rebuild(vault, notes)
    assert result.created == 2
    assert (vault / "requirements/unscoped/a.md").is_file()
    assert (vault / "decisions/unscoped/s.md").is_file()
    assert result.manifest_stored is True
    assert len(result.manifest.entries) == 2


def test_two_clean_rebuilds_byte_equivalent(tmp_path):
    notes = [
        _mk_note("requirements/unscoped/a.md", "body a", resource_id="A"),
        _mk_note("requirements/unscoped/b.md", "body b", resource_id="B"),
        _mk_note("decisions/unscoped/s.md", "body s", resource_id="S",
                  note_type="decision", resource_type="decision"),
    ]
    va = _cfg_vault(tmp_path) / "a"
    vb = _cfg_vault(tmp_path) / "b"
    va.mkdir(); vb.mkdir()
    rebuild(va, notes)
    rebuild(vb, notes)

    def _tree(root: Path):
        out = {}
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                out[rel] = p.read_bytes()
        return out

    assert _tree(va) == _tree(vb)


def test_rebuild_reverse_source_order_byte_equivalent(tmp_path):
    notes = [
        _mk_note("requirements/unscoped/a.md", "body a", resource_id="A"),
        _mk_note("requirements/unscoped/b.md", "body b", resource_id="B"),
        _mk_note("decisions/unscoped/s.md", "body s", resource_id="S",
                  note_type="decision", resource_type="decision"),
    ]
    va = _cfg_vault(tmp_path) / "a"
    vb = _cfg_vault(tmp_path) / "b"
    va.mkdir(); vb.mkdir()
    rebuild(va, list(notes))
    rebuild(vb, list(reversed(notes)))
    assert (va / MANIFEST_RELATIVE_PATH).read_bytes() == \
        (vb / MANIFEST_RELATIVE_PATH).read_bytes()


# ---------------------------------------------------------------------------
# Zero-write unchanged rerun
# ---------------------------------------------------------------------------

def test_unchanged_rerun_writes_zero_notes(tmp_path):
    vault = _cfg_vault(tmp_path)
    notes = [
        _mk_note("requirements/unscoped/a.md", "body a", resource_id="A"),
        _mk_note("decisions/unscoped/s.md", "body s", resource_id="S",
                  note_type="decision", resource_type="decision"),
    ]
    r1 = rebuild(vault, notes)
    assert r1.created == 2
    r2 = reconcile(vault, notes)
    # No note bytes changed on the second, identical run.
    assert r2.note_writes == 0
    assert r2.written == 0
    # The manifest was already current, so it is not needlessly rewritten.
    assert r2.manifest_stored is False
    # Exactly the prior manifest bytes remain on disk.
    assert load_manifest(vault).entries == r1.manifest.entries


def test_unchanged_rerun_manifest_not_rewritten_when_unchanged(tmp_path):
    vault = _cfg_vault(tmp_path)
    notes = [_mk_note("requirements/unscoped/a.md", "body a", resource_id="A")]
    rebuild(vault, notes)
    mtime_before = (vault / MANIFEST_RELATIVE_PATH).stat().st_mtime_ns
    r = reconcile(vault, notes)
    mtime_after = (vault / MANIFEST_RELATIVE_PATH).stat().st_mtime_ns
    assert r.manifest_stored is False
    assert mtime_before == mtime_after


# ---------------------------------------------------------------------------
# One-change incremental write set
# ---------------------------------------------------------------------------

def test_one_change_updates_only_changed_note(tmp_path):
    vault = _cfg_vault(tmp_path)
    base = [
        _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A"),
        _mk_note("requirements/unscoped/b.md", "body b", resource_id="B"),
        _mk_note("decisions/unscoped/s.md", "body s", resource_id="S",
                  note_type="decision", resource_type="decision"),
    ]
    r1 = rebuild(vault, base)
    assert r1.created == 3

    # Change EXACTLY the content of note A.
    updated = [_mk_note("requirements/unscoped/a.md", "body a v2", resource_id="A"),
               _mk_note("requirements/unscoped/b.md", "body b", resource_id="B"),
               _mk_note("decisions/unscoped/s.md", "body s", resource_id="S",
                         note_type="decision", resource_type="decision")]
    r2 = reconcile(vault, updated)
    # Exactly one note rewritten (A). B and S unchanged -> zero writes.
    assert r2.updated == 1
    assert r2.created == 0
    assert r2.note_writes == 1
    # Manifest recorded the new fingerprint for A only.
    entry_a = r2.manifest.get(
        [n for n in updated if n.relative_path.endswith("a.md")][0].note_id)
    assert entry_a.content_fingerprint == content_fingerprint(
        [n for n in updated if n.relative_path.endswith("a.md")][0].content)


def test_create_new_authorized_note_incremental(tmp_path):
    vault = _cfg_vault(tmp_path)
    r1 = rebuild(vault, [
        _mk_note("requirements/unscoped/a.md", "body a", resource_id="A"),
    ])
    assert r1.created == 1
    r2 = reconcile(vault, [
        _mk_note("requirements/unscoped/a.md", "body a", resource_id="A"),
        _mk_note("requirements/unscoped/c.md", "body c", resource_id="C"),
    ])
    assert r2.created == 1
    assert r2.note_writes == 1
    assert (vault / "requirements/unscoped/c.md").is_file()


# ---------------------------------------------------------------------------
# Safe stale retirement — three-signal ownership
# ---------------------------------------------------------------------------

def _seed_managed_file(vault, note):
    """Write a note file the way M9.2 would, so it carries the marker."""
    path = vault / note.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note.content)


def test_stale_retirement_ownership_proven_deletes(tmp_path):
    vault = _cfg_vault(tmp_path)
    note_a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    note_b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    # Initial projection creates A and B.
    r1 = rebuild(vault, [note_a, note_b])
    assert r1.created == 2
    # Desire drops B -> B is no longer desired.
    r2 = reconcile(vault, [note_a])
    retired = [w for w in r2.writes if w.status is WriteStatus.RETIRED]
    assert len(retired) == 1
    assert not (vault / "requirements/unscoped/b.md").exists()
    # Manifest records B as RETIRED, A as CURRENT.
    by_path = {e.relative_path: e for e in r2.manifest.entries}
    assert by_path["requirements/unscoped/b.md"].status is NoteStatus.RETIRED


def test_stale_retirement_ownership_not_proven_preserves(tmp_path):
    vault = _cfg_vault(tmp_path)
    note_a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    note_b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    # Seed A and B as MANAGED (manifest lists both).
    r1 = rebuild(vault, [note_a, note_b])
    assert r1.created == 2
    # Now the operator (or an attacker) REPLACES B with a human file that does
    # NOT carry the Zero-Mem managed marker. Ownership signal 3 is absent.
    human_path = vault / "requirements/unscoped/b.md"
    human_path.write_text("# Human note\n\nThis is my personal file, not generated.\n")
    # Desire drops B. Without the marker, retirement must NOT delete it.
    r2 = reconcile(vault, [note_a])
    assert (vault / "requirements/unscoped/b.md").read_text() == \
        "# Human note\n\nThis is my personal file, not generated.\n"
    # The outcome is a safe skip (ownership unproven for deletion), never a
    # retire. M9.5 classifies the marker-less replacement precisely as
    # HUMAN_OWNED and preserves it; M9.4's label for the same safe outcome was
    # SKIPPED_UNSAFE_OWNERSHIP. The load-bearing invariant — the human file is
    # preserved byte-for-byte and never deleted — is identical either way.
    assert any(
        w.status in (WriteStatus.SKIPPED_UNSAFE_OWNERSHIP, WriteStatus.SKIPPED_HUMAN_MODIFIED)
        for w in r2.writes
    )


def test_human_owned_same_name_never_deleted(tmp_path):
    vault = _cfg_vault(tmp_path)
    note_a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    note_b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    r1 = rebuild(vault, [note_a, note_b])
    assert r1.created == 2
    # Operator places a human-owned file at B's path (no marker) BEFORE the run
    # even knows B is stale.
    human_path = vault / "requirements/unscoped/b.md"
    human_bytes = b"# Personal, do not touch\n"
    human_path.write_bytes(human_bytes)
    r2 = reconcile(vault, [note_a])
    assert (vault / "requirements/unscoped/b.md").read_bytes() == human_bytes


# ---------------------------------------------------------------------------
# Human modification of a managed note -> fail safe (no silent overwrite)
# ---------------------------------------------------------------------------

def test_human_modified_managed_note_not_silently_overwritten(tmp_path):
    vault = _cfg_vault(tmp_path)
    note_a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    note_b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    r1 = rebuild(vault, [note_a, note_b])
    assert r1.created == 2
    # The human edits B in place (bytes now differ, but marker + note_id remain,
    # so all THREE signals still hold -> this is a genuine managed-note edit,
    # not a foreign file). M9.4 must refuse a silent overwrite of the human
    # change and let M9.5 resolve it.
    edited_path = vault / "requirements/unscoped/b.md"
    edited_content = edited_path.read_text().replace("body b", "body b EDITED BY HUMAN")
    edited_path.write_text(edited_content)
    r2 = reconcile(vault, [note_a, note_b])
    # The human-edited bytes are preserved exactly; no UPDATE happened.
    assert edited_path.read_text() == edited_content
    assert not any(w.status is WriteStatus.UPDATED for w in r2.writes)
    assert any(w.status is WriteStatus.SKIPPED_HUMAN_MODIFIED
               for w in r2.writes) or \
        any(w.status is WriteStatus.SKIPPED_UNSAFE_OWNERSHIP for w in r2.writes)


# ---------------------------------------------------------------------------
# Path / symlink safety on manifest-driven operations
# ---------------------------------------------------------------------------

def test_retire_through_hostile_symlink_chain_refused(tmp_path):
    vault = _cfg_vault(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("should never be deleted")
    # Managed dir becomes a symlink to outside/.
    managed_dir = vault / "requirements"
    managed_dir.symlink_to(outside, target_is_directory=True)
    # A manifest entry naming a file under requirements/ must NOT resolve
    # outside the root. We simulate the resolution: it should raise, never
    # return a path under `outside`.
    entry = ManifestEntry.from_note(
        _mk_note("requirements/unscoped/b.md", "body b", resource_id="B"))
    with pytest.raises(Exception):
        resolve_entry_path(vault, entry)


def test_manifest_path_escape_rejected_on_load(tmp_path):
    vault = _cfg_vault(tmp_path)
    # A manifest entry with a traversal path must be rejected at parse time.
    payload = {
        "manifest_version": 1,
        "projection_version": 1,
        "managed_dir_name": "",
        "notes": [{
            "note_id": derive_note_id(
                note_type=NoteType.REQUIREMENT, resource_type="requirement",
                resource_id="X", project_id="P", profile_id=None),
            "note_type": "requirement",
            "resource_type": "requirement",
            "resource_id": "X",
            "project_id": "P",
            "relative_path": "../escape.md",
            "content_fingerprint": "sha256:" + "0" * 64,
            "source_trace_ids": [],
            "status": "current",
        }],
    }
    (vault / "_meta").mkdir(exist_ok=True)
    (vault / MANIFEST_RELATIVE_PATH).write_text(json.dumps(payload))
    with pytest.raises(ManifestError):
        load_manifest(vault)
