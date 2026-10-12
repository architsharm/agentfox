"""Validators: text. See `validators/builtin/__init__.py`.

Shape checks on a piece of text: a pattern it must match, a string it must hold,
its case, its length, how hard and how long it is to read. All offline, all
deterministic; most are format checks, so they neither run as stand-alone
detectors nor re-run on decoded readings of the text.
"""

from __future__ import annotations

import difflib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentfox.capabilities.detection.validators import register_validator
from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    Validator,
    span_finding,
)

_TEXT_SURFACES = ("input", "output", "tool_args", "tool_result")


# --------------------------------------------------------------------------- regex


class RegexMatchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regex: str = Field(min_length=1, max_length=2000)
    #: ``fullmatch`` (upstream's default): the whole text; ``search``: anywhere in it.
    match_type: Literal["search", "fullmatch"] = "fullmatch"

    @field_validator("regex")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"not a valid regular expression: {exc}") from None
        return value


@register_validator
class RegexMatch(Validator):
    """Adapted from guardrails-ai/regex_match (Apache-2.0)."""

    name = "regex_match"
    label = "Matches a pattern"
    description = "The text must match a regular expression, in full or anywhere in it."
    entity_type = "FORMAT.REGEX"
    surfaces = _TEXT_SURFACES
    Params = RegexMatchParams
    upstream = "guardrails-ai/regex_match"
    scan_views = False

    def check(self, text: str, params: RegexMatchParams, ctx: CheckContext) -> list[Finding]:
        matcher = getattr(re.compile(params.regex), params.match_type)
        if matcher(text):
            return []
        how = "match" if params.match_type == "fullmatch" else "contain a match for"
        return [Finding(reason=f"text does not {how} the required pattern")]


# ---------------------------------------------------------------- contains / ends


class ContainsStringParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    substring: str = Field(min_length=1, max_length=2000)


@register_validator
class ContainsString(Validator):
    """Adapted from guardrails-ai/contains_string (Apache-2.0)."""

    name = "contains_string"
    label = "Contains a string"
    description = "The text must contain a given substring (exact, case-sensitive)."
    entity_type = "FORMAT.CONTAINS"
    surfaces = _TEXT_SURFACES
    Params = ContainsStringParams
    upstream = "guardrails-ai/contains_string"
    scan_views = False

    def check(self, text: str, params: ContainsStringParams, ctx: CheckContext) -> list[Finding]:
        if params.substring in text:
            return []
        return [Finding(reason="text does not contain the required string")]


class EndsWithParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end: str = Field(min_length=1, max_length=2000)


@register_validator
class EndsWith(Validator):
    """Adapted from guardrails-ai/ends_with (Apache-2.0)."""

    name = "ends_with"
    label = "Ends with"
    description = "The text must end with a given string."
    entity_type = "FORMAT.ENDS_WITH"
    surfaces = _TEXT_SURFACES
    Params = EndsWithParams
    upstream = "guardrails-ai/ends_with"
    scan_views = False

    def check(self, text: str, params: EndsWithParams, ctx: CheckContext) -> list[Finding]:
        # Upstream compared `value[-1] != end`, which for a string is its last
        # *character*, so any `end` longer than one character always failed, and an
        # empty value raised IndexError. `str.endswith` is what was meant.
        if text.endswith(params.end):
            return []
        return [Finding(reason="text does not end with the required string")]


# -------------------------------------------------------------------------- case


@register_validator
class LowerCase(Validator):
    """Adapted from guardrails-ai/lowercase (Apache-2.0)."""

    name = "lowercase"
    label = "Lower case"
    description = "The text must be all lower case."
    entity_type = "FORMAT.CASE"
    surfaces = _TEXT_SURFACES
    upstream = "guardrails-ai/lowercase"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        if text.lower() == text:
            return []
        i = next(i for i, ch in enumerate(text) if ch.lower() != ch)
        return [span_finding(text, i, i + 1, "text is not lower case")]


@register_validator
class UpperCase(Validator):
    """Adapted from guardrails-ai/uppercase (Apache-2.0)."""

    name = "uppercase"
    label = "Upper case"
    description = "The text must be all upper case."
    entity_type = "FORMAT.CASE"
    surfaces = _TEXT_SURFACES
    upstream = "guardrails-ai/uppercase"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        if text.upper() == text:
            return []
        i = next(i for i, ch in enumerate(text) if ch.upper() != ch)
        return [span_finding(text, i, i + 1, "text is not upper case")]


