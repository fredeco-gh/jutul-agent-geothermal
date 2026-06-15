"""Unit tests for eval scorers whose logic is worth pinning directly."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("inspect_ai", reason="eval extra not installed")

from inspect_ai.scorer import CORRECT, INCORRECT

from jutul_agent.eval.scorers import _levenshtein, reads_word


def test_levenshtein_basic() -> None:
    assert _levenshtein("SINTEF", "SINTEF") == 0
    assert _levenshtein("SINTEF", "SINEF") == 1  # one deletion
    assert _levenshtein("SINTEF", "SINTERF") == 1  # one insertion
    assert _levenshtein("SINTEF", "SINTEX") == 1  # one substitution
    assert _levenshtein("SINTEF", "SHIFT") >= 3
    assert _levenshtein("", "abc") == 3


def _score(scorer, completion: str):
    state = SimpleNamespace(output=SimpleNamespace(completion=completion))
    return asyncio.run(scorer(state, None)).value


def test_reads_word_tolerates_one_slip() -> None:
    s = reads_word("SINTEF", max_edits=1)
    # Exact and single-slip reads pass (a plotted-word OCR may drop/double a letter).
    assert _score(s, "The points spell **SINTEF**.") == CORRECT
    assert _score(s, "It spells SINEF") == CORRECT
    assert _score(s, "I read SINTERF") == CORRECT
    # An unrelated word, or no word, does not.
    assert _score(s, "The word is SIMPLE") == INCORRECT
    assert _score(s, "It looks like HELLO to me") == INCORRECT
    assert _score(s, "no letters, just 123") == INCORRECT


def test_reads_word_is_case_insensitive() -> None:
    s = reads_word("SINTEF")
    assert _score(s, "the word is sintef") == CORRECT
