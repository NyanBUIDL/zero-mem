"""T7 - the fast scoring tokenizer must split and fold exactly like the original character loop.

The ranking code tokenizes every candidate unit on every query; the original per-character loop was the main
latency cost of ``Memory.recall`` (about 20 ms of 29 ms median on a LoCoMo conversation).  The regex version is only
acceptable while it is observably identical, so this file keeps the original loop as the reference.
"""
from __future__ import annotations

import random
import unicodedata

import pytest

from src.corpus import retrieval


def _ref_is_word_char(ch: str) -> bool:
    return ch.isalnum() or unicodedata.category(ch)[0] == "M"


def _ref_split(text: str) -> list[str]:
    words, current = [], []
    for ch in unicodedata.normalize("NFC", text):
        if _ref_is_word_char(ch):
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def _ref_fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFD", word.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d")


SAMPLES = [
    "",
    "   ",
    "Caroline: I went to the LGBTQ support group yesterday!",
    "blue-green deploy, pre-commit hooks; C++ and C# (and F#)",
    "snake_case_name and CamelCase2Name",
    "Tiếng Việt có dấu: Nguyễn Văn Đạt đã đến Hà Nội ngày 12/03",
    "Café au lait, naïve résumé",  # decomposed accents stay inside their word
    "日本語のテキストと中文文本 mixed with english",
    "emoji 🎉 party 🎈 time",
    "Ångström, İstanbul, straße, ÇA VA",
    "tabs\tand\nnewlines\r\nand nbsp em-space",
    "12:30pm on 2023-05-07, $1,234.56 (approx.)",
    "ﬁne ligature and ǆ digraph",
    "हिन्दी पाठ और தமிழ் உரை",  # Indic vowel signs are combining marks inside words
    "x" * 500 + " " + "y" * 20,
]


@pytest.mark.parametrize("text", SAMPLES)
def test_split_words_matches_the_reference_loop(text):
    assert retrieval._split_words(text) == _ref_split(text)


@pytest.mark.parametrize("word", ["Hello", "Việt", "Đạt", "đường", "Café", "Ångström", "straße", "İstanbul", "日本", "x"])
def test_fold_matches_the_reference(word):
    assert retrieval._fold(word) == _ref_fold(word)


def test_random_strings_split_identically():
    rng = random.Random(20261001)
    alphabet = list("abcXYZ019 _-.,;:!?'\"()/\\\t\n") + list("éèêàùçñöüßđĐăâêôơưệ") + ["́", "̣", "日", "本", "🎉"]
    for _ in range(400):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        assert retrieval._split_words(text) == _ref_split(text), repr(text)
        for word in _ref_split(text):
            assert retrieval._fold(word) == _ref_fold(word), repr(word)


# ----------------------------------------------------------------------------- phrase matching parity
def _ref_token_matches(token: str, term: str) -> bool:
    return token.startswith(term) if len(term) > 1 else token == term


def _ref_has_phrase(tokens, phrase) -> bool:
    width = len(phrase)
    for start in range(len(tokens) - width + 1):
        if all(_ref_token_matches(tokens[start + i], phrase[i]) for i in range(width)):
            return True
    return False


def test_has_phrase_matches_the_reference_on_random_token_streams():
    rng = random.Random(7)
    vocab = ["blue", "green", "greenhouse", "c", "x", "rollout", "roll", "pre", "commit", "a", "ab", "abc", "deploy"]
    for _ in range(600):
        tokens = [rng.choice(vocab) for _ in range(rng.randint(0, 12))]
        phrase = tuple(rng.choice(vocab) for _ in range(rng.randint(2, 3)))
        assert retrieval._has_phrase(tokens, phrase) == _ref_has_phrase(tokens, phrase), (tokens, phrase)


def test_prefix_term_frequency_matches_a_full_scan():
    rng = random.Random(3)
    vocab = ["roll", "rollout", "rolls", "rolled", "ro", "r", "blue", "green", "5", "23", "2023", "x", "xy"]
    for _ in range(300):
        text = " ".join(rng.choice(vocab) for _ in range(rng.randint(0, 15)))
        doc = retrieval._doc_terms(text)
        for word in vocab:
            term = retrieval._QueryTerm(word, word, "")
            expected = (sum(c for t, c in doc[1].items() if t.startswith(word)) if len(word) > 1
                        else doc[1].get(word, 0))
            assert retrieval._term_frequency(doc, term) == expected, (text, word)