@register_validator
class OneLine(Validator):
    """Adapted from guardrails-ai/one_line (Apache-2.0)."""

    name = "one_line"
    label = "One line"
    description = "The text must be a single line."
    entity_type = "FORMAT.ONE_LINE"
    surfaces = _TEXT_SURFACES
    upstream = "guardrails-ai/one_line"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        lines = text.splitlines(keepends=True)
        if len(lines) <= 1:
            return []
        # Point at everything after the first line, which is what upstream's fix drops.
        first = len(lines[0])
        return [span_finding(text, first, len(text), f"text has {len(lines)} lines, not one")]


@register_validator
class TwoWords(Validator):
    """Adapted from guardrails-ai/two_words (Apache-2.0)."""

    name = "two_words"
    label = "Exactly two words"
    description = "The text must be exactly two whitespace-separated words."
    entity_type = "FORMAT.WORD_COUNT"
    surfaces = _TEXT_SURFACES
    upstream = "guardrails-ai/two_words"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        n = len(text.split())
        if n == 2:
            return []
        return [Finding(reason=f"text has {n} words, not exactly two", detail={"words": n})]


# ------------------------------------------------------------------ length/choice


class ValidLengthParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int | None = Field(None, ge=0)
    max: int | None = Field(None, ge=0)
    #: ``chars``: length of the text. ``items``: the text is a JSON array; count it.
    unit: Literal["chars", "items"] = "chars"

    @model_validator(mode="after")
    def _ordered(self) -> ValidLengthParams:
        if self.min is None and self.max is None:
            raise ValueError("set min, max or both")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


@register_validator
class ValidLength(Validator):
    """Adapted from guardrails-ai/valid_length (Apache-2.0)."""

    name = "valid_length"
    label = "Length within range"
    description = (
        "The text's length in characters (or, for a JSON array, its number of items) "
        "must be within an inclusive range."
    )
    entity_type = "FORMAT.LENGTH"
    surfaces = _TEXT_SURFACES
    Params = ValidLengthParams
    upstream = "guardrails-ai/valid_length"
    scan_views = False

    def check(self, text: str, params: ValidLengthParams, ctx: CheckContext) -> list[Finding]:
        if params.unit == "items":
            try:
                value = json.loads(text)
            except ValueError:
                return [Finding(reason="text is not a JSON array")]
            if not isinstance(value, list):
                return [Finding(reason="text is not a JSON array")]
            n, what = len(value), "items"
        else:
            n, what = len(text), "characters"
        if params.min is not None and n < params.min:
            return [Finding(reason=f"{n} {what}, fewer than {params.min}", detail={"length": n})]
        if params.max is not None and n > params.max:
            if params.unit == "chars":
                return [
                    span_finding(
                        text, params.max, n, f"{n} {what}, more than {params.max}", length=n
                    )
                ]
            return [Finding(reason=f"{n} {what}, more than {params.max}", detail={"length": n})]
        return []


class ValidChoiceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    choices: list[str] = Field(min_length=1, max_length=1000)


@register_validator
class ValidChoice(Validator):
    """Adapted from guardrails-ai/valid_choice (Apache-2.0)."""

    name = "valid_choice"
    label = "One of a set of choices"
    description = "The text, trimmed, must be exactly one of the listed choices."
    entity_type = "FORMAT.CHOICE"
    surfaces = _TEXT_SURFACES
    Params = ValidChoiceParams
    upstream = "guardrails-ai/valid_choice"
    scan_views = False

    def check(self, text: str, params: ValidChoiceParams, ctx: CheckContext) -> list[Finding]:
        if text.strip() in params.choices:
            return []
        return [Finding(reason="text is not one of the allowed choices")]


class ValidRangeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _ordered(self) -> ValidRangeParams:
        if self.min is None and self.max is None:
            raise ValueError("set min, max or both")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


