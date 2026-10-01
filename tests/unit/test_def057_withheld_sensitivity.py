"""DEF-057 (T1 part): a single pure predicate for "this sensitivity is withheld from derived/retrieved output".

``src/corpus/contracts.py`` documents that ``secret`` sources are withheld (never stored or projected by the
corpus path). Projection (T2) and retrieval (T3) enforce it through this one predicate instead of each
re-implementing a string comparison. Fail closed: anything that is not a recognized non-secret level is withheld.
"""
from __future__ import annotations

import pytest

from src.corpus.contracts import SourceSensitivity, is_withheld_sensitivity


def test_secret_is_withheld_as_enum_and_string():
    assert is_withheld_sensitivity(SourceSensitivity.SECRET) is True
    assert is_withheld_sensitivity("secret") is True


@pytest.mark.parametrize("level", ["public", "internal", "private",
                                   SourceSensitivity.PUBLIC, SourceSensitivity.INTERNAL,
                                   SourceSensitivity.PRIVATE])
def test_non_secret_levels_are_not_withheld(level):
    assert is_withheld_sensitivity(level) is False


@pytest.mark.parametrize("value", [None, "", "SECRET", "Secret", " secret", "top-secret", "confidential", 0, 1, b"secret", ["secret"]])
def test_unknown_or_malformed_values_fail_closed(value):
    assert is_withheld_sensitivity(value) is True


def test_predicate_matches_the_closed_enum_exactly():
    withheld = {s for s in SourceSensitivity if is_withheld_sensitivity(s)}
    assert withheld == {SourceSensitivity.SECRET}
