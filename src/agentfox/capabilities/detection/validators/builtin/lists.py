"""Validators: word and name lists, matched loosely.

`custom.lists` matches a workspace's terms exactly, on word boundaries. These match
the way a person dodges an exact list: one letter off, or letters spaced apart.
"""

from __future__ import annotations

import os
import re
import tempfile
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentfox.capabilities.detection.validators import register_validator
from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    Validator,
    span_finding,
)


def _squeezed(text: str) -> tuple[str, list[int]]:
    """Lower-cased text without whitespace, and each kept character's original index."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch.lower())
            index.append(i)
    return "".join(chars), index


def near_matches(pattern: str, text: str, max_dist: int) -> list[tuple[int, int, int]]:
    """(start, end, distance) of substrings of `text` within `max_dist` edits of `pattern`.

    Sellers' algorithm: edit distance where a match may start anywhere in the text.
    Overlapping hits are collapsed to the best one, so "bannedword" is one finding.
    """
    m = len(pattern)
    if not m:
        return []
    # prev[i]: distance of pattern[:i] to the best substring ending at the current
    # text position; start[i]: where that substring starts.
    prev = list(range(m + 1))
    prev_start = [0] * (m + 1)
    hits: list[tuple[int, int, int]] = []
    for j, ch in enumerate(text, start=1):
        cur = [0] * (m + 1)
        cur_start = [j] * (m + 1)
        for i in range(1, m + 1):
            sub = prev[i - 1] + (pattern[i - 1] != ch)
            ins = prev[i] + 1  # extra character in the text
            dele = cur[i - 1] + 1  # character missing from the text
            best = min(sub, ins, dele)
            cur[i] = best
            if best == sub:
                cur_start[i] = prev_start[i - 1]
            elif best == ins:
                cur_start[i] = prev_start[i]
            else:
                cur_start[i] = cur_start[i - 1]
        if cur[m] <= max_dist:
            hits.append((cur_start[m], j, cur[m]))
        prev, prev_start = cur, cur_start
    # Keep the best of each run of overlapping hits.
    out: list[tuple[int, int, int]] = []
    for hit in hits:
        if out and hit[0] < out[-1][1]:
            if (hit[2], -(hit[1] - hit[0])) < (out[-1][2], -(out[-1][1] - out[-1][0])):
                out[-1] = hit
            continue
        out.append(hit)
    return out


class BanListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    banned_words: list[str] = Field(min_length=1, max_length=500)
    #: Edits allowed (Levenshtein). 0 is exact, ignoring spaces and case.
    max_l_dist: int = Field(1, ge=0, le=3)


@register_validator
class BanList(Validator):
    name = "ban_list"
    label = "Banned words (fuzzy)"
    description = (
        "Words or phrases that must not appear, matched ignoring case and spaces and "
        "within a small number of typos, so 'b a n n e d' and 'bannd' still match."
    )
    entity_type = "SAFETY.BANNED_TERM"
    surfaces = ("input", "output", "tool_args", "tool_result", "retrieved")
    Params = BanListParams
    upstream = "guardrails-ai/ban_list"

    def check(self, text: str, params: BanListParams, ctx: CheckContext) -> list[Finding]:
        squeezed, index = _squeezed(text)
        out: list[Finding] = []
        for word in params.banned_words:
            target, _ = _squeezed(word)
            # Short words with typos allowed match nearly anything ("ab" within 1 edit
            # of every two-letter run), so the allowance shrinks with the word.
            dist = min(params.max_l_dist, max(0, (len(target) - 1) // 3))
            for start, end, d in near_matches(target, squeezed, dist):
                if end <= start:
                    continue
                s, e = index[start], index[end - 1] + 1
                # Inside a longer word is not a mention: "class" is not "ass" (upstream
                # matched there). Widen to whole words, read from the original text
                # since spaces were squeezed out, and keep it only if the widened
                # span is still within the edit allowance.
                while s > 0 and text[s - 1].isalnum():
                    s -= 1
                while e < len(text) and text[e].isalnum():
                    e += 1
                if len(_squeezed(text[s:e])[0]) > len(target) + dist:
                    continue
                out.append(
                    span_finding(
                        text, s, e, f"close to banned word '{word}'", word=word, distance=d
                    )
                )
        return out


# ------------------------------------------------------------------ drug names

_DATA = Path(__file__).resolve().parent.parent / "data"


@cache
def drug_names() -> tuple[str, ...]:
    """Upstream's drug list, from `validators/data/drug_names.txt`."""
    lines = (_DATA / "drug_names.txt").read_text(encoding="utf-8").splitlines()
    return tuple(x.strip() for x in lines if x.strip() and not x.startswith("#"))


@cache
def _drug_pattern() -> re.Pattern[str]:
    # Longest first, so "Zyflo CR" wins over "Zyflo".
    names = sorted({n.lower() for n in drug_names()}, key=len, reverse=True)
    alternation = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<!\w)(?:{alternation})(?!\w)", re.IGNORECASE)


@register_validator
class MentionsDrugs(Validator):
    """Adapted from guardrails-ai/mentions_drugs (Apache-2.0).

    Upstream split the text on whitespace and intersected single tokens with the
    list, so no multi-word name ("Acetic Acid", "Plan B") could ever match, and a
    hyphenated one only by luck. This matches each listed name on word boundaries.
    """

    name = "mentions_drugs"
    label = "Mentions a drug"
    description = "Flags drug names (about 3,000 brand and generic names) in the text."
    entity_type = "SAFETY.DRUGS"
    surfaces = ("output", "agent_message")
    upstream = "guardrails-ai/mentions_drugs"

    def warm(self) -> None:
        _drug_pattern()

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        return [
            span_finding(text, m.start(), m.end(), "drug name in text", drug=m.group())
            for m in _drug_pattern().finditer(text)
        ]