@register_validator
class ValidRange(Validator):
    """Adapted from guardrails-ai/valid_range (Apache-2.0)."""

    name = "valid_range"
    label = "Number within range"
    description = "The text must be a number within an inclusive range."
    entity_type = "FORMAT.RANGE"
    surfaces = _TEXT_SURFACES
    Params = ValidRangeParams
    upstream = "guardrails-ai/valid_range"
    scan_views = False

    def check(self, text: str, params: ValidRangeParams, ctx: CheckContext) -> list[Finding]:
        raw = text.strip()
        try:
            value: float = int(raw)
        except ValueError:
            try:
                value = float(raw)
            except ValueError:
                return [Finding(reason="text is not a number")]
        if value != value:  # NaN compares false with everything
            return [Finding(reason="text is not a number")]
        # Upstream cast the bound to the value's type (`int(min)` for an int value),
        # so 5 passed a minimum of 5.5. Compare the numbers as they are.
        if params.min is not None and value < params.min:
            return [Finding(reason=f"{raw} is less than {params.min:g}")]
        if params.max is not None and value > params.max:
            return [Finding(reason=f"{raw} is greater than {params.max:g}")]
        return []


# ---------------------------------------------------------------------- reading

#: Upstream's reading speed, words per minute.
WORDS_PER_MINUTE = 200


class ReadingTimeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Maximum reading time in minutes.
    reading_time: float = Field(gt=0, le=10_000)


@register_validator
class ReadingTime(Validator):
    """Adapted from guardrails-ai/reading_time (Apache-2.0)."""

    name = "reading_time"
    label = "Reading time"
    description = (
        f"The text must be readable within a number of minutes, at {WORDS_PER_MINUTE} "
        "words a minute."
    )
    entity_type = "FORMAT.READING_TIME"
    surfaces = ("output", "agent_message")
    Params = ReadingTimeParams
    upstream = "guardrails-ai/reading_time"
    scan_views = False

    def check(self, text: str, params: ReadingTimeParams, ctx: CheckContext) -> list[Finding]:
        minutes = len(text.split()) / WORDS_PER_MINUTE
        if minutes <= params.reading_time:
            return []
        return [
            Finding(
                reason=(
                    f"takes {round(minutes, 3)} min to read, more than "
                    f"{round(params.reading_time, 3)}"
                ),
                detail={"minutes": round(minutes, 3)},
            )
        ]


_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)")
_VOWEL_GROUP = re.compile(r"[aeiouy]+")


def syllables(word: str) -> int:
    """A stdlib estimate of English syllables: vowel groups, less a silent final e."""
    w = word.lower().replace("'", "")
    if not w:
        return 0
    count = len(_VOWEL_GROUP.findall(w))
    # "make", "hope": a final e after a consonant is silent, but not in "-le" ("table").
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and count > 1:
        count -= 1
    # "-ed" after anything but t/d is not its own syllable ("jumped", not "wanted").
    if w.endswith("ed") and len(w) > 3 and w[-3] not in "td" and count > 1:
        count -= 1
    return max(1, count)


def flesch_kincaid_grade(text: str) -> float | None:
    """Flesch-Kincaid grade level, or None when there are no words."""
    words = _WORD.findall(text)
    if not words:
        return None
    sentences = max(1, len(_SENTENCE_END.findall(text)))
    syl = sum(syllables(w) for w in words)
    return 0.39 * (len(words) / sentences) + 11.8 * (syl / len(words)) - 15.59


class ReadingLevelParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Inclusive US school grades, 0 to 12.
    min: int = Field(0, ge=0, le=12)
    max: int = Field(12, ge=0, le=12)

    @model_validator(mode="after")
    def _ordered(self) -> ReadingLevelParams:
        if self.min > self.max:
            raise ValueError("min must not exceed max")
        return self


@register_validator
class ReadingLevel(Validator):
    """Adapted from guardrails-ai/reading_level (Apache-2.0).

    Upstream used the `readability` package (Flesch-Kincaid, falling back to Spache
    below grade 4, and raising on texts under 100 words). This computes
    Flesch-Kincaid with a stdlib syllable estimate, clamped to 0..12 as upstream
    did, on any length of text; there is no Spache fallback (it needs a word list).
    """

    name = "reading_level"
    label = "Reading level"
    description = "The text's Flesch-Kincaid US grade level (0-12) must be within a range."
    entity_type = "FORMAT.READING_LEVEL"
    surfaces = ("output", "agent_message")
    Params = ReadingLevelParams
    upstream = "guardrails-ai/reading_level"
    scan_views = False

    def check(self, text: str, params: ReadingLevelParams, ctx: CheckContext) -> list[Finding]:
        grade = flesch_kincaid_grade(text)
        if grade is None:
            return []
        level = min(12, max(0, int(grade)))
        detail = {"grade": round(grade, 2), "level": level}
        if level < params.min:
            return [Finding(reason=f"reading level {level}, below {params.min}", detail=detail)]
        if level > params.max:
            return [Finding(reason=f"reading level {level}, above {params.max}", detail=detail)]
        return []


