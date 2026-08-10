"""M9.4 focused tests — deterministic manifest, incremental reconcile, safe
stale retirement, three-signal ownership, and path/symlink safety.

Every projection write/retirement under test targets a fresh OS-safe temporary
vault under ``tmp_path`` (plan-m9.md §11, §23). The real operator vault is never
touched; one test snapshots it read-only and asserts non-modification.

The M9.4 contract is exercised at two layers:

* **unit** — :class:`~src.projection.manifest.ProjectionManifest` /
  :class:`~src.projection.manifest.ManifestEntry` validation and serialization,
  and :func:`~src.projection.reconcile.reconcile` against hand-built notes;
* **end-to-end** — :func:`~src.projection.engine.project_to_vault` over the
  VERIFIED M4/M5/M6.6/M7 fixtures, so authorization, resource_type isolation,
  sensitivity, lifecycle, provenance and Conflict behavior all survive into the
  manifest/incremental path.

No test asserts a behavior that contradicts the approved contracts; where the
architecture legitimately requires two writes (e.g. a note update plus the
objectively-changed manifest), the expected write SET is stated exactly.
"""

import json
import sys
from pathlib import Path

ROOT = Path("/home/brian-nguyen/Hermes Workplace/Zero-mem")
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.projection.identity import content_fingerprint, derive_note_id  # noqa: E402
from src.projection.contracts import (  # noqa: E402
    NoteStatus,
    NoteType,
    ProjectedNote,
)
from src.projection.manifest import (  # noqa: E402
    MANIFEST_RELATIVE_PATH,
    ManifestEntry,
    ManifestError,
    ProjectionManifest,
    empty_manifest,
    load_manifest,
    store_manifest,
    validate_fingerprint,
    validate_manifest_relative_path,
)
from src.projection.reconcile import (  # noqa: E402
    ReconcileResult,
    reconcile,
    rebuild,
)
from src.projection.writer import WriteStatus  # noqa: E402
from src.projection.engine import project_to_vault, run_projection  # noqa: E402
from src.projection.config import ProjectionConfig  # noqa: E402

import tests.unit.m9_2_fixtures as fx  # noqa: E402


# ---------------------------------------------------------------------------
# Note builders
# ---------------------------------------------------------------------------

def _mk_note(note_id, rel, body, *, note_type="requirement",
             resource_type="requirement", resource_id=None, project_id="P"):
    # note_id is positional for call-site readability but is ALWAYS derived from
    # the authoritative identity (resource_type + resource_id/rel + project_id),
    # exactly as the renderer does, so every note carries a valid closed-format
    # id and the manifest can never disagree with the file.
    identity_seed = resource_id or note_id or rel
    derived = derive_note_id(
        note_type=NoteType(note_type), resource_type=resource_type,
        resource_id=identity_seed, project_id=project_id, profile_id=None,
    )
    content = (
        "---\n"
        f"zero_mem_managed: true\n"
        f"note_id: {derived}\n"
        f"note_type: {note_type}\n"
        "---\n"
        f"{body}\n"
    )
    return ProjectedNote(
        note_id=derived,
        note_type=NoteType(note_type),
        relative_path=rel,
        content=content,
        content_fingerprint=content_fingerprint(content),
        resource_type=resource_type,
        resource_id=resource_id or derived,
        project_id=project_id,
        source_trace_ids=(),
    )


def _empty_manifest():
    return ProjectionManifest(entries=())


# ---------------------------------------------------------------------------
# Manifest determinism + validation
# ---------------------------------------------------------------------------

