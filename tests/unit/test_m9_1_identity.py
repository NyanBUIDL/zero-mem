"""M9.1 — deterministic note identity, slug totality, and filename tests.

Identity must be reproducible from canonical inputs alone, across processes and
``PYTHONHASHSEED`` values (plan-m9.md §9 / §16.2).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.projection.contracts import NoteType, ProjectionVocabularyError
from src.projection.identity import (
    FILENAME_SEPARATOR,
    MAX_SLUG_LENGTH,
    NOTE_ID_DIGEST_CHARS,
    NOTE_ID_PREFIX,
    RESERVED_FILENAMES,
    content_fingerprint,
    derive_note_id,
    note_filename,
    note_id_suffix,
    slug,
    validate_note_id,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _id(**overrides):
    kwargs = dict(
        note_type=NoteType.DECISION,
        resource_type="decision",
        resource_id="DEC-014",
        project_id="hermes-external-zero-mem",
        profile_id="developer",
    )
    kwargs.update(overrides)
    return derive_note_id(**kwargs)


class TestNoteIdDeterminism:
    def test_same_inputs_same_id(self):
        assert _id() == _id()

    def test_id_shape(self):
        note_id = _id()
        assert note_id.startswith(NOTE_ID_PREFIX + "decision-")
        assert len(note_id_suffix(note_id)) == NOTE_ID_DIGEST_CHARS

    def test_note_type_changes_identity(self):
        assert _id(note_type=NoteType.DECISION) != _id(note_type=NoteType.REQUIREMENT)

    def test_resource_type_changes_identity(self):
        """M6.6: same raw id under a different resource type is a DIFFERENT resource."""
        assert _id(resource_type="decision") != _id(resource_type="artifact")

    def test_resource_id_changes_identity(self):
        assert _id(resource_id="DEC-014") != _id(resource_id="DEC-015")

    def test_project_scope_changes_identity(self):
        assert _id(project_id="a") != _id(project_id="b")

    def test_profile_scope_changes_identity(self):
        assert _id(profile_id="dev") != _id(profile_id="ops")

    def test_none_scope_is_distinct_from_empty_and_from_a_value(self):
        unbound = _id(profile_id=None)
        bound = _id(profile_id="developer")
        assert unbound != bound
        with pytest.raises(ProjectionVocabularyError):
            _id(profile_id="")

    def test_title_never_participates_in_identity(self):
        note_id = _id()
        assert note_filename(note_id=note_id, display_title="One")[-19:] == \
            note_filename(note_id=note_id, display_title="Two")[-19:]

    def test_identity_is_stable_across_processes_and_hashseeds(self):
        script = (
            "import sys; sys.path.insert(0, %r);"
            "from src.projection.identity import derive_note_id;"
            "from src.projection.contracts import NoteType;"
            "print(derive_note_id(note_type=NoteType.DECISION, resource_type='decision',"
            "resource_id='DEC-014', project_id='hermes-external-zero-mem',"
            "profile_id='developer'))" % str(REPO_ROOT)
        )
        results = set()
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            out = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), check=True,
            )
            results.add(out.stdout.strip())
        assert len(results) == 1
        assert results == {_id()}

    def test_invalid_resource_type_fails_closed(self):
        with pytest.raises(ProjectionVocabularyError):
            _id(resource_type="not_a_resource_type")

    def test_missing_resource_id_fails_closed(self):
        for bad in ("", "   ", None):
            with pytest.raises(ProjectionVocabularyError):
                _id(resource_id=bad)


class TestNoteIdValidation:
    def test_valid_id_round_trips(self):
        note_id = _id()
        assert validate_note_id(note_id) == note_id

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "decision-abc",
            "zm-",
            "zm-decision-",
            "zm-notatype-0123456789abcdef",
            "zm-decision-XYZ",
            "zm-decision-0123456789abcde",     # one char short
            "zm-decision-0123456789abcdef0",   # one char long
            "zm-decision-0123456789abcdeZ",    # non-hex
            "zm-decision-../../etc/passwd",
        ],
    )
    def test_malformed_id_rejected(self, bad):
        with pytest.raises(ProjectionVocabularyError):
            validate_note_id(bad)


class TestSlugTotality:
    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            None,
            "...",
            "!!!???",
            "///",
            "\\\\\\",
            "..",
            ".",
            "\x00",
            "\u200b\u200c\u200d",   # zero-width only
            "\u202e",               # bidi override only
            "\t\n\r",
        ],
    )
    def test_degenerate_input_falls_back(self, value):
        result = slug(value, fallback="note")
        assert result == "note"

    def test_slug_never_contains_unsafe_characters(self):
        hostile = "../../etc/passwd\x00\\C:\\Windows |[[link]] #tag\n---"
        result = slug(hostile)
        assert all(c.islower() or c.isdigit() or c == "-" for c in result)
        for banned in ("/", "\\", "\x00", ":", " ", "..", "|", "[", "#"):
            assert banned not in result

    def test_slug_has_no_outer_dashes(self):
        assert not slug("---hello---").startswith("-")
        assert not slug("---hello---").endswith("-")

    def test_slug_length_capped(self):
        result = slug("a" * 5000)
        assert len(result) <= MAX_SLUG_LENGTH

    def test_long_slug_truncation_is_deterministic(self):
        long_title = "decision about " + ("x" * 500)
        assert slug(long_title) == slug(long_title)

    def test_unicode_normalization_equivalence(self):
        assert slug("café") == slug("cafe\u0301")

    def test_case_insensitive_titles_produce_same_slug(self):
        assert slug("Decision") == slug("decision") == slug("DECISION")

    def test_reserved_names_are_neutralized(self):
        for reserved in sorted(RESERVED_FILENAMES):
            result = slug(reserved)
            assert result not in RESERVED_FILENAMES
            assert result.startswith(reserved)

    def test_control_characters_stripped(self):
        # Control characters are REMOVED (not mapped to a separator), so they
        # cannot pad a slug or forge a visual separator.
        assert slug("a\x01\x02b") == "ab"
        assert slug("a\x00b") == "ab"

    def test_slug_is_deterministic(self):
        for value in ("Adopt SQLite", "Quyết định kiến trúc", "  spaced  out  "):
            assert slug(value) == slug(value)

    def test_non_string_input_rejected(self):
        with pytest.raises(ProjectionVocabularyError):
            slug(123)  # type: ignore[arg-type]


class TestFilenames:
    def test_filename_shape(self):
        note_id = _id()
        name = note_filename(note_id=note_id, display_title="Adopt SQLite")
        assert name == f"adopt-sqlite{FILENAME_SEPARATOR}{note_id_suffix(note_id)}.md"

    def test_duplicate_titles_do_not_collide(self):
        first = _id(resource_id="DEC-1")
        second = _id(resource_id="DEC-2")
        assert note_filename(note_id=first, display_title="Same Title") != \
            note_filename(note_id=second, display_title="Same Title")

    def test_same_slug_different_stable_ids(self):
        first = note_filename(note_id=_id(resource_id="A"), display_title="X")
        second = note_filename(note_id=_id(resource_id="B"), display_title="X")
        assert first.split(FILENAME_SEPARATOR)[0] == second.split(FILENAME_SEPARATOR)[0]
        assert first != second

    def test_same_stable_id_deterministic_filename(self):
        note_id = _id()
        assert note_filename(note_id=note_id, display_title="T") == \
            note_filename(note_id=note_id, display_title="T")

    def test_empty_title_uses_note_type_fallback(self):
        note_id = _id()
        name = note_filename(note_id=note_id, display_title="")
        assert name.startswith("decision" + FILENAME_SEPARATOR)

    def test_title_change_keeps_identity_suffix(self):
        note_id = _id()
        first = note_filename(note_id=note_id, display_title="Old")
        second = note_filename(note_id=note_id, display_title="New")
        assert first.split(FILENAME_SEPARATOR)[1] == second.split(FILENAME_SEPARATOR)[1]

    def test_case_only_title_difference_yields_identical_filename(self):
        """Case-insensitive filesystems cannot see two variants of one note."""
        note_id = _id()
        assert note_filename(note_id=note_id, display_title="Decision") == \
            note_filename(note_id=note_id, display_title="DECISION")

    def test_invalid_note_id_rejected(self):
        with pytest.raises(ProjectionVocabularyError):
            note_filename(note_id="not-an-id", display_title="x")


class TestContentFingerprint:
    def test_deterministic(self):
        assert content_fingerprint("body") == content_fingerprint("body")

    def test_prefix_and_length(self):
        value = content_fingerprint("body")
        assert value.startswith("sha256:")
        assert len(value.split(":", 1)[1]) == 64

    def test_different_content_different_fingerprint(self):
        assert content_fingerprint("a") != content_fingerprint("b")

    def test_empty_content_supported(self):
        assert content_fingerprint("").startswith("sha256:")

    def test_no_wall_clock_influence(self):
        first = content_fingerprint("stable body")
        second = content_fingerprint("stable body")
        assert first == second

    def test_non_string_rejected(self):
        with pytest.raises(ProjectionVocabularyError):
            content_fingerprint(None)  # type: ignore[arg-type]

    def test_fingerprint_domain_separated_from_note_id(self):
        assert not content_fingerprint("x").startswith(NOTE_ID_PREFIX)
