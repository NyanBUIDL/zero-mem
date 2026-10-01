"""Deterministic English suffix stemming for lexical retrieval (the 1980 Porter algorithm, stdlib only).

Used by ``src/corpus/retrieval.py`` to let an inflected query term ("adopted", "teaching") match the other forms of the
same word ("adopt", "adoption", "teacher").  Pure and dependency free; callers fold case/diacritics first and only
pass plain ASCII letters (``stem`` returns every other token unchanged, so Vietnamese or numeric tokens are never
rewritten by English rules).
"""
from __future__ import annotations

from functools import lru_cache

_VOWELS = frozenset("aeiou")


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in _VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """Number of vowel-consonant sequences in ``stem`` ([C](VC){m}[V])."""
    count = 0
    i, n = 0, len(stem)
    while i < n and _is_consonant(stem, i):
        i += 1
    while i < n:
        while i < n and not _is_consonant(stem, i):
            i += 1
        if i >= n:
            break
        count += 1
        while i < n and _is_consonant(stem, i):
            i += 1
    return count


def _has_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(word: str) -> bool:
    return len(word) >= 2 and word[-1] == word[-2] and _is_consonant(word, len(word) - 1)


def _cvc(word: str) -> bool:
    """Ends consonant-vowel-consonant where the last consonant is not w, x or y."""
    n = len(word)
    if n < 3:
        return False
    return (_is_consonant(word, n - 3) and not _is_consonant(word, n - 2) and _is_consonant(word, n - 1)
            and word[-1] not in "wxy")


def _replace(word: str, suffix: str, replacement: str, min_measure: int):
    """``(new_word, matched)``: replace ``suffix`` when the remaining stem has measure > ``min_measure``."""
    if not word.endswith(suffix):
        return word, False
    stem = word[: len(word) - len(suffix)]
    if _measure(stem) > min_measure:
        return stem + replacement, True
    return word, True  # the longest matching suffix decides; a failed condition ends the step


_STEP2 = (
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"), ("izer", "ize"), ("abli", "able"),
    ("alli", "al"), ("entli", "ent"), ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"), ("ousness", "ous"), ("aliti", "al"),
    ("iviti", "ive"), ("biliti", "ble"),
)
_STEP3 = (
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"), ("ical", "ic"), ("ful", ""), ("ness", ""),
)
_STEP4 = (
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment", "ent", "ion", "ou", "ism", "ate",
    "iti", "ous", "ive", "ize",
)


def _step1a(word: str) -> str:
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def _step1b(word: str) -> str:
    if word.endswith("eed"):
        return word[:-1] if _measure(word[:-3]) > 0 else word
    for suffix in ("ed", "ing"):
        if word.endswith(suffix) and _has_vowel(word[: -len(suffix)]):
            word = word[: -len(suffix)]
            if word.endswith(("at", "bl", "iz")):
                return word + "e"
            if _ends_double_consonant(word) and word[-1] not in "lsz":
                return word[:-1]
            if _measure(word) == 1 and _cvc(word):
                return word + "e"
            return word
    return word


def _step1c(word: str) -> str:
    if word.endswith("y") and _has_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


def _step2_3(word: str, table) -> str:
    for suffix, replacement in sorted(table, key=lambda item: -len(item[0])):
        if word.endswith(suffix):
            return _replace(word, suffix, replacement, 0)[0]
    return word


def _step4(word: str) -> str:
    for suffix in sorted(_STEP4, key=len, reverse=True):
        if word.endswith(suffix):
            stem = word[: len(word) - len(suffix)]
            if suffix == "ion" and not stem.endswith(("s", "t")):
                continue
            return stem if _measure(stem) > 1 else word
    return word


def _step5(word: str) -> str:
    if word.endswith("e"):
        stem = word[:-1]
        measure = _measure(stem)
        if measure > 1 or (measure == 1 and not _cvc(stem)):
            word = stem
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        word = word[:-1]
    return word


@lru_cache(maxsize=65536)
def stem(token: str) -> str:
    """The Porter stem of a lowercase ASCII-letter token; anything else (digits, accents, short words) is unchanged."""
    if len(token) <= 2 or not (token.isascii() and token.isalpha()):
        return token
    word = _step1c(_step1b(_step1a(token)))
    word = _step2_3(word, _STEP2)
    word = _step2_3(word, _STEP3)
    return _step5(_step4(word))


__all__ = ["stem"]
