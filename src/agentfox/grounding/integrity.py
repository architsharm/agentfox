"""F7 — numeric, temporal and entity integrity.

The failures here are the ones that survive every other control. The answer is
grounded, the source is authoritative, the action is safe, nobody needed to escalate
— and the number is for the wrong quarter, or in the wrong currency, or belongs to a
different customer with a similar name. The reconciliation incident is the canonical
shape: a record "matched" that was never in the data.

These are high-frequency in finance and operations and they are almost entirely
undetected in practice, because the usual quality metrics are about *language*.
Groundedness asks whether the claim is supported by the text; it does not ask whether
5 + 3 = 9, or whether "Q1" in the question means the same three months as "Q1" in the
source.

Every check here is deterministic arithmetic or string comparison. That is not a
limitation to apologise for: these are exactly the questions where a probabilistic
judge is the wrong instrument, and a false negative on a currency mismatch costs more
than the check.

**Locale.** These checks run on live output, and live output is not always English.
`benchmarks/multilingual/` measured what that cost: on matched pairs of the same
logical content, English-formatted and localised, 12 checks went silent on the
localised member and one invented an error that was not there — a parser that read
`2,5 + 2,5 = 5` as "25 + 25 is 50, not 5". Numbers are therefore parsed under an
explicit *separator convention* rather than by stripping commas, and the connective
vocabulary that gates four of the check families is no longer English-only.

The rule that governs the whole locale layer: **ambiguity is reported, never
resolved by assumption.** `1,234` is one thousand two hundred thirty-four in English
and 1.234 in German, and nothing in the string says which. So an expression is read
under every convention it is well-formed in; an error is reported only when the
content is wrong under *all* of them; and where the verdict depends on which
convention applies, that dependence is what gets reported — the same stance
`detect_timezone_ambiguity` already takes towards an undeclared timezone. Callers
that know their locale pass it (``locale="de"``) and get a single resolved reading
with no ambiguity findings at all.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Numbers
#
# A numeric literal is digits plus separators, and which separator means what is a
# property of the writer's locale, not of the string. Both of these are the same
# quantity:
#
#     1,234.56   (en, en-GB, ja, zh, …)
#     1.234,56   (de, fr, es, it, pt, nl, …)
#
# and `1,234` alone is *two different numbers* depending on who wrote it. The old
# parser resolved this by stripping commas, which silently converted 1.234,56 into
# the pair (1.234, 56) and 2,5 into 25.
# ---------------------------------------------------------------------------

#: Every space character used as a thousands separator in the wild. French and the
#: SI convention use a non-breaking or narrow non-breaking space; plain text written
#: by hand (and the French rows in `benchmarks/multilingual/`) uses an ASCII space.
_GROUP_SPACES = "     "

#: One numeric literal, in any of the conventions above. The grouped branch is tried
#: first so that `1.234,56` is one token rather than three; the plain branch catches
#: `5`, `2,5`, `2.5` and `1234.56`, none of which are grouped. Space grouping demands
#: strictly-three-digit groups after a 1-3 digit lead, which is what keeps "in 2024
#: 500 units" from being read as 2024500.
_NUM_TOKEN = r"(?:\d{1,3}(?:[.,      ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_NUMBER = re.compile(rf"[-+]?{_NUM_TOKEN}")

#: Which separator is the decimal point. Locales are mapped rather than guessed, and
#: an unrecognised tag is treated as *undeclared* — a wrong resolution is worse than
#: no resolution.
_DECIMAL_COMMA_LOCALES = {
    "de",
    "fr",
    "es",
    "it",
    "pt",
    "nl",
    "da",
    "fi",
    "sv",
    "nb",
    "no",
    "pl",
    "cs",
    "sk",
    "sl",
    "hr",
    "hu",
    "ro",
    "bg",
    "el",
    "ru",
    "uk",
    "tr",
    "lv",
    "lt",
    "et",
    "is",
    "ca",
    "af",
    "id",
    "vi",
    "sq",
    "sr",
    "be",
    "az",
}
_DECIMAL_POINT_LOCALES = {
    "en",
    "ja",
    "zh",
    "ko",
    "he",
    "th",
    "hi",
    "ta",
    "bn",
    "ms",
    "ga",
    "mt",
    "sw",
    "ar",
    "fa",
    "ur",
    "km",
    "my",
    "si",
    "ne",
    "ka",
    "am",
}

#: The two conventions a literal can be read under, in the order they are tried.
_CONVENTIONS = (".", ",")


def _locale_convention(locale: str | None) -> str | None:
    """The decimal separator this locale declares, or None if it declares nothing.

    An unknown tag returns None rather than a default: a caller who passes `"xx"` has
    told us nothing, and inventing a convention for them is exactly the guess this
    module refuses to make.
    """
    if not locale:
        return None
    tag = str(locale).strip().lower().replace("_", "-").split("-")[0]
    if tag in _DECIMAL_COMMA_LOCALES:
        return ","
    if tag in _DECIMAL_POINT_LOCALES:
        return "."
    return None


def _ascii_digits(text: str) -> str:
    """Arabic-Indic ٥ and Devanagari ५ are decimal digits; `float` wants ASCII."""
    if text.isascii():
        return text
    out = []
    for ch in text:
        if ch.isdecimal() and not ch.isascii():
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    return "".join(out)


def _read_number(raw: str, convention: str) -> float | None:
    """Parse one numeric literal under one separator convention, or fail.

    ``convention`` is the decimal separator; the other of ``.``/``,`` and every space
    character group instead. Failing is the point: `2,5` has no well-formed reading
    under the decimal-point convention, and `1.234,56` has none under the
    decimal-comma one, which is how a convention gets *ruled out* rather than
    guessed at.
    """
    text = str(raw).strip()
    for space in _GROUP_SPACES:
        text = text.replace(space, " ")
    sign = 1.0
    if text[:1] in "+-":
        if text[0] == "-":
            sign = -1.0
        text = text[1:]
    if not text:
        return None

    group = "," if convention == "." else "."
    if convention in text:
        if text.count(convention) != 1:
            return None
        integer, _, fraction = text.partition(convention)
        if not fraction or not fraction.isdecimal():
            return None
    else:
        integer, fraction = text, ""
    if not integer:
        return None

    parts = re.split(rf"[{re.escape(group)} ]", integer)
    if any(not part.isdecimal() for part in parts):
        return None
    if len(parts) > 1:
        # Grouped: a 1-3 digit lead followed by strictly-three-digit groups. Anything
        # else ("1.2345", "12,34,567") is not this convention's grouping.
        if not 1 <= len(parts[0]) <= 3:
            return None
        if any(len(part) != 3 for part in parts[1:]):
            return None

    digits = _ascii_digits("".join(parts))
    try:
        return sign * float(f"{digits}.{_ascii_digits(fraction)}" if fraction else digits)
    except ValueError:
        return None


def number_readings(raw: str, *, locale: str | None = None) -> list[float]:
    """Every value this literal could denote, most-common convention first.

    One reading means the literal is unambiguous (`2,5`, `1.234,56`, `1234.56`, `٥`).
    Two means it genuinely is not (`1,234` is 1234 or 1.234, `5.000` is 5 or 5000) and
    the caller must not pick one. A declared locale collapses it to one reading.
    """
    convention = _locale_convention(locale)
    conventions = (convention,) if convention else _CONVENTIONS
    out: list[float] = []
    for candidate in conventions:
        value = _read_number(raw, candidate)
        if value is not None and value not in out:
            out.append(value)
    return out


def _consistent_readings(
    tokens: list[str], *, locale: str | None = None
) -> list[tuple[str, list[float]]]:
    """Read a whole expression under one convention at a time.

    Reading each operand independently would let `1,234` be English and `2,5` German
    in the same sentence, which no writer does. A convention survives only if *every*
    token in the expression is well-formed under it.
    """
    convention = _locale_convention(locale)
    conventions = (convention,) if convention else _CONVENTIONS
    out: list[tuple[str, list[float]]] = []
    for candidate in conventions:
        values = [_read_number(token, candidate) for token in tokens]
        if all(value is not None for value in values):
            out.append((candidate, [v for v in values if v is not None]))
    # Two conventions that agree on every value are one reading, not two.
    if len(out) == 2 and out[0][1] == out[1][1]:
        return out[:1]
    return out


def _to_float(raw: str, *, locale: str | None = None) -> float:
    """The single value of an unambiguous literal.

    Kept for callers that have already established there is only one reading. On an
    ambiguous literal it returns the first reading, so it is deliberately *not* used
    by any check that reports an error.
    """
    readings = number_readings(raw, locale=locale)
    if not readings:
        return float(_ascii_digits(str(raw).replace(",", "").replace(" ", "")))
    return readings[0]


def numbers_in(text: str) -> set[str]:
    """Canonical numeric values in a text, as strings.

    Every reading of an ambiguous literal is included. That makes set intersection —
    which is how `sycophancy.py` asks "does the answer carry this value" — charitable
    where the format is ambiguous, which is the right direction for a check whose
    false positive is an accusation.
    """
    out: set[str] = set()
    for match in _NUMBER.finditer(text or ""):
        for value in number_readings(match.group(0)):
            out.add(repr(value))
    return out


# --- Scale words -----------------------------------------------------------
#
# The four check families below were gated on English vocabulary, which meant they did
# not run at all on localised content rather than running and being wrong — a silent
# disablement, which is the worse of the two failures.
#
# Two abbreviations were tried and removed for colliding with text that is not a
# scale word: bare `md` (French milliard) matched the typo "2md line" in the benign
# English pool, and `mia` (Swiss-German Milliarde) is the Italian word for "my".
# `mds`, `mrd` and `mld` carry the same meanings with no collision measured.
#
# Known false friend, deliberately not handled: German and French "Billion" is 10^12,
# not 10^9. Mapping it would require knowing the language of the text, which this
# module does not and will not infer; a comparison between two texts in the *same*
# language is unaffected, which is the comparison these checks actually make.

_SCALE = {
    # thousand
    "k": 1_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "tsd": 1_000,  # de
    "tausend": 1_000,  # de
    "millier": 1_000,  # fr
    "milliers": 1_000,  # fr
    "duizend": 1_000,  # nl
    # million
    "m": 1_000_000,
    "mn": 1_000_000,
    "mio": 1_000_000,  # de, fr, it
    "mln": 1_000_000,  # pl, nl, it
    "million": 1_000_000,
    "millions": 1_000_000,
    "millionen": 1_000_000,  # de
    "millones": 1_000_000,  # es
    "millón": 1_000_000,  # es
    "milhão": 1_000_000,  # pt
    "milhões": 1_000_000,  # pt
    "milioni": 1_000_000,  # it
    "milione": 1_000_000,  # it
    # billion (10^9)
    "b": 1_000_000_000,
    "bn": 1_000_000_000,
    "mds": 1_000_000_000,  # fr
    "mrd": 1_000_000_000,  # de (Milliarde)
    "mld": 1_000_000_000,  # it, nl
    "billion": 1_000_000_000,
    "billions": 1_000_000_000,
    "milliard": 1_000_000_000,  # fr
    "milliards": 1_000_000_000,  # fr
    "milliarde": 1_000_000_000,  # de
    "milliarden": 1_000_000_000,  # de
    "miliardi": 1_000_000_000,  # it
    "mil millones": 1_000_000_000,  # es
    "mil milhões": 1_000_000_000,  # pt
}
#: Longest alternative first, or `Mio.` would match as `m` and `Mrd.` as `m`.
_SCALE_ALTERNATION = "|".join(re.escape(word) for word in sorted(_SCALE, key=len, reverse=True))
_SCALE_RE = re.compile(rf"{_NUM_TOKEN}\s*({_SCALE_ALTERNATION})\b", re.I)

_CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "¥": "JPY"}
_CURRENCY_CODES = re.compile(r"\b(USD|EUR|GBP|JPY|CHF|CAD|AUD|INR|CNY)\b")

#: Equality words, so that "5 + 3 ergibt 9" is checked like "5 + 3 is 9". Each needs a
#: number on both sides to match at all, which is what keeps the short ones honest.
_EQUALS = r"=|equals|is|are|ist|sind|ergibt|macht|est|font|égale|egale|es|son|è|fa|é|são|sao"
_ARITHMETIC = re.compile(
    rf"([-+]?{_NUM_TOKEN})\s*([+\-*/x×])\s*([-+]?{_NUM_TOKEN})\s*(?:{_EQUALS})\s*"
    rf"([-+]?{_NUM_TOKEN})",
    re.I,
)

#: "The total is", in the six languages this repo's own multilingual benchmark scores.
_TOTAL_WORD = (
    r"gesamtsumme|gesamtbetrag|gesamtkosten|endsumme|summe|insgesamt|gesamt|"
    r"montant total|somme totale|somme|total général|total generale|totale|totaal|"
    r"grand total|subtotal|sub-total|total|sum|altogether|combined|aggregate|"
    r"suma total|suma|importe total|soma|totalizando"
)
#: …and the connective that introduces the figure. Longest first, so that French
#: "est de" is not consumed as Spanish "es". Word-bounded, so that "sum" no longer
#: matches inside "assume" — a pre-existing hole this rewrite closes on the way past.
_TOTAL_CONNECT = (
    r"s'élève à|s'eleve a|se eleva a|asciende a|ammonta a|belief sich auf|"
    r"beläuft sich auf|belaeuft sich auf|liegt bei|est de|é de|es de|è di|beträgt|"
    r"betraegt|betragen|totalise|totaliza|ergibt|ist|sind|is|are|of|est|es|é|è"
)
_TOTAL_CLAIM = re.compile(
    rf"\b(?:{_TOTAL_WORD})\b[^.\n]*?(?:\b(?:{_TOTAL_CONNECT})\b|[=:])"
    rf"\s*[£$€¥]?\s*([-+]?{_NUM_TOKEN})",
    re.I,
)

# --- Periods ---------------------------------------------------------------
#
# `Q1` is English-and-borrowed; `1. Quartal`, `1er trimestre` and `T1 2024` are not.
# The `T1` form demands an adjacent four-digit year, because a bare "T1" in English
# prose is far more often a tax form, a vertebra or a network circuit than a quarter.

_QUARTER_PATTERNS = (
    re.compile(r"\bQ([1-4])\s*(?:of\s*)?(?:FY)?\s*(\d{2,4})?\b", re.I),
    re.compile(r"\b([1-4])\s*\.\s*Quartal\b", re.I),  # de
    re.compile(
        r"\b([1-4])\s*(?:er|re|ère|ere|ème|eme|º|ª|°|o|a|e)?\s*trimestre\b", re.I
    ),  # fr, es, pt, it
    re.compile(r"\bT([1-4])\s*[/ -]?\s*((?:19|20)\d{2})\b"),  # fr abbreviation
)
_FISCAL_PATTERNS = (
    re.compile(r"\b(?:FY|fiscal(?:\s+year)?)\s*(\d{2,4})\b", re.I),
    re.compile(r"\b(?:GJ|Gesch[äa]ftsjahr|Finanzjahr)\s*(\d{2,4})\b", re.I),  # de
    re.compile(r"\bexercice(?:\s+(?:fiscal|comptable|budgétaire|budgetaire))?\s*(\d{4})\b", re.I),
    re.compile(r"\bejercicio(?:\s+fiscal)?\s*(\d{4})\b", re.I),  # es
    re.compile(r"\bexerc[íi]cio(?:\s+fiscal)?\s*(\d{4})\b", re.I),  # pt
    re.compile(r"\besercizio(?:\s+fiscale)?\s*(\d{4})\b", re.I),  # it
    re.compile(r"\bboekjaar\s*(\d{4})\b", re.I),  # nl
)
_CALENDAR_PATTERNS = (
    re.compile(r"\b(?:calendar(?:\s+year)?|CY)\s*(\d{4})\b", re.I),
    re.compile(r"\bKalenderjahr\s*(\d{4})\b", re.I),  # de
    re.compile(r"\bann[ée]e\s+civile\s*(\d{4})\b", re.I),  # fr
    re.compile(r"\ba[ñn]o\s+(?:natural|calendario)\s*(\d{4})\b", re.I),  # es
    re.compile(r"\bano\s+civil\s*(\d{4})\b", re.I),  # pt
    re.compile(r"\banno\s+solare\s*(\d{4})\b", re.I),  # it
)
_YEAR = re.compile(r"\b(20\d{2}|19\d{2})\b")

# --- Dates -----------------------------------------------------------------
#
# See `detect_date_mismatch` for why this is deliberately narrow. Two-digit years are
# not parsed at all: `03.04.26` would require guessing a century on top of guessing a
# convention.

_DATE_ISO = re.compile(r"(?<![\d./-])((?:19|20)\d{2})-(\d{2})-(\d{2})(?![\d/-])")
_DATE_NUMERIC = re.compile(r"(?<![\d./-])(\d{1,2})([./-])(\d{1,2})\2((?:19|20)\d{2})(?![\d])")

# --- Timezones -------------------------------------------------------------

#: Case-sensitive, and that is load-bearing rather than incidental: timezone
#: abbreviations are upper-case by convention, and matching them case-insensitively
#: makes German "ist" an Indian timezone and French "est" an American one — which
#: suppresses the deadline finding on every German and French sentence containing the
#: verb "to be". Adding `re.I` here silently disabled this check in two languages.
#:
#: `WET` and `WEST` are real zone names and are still left out, for the mirror-image
#: reason: an upper-cased English "WEST" would suppress a deadline finding that should
#: have fired. A suppression list has to be more careful than a detection list.
_TZ_NAMED = re.compile(
    r"\b(?:UTC|GMT|EST|EDT|PST|PDT|CET|CEST|MEZ|MESZ|WEZ|WESZ|OEZ|OESZ|EET|"
    r"EEST|IST|JST|BST|AEST|AEDT|NZST)\b|\b(?:UTC|GMT)\s*[+-]\s*\d{1,2}(?::\d{2})?"
)
#: A clock time. `17:00` is universal; `17.00 Uhr` and `17h00` are not, and the
#: trailing marker is mandatory on the dotted form — a bare `17.00` is a price far
#: more often than it is a time.
_TIME = re.compile(
    r"\b\d{1,2}:\d{2}(?:\s*(?:am|pm|a\.m\.|p\.m\.))?\b"
    r"|\b\d{1,2}[.:]\d{2}\s*(?:Uhr|uur|heures?|hrs?|h)\b"
    r"|\b\d{1,2}\s*h\s*\d{2}\b",
    re.I,
)
#: Deadline language. The check exists because a deadline is where an off-by-one costs
#: something; flagging every clock time would be noise, in any language.
_DEADLINE = re.compile(
    r"\b(?:by|before|due|deadline|expires?|closes?|cut-?off"
    r"|frist|fristen|f[äa]llig|sp[äa]testens|stichtag|abgabetermin|bis"  # de
    r"|date limite|échéance|echeance|délai|delai|au plus tard|avant"  # fr
    r"|fecha límite|fecha limite|plazo|a más tardar|a mas tardar|vence|antes de"  # es
    r"|scadenza|entro|termine ultimo"  # it
    r"|prazo|data limite|até"  # pt
    r"|uiterlijk)\b",  # nl
    re.I,
)


# ---------------------------------------------------------------------------
# F7.1 — hallucinated record match
# ---------------------------------------------------------------------------


def detect_unmatched_records(
    answer: str, records: list[dict[str, Any]] | None, *, id_fields: tuple[str, ...] = ("id",)
) -> list[dict[str, Any]]:
    """F7.1 — the reconciliation incident: a record "matched" that was never there.

    Only identifier-shaped tokens are checked. Comparing every number in the answer
    against the record set would flag quantities and dates, which is noise; an
    identifier that resolves to nothing is signal.
    """
    if records is None:
        return []
    known = {
        str(record.get(field, "")).casefold()
        for record in records
        for field in id_fields
        if record.get(field) is not None
    }
    known |= {str(v).casefold() for r in records for v in r.values() if isinstance(v, str)}

    candidates = re.findall(r"\b(?:[A-Z]{2,}[-_]?\d{3,}|#\d{4,}|\d{6,})\b", answer or "")
    out: list[dict[str, Any]] = []
    for candidate in dict.fromkeys(candidates):
        if candidate.casefold().lstrip("#") in {k.lstrip("#") for k in known}:
            continue
        out.append(
            {
                "identifier": candidate,
                "reason": (
                    f"the answer references record '{candidate}', which is not in the "
                    f"{len(records)} record(s) that were actually retrieved"
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# F7.2 — arithmetic
# ---------------------------------------------------------------------------


def _off_by_more_than_tolerance(actual: float, stated: float) -> bool:
    return abs(actual - stated) > max(0.01, abs(actual) * 0.001)


def _apply(op: str, a: float, b: float) -> float | None:
    return {
        "+": a + b,
        "-": a - b,
        "*": a * b,
        "x": a * b,
        "×": a * b,
        "/": a / b if b else None,
    }.get(op)


def check_arithmetic(
    answer: str, *, components: list[float] | None = None, locale: str | None = None
) -> list[dict]:
    """F7.2 — the sum does not match the rows cited.

    Two forms: an explicit statement of arithmetic, and a total claimed over a
    component list the caller supplies. Tolerance is relative, so rounding in a
    currency figure is not reported as an error.

    The expression is evaluated once per separator convention it is well-formed in.
    An `arithmetic_error` is reported only when the claim is wrong under *every*
    convention — so a correct sum written `2,5 + 2,5 = 5` is never accused, which is
    the failure that matters most: a false positive on valid content is worse than a
    miss. Where the conventions disagree about whether the claim holds, that
    disagreement is reported as `number_format_ambiguity` instead of a verdict
    invented by picking one. Passing `locale` removes the ambiguity entirely.
    """
    out: list[dict[str, Any]] = []
    for left, op, right, claimed in _ARITHMETIC.findall(answer or ""):
        readings = _consistent_readings([left, right, claimed], locale=locale)
        verdicts: list[dict[str, Any]] = []
        for convention, (a, b, stated) in readings:
            actual = _apply(op, a, b)
            if actual is None:
                continue
            verdicts.append(
                {
                    "convention": convention,
                    "a": a,
                    "b": b,
                    "stated": stated,
                    "actual": actual,
                    "wrong": _off_by_more_than_tolerance(actual, stated),
                }
            )
        if not verdicts:
            continue
        wrong = [v for v in verdicts if v["wrong"]]
        if len(wrong) != len(verdicts):
            if wrong:
                # One convention says this is correct and another says it is wrong.
                # Which one applies is a property of the writer, not of the string.
                out.append(
                    {
                        "kind": "number_format_ambiguity",
                        "expression": f"{left} {op} {right}",
                        "readings": [
                            {
                                "decimal_separator": v["convention"],
                                "reads_as": f"{v['a']:g} {op} {v['b']:g} = {v['stated']:g}",
                                "holds": not v["wrong"],
                            }
                            for v in verdicts
                        ],
                        "reason": (
                            f"'{left} {op} {right}' is correct read with "
                            f"'{[v['convention'] for v in verdicts if not v['wrong']][0]}' as the "
                            f"decimal separator and wrong read with "
                            f"'{wrong[0]['convention']}'; no locale was declared, so which "
                            "one applies is unknown"
                        ),
                    }
                )
            continue
        # Wrong under every reading. Report the most charitable one.
        best = min(wrong, key=lambda v: abs(v["actual"] - v["stated"]))
        out.append(
            {
                "kind": "arithmetic_error",
                "expression": f"{left} {op} {right}",
                "stated": best["stated"],
                "actual": round(best["actual"], 4),
                "reason": f"{left} {op} {right} is {best['actual']:g}, not {best['stated']:g}",
            }
        )

    if components:
        expected = sum(components)
        for claimed in _TOTAL_CLAIM.findall(answer or ""):
            readings = number_readings(claimed, locale=locale)
            if not readings:
                continue
            wrong = [v for v in readings if _off_by_more_than_tolerance(expected, v)]
            if len(wrong) != len(readings):
                if wrong:
                    out.append(
                        {
                            "kind": "number_format_ambiguity",
                            "claimed": claimed,
                            "readings": [
                                {"reads_as": v, "holds": v not in wrong} for v in readings
                            ],
                            "reason": (
                                f"the stated total '{claimed}' matches the sum of "
                                f"{len(components)} cited values ({expected:g}) under one "
                                "number format and not under the other; no locale was declared"
                            ),
                        }
                    )
                continue
            stated = min(wrong, key=lambda v: abs(expected - v))
            out.append(
                {
                    "kind": "aggregation_error",
                    "stated": stated,
                    "actual": round(expected, 4),
                    "components": len(components),
                    "reason": (
                        f"the stated total {stated:g} does not match the sum of "
                        f"{len(components)} cited values ({expected:g})"
                    ),
                }
            )
    return out


# ---------------------------------------------------------------------------
# F7.3 — period
# ---------------------------------------------------------------------------


def _quarters(text: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for pattern in _QUARTER_PATTERNS:
        for match in pattern.finditer(text or ""):
            groups = match.groups()
            year = groups[1] if len(groups) > 1 and groups[1] else ""
            found.add((groups[0], year))
    return found


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> set[str]:
    found: set[str] = set()
    for pattern in patterns:
        found |= set(pattern.findall(text or ""))
    return found


def _periods(text: str) -> dict[str, Any]:
    return {
        "quarters": _quarters(text),
        "fiscal": _matches(_FISCAL_PATTERNS, text),
        "calendar": _matches(_CALENDAR_PATTERNS, text),
        "years": set(_YEAR.findall(text or "")),
    }


def detect_period_mismatch(question: str, answer: str, context: str = "") -> list[dict]:
    """F7.3 — fiscal versus calendar, or an answer about a period nobody asked about.

    The fiscal/calendar case is the expensive one: both parties say "2024" and mean
    date ranges that overlap by nine months, so the answer looks right to everyone in
    the room and reconciles against nothing.

    `Q1`, `1. Quartal`, `1er trimestre` and `T1 2024` are the same quarter; `FY`,
    `GJ`, `exercice` and `ejercicio` are the same fiscal year.
    """
    asked, given = _periods(question), _periods(answer)
    out: list[dict[str, Any]] = []

    if asked["fiscal"] and given["calendar"]:
        out.append(
            {
                "kind": "fiscal_calendar_mismatch",
                "asked": sorted(asked["fiscal"]),
                "answered": sorted(given["calendar"]),
                "reason": "the question is about a fiscal year and the answer is calendar-year",
            }
        )
    if asked["calendar"] and given["fiscal"]:
        out.append(
            {
                "kind": "fiscal_calendar_mismatch",
                "asked": sorted(asked["calendar"]),
                "answered": sorted(given["fiscal"]),
                "reason": "the question is about a calendar year and the answer is fiscal-year",
            }
        )

    asked_q = {q for q, _y in asked["quarters"]}
    given_q = {q for q, _y in given["quarters"]}
    if asked_q and given_q and not (asked_q & given_q):
        out.append(
            {
                "kind": "quarter_mismatch",
                "asked": sorted(asked_q),
                "answered": sorted(given_q),
                "reason": f"asked about Q{'/Q'.join(sorted(asked_q))}, "
                f"answered about Q{'/Q'.join(sorted(given_q))}",
            }
        )

    asked_years = asked["years"] - asked["calendar"] - asked["fiscal"]
    given_years = given["years"] - given["calendar"] - given["fiscal"]
    if asked_years and given_years and not (asked_years & given_years):
        out.append(
            {
                "kind": "year_mismatch",
                "asked": sorted(asked_years),
                "answered": sorted(given_years),
                "reason": (
                    f"asked about {sorted(asked_years)}, answered about {sorted(given_years)}"
                ),
            }
        )
    if context:
        ctx = _periods(context)
        stray = given["years"] - ctx["years"] if ctx["years"] else set()
        if stray:
            out.append(
                {
                    "kind": "period_not_in_context",
                    "answered": sorted(stray),
                    "reason": f"the answer cites {sorted(stray)}, which is not in the retrieved "
                    "context",
                }
            )
    return out


# ---------------------------------------------------------------------------
# F7.3b — numeric date format
# ---------------------------------------------------------------------------


def _numeric_dates(text: str) -> list[dict[str, Any]]:
    """Numeric dates, as *written* — the day/month roles are not assigned here."""
    found: list[dict[str, Any]] = []
    for match in _DATE_ISO.finditer(text or ""):
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        found.append(
            {"raw": match.group(0), "year": year, "first": month, "second": day, "iso": True}
        )
    for match in _DATE_NUMERIC.finditer(text or ""):
        found.append(
            {
                "raw": match.group(0),
                "year": int(match.group(4)),
                "first": int(match.group(1)),
                "second": int(match.group(3)),
                "iso": False,
            }
        )
    return found


def _resolve_date(date: dict[str, Any], convention: str | None) -> tuple[int, int] | None:
    """(month, day), or None when the written form does not determine them.

    `convention` is "dmy" or "mdy". A component above 12 cannot be a month, so some
    dates resolve themselves with no convention at all.
    """
    if date["iso"]:
        return date["first"], date["second"]
    first, second = date["first"], date["second"]
    if first > 12 and second <= 12:
        return second, first
    if second > 12 and first <= 12:
        return first, second
    if first > 12 and second > 12:
        return None
    if convention == "dmy":
        return second, first
    if convention == "mdy":
        return first, second
    return None


#: Which way round a locale writes a numeric date. en-US is the outlier that makes
#: this necessary; everyone else is dmy or ymd.
_MDY_LOCALES = {"en-us", "en_us"}


def _date_convention(locale: str | None) -> str | None:
    if not locale:
        return None
    tag = str(locale).strip().lower().replace("_", "-")
    if tag in _MDY_LOCALES:
        return "mdy"
    if tag == "en":
        # Bare "en" does not say whether this is en-US or en-GB, and those disagree.
        return None
    if _locale_convention(tag) is not None:
        return "dmy"
    return None


def detect_date_mismatch(
    question: str, answer: str, context: str = "", *, locale: str | None = None
) -> list[dict[str, Any]]:
    """F7.3b — `03/04/2024` in the source against `04.03.2024` in the answer.

    This is deliberately the narrowest check in the module, and the narrowness is the
    design. A standalone "is this date ambiguous" check would fire on almost every
    English date ever written, which would destroy the precision of everything around
    it. So it fires only on a *transposed pair*: a date in the answer and a date in
    the source with the same year and the same two components in the opposite order.
    That shape is either a day/month transposition — the error worth catching — or the
    same date rendered in two conventions, which is how transpositions are born.

    Which of the two it is cannot be determined from the strings. With no declared
    locale the ambiguity itself is reported; with one, the dates are resolved and
    compared. Components above 12 resolve themselves and need no locale. Two-digit
    years are not parsed: that would be a second guess stacked on the first.
    """
    reference = "\n".join(t for t in (context or "", question or "") if t)
    answer_dates, reference_dates = _numeric_dates(answer), _numeric_dates(reference)
    if not answer_dates or not reference_dates:
        return []

    convention = _date_convention(locale)
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for given in answer_dates:
        for asked in reference_dates:
            if given["year"] != asked["year"]:
                continue
            if (given["first"], given["second"]) == (asked["first"], asked["second"]):
                continue
            if {given["first"], given["second"]} != {asked["first"], asked["second"]}:
                continue
            key = (given["raw"], asked["raw"])
            if key in seen:
                continue
            seen.add(key)

            given_resolved = _resolve_date(given, convention)
            asked_resolved = _resolve_date(asked, convention)
            if given_resolved is None or asked_resolved is None:
                out.append(
                    {
                        "kind": "date_format_ambiguity",
                        "answer": given["raw"],
                        "context": asked["raw"],
                        "reason": (
                            f"the answer writes '{given['raw']}' where the source writes "
                            f"'{asked['raw']}' — the same two components in the opposite "
                            "order. With no declared locale these are either the same date "
                            "in two formats or a day/month transposition, and the strings "
                            "do not say which"
                        ),
                    }
                )
            elif given_resolved != asked_resolved:
                out.append(
                    {
                        "kind": "date_mismatch",
                        "answer": given["raw"],
                        "context": asked["raw"],
                        "reason": (
                            f"the answer's '{given['raw']}' is "
                            f"{given_resolved[1]:02d}/{given_resolved[0]:02d} and the source's "
                            f"'{asked['raw']}' is {asked_resolved[1]:02d}/{asked_resolved[0]:02d} "
                            "— a day/month transposition"
                        ),
                    }
                )
    return out


# ---------------------------------------------------------------------------
# F7.4 — unit and currency
# ---------------------------------------------------------------------------


def _currencies(text: str) -> set[str]:
    found = {_CURRENCY_SYMBOLS[s] for s in _CURRENCY_SYMBOLS if s in (text or "")}
    return found | set(_CURRENCY_CODES.findall(text or ""))


def _scales(text: str) -> set[str]:
    return {match.group(1).lower() for match in _SCALE_RE.finditer(text or "")}


def detect_unit_mismatch(answer: str, context: str = "") -> list[dict[str, Any]]:
    """F7.4 — USD stated for a EUR figure, or thousands read as millions.

    Reported when the answer asserts a currency or scale the context does not, which
    means a conversion happened somewhere with nothing recording that it did.

    Currency is tested by symbol membership rather than position, so `$1,234.56` and
    `1.234,56 €` were already handled identically. Scale was not: `Mio.`, `Tsd.` and
    `Mds` are the same multipliers as `m`, `k` and `bn`.
    """
    out: list[dict[str, Any]] = []
    answer_ccy, context_ccy = _currencies(answer), _currencies(context)
    if len(answer_ccy) > 1:
        out.append(
            {
                "kind": "mixed_currency",
                "currencies": sorted(answer_ccy),
                "reason": f"the answer mixes {sorted(answer_ccy)} without stating a conversion",
            }
        )
    if context_ccy and answer_ccy and not (answer_ccy & context_ccy):
        out.append(
            {
                "kind": "currency_mismatch",
                "answer": sorted(answer_ccy),
                "context": sorted(context_ccy),
                "reason": (
                    f"the answer is in {sorted(answer_ccy)} and the source is in "
                    f"{sorted(context_ccy)}, with no conversion recorded"
                ),
            }
        )
    answer_scale, context_scale = _scales(answer), _scales(context)
    if context_scale and answer_scale:
        answer_factors = {_SCALE[s] for s in answer_scale}
        context_factors = {_SCALE[s] for s in context_scale}
        if not answer_factors & context_factors:
            out.append(
                {
                    "kind": "scale_mismatch",
                    "answer": sorted(answer_scale),
                    "context": sorted(context_scale),
                    "reason": (
                        f"the answer states {sorted(answer_scale)} and the source states "
                        f"{sorted(context_scale)}"
                    ),
                }
            )
    return out


# ---------------------------------------------------------------------------
# F7.5 — entity confusion
# ---------------------------------------------------------------------------


def detect_entity_confusion(
    question: str, answer: str, entities: list[str] | None = None
) -> list[dict[str, Any]]:
    """F7.5 — the right answer about the wrong customer.

    Fires when the question names one known entity and the answer names a different
    one. Bounded to the declared entity list on purpose: inferring entities from prose
    would flag every product name and place.

    Comparison is by `casefold`, not `lower`. German upper-cases `ß` to `SS`, so a
    registered `Weiß AG` does not match a mention of `WEISS AG` under `lower()` —
    the entity check silently switches itself off on exactly the German company names
    it is there to protect.
    """
    if not entities:
        return []
    folded_q, folded_a = (question or "").casefold(), (answer or "").casefold()
    asked = [e for e in entities if e and e.casefold() in folded_q]
    answered = [e for e in entities if e and e.casefold() in folded_a]
    if not asked or not answered:
        return []
    wrong = [e for e in answered if e not in asked]
    if not wrong:
        return []
    return [
        {
            "kind": "entity_confusion",
            "asked_about": asked,
            "answered_about": wrong,
            "reason": (
                f"the question is about {asked} and the answer is about {wrong} — right "
                "answer, wrong entity"
            ),
        }
    ]


# ---------------------------------------------------------------------------
# F7.6 — timezone
# ---------------------------------------------------------------------------


def detect_timezone_ambiguity(answer: str) -> list[dict[str, Any]]:
    """F7.6 — a deadline stated as a bare time, which is off by one day somewhere.

    Only fires on deadline language. Flagging every clock time would be noise, and a
    deadline is where the off-by-one actually costs something.

    Both halves of that gate were English-only: `Frist` and `date limite` are deadline
    words, and `17.00 Uhr` and `17h00` are clock times. The dotted form requires its
    trailing marker — an unmarked `17.00` is a price far more often than a time.
    """
    if not _DEADLINE.search(answer or ""):
        return []
    if not _TIME.search(answer or ""):
        return []
    if _TZ_NAMED.search(answer or ""):
        return []
    return [
        {
            "kind": "timezone_ambiguity",
            "reason": "a deadline is stated as a clock time with no timezone, which is "
            "off by a day for someone",
        }
    ]


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------


@dataclass
class IntegrityAssessment:
    issues: list[dict[str, Any]] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.issues

    @property
    def kinds(self) -> list[str]:
        return sorted({i["kind"] for i in self.issues if "kind" in i})

    def to_json(self) -> dict[str, Any]:
        return {"clean": self.clean, "kinds": self.kinds, "issues": self.issues}


def assess_integrity(
    *,
    question: str = "",
    answer: str = "",
    context: str = "",
    records: list[dict[str, Any]] | None = None,
    entities: list[str] | None = None,
    components: list[float] | None = None,
    locale: str | None = None,
) -> IntegrityAssessment:
    """All seven deterministic checks in one pass. F7.7 is the self-consistency scorer.

    `locale` is the caller's declaration of how this content is formatted (`"de"`,
    `"fr-CA"`, `"en-US"`). It is optional and defaults to undeclared, which is the
    honest default: no caller should have a locale invented for it. Declaring one
    removes the `number_format_ambiguity` and `date_format_ambiguity` findings, which
    exist precisely to say "this cannot be decided without knowing that".
    """
    issues: list[dict[str, Any]] = []
    issues.extend(
        {"kind": "hallucinated_record", **r} for r in detect_unmatched_records(answer, records)
    )
    issues.extend(check_arithmetic(answer, components=components, locale=locale))
    issues.extend(detect_period_mismatch(question, answer, context))
    issues.extend(detect_date_mismatch(question, answer, context, locale=locale))
    issues.extend(detect_unit_mismatch(answer, context))
    issues.extend(detect_entity_confusion(question, answer, entities))
    issues.extend(detect_timezone_ambiguity(answer))
    return IntegrityAssessment(issues=issues)