# ---------------------------------------------------------------- price quotes

#: Upstream's currencies and symbols.
CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "AUD": "A$",
    "CAD": "C$",
    "CNY": "¥",
    "NZD": "NZ$",
}


class QuotesPriceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD", "EUR", "GBP", "JPY", "AUD", "CAD", "CNY", "NZD"] = "USD"


@register_validator
class QuotesPrice(Validator):
    """Adapted from guardrails-ai/quotes_price (Apache-2.0)."""

    name = "quotes_price"
    label = "Quotes a price"
    description = "Flags a price quoted in a currency: a symbol followed by an amount."
    entity_type = "BRAND.PRICE_QUOTE"
    surfaces = ("output", "agent_message")
    Params = QuotesPriceParams
    upstream = "guardrails-ai/quotes_price"

    def check(self, text: str, params: QuotesPriceParams, ctx: CheckContext) -> list[Finding]:
        symbol = CURRENCY_SYMBOLS[params.currency]
        # Upstream's pattern is `symbol\s*\d+(?:\.\d+)?`. Two changes: thousands
        # separators are part of the amount, so the span covers "$1,299.00" rather
        # than "$1"; and a bare "$" must not be the tail of "A$", "C$" or "NZ$",
        # which upstream reported as US dollars.
        guard = r"(?<![A-Za-z])" if symbol == "$" else ""
        pattern = rf"{guard}{re.escape(symbol)}\s*\d+(?:,\d{{3}})*(?:\.\d+)?"
        return [
            span_finding(text, m.start(), m.end(), f"price quoted in {params.currency}")
            for m in re.finditer(pattern, text)
        ]


# ----------------------------------------------------------------- competitors


@cache
def _spacy_nlp() -> Any | None:
    """spaCy's small English model when it is installed, else None."""
    try:
        import spacy

        return spacy.load("en_core_web_sm")
    except (ImportError, OSError):
        return None


class CompetitorCheckParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competitors: list[str] = Field(min_length=1, max_length=1000)


@register_validator
class CompetitorCheck(Validator):
    """Adapted from guardrails-ai/competitor_check (Apache-2.0).

    As upstream: an exact, case-insensitive, word-boundary match, confirmed by
    spaCy's named-entity recogniser when a model is installed (upstream used
    `en_core_web_trf`; this uses `en_core_web_sm`, and the plain match alone when
    no model loads). Upstream's spans were offsets within each sentence, not the
    text, and were found by substring search ("Acme" inside "Acmeville"); here
    they are offsets into the text, on word boundaries.
    """

    name = "competitor_check"
    label = "Names a competitor"
    description = "Flags any of a list of competitor names, matched as whole words."
    entity_type = "BRAND.COMPETITOR"
    surfaces = ("output", "agent_message")
    Params = CompetitorCheckParams
    upstream = "guardrails-ai/competitor_check"

    def warm(self) -> None:
        _spacy_nlp()

    def check(self, text: str, params: CompetitorCheckParams, ctx: CheckContext) -> list[Finding]:
        hits: list[tuple[int, int, str]] = []
        for name in params.competitors:
            if not name.strip():
                continue
            for m in re.finditer(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                hits.append((m.start(), m.end(), name))
        if not hits:
            return []
        nlp = _spacy_nlp()
        if nlp is not None:
            # Upstream kept a name only where the recogniser tagged it as an entity.
            ents = [(e.start_char, e.end_char, e.text.lower()) for e in nlp(text).ents]
            hits = [
                h
                for h in hits
                if any(s < h[1] and h[0] < e and t == h[2].lower() for s, e, t in ents)
            ]
        hits.sort()
        return [
            span_finding(text, s, e, f"competitor named: {name}", competitor=name)
            for s, e, name in hits
        ]


# --------------------------------------------------------------------- secrets


@register_validator
class SecretsPresent(Validator):
    """Adapted from guardrails-ai/secrets_present (Apache-2.0).

    Runs Yelp's detect-secrets over the text written to a temporary file, as
    upstream did. Kept to compare against `secrets.native`; the reason never
    carries the secret.
    """

    name = "secrets_present"
    label = "Secrets (detect-secrets)"
    description = "Flags secrets that Yelp's detect-secrets plugins recognise in the text."
    entity_type = "SECRET.DETECT_SECRETS"
    surfaces = ("output", "tool_args", "tool_result")
    requires = ("detect_secrets",)
    upstream = "guardrails-ai/secrets_present"
    detector = True

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        from detect_secrets import settings
        from detect_secrets.core.secrets_collection import SecretsCollection

        # Upstream appended a newline to single-line input; the scanner reads lines.
        value = text if "\n" in text else text + "\n"
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="agentfox_secrets_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(value)
            secrets = SecretsCollection()
            with settings.default_settings():
                secrets.scan_file(path)
            found: list[tuple[str, int, str]] = []
            for _, secret in secrets:
                if secret.secret_value:
                    found.append((secret.secret_value, secret.line_number, secret.type))
        finally:
            if os.path.exists(path):
                os.unlink(path)

        line_starts = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                line_starts.append(i + 1)
        out: list[Finding] = []
        seen: set[tuple[int, int]] = set()
        for value_, line, kind in found:
            if line - 1 >= len(line_starts):
                continue
            ls = line_starts[line - 1]
            le = text.find("\n", ls)
            le = len(text) if le < 0 else le
            start = text.find(value_, ls, le)
            span = (start, start + len(value_)) if start >= 0 else (ls, le)
            if span in seen:
                continue
            seen.add(span)
            out.append(span_finding(text, *span, f"secret detected ({kind})", type=kind, line=line))
        out.sort(key=lambda f: f.start)
        return out
