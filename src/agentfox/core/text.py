"""Word tokens, shared by the eval scorers and the offline provider's judge.

Deterministic and dependency-free: a lowercase word split and a stopword filter.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9']+")

#: Words too common to carry evidence of grounding.
_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "then",
    "of",
    "to",
    "in",
    "on",
    "at",
    "for",
    "with",
    "as",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
    "you",
    "your",
    "we",
    "our",
    "they",
    "their",
    "i",
    "he",
    "she",
    "not",
    "no",
    "can",
    "will",
    "would",
    "should",
    "may",
    "there",
    "from",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "so",
    "than",
    "also",
}


def tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def content_tokens(text: str) -> set[str]:
    """Tokens that carry evidence.

    Numerals are kept regardless of length. "30" vs "90" is exactly the kind of
    difference a confidently-wrong answer turns on, and dropping short tokens would
    make the two indistinguishable to the grounding check.
    """
    return {
        t
        for t in tokens(text)
        if (t not in _STOPWORDS and len(t) > 2) or any(c.isdigit() for c in t)
    }


__all__ = ["content_tokens", "tokens"]
