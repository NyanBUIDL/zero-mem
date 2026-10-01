"""T7 - English suffix stemming (Porter 1980) used by the lexical ranking.

The reference pairs are the examples published with the algorithm (Porter, "An algorithm for suffix stripping").
"""
from __future__ import annotations

import pytest

from src.corpus.stemming import stem

PAIRS = """
caresses caress ponies poni ties ti caress caress cats cat feed feed agreed agre plastered plaster bled bled
motoring motor sing sing conflated conflat troubled troubl sized size hopping hop tanned tan falling fall
hissing hiss fizzed fizz failing fail filing file happy happi sky sky relational relat conditional condit
rational ration valenci valenc hesitanci hesit digitizer digit conformabli conform radicalli radic
differentli differ vileli vile analogousli analog vietnamization vietnam predication predic operator oper
feudalism feudal decisiveness decis hopefulness hope callousness callous formaliti formal sensitiviti sensit
sensibiliti sensibl triplicate triplic formative form formalize formal electriciti electr electrical electr
hopeful hope goodness good revival reviv allowance allow inference infer airliner airlin gyroscopic gyroscop
adjustable adjust defensible defens irritant irrit replacement replac adjustment adjust dependent depend
adoption adopt homologou homolog communism commun activate activ angulariti angular homologous homolog
effective effect bowdlerize bowdler probate probat rate rate cease ceas controll control roll roll
""".split()


@pytest.mark.parametrize("word,expected", list(zip(PAIRS[::2], PAIRS[1::2])))
def test_published_porter_examples(word, expected):
    assert stem(word) == expected


@pytest.mark.parametrize("group", [
    ["adopt", "adopted", "adopting", "adopts", "adoption"],
    ["learn", "learned", "learning", "learns"],
    ["live", "living", "lived", "lives"],
    ["run", "running", "runs"],
    ["study", "studies", "studying", "studied"],
    ["walk", "walked", "walking", "walks"],
    ["paint", "painted", "painting", "paints"],
])
def test_inflected_forms_share_one_stem(group):
    assert len({stem(word) for word in group}) == 1, [stem(word) for word in group]


@pytest.mark.parametrize("word", ["a", "of", "is", "c", "", "2023", "12th", "c++", "đường", "việt", "café", "x1y"])
def test_short_non_ascii_or_non_alphabetic_tokens_are_never_rewritten(word):
    assert stem(word) == word


def test_stem_is_deterministic_and_cached():
    assert [stem("generalizations") for _ in range(3)] == ["gener"] * 3
