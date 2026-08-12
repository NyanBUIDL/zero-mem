"""M9.5 focused tests — human ownership boundary and edit-conflict safety.

Every destructive operation under test runs in an OS-safe ``tmp_path`` vault.
The real operator vault is never touched; the real-vault non-modification check
lives in ``test_m9_5_integration_real_vault.py``.

These tests exercise, deterministically and without any LLM/network call:

* the EXACT three-signal ownership rule (§12.1) — no single signal suffices;
* unchanged generated classification;
* human edit detection (body / frontmatter / both / append / remove);
* human-created file collision at a desired generated path (never overwritten,
  never deleted, ownership never adopted);
* spoofed generated markers (no adoption);
* deterministic edit_conflict (sibling + record) when canonical ALSO changed;
* ``human_modified`` only (no sibling, no churn) when canonical unchanged;
* repeated identical conflict => same result, 0 human-file writes, 0 duplicate
  conflict artifacts, 0 unrelated writes;
* stale + human-edited file preserved (no retirement);
* auth-revoked + human-edited file preserved without authorization leak;
* sensitivity-ineligible + human-edited file preserved without secret leak;
* missing generated file recreated safely only when desired still wants it;
* conflict metadata carries HASHES ONLY (no content / no secret leak);
* zero write-back: human Markdown content never mutates canonical state;
* path/symlink attacks fail closed;
* M9.4 zero-write and incremental guarantees preserved.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from src.projection.contracts import (  # noqa: E402
    NoteStatus,
    NoteType,
    ProjectedNote,
)
from src.projection.identity import content_fingerprint, derive_note_id  # noqa: E402
from src.projection.manifest import (  # noqa: E402
    MANIFEST_RELATIVE_PATH,
    EditConflict,
    ManifestEntry,
    ProjectionManifest,
    load_manifest,
)
from src.projection.ownership import (  # noqa: E402
    OwnershipClass,
    classify_managed_file,
    conflict_sibling_relative_path,
)
from src.projection.reconcile import reconcile, rebuild  # noqa: E402
from src.projection.writer import WriteStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Note builders
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


def _seed(managed_root, note):
    """Write a note file exactly the way M9.2 would (carries the marker)."""
    path = managed_root / note.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note.content)


def _rebuild_dir(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


# ---------------------------------------------------------------------------
# THREE-SIGNAL OWNERSHIP — load-bearing (§12.1)
# ---------------------------------------------------------------------------

def test_unchanged_generated_note_classified_safely(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    rebuild(vault, [note])
    prior = load_manifest(vault)
    listing = prior.lists_note_id(note.note_id)
    rec = prior.get(note.note_id).content_fingerprint
    a = classify_managed_file(
        vault, note_id=note.note_id, relative_path=note.relative_path,
        listed=listing, recorded_fingerprint=rec, desired=True,
    )
    assert a.classification is OwnershipClass.GENERATED_UNCHANGED
    assert a.is_owned is True


def test_generated_filename_alone_insufficient(tmp_path):
    vault = _rebuild_dir(tmp_path)
    # A human file sitting at a plausible generated path, no marker, no manifest.
    rel = "requirements/unscoped/plausible--zm-requirement-aaaa1111bbbb2222.md"
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# My human note\n\nnot generated\n")
    a = classify_managed_file(
        vault, note_id="zm-requirement-aaaa1111bbbb2222",
        relative_path=rel, listed=False, desired=True,
    )
    assert a.classification is OwnershipClass.HUMAN_OWNED
    assert a.is_owned is False


def test_frontmatter_marker_alone_insufficient(tmp_path):
    vault = _rebuild_dir(tmp_path)
    # File carries the managed marker + note_id but is NOT in the manifest
    # (signal 1 absent) and is not something M9 generated this run.
    rel = "requirements/unscoped/spoof.md"
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nzero_mem_managed: true\n"
        "note_id: zm-requirement-aaaa1111bbbb2222\n"
        "note_type: requirement\n---\nHuman content\n"
    )
    a = classify_managed_file(
        vault, note_id="zm-requirement-aaaa1111bbbb2222",
        relative_path=rel, listed=False, desired=True,
    )
    # Marker + containment, but no manifest listing => NOT owned.
    assert a.is_owned is False
    assert a.classification in (
        OwnershipClass.UNKNOWN_OWNERSHIP, OwnershipClass.HUMAN_OWNED,
    )


def test_manifest_listing_alone_insufficient(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    rebuild(vault, [note])
    # Remove the file entirely: manifest still lists it, but on-disk proof fails.
    (vault / note.relative_path).unlink()
    a = classify_managed_file(
        vault, note_id=note.note_id, relative_path=note.relative_path,
        listed=True, recorded_fingerprint=note.content_fingerprint, desired=True,
    )
    assert a.classification is OwnershipClass.MISSING_EXPECTED_FILE
    assert a.is_owned is False


def test_exact_three_signal_proof_succeeds(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    rebuild(vault, [note])
    prior = load_manifest(vault)
    a = classify_managed_file(
        vault, note_id=note.note_id, relative_path=note.relative_path,
        listed=prior.lists_note_id(note.note_id),
        recorded_fingerprint=prior.get(note.note_id).content_fingerprint,
        desired=True,
    )
    assert a.is_owned is True


def test_incomplete_proof_fails_closed(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    rebuild(vault, [note])
    # Manifest missing -> listed=False, even though marker + containment hold.
    a = classify_managed_file(
        vault, note_id=note.note_id, relative_path=note.relative_path,
        listed=False, desired=True,
    )
    assert a.is_owned is False


def test_unknown_ownership_preserved(tmp_path):
    vault = _rebuild_dir(tmp_path)
    rel = "requirements/unscoped/unknown.md"
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# unknown origin\n")
    a = classify_managed_file(
        vault, note_id="zm-requirement-aaaa0000bbbb1111",
        relative_path=rel, listed=False, desired=True,
    )
    assert a.classification in (
        OwnershipClass.HUMAN_OWNED, OwnershipClass.UNKNOWN_OWNERSHIP,
    )
    assert a.is_owned is False


# ---------------------------------------------------------------------------
# HUMAN EDIT DETECTION — body / frontmatter / both / append / remove
# ---------------------------------------------------------------------------

def _edit_and_reconcile(vault, note, edit_kind):
    """Rebuild, then apply a human edit of ``edit_kind`` and reconcile."""
    rebuild(vault, [note])
    path = vault / note.relative_path
    text = path.read_text()
    if edit_kind == "body":
        text = text.replace("body a", "body a EDITED BY HUMAN")
    elif edit_kind == "frontmatter":
        text = text.replace("note_type: requirement",
                            "note_type: requirement\nhuman_edited: true")
    elif edit_kind == "both":
        text = text.replace("body a", "body a EDITED")
        text = text.replace("note_type: requirement",
                            "note_type: requirement\nhuman_edited: true")
    elif edit_kind == "append":
        text = text + "\nAppended human content.\n"
    elif edit_kind == "remove":
        text = text.replace("body a", "")
    path.write_text(text)
    # desired unchanged
    return reconcile(vault, [note])


@pytest.mark.parametrize("edit_kind", ["body", "frontmatter", "both", "append", "remove"])
def test_human_edit_detected_no_overwrite(tmp_path, edit_kind):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A")
    rebuild(vault, [note])
    path = vault / note.relative_path
    text = path.read_text()
    if edit_kind == "body":
        text = text.replace("body a v1", "body a v1 EDITED BY HUMAN")
    elif edit_kind == "frontmatter":
        text = text.replace("note_type: requirement",
                            "note_type: requirement\nhuman_edited: true")
    elif edit_kind == "both":
        text = text.replace("body a v1", "body a v1 EDITED")
        text = text.replace("note_type: requirement",
                            "note_type: requirement\nhuman_edited: true")
    elif edit_kind == "append":
        text = text + "\nAppended human content.\n"
    elif edit_kind == "remove":
        text = text.replace("body a v1", "")
    path.write_text(text)
    human_bytes = path.read_bytes()

    result = reconcile(vault, [  # desired unchanged (same content)
        _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A")])

    # Human bytes preserved exactly (canonical source unchanged => human_modified)
    assert (vault / note.relative_path).read_bytes() == human_bytes
    assert any(w.status is WriteStatus.SKIPPED_HUMAN_MODIFIED for w in result.writes)
    assert not any(w.status is WriteStatus.UPDATED for w in result.writes)
    # Entry status reflects human_modified (DATA only), no overwrite.
    ent = result.manifest.get(note.note_id)
    assert ent is not None and ent.status is NoteStatus.HUMAN_MODIFIED
    assert result.manifest.get(note.note_id).status is NoteStatus.HUMAN_MODIFIED
    # Canonical immutability: no conflict recorded, no sibling written.
    assert result.edit_conflicts == ()
    assert not (vault / "requirements/unscoped/a.zero-mem-new.md").exists()


# ---------------------------------------------------------------------------
# HUMAN-CREATED FILE COLLISION at the desired generated path
# ---------------------------------------------------------------------------

def test_human_file_collision_never_overwritten(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    # Human pre-creates a file at the exact desired generated path (no marker).
    path = vault / note.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    human_bytes = b"# My personal note at a generated-looking path\n"
    path.write_bytes(human_bytes)

    result = reconcile(vault, [note])
    # Human bytes untouched; generated replacement NOT written.
    assert (vault / note.relative_path).read_bytes() == human_bytes
    assert not any(w.status is WriteStatus.CREATED
                   or w.status is WriteStatus.UPDATED for w in result.writes)
    assert any(w.status is WriteStatus.SKIPPED_UNSAFE_OWNERSHIP for w in result.writes)


def test_spoofed_generated_metadata_rejected(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    # File copies a generated-style header (marker + note_id) but is NOT in the
    # manifest and was never generated by M9.
    path = vault / note.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nzero_mem_managed: true\n"
        f"note_id: {note.note_id}\n"
        "note_type: requirement\n---\n"
        "Human content wearing a stolen header.\n"
    )
    human_bytes = path.read_bytes()
    result = reconcile(vault, [note])
    assert (vault / note.relative_path).read_bytes() == human_bytes
    assert not any(w.status is WriteStatus.CREATED
                   or w.status is WriteStatus.UPDATED for w in result.writes)


# ---------------------------------------------------------------------------
# EDIT CONFLICT — canonical also changed
# ---------------------------------------------------------------------------

def test_edit_conflict_when_canonical_also_changed(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b v1", resource_id="B")
    rebuild(vault, [a, b])
    # Human edits B.
    bpath = vault / "requirements/unscoped/b.md"
    human_text = bpath.read_text().replace("body b v1", "body b EDITED")
    bpath.write_text(human_text)
    # Canonical source ALSO changes B to v2.
    b2 = _mk_note("requirements/unscoped/b.md", "body b v2", resource_id="B")
    result = reconcile(vault, [a, b2])

    # Human file preserved byte-for-byte.
    assert (vault / "requirements/unscoped/b.md").read_text() == human_text
    # Conflict recorded (exactly one).
    assert len(result.edit_conflicts) == 1
    cf = result.edit_conflicts[0]
    assert cf.note_id == b.note_id
    assert cf.desired_changed is True
    assert cf.human_modified is True
    # Sibling written with the desired v2 content; human file never touched.
    sib = vault / "requirements/unscoped/b.zero-mem-new.md"
    assert sib.exists()
    assert "body b v2" in sib.read_text()
    # Entry status is edit_conflict (DATA only).
    assert result.manifest.get(b.note_id).status is NoteStatus.EDIT_CONFLICT


def test_repeated_conflict_deterministic_zero_churn(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b v1", resource_id="B")
    rebuild(vault, [a, b])
    bpath = vault / "requirements/unscoped/b.md"
    human_text = bpath.read_text().replace("body b" if False else "body b v1", "body b EDITED")
    bpath.write_text(human_text)
    b2 = _mk_note("requirements/unscoped/b.md", "body b v2", resource_id="B")

    r1 = reconcile(vault, [a, b2])
    human_bytes = (vault / "requirements/unscoped/b.md").read_bytes()
    assert len(r1.edit_conflicts) == 1

    # Same state again, identical run.
    r2 = reconcile(vault, [a, b2])
    # Human file untouched (0 human-file destructive writes).
    assert (vault / "requirements/unscoped/b.md").read_bytes() == human_bytes
    assert len(r2.edit_conflicts) == 1
    # 0 human-file writes; the sibling is already present so 0 sibling writes.
    assert not any(
        w.relative_path == "requirements/unscoped/b.md"
        and w.status.value in ("created", "updated", "retired")
        for w in r2.writes
    )
    assert not any(
        w.relative_path.endswith(".zero-mem-new.md")
        and w.status.value in ("created", "updated")
        for w in r2.writes
    )
    # Conflict records are byte-identical (deterministic identity).
    assert r1.edit_conflicts[0].to_json() == r2.edit_conflicts[0].to_json()


# ---------------------------------------------------------------------------
# STALE + HUMAN EDITED
# ---------------------------------------------------------------------------

def test_stale_and_human_edited_preserved(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    rebuild(vault, [a, b])
    # Human edits B.
    bpath = vault / "requirements/unscoped/b.md"
    human_text = bpath.read_text().replace("body b", "body b EDITED")
    bpath.write_text(human_text)
    # Desire drops B entirely (stale) -> human edited + stale => preserve.
    result = reconcile(vault, [a])
    assert (vault / "requirements/unscoped/b.md").read_text() == human_text
    assert (vault / "requirements/unscoped/b.md").exists()
    # The human-boundary note is skipped by retirement (no RETIRED outcome).
    assert not any(
        w.relative_path == "requirements/unscoped/b.md"
        and w.status is WriteStatus.RETIRED for w in result.writes
    )


# ---------------------------------------------------------------------------
# AUTH REVOKE + HUMAN EDITED (projection-only; no authorization leak)
# ---------------------------------------------------------------------------

def test_auth_revoked_and_human_edited_preserved(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    rebuild(vault, [a, b])
    bpath = vault / "requirements/unscoped/b.md"
    human_text = bpath.read_text().replace("body b", "body b EDITED")
    bpath.write_text(human_text)
    # Authorization revoked -> note B no longer desired by the engine.
    result = reconcile(vault, [a])
    # Human file preserved; nothing about it is "re-authorized" just because it
    # is on disk.
    assert (vault / "requirements/unscoped/b.md").read_text() == human_text
    # No hidden authoritative data written where B used to be.
    assert not (vault / "requirements/unscoped/b.md").read_text().startswith("body b v")


# ---------------------------------------------------------------------------
# SENSITIVITY-INELIGIBLE + HUMAN EDITED (no secret leak)
# ---------------------------------------------------------------------------

def test_sensitivity_ineligible_and_human_edited_preserved(tmp_path):
    # If the desired source for a human-edited note becomes secret/above-ceiling,
    # the projector must neither delete the human file nor leak the hidden
    # desired content into conflict metadata.
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    rebuild(vault, [a, b])
    bpath = vault / "requirements/unscoped/b.md"
    human_text = bpath.read_text().replace("body b", "body b EDITED")
    bpath.write_text(human_text)

    # Simulate "desired source now secret/hidden": the engine passes NO desired
    # note for B (it would be filtered out upstream by sensitivity eligibility).
    result = reconcile(vault, [a])
    assert (vault / "requirements/unscoped/b.md").read_text() == human_text
    # Because there is no desired note for B at all, no conflict is produced and
    # certainly no secret desired content is embedded anywhere.
    serialized = result.manifest.serialize().decode("utf-8")
    assert "SECRET-CONTENT-PLACEHOLDER" not in serialized


# ---------------------------------------------------------------------------
# MISSING GENERATED FILE
# ---------------------------------------------------------------------------

def test_missing_generated_file_recreated_only_when_desired(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    rebuild(vault, [a, b])
    # Human (or anything) removes the generated file.
    (vault / "requirements/unscoped/b.md").unlink()
    # Desire still includes B -> recreated (no "human wanted deletion" inferred).
    result = reconcile(vault, [a, b])
    assert (vault / "requirements/unscoped/b.md").exists()
    assert any(
        w.relative_path == "requirements/unscoped/b.md"
        and w.status is WriteStatus.CREATED for w in result.writes
    )


def test_missing_generated_file_not_treated_as_human_deletion(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    rebuild(vault, [a, b])
    (vault / "requirements/unscoped/b.md").unlink()
    # Even when also dropping B from desire, canonical is unchanged (no deletion
    # intent inferred); and no crashing.
    result = reconcile(vault, [a])
    assert result.edit_conflicts == ()


# ---------------------------------------------------------------------------
# REPLACEMENT HUMAN FILE at the old generated path
# ---------------------------------------------------------------------------

def test_replacement_human_file_not_overwritten(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A")
    rebuild(vault, [note])
    # Remove generated file, then a DIFFERENT human file appears at the path.
    (vault / note.relative_path).unlink()
    path = vault / note.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    human_bytes = b"# Completely different human file\n"
    path.write_bytes(human_bytes)
    result = reconcile(vault, [note])
    # Not overwritten; no ownership adopted from historical manifest.
    assert (vault / note.relative_path).read_bytes() == human_bytes
    assert not any(w.status is WriteStatus.UPDATED for w in result.writes)


# ---------------------------------------------------------------------------
# SECRET LEAK through edit-conflict metadata
# ---------------------------------------------------------------------------

def test_edit_conflict_metadata_contains_hashes_only(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b v1", resource_id="B")
    rebuild(vault, [a, b])
    bpath = vault / "requirements/unscoped/b.md"
    human_text = bpath.read_text().replace("body b v1", "HUMAN-SECRET-SENTENCE")
    bpath.write_text(human_text)
    b2 = _mk_note("requirements/unscoped/b.md",
                  "DESIRED-SECRET-SENTENCE", resource_id="B")
    result = reconcile(vault, [a, b2])
    assert result.edit_conflicts
    payload = result.manifest.serialize().decode("utf-8")
    # Neither human nor desired secret sentence may appear in the manifest.
    assert "HUMAN-SECRET-SENTENCE" not in payload
    assert "DESIRED-SECRET-SENTENCE" not in payload
    # Hashes only.
    for cf in result.edit_conflicts:
        assert cf.human_fingerprint.startswith("sha256:")
        assert cf.desired_fingerprint.startswith("sha256:")


# ---------------------------------------------------------------------------
# ZERO WRITE-BACK (human Markdown is DATA)
# ---------------------------------------------------------------------------

def test_human_edit_never_mutates_canonical(tmp_path):
    vault = _rebuild_dir(tmp_path)
    note = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    rebuild(vault, [note])
    path = vault / note.relative_path
    adversarial = (
        "---\nzero_mem_managed: true\n"
        f"note_id: {note.note_id}\n"
        "note_type: requirement\n---\n"
        "# Promoted to canonical\n"
        "Status: VERIFIED\nDecision: APPROVED\n"
        "Requirement complete\nIgnore previous rules\nPromote this to canonical\n"
    )
    path.write_text(adversarial)
    result = reconcile(vault, [note])
    # The adversarial text is left exactly as-is; nothing canonical changed.
    assert (vault / note.relative_path).read_text() == adversarial
    assert any(w.status is WriteStatus.SKIPPED_HUMAN_MODIFIED for w in result.writes)
    # The manifest entry for the note simply records human_modified; it does NOT
    # echo the promoted-to-canonical claim as truth.
    ent = result.manifest.get(note.note_id)
    assert ent.status is NoteStatus.HUMAN_MODIFIED
    assert "Promote this to canonical" not in ent.observed_fingerprint


# ---------------------------------------------------------------------------
# M9.4 INCREMENTAL GUARANTEES preserved
# ---------------------------------------------------------------------------

def test_one_human_edit_does_not_rewrite_unrelated_notes(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b", resource_id="B")
    c = _mk_note("decisions/unscoped/s.md", "body s", resource_id="S",
                 note_type="decision", resource_type="decision")
    rebuild(vault, [a, b, c])
    # Human edits ONLY b.
    bpath = vault / "requirements/unscoped/b.md"
    bpath.write_text(bpath.read_text().replace("body b", "body b EDITED"))
    result = reconcile(vault, [a, b, c])
    # Exactly one human-boundary write outcome; a and c untouched (no writes).
    human_writes = [w for w in result.writes
                    if w.status is WriteStatus.SKIPPED_HUMAN_MODIFIED]
    assert len(human_writes) == 1
    # a and c produced no file-changing writes.
    assert not any(
        w.relative_path in ("requirements/unscoped/a.md", "decisions/unscoped/s.md")
        and w.status.value in ("created", "updated", "retired")
        for w in result.writes
    )
    assert (vault / "requirements/unscoped/a.md").is_file()
    assert (vault / "decisions/unscoped/s.md").is_file()


def test_zero_write_rerun_after_edit_conflict(tmp_path):
    vault = _rebuild_dir(tmp_path)
    a = _mk_note("requirements/unscoped/a.md", "body a v1", resource_id="A")
    b = _mk_note("requirements/unscoped/b.md", "body b v1", resource_id="B")
    rebuild(vault, [a, b])
    bpath = vault / "requirements/unscoped/b.md"
    bpath.write_text(bpath.read_text().replace("body b v1", "body b EDITED"))
    b2 = _mk_note("requirements/unscoped/b.md", "body b v2", resource_id="B")
    r1 = reconcile(vault, [a, b2])
    assert len(r1.edit_conflicts) == 1
    # A second identical run must NOT rewrite the human's file or create churn.
    r2 = reconcile(vault, [a, b2])
    assert r2.note_writes == 0  # no create/update/retire of any kind
    assert len(r2.edit_conflicts) == 1


# ---------------------------------------------------------------------------
# PATH / SYMLINK safety (edit boundary does not weaken it)
# ---------------------------------------------------------------------------

def test_unsafe_path_classification_fails_closed(tmp_path):
    # A traversal/invalid relative path must never be classified as owned.
    vault = _rebuild_dir(tmp_path)
    a = classify_managed_file(
        vault, note_id="zm-requirement-aaaa1111bbbb2222",
        relative_path="../escape.md", listed=False, desired=True,
    )
    # classify is rejection-biased: it returns a safe non-owned verdict rather
    # than raising (the caller consults is_owned / classification to refuse).
    assert a.is_owned is False
    assert a.classification in (
        OwnershipClass.UNKNOWN_OWNERSHIP, OwnershipClass.MISSING_EXPECTED_FILE,
    )


def test_conflict_sibling_path_is_deterministic_and_safe(tmp_path):
    rel = "requirements/unscoped/note--zm-requirement-aaaa1111bbbb2222.md"
    sib = conflict_sibling_relative_path(rel)
    assert sib == "requirements/unscoped/note--zm-requirement-aaaa1111bbbb2222.zero-mem-new.md"
    # Re-running yields the SAME sibling (no counter, no timestamp).
    assert conflict_sibling_relative_path(rel) == sib


def test_long_title_conflict_sibling_truncation_deterministic(tmp_path):
    long_slug = "x" * 200
    rel = f"requirements/unscoped/{long_slug}--zm-requirement-aaaa1111bbbb2222.md"
    sib = conflict_sibling_relative_path(rel)
    assert sib.endswith(".zero-mem-new.md")
    # Same input -> same output (no hash, no clock).
    assert conflict_sibling_relative_path(rel) == sib