# -------------------------------------------------------------------- redundancy

_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence, trimmed of surrounding whitespace."""
    out: list[tuple[int, int]] = []
    for m in _SENTENCE.finditer(text):
        s, e = m.start(), m.end()
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e > s:
            out.append((s, e))
    return out


class RedundantSentencesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Similarity (0-100) above which a later sentence repeats an earlier one.
    threshold: int = Field(70, ge=0, le=100)


@register_validator
class RedundantSentences(Validator):
    """Adapted from guardrails-ai/redundant_sentences (Apache-2.0).

    Upstream scored pairs with `thefuzz.fuzz.ratio`; this uses the stdlib
    `difflib.SequenceMatcher.ratio`, scaled to 0-100, which is the same measure
    (thefuzz's pure-Python path is built on it).
    """

    name = "redundant_sentences"
    label = "Redundant sentences"
    description = "Flags sentences that nearly repeat an earlier sentence."
    entity_type = "FORMAT.REDUNDANT"
    surfaces = ("output", "agent_message")
    Params = RedundantSentencesParams
    upstream = "guardrails-ai/redundant_sentences"
    scan_views = False

    def check(
        self, text: str, params: RedundantSentencesParams, ctx: CheckContext
    ) -> list[Finding]:
        spans = sentence_spans(text)
        # Upstream indexed sentences[0] without checking, so an empty text raised.
        if len(spans) < 2:
            return []
        # Upstream's greedy pass: keep the first sentence, drop every later one that
        # is too close to it, then repeat with the first sentence that survived.
        out: list[Finding] = []
        current, rest = spans[0], spans[1:]
        while rest:
            base = text[current[0] : current[1]]
            unique = []
            for other in rest:
                ratio = 100 * difflib.SequenceMatcher(None, base, text[other[0] : other[1]]).ratio()
                if ratio > params.threshold:
                    out.append(
                        span_finding(
                            text,
                            other[0],
                            other[1],
                            "sentence repeats an earlier one",
                            similarity=round(ratio),
                            repeats=[current[0], current[1]],
                        )
                    )
                else:
                    unique.append(other)
            if not unique:
                break
            current, rest = unique[0], unique[1:]
        out.sort(key=lambda f: f.start)
        return out


# --------------------------------------------------------------------- cucumber


class CucumberParameterType(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    regexp: str = Field(min_length=1, max_length=2000)


class CucumberExpressionMatchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=2000)
    #: Extra ``{name}`` placeholders, each a regular expression.
    parameter_types: list[CucumberParameterType] = Field(default_factory=list, max_length=50)


@register_validator
class CucumberExpressionMatch(Validator):
    """Adapted from guardrails-ai/cucumber_expression_match (MIT, by jenisys)."""

    name = "cucumber_expression_match"
    label = "Matches a Cucumber expression"
    description = (
        "The text must match a Cucumber expression, a readable pattern such as "
        "'I buy {int} apple(s)/banana(s)'."
    )
    entity_type = "FORMAT.CUCUMBER"
    surfaces = _TEXT_SURFACES
    Params = CucumberExpressionMatchParams
    requires = ("cucumber_expressions",)
    upstream = "guardrails-ai/cucumber_expression_match"
    license = "MIT"
    scan_views = False

    def check(
        self, text: str, params: CucumberExpressionMatchParams, ctx: CheckContext
    ) -> list[Finding]:
        from cucumber_expressions.expression import CucumberExpression
        from cucumber_expressions.parameter_type import ParameterType
        from cucumber_expressions.parameter_type_registry import ParameterTypeRegistry

        registry = ParameterTypeRegistry()
        for p in params.parameter_types:
            registry.define_parameter_type(ParameterType(p.name, regexp=p.regexp, type=str))
        expression = CucumberExpression(params.expression, registry)
        if expression.match(text) is not None:
            return []
        return [Finding(reason="text does not match the required Cucumber expression")]
