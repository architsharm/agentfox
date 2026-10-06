"""A cheap, sound pre-check that lets a regex be skipped on text it cannot match.

Python's `re` scans the whole input once per pattern, so a detector with dozens of
patterns pays dozens of passes over a large benign document even though almost none
of them can match. Most patterns open with a fixed word ("ignore", "reveal", "you
are now"). If none of the words a match must begin with appear anywhere in the text,
the pattern cannot match and the scan is skipped; `str.__contains__` finds that out
far faster than the regex engine.

The check only ever skips. When a pattern's opening cannot be reduced to literals
(a character class, an optional group, a backreference) it is always run, and the
check is not applied to non-ASCII text, where case-insensitive matching folds
characters that `str.lower` does not (the Kelvin sign, long s, dotted capital I).
"""

from __future__ import annotations

import re
from re import _constants as _C
from re import _parser as _P

_ZERO_WIDTH = {_C.AT, _C.ASSERT, _C.ASSERT_NOT}
_REPEATS = {_C.MAX_REPEAT, _C.MIN_REPEAT, _C.POSSESSIVE_REPEAT}


def opening_literals(pattern: re.Pattern[str]) -> frozenset[str] | None:
    """The lower-cased literals one of which every match of `pattern` starts with.

    None when no such set can be derived; the pattern must then always run.
    """
    try:
        parsed = _P.parse(pattern.pattern, pattern.flags)
    except Exception:  # noqa: BLE001 - anything unparseable simply always runs
        return None
    found = _opening(list(parsed))
    if not found or any(len(s) < 2 for s in found):
        return None
    return frozenset(s.lower() for s in found)


def _opening(items: list) -> set[str] | None:
    i = 0
    while i < len(items) and items[i][0] in _ZERO_WIDTH:
        i += 1
    if i >= len(items):
        return None
    op, av = items[i]
    if op is _C.LITERAL:
        text = ""
        while i < len(items) and items[i][0] is _C.LITERAL:
            text += chr(items[i][1])
            i += 1
        return {text}
    if op is _C.SUBPATTERN:
        return _opening(list(av[-1]))
    if op is _C.BRANCH:
        acc: set[str] = set()
        for alternative in av[1]:
            found = _opening(list(alternative))
            if found is None:
                return None
            acc |= found
        return acc
    if op in _REPEATS and av[0] >= 1:
        return _opening(list(av[2]))
    return None


class LoweredText:
    """One text, lower-cased once, for checking many patterns against."""

    __slots__ = ("ascii", "lowered")

    def __init__(self, text: str) -> None:
        self.ascii = text.isascii()
        self.lowered = text.lower() if self.ascii else ""

    def may_match(self, literals: frozenset[str] | None) -> bool:
        if literals is None or not self.ascii:
            return True
        lowered = self.lowered
        return any(word in lowered for word in literals)