def test_manifest_lives_under_meta(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    manifest = rebuild(vault, ())
    path = vault / MANIFEST_RELATIVE_PATH
    assert path.exists(), "manifest must live at _meta/manifest.json"
    assert load_manifest(vault).entries == ()


def test_manifest_deterministic_json_bytes(tmp_path):
    notes = [
        _mk_note("", "requirements/unscoped/a.md", "body a", resource_id="A"),
        _mk_note("", "requirements/unscoped/b.md", "body b", resource_id="B"),
        _mk_note("", "state/unscoped/c.md", "body c", resource_id="C"),
    ]
    m1 = ProjectionManifest.from_notes(notes)
    m2 = ProjectionManifest.from_notes(notes)
    assert m1.serialize() == m2.serialize()


def test_manifest_reverse_insertion_order_identical(tmp_path):
    notes = [
        _mk_note("", "requirements/unscoped/a.md", "body a", resource_id="A"),
        _mk_note("", "requirements/unscoped/b.md", "body b", resource_id="B"),
        _mk_note("", "state/unscoped/c.md", "body c", resource_id="C"),
    ]
    forward = ProjectionManifest.from_notes(list(notes))
    reverse = ProjectionManifest.from_notes(list(reversed(notes)))
    assert forward.serialize() == reverse.serialize()


def test_manifest_sorted_keys_and_note_order(tmp_path):
    notes = [
        _mk_note("", "requirements/unscoped/z.md", "z", resource_id="Z"),
        _mk_note("", "requirements/unscoped/a.md", "a", resource_id="A"),
    ]
    data = json.loads(ProjectionManifest.from_notes(notes).serialize())
    # sort_keys=True yields alphabetical key order in the serialized bytes.
    # ``edit_conflicts`` is the M9.5 channel; it is always emitted (even when
    # empty) so a manifest produced by M9.5 round-trips through any parser.
    assert list(data.keys()) == [
        "edit_conflicts",
        "managed_dir_name",
        "manifest_version",
        "notes",
        "projection_version",
    ]
    # notes ordered by note_id, not insertion order
    assert len(data["notes"]) == 2
    assert data["notes"][0]["note_id"] < data["notes"][1]["note_id"]


def test_manifest_records_projection_version_and_fingerprints(tmp_path):
    notes = [_mk_note("", "requirements/unscoped/a.md", "body a", resource_id="A")]
    data = json.loads(ProjectionManifest.from_notes(notes).serialize())
    assert data["projection_version"] >= 1
    entry = data["notes"][0]
    assert entry["content_fingerprint"].startswith("sha256:")
    assert len(entry["content_fingerprint"]) == 7 + 64
    assert entry["note_id"].startswith("zm-requirement-")
    assert entry["status"] == "current"


def test_manifest_contains_no_absolute_runtime_paths(tmp_path):
    notes = [_mk_note("", "requirements/unscoped/a.md", "body a", resource_id="A")]
    data = json.loads(ProjectionManifest.from_notes(notes).serialize())
    text = json.dumps(data)
    assert "/home" not in text
    assert str(tmp_path) not in text
    assert data["notes"][0]["relative_path"] == "requirements/unscoped/a.md"


# ---------------------------------------------------------------------------
# Manifest tamper / corruption — fail closed
# ---------------------------------------------------------------------------

def test_manifest_malformed_json_fails_closed(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "_meta").mkdir(exist_ok=True)
    (vault / MANIFEST_RELATIVE_PATH).write_text("{not valid json")
    with pytest.raises(ManifestError):
        load_manifest(vault)


def test_manifest_unsupported_version_fails_closed(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    payload = {
        "manifest_version": 999,
        "projection_version": 1,
        "managed_dir_name": "",
        "notes": [],
    }
    (vault / "_meta").mkdir(exist_ok=True)
    (vault / MANIFEST_RELATIVE_PATH).write_text(json.dumps(payload))
    with pytest.raises(ManifestError):
        load_manifest(vault)


def test_manifest_future_projection_version_fails_closed(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    payload = {
        "manifest_version": 1,
        "projection_version": 9999,
        "managed_dir_name": "",
        "notes": [],
    }
    (vault / "_meta").mkdir(exist_ok=True)
    (vault / MANIFEST_RELATIVE_PATH).write_text(json.dumps(payload))
    with pytest.raises(ManifestError):
        load_manifest(vault)


def test_manifest_duplicate_note_id_rejected(tmp_path):
    a = _mk_note("", "requirements/unscoped/a.md", "a", resource_id="SAME")
    b = _mk_note("", "requirements/unscoped/b.md", "b", resource_id="SAME")
    with pytest.raises(ManifestError):
        ProjectionManifest.from_notes([a, b])


def test_manifest_duplicate_relative_path_rejected(tmp_path):
    a = _mk_note("", "requirements/unscoped/dup.md", "a", resource_id="RA")
    b = _mk_note("", "requirements/unscoped/dup.md", "b", resource_id="RB")
    with pytest.raises(ManifestError):
        ProjectionManifest.from_notes([a, b])


def test_manifest_case_collision_path_rejected(tmp_path):
    a = _mk_note("", "requirements/unscoped/collide.md", "a", resource_id="CA")
    b = _mk_note("", "requirements/unscoped/COLLIDE.md", "b", resource_id="CB")
    with pytest.raises(ManifestError):
        ProjectionManifest.from_notes([a, b])


def test_manifest_hostile_relative_path_rejected(tmp_path):
    with pytest.raises(ManifestError):
        validate_manifest_relative_path("../escape.md")
    with pytest.raises(ManifestError):
        validate_manifest_relative_path("/abs.md")
    with pytest.raises(ManifestError):
        validate_manifest_relative_path("a/../../b.md")


def test_manifest_bad_fingerprint_rejected(tmp_path):
    with pytest.raises(ManifestError):
        validate_fingerprint("md5:abc")
    with pytest.raises(ManifestError):
        validate_fingerprint("sha256:ZZZZ")
    with pytest.raises(ManifestError):
        validate_fingerprint("not-a-fingerprint")


def test_manifest_entry_unknown_note_type_rejected(tmp_path):
    entry = {
        "note_id": "N-X",
        "note_type": "totally_unknown",
        "resource_type": "requirement",
        "resource_id": "X",
        "project_id": "P",
        "relative_path": "requirements/unscoped/x.md",
        "content_fingerprint": "sha256:" + "0" * 64,
        "source_trace_ids": [],
        "status": "current",
    }
    with pytest.raises(ManifestError):
        ManifestEntry.from_json(entry)


def test_manifest_unexpected_key_rejected(tmp_path):
    entry = {
        "note_id": "N-X",
        "note_type": "requirement",
        "resource_type": "requirement",
        "resource_id": "X",
        "project_id": "P",
        "relative_path": "requirements/unscoped/x.md",
        "content_fingerprint": "sha256:" + "0" * 64,
        "source_trace_ids": [],
        "status": "current",
        "extra_field": "smuggled",
    }
    with pytest.raises(ManifestError):
        ManifestEntry.from_json(entry)
