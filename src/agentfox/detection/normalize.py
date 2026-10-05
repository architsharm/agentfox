"""Text normalisation — the layer that decides whether the detectors are worth having.

Measured against the adversarial corpus, the injection detector caught 28% of attacks.
The misses were not clever: separators between letters, a Cyrillic *а*, fullwidth
characters, base64, percent-encoding, and five languages that are not English. None of
those is an attack on the *pattern*; every one is an attack on the assumption that the
bytes a detector sees are the text a model will read.

So this normalises first, and the same normaliser feeds every detector — which means
secrets and PII detection get the same resistance for free, and a future model-based
detector inherits it too.

**Views, not a single rewrite.** Some transforms are safe to apply always (stripping
zero-width characters); others are only sometimes right (folding ``3`` to ``e`` would
turn "30 days" into "EO days"). Rather than choose, normalisation produces several
*views* of the same text and detectors run against all of them. A view is cheap, and
the alternative — one aggressive normalisation — trades false negatives for false
positives, which is the worse currency: over-blocking is what gets a guardrail
switched off.

**Offsets are carried, not recomputed.** Every view knows where each of its characters
came from, so a detection found in a decoded base64 blob still reports a span in the
original text. Without that, violation specificity (P3-12) would point at coordinates
in a string the user never sent, and redaction would corrupt the payload.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field

#: Characters that are invisible to a reader and meaningless to a model, but which
#: break every literal pattern they are sprinkled into.
_INVISIBLE = {
    "​",
    "‌",
    "‍",
    "⁠",
    "﻿",  # zero-width family
    "­",  # soft hyphen
    "᠎",  # Mongolian vowel separator
    "͏",  # combining grapheme joiner
}
#: Directional overrides, which can visually reverse text without changing codepoints.
_BIDI = {"‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"}

#: Homoglyphs NFKC does not fold, because they are legitimately different letters. A
#: Cyrillic "а" in an English sentence is not a typo, and folding it is the only way to
#: see the sentence the model will see.
#:
#: This table is a *convenience*, not the defence. Enumerating every lookalike is not
#: winnable — Unicode has more of them than anyone will type into a dict, and an
#: adaptive-attack run (``benchmarks/adaptive/``) measured a 55.3% solo bypass for the
#: letters this table happened to omit against 4.0% for the ones it covered. What makes
#: an unknown lookalike visible is ``_mixed_script_words`` below, which is structural
#: and needs no table. The table earns its place by *folding* the common cases, so the
#: lexical patterns still match rather than only an obfuscation signal firing; it is
#: kept broad for that reason and relied on for nothing.
_CONFUSABLE_LETTERS = {
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "А": "A",
    "Е": "E",
    "О": "O",
    "Р": "P",
    "С": "C",
    "У": "Y",
    "Х": "X",
    "м": "m",
    "н": "h",
    "в": "b",
    "т": "t",
    "к": "k",
    "ο": "o",
    "α": "a",
    "ρ": "p",
    "υ": "u",
    "Ι": "I",
    "Β": "B",
    "Ο": "O",
    "Ρ": "P",
    "ı": "i",
    "і": "i",
    "ӏ": "i",
    # Lookalikes the adaptive benchmark's `char.homoglyph_unmapped` operator used, and
    # their neighbours. Cross-script ones are also caught structurally; the Latin-block
    # ones (ɡ, ɑ, ɪ, ...) are *not*, because they are genuinely Latin — for those the
    # table is the only thing that sees them, which is why it is worth extending.
    "ѕ": "s",
    "ԁ": "d",
    "ј": "j",
    "ԝ": "w",
    "ѵ": "v",
    "ԛ": "q",
    "ԍ": "g",
    "һ": "h",
    "ԑ": "e",
    "ӡ": "3",
    "ո": "n",
    "օ": "o",
    "ս": "u",
    "ց": "g",
    "ɡ": "g",
    "ɑ": "a",
    "ɩ": "i",
    "ɪ": "i",
    "ɴ": "n",
    "ʀ": "r",
    "ʟ": "l",
    "ʏ": "y",
    "ʜ": "h",
    "ᴄ": "c",
    "ᴏ": "o",
    "ᴜ": "u",
    "ᴠ": "v",
    "ᴡ": "w",
    "ν": "v",
    "τ": "t",
    "κ": "k",
    "ε": "e",
    "ι": "i",
    "χ": "x",
    "η": "n",
    "γ": "y",
    "ϲ": "c",
    "ѡ": "w",
    "џ": "u",
}

#: Typographic punctuation folded for the same reason — a curly apostrophe must not
#: break a pattern written with a straight one. Kept *separate* from the letter table
#: because folding it is not evidence of anything: ordinary CJK text quotes with “ ”,
#: ordinary English em-dashes, and counting those as "homoglyphs" put 28 of the 339
#: deliberately-benign NotInject prompts over the obfuscation threshold.
_CONFUSABLE_PUNCT = {
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
}

_CONFUSABLES = {**_CONFUSABLE_LETTERS, **_CONFUSABLE_PUNCT}

#: Conservative leetspeak. Deliberately excludes 8→b and 6→g, which appear constantly
#: in legitimate technical text ("8GB", "IPv6").
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}

#: Every ASCII punctuation or symbol character, plus the space and the Unicode dashes
#: and middle dot. Deliberately a *complete* class rather than a curated one: the
#: attacker picks the separator, so a list of "separators we know about" is a list of
#: separators to avoid. ``I~g~n~o~r~e`` was the single most effective readable operator
#: in the adaptive run (68.4% solo bypass) purely because ``~`` was not in the old
#: class. What keeps this from over-firing is not the character set but the *shape*
#: required below: single alphanumerics, one repeated separator, four or more letters.
_SEP_CLASS = r"[!-/:-@\[-`{-~ ·‐-―]"

#: A run of single characters joined by separators — ``I-g-n-o-r-e``. Requires four or
#: more so that hyphenated words ("state-of-the-art", "opt-in") are untouched. The
#: space is in the class so that a whole separated *phrase* is one run and short words
#: inside it ("a-l-l") collapse too — but it is a word boundary, not a separator, and
#: ``_collapse_separators`` preserves it. See that function.
_SEPARATED = re.compile(r"(?:[A-Za-z0-9]" + _SEP_CLASS + r"){3,}[A-Za-z0-9]")

#: A cheap necessary condition for a run worth collapsing: two single alphanumerics
#: each followed by a *non-space* separator. Every run ``_collapse_separators`` will act
#: on contains one, because it requires at least two real separators in a chunk — but
#: unlike ``_SEPARATED`` it has no space in the class, so it fails at almost every
#: position instead of matching at the end of every word and backtracking. On a 32 KB
#: document it costs 0.3 ms against 0.7 ms for the full pattern, which matters because
#: `_is_plain` runs on every piece of content the gateway sees (NFR-1, X-7).
_SEPARATED_HINT = re.compile(r"[A-Za-z0-9][!-/:-@\[-`{-~][A-Za-z0-9][!-/:-@\[-`{-~]")

#: The word-sized chunks inside a separated run, split on the whitespace that separates
#: them. Each is validated on its own, so ``I-g-n-o-r-e a.l.l`` still collapses.
_RUN_CHUNK = re.compile(r"\S+")

#: Scripts written without spaces between words, so a run of letters is a *phrase*
#: rather than a word and mixing Latin into it is ordinary ("Tシャツ", "iPhone用").
#: Excluded from the mixed-script check entirely rather than weighted down: there is no
#: word boundary to reason about, so the signal has no meaning there.
_UNSEGMENTED_SCRIPTS = frozenset(
    {"CJK", "HIRAGANA", "KATAKANA", "HANGUL", "THAI", "LAO", "KHMER", "MYANMAR", "TIBETAN"}
)

#: Greek-by-codepoint characters that are Latin-by-usage in scientific and engineering
#: prose — "5μm", "10kΩ", "Δt". Narrow, closed, and about *legitimate* notation rather
#: than about lookalikes, so it does not reintroduce the enumeration problem.
_SCIENTIFIC_SYMBOLS = frozenset("μΩπΔΣ∆Åℓ")

#: A maximal run of letters in any script — the closest thing to a "word" that works
#: without a segmenter.
_LETTER_RUN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

#: Base64 candidates: long enough to carry a sentence, and correctly padded.
_B64 = re.compile(r"\b[A-Za-z0-9+/]{16,}={0,2}")

#: A leet substitute *between* two letters — "1gn0r3" has "n0r", while ordinary text
#: like "4.2m", "8GB" and "IPv6" does not. The looser "letter next to digit" version
#: matched almost every real document that mentions a quantity, which pushed all of
#: them onto the slow path and cost 35 ms on a 32 KB page for nothing.
_LEET_CANDIDATE = re.compile(r"[A-Za-z][0-9@$][A-Za-z]")

_MULTISPACE = re.compile(r"\s+")


@dataclass
class View:
    """One reading of the text, with a map back to where each character came from."""

    text: str
    #: ``offsets[i]`` is the index in the original string that produced ``text[i]``.
    #: ``None`` means the identity map — the view *is* the original text. Almost all
    #: real content needs no transformation at all, and materialising 30,000 integers
    #: to say "index i came from index i" was most of the cost of normalising a large
    #: document.
    offsets: list[int] | None = None
    kind: str = "normalized"
    note: str = ""

    def origin(self, start: int, end: int) -> tuple[int, int]:
        """Translate a span in this view back to a span in the original text.

        Clamped rather than exact for decoded views: a detection inside a base64 blob
        maps to the blob, because there is no finer truth to report — the offending
        bytes genuinely occupy that whole span in what the user sent.
        """
        if self.offsets is None:
            return (start, end)
        if not self.offsets:
            return (0, 0)
        lo = self.offsets[min(start, len(self.offsets) - 1)]
        hi = self.offsets[min(max(end - 1, start), len(self.offsets) - 1)] + 1
        return (min(lo, hi), max(lo, hi))


@dataclass
class Normalized:
    original: str
    views: list[View] = field(default_factory=list)
    transforms: list[str] = field(default_factory=list)
    #: Obfuscation observed. Worth reporting on its own: zero-width characters in a
    #: tool result are not an accident, whatever else the content turns out to say.
    evasion: list[dict] = field(default_factory=list)

    @property
    def primary(self) -> View:
        return self.views[0]

    @property
    def text(self) -> str:
        return self.primary.text


#: Anything that could make normalisation change the text. Cheap to test, and false
#: positives here only cost the slow path, never correctness.
_NEEDS_WORK = re.compile(r"\s\s|%[0-9A-Fa-f]{2}|&#?\w+;")


def _is_plain(text: str) -> bool:
    """True when every transform would be the identity, so none needs running."""
    if not text.isascii():
        return False
    if _NEEDS_WORK.search(text):
        return False
    if _LEET_CANDIDATE.search(text):
        return False
    # Separated runs. The old proxy lived in `_NEEDS_WORK` over a short separator
    # class; now that the class is every punctuation character it gets its own cheap
    # necessary condition, confirmed by the real pattern only when it fires.
    if _SEPARATED_HINT.search(text) and _SEPARATED.search(text):
        return False
    return not _B64.search(text)


def _chars(text: str) -> list[tuple[str, int]]:
    return [(ch, i) for i, ch in enumerate(text)]


def _render(pairs: list[tuple[str, int]]) -> tuple[str, list[int]]:
    return "".join(ch for ch, _ in pairs), [i for _, i in pairs]


# ---------------------------------------------------------------------------
# Transforms, each over (char, origin) pairs so offsets survive
# ---------------------------------------------------------------------------


def _strip_invisible(pairs: list[tuple[str, int]]) -> tuple[list[tuple[str, int]], int]:
    kept = [(ch, i) for ch, i in pairs if ch not in _INVISIBLE and ch not in _BIDI]
    return kept, len(pairs) - len(kept)


def _fold_compatibility(pairs: list[tuple[str, int]]) -> tuple[list[tuple[str, int]], int]:
    """NFKC per character, so one fullwidth char can expand without losing its origin."""
    out: list[tuple[str, int]] = []
    changed = 0
    for ch, i in pairs:
        if ch.isascii():
            out.append((ch, i))
            continue
        folded = unicodedata.normalize("NFKC", ch)
        if folded != ch:
            changed += 1
        for sub in folded:
            out.append((sub, i))
    return out, changed


def _dominant_scripts(text: str) -> set[str]:
    """Which scripts the text is genuinely written in, as opposed to salted with.

    A single Cyrillic "а" among English words is an attack. A page of Russian is a
    page of Russian, and folding it into Latin lookalikes destroys it — which is
    exactly what the first version of this did, turning "предыдущие" into "пpeдыдyщиe"
    and making every Russian pattern miss.
    """
    if text.isascii():
        # Nothing to protect: every confusable in the table is non-ASCII, so an ASCII
        # string cannot be "written in" a script the folding would damage.
        return set()
    counts: dict[str, int] = {}
    alphabetic = 0
    for ch in text:
        if not ch.isalpha():
            continue
        # Every letter counts towards the denominator, including ASCII ones. Counting
        # only non-ASCII letters would make a single smuggled Cyrillic character look
        # like a 100%-Cyrillic document and protect it from folding — the exact attack
        # this function exists to defeat.
        alphabetic += 1
        if ch.isascii():
            continue
        try:
            name = unicodedata.name(ch)
        except ValueError:
            continue
        script = name.split(" ")[0]
        counts[script] = counts.get(script, 0) + 1
    if not alphabetic:
        return set()
    # A third of the letters is comfortably more than salting and comfortably less
    # than a threshold that a mixed-language document would fail.
    return {script for script, n in counts.items() if n / alphabetic >= 0.3}


def _fold_confusables(pairs: list[tuple[str, int]]) -> tuple[list[tuple[str, int]], int]:
    """Fold lookalike characters, but never the script the text is actually written in.

    Returns the count of folded letters that were *inside a word*, which is the only
    form of this that is evidence. Two things are deliberately not counted:

    * punctuation — folding a curly quote or an en-dash is evidence of a word
      processor, not of evasion, and counting it made 28 of NotInject's 339
      deliberately-benign prompts score over the obfuscation threshold, every one of
      them for quoting with “ ”;
    * a lookalike standing on its own — NotInject also asks for "a logo with the letter
      'ɴ'". A character being *discussed* is not a character being *smuggled*; the
      attack is a substitution that changes a word, so a neighbouring letter is
      required. This is the same within-word rule `_mixed_script_words` applies, for
      the same reason.
    """
    text = "".join(ch for ch, _ in pairs)
    if text.isascii():
        return pairs, 0
    protected = _dominant_scripts(text)
    out: list[tuple[str, int]] = []
    changed = 0
    for position, (ch, i) in enumerate(pairs):
        mapped = _CONFUSABLES.get(ch)
        if mapped is not None and ch.isalpha():
            try:
                script = unicodedata.name(ch).split(" ")[0]
            except ValueError:
                script = ""
            if script in protected:
                out.append((ch, i))
                continue
        if mapped is not None:
            if ch in _CONFUSABLE_LETTERS and _has_letter_neighbour(pairs, position):
                changed += 1
            out.append((mapped, i))
        else:
            out.append((ch, i))
    return out, changed


def _has_letter_neighbour(pairs: list[tuple[str, int]], position: int) -> bool:
    """Is the character at ``position`` part of a word, rather than standing alone?"""
    before = pairs[position - 1][0] if position > 0 else ""
    after = pairs[position + 1][0] if position + 1 < len(pairs) else ""
    return before.isalpha() or after.isalpha()


def _script_of(ch: str) -> str:
    """The Unicode script family of one character, coarsely and without a dependency."""
    try:
        prefix = unicodedata.name(ch).split(" ")[0]
    except ValueError:
        return ""
    return prefix


def _mixed_script_words(text: str) -> int:
    """Count words that are written in more than one script.

    This is the answer to the table problem. A lookalike substitution is visible
    *structurally* — "previouѕ" mixes Latin with one Cyrillic letter — and that is true
    of every lookalike, including the ones no table lists. Nothing here needs to know
    which character was substituted or what it was meant to be.

    What it must not do is fire on ordinary multilingual text, so:

    * a document written in one script is never mixed, by construction — this is a
      *within-word* test, and Russian words are Russian all the way through;
    * scripts written without spaces (CJK, Thai) are skipped entirely, because a letter
      run there is a phrase and "iPhone用" is an ordinary Japanese phrase;
    * combining marks and modifier letters are ignored, so decomposed accents and the
      ʻokina do not count as a second script;
    * a short closed list of scientific symbols (μ, Ω, Δ) is ignored, because "5μm" is
      notation rather than obfuscation;
    * and a word must be four letters or longer, below which the evidence is too thin.

    It runs *after* confusable folding, so it reports only the residue — the lookalikes
    the table did not know. A mapped homoglyph is already reported as one.
    """
    if text.isascii():
        return 0
    count = 0
    for match in _LETTER_RUN.finditer(text):
        word = match.group(0)
        if word.isascii() or len(word) < 4:
            continue
        scripts: set[str] = set()
        skip = False
        for ch in word:
            if ch in _SCIENTIFIC_SYMBOLS:
                continue
            category = unicodedata.category(ch)
            if category in ("Mn", "Mc", "Me", "Lm"):
                continue
            script = _script_of(ch)
            if script in _UNSEGMENTED_SCRIPTS:
                skip = True
                break
            if script:
                scripts.add(script)
        if not skip and len(scripts) > 1:
            count += 1
    return count


def _collapse_separators(pairs: list[tuple[str, int]]) -> tuple[list[tuple[str, int]], int]:
    """Collapse ``I-g-n-o-r-e`` to a *word*, preserving the boundaries between words.

    The earlier version dropped every non-alphanumeric character inside a run, and the
    space was in the separator class, so a run was welded onto whatever followed it::

        "I-g-n-o-r-e a-l-l p-r-e-v-i-o-u-s i-n-s-t-r-u-c-t-i-o-n-s now"
            -> "Ignoreallpreviousinstructionsnow"

    Every lexical pattern ends in ``s?\b``, which cannot match mid-word, so appending a
    single word to a separated attack defeated the whole transform. The corpus case
    passed only because its separated run happened to be the entire string. Measured in
    ``benchmarks/adaptive/``: nothing fired at all on the ``input`` surface.

    So the space is treated as what it is — a word boundary — and survives. Each
    whitespace-delimited chunk of a run is then validated on its own:

    * one repeated separator per chunk, because a machine applying an obfuscation uses
      one character and ordinary punctuation-dense text ("a+b=c") does not;
    * at least three alphanumerics in the chunk, so "e.g" is left alone;
    * at least four *letters* across the whole run, so "1,2,3,4" is data;
    * and, for a run that is a single lone token, at least five alphanumerics — because
      a four-letter dotted token is an initialism ("N.A.S.A", "R.S.V.P") or a path
      ("a/b/c/d") far more often than it is an obfuscated word. A run spanning two or
      more separated words needs no such floor: a whole *phrase* written this way is
      unambiguous, which is what lets "a-l-l" collapse inside one.
    """
    text, offsets = _render(pairs)
    drop: set[int] = set()
    runs = 0
    for match in _SEPARATED.finditer(text):
        start, end = match.span()
        run = text[start:end]
        if sum(1 for ch in run if ch.isalpha()) < 4:
            continue
        chunks = []
        for chunk in _RUN_CHUNK.finditer(run):
            body = chunk.group(0)
            separators = {ch for ch in body if not ch.isalnum()}
            if len(separators) != 1:
                continue
            if sum(1 for ch in body if ch.isalnum()) < 3:
                continue
            chunks.append(chunk)
        if not chunks:
            continue
        if len(chunks) == 1 and sum(1 for ch in chunks[0].group(0) if ch.isalnum()) < 5:
            continue
        for chunk in chunks:
            base = start + chunk.start()
            for index, ch in enumerate(chunk.group(0), start=base):
                if not ch.isalnum():
                    drop.add(index)
        runs += 1
    if not drop:
        return pairs, 0
    kept = [(ch, offsets[i]) for i, ch in enumerate(text) if i not in drop]
    return kept, runs


def _collapse_whitespace(pairs: list[tuple[str, int]]) -> tuple[list[tuple[str, int]], int]:
    out: list[tuple[str, int]] = []
    previous_space = False
    for ch, i in pairs:
        space = ch.isspace()
        if space and previous_space:
            continue
        out.append((" " if space else ch, i))
        previous_space = space
    return out, 0


def _fold_leet(pairs: list[tuple[str, int]]) -> tuple[list[tuple[str, int]], int]:
    """Fold digits to letters only inside tokens that mix both.

    Applying this everywhere would rewrite "30 days" as "eo days" and "8GB" as "8gb",
    manufacturing nonsense for a detector to trip over. Restricting it to mixed tokens
    means ``1gn0r3`` folds and ``30`` does not.
    """
    text, offsets = _render(pairs)
    if not _LEET_CANDIDATE.search(text):
        return pairs, 0
    out: list[tuple[str, int]] = []
    changed = 0
    for token in re.finditer(r"\S+|\s+", text):
        chunk = token.group(0)
        mixed = any(c.isalpha() for c in chunk) and any(c in _LEET for c in chunk)
        for index, ch in enumerate(chunk, start=token.start()):
            if mixed and ch in _LEET:
                changed += 1
                out.append((_LEET[ch], offsets[index]))
            else:
                out.append((ch, offsets[index]))
    return out, changed


# ---------------------------------------------------------------------------
# Decoded views
# ---------------------------------------------------------------------------


def _decoded_views(text: str) -> tuple[list[View], list[dict]]:
    """Views for content that was encoded rather than written.

    Decoding is not the same as accusing: a base64 attachment name is ordinary, so the
    decoded view is only *offered* to the detectors. If it says nothing, nothing
    happens.
    """
    views: list[View] = []
    evasion: list[dict] = []

    for match in _B64.finditer(text):
        blob = match.group(0)
        try:
            raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True)
            decoded = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        # Require it to look like language, not like bytes that happen to decode.
        printable = sum(1 for c in decoded if c.isprintable() or c.isspace())
        if len(decoded) < 8 or printable / len(decoded) < 0.9:
            continue
        views.append(
            View(
                text=decoded,
                offsets=[match.start()] * len(decoded),
                kind="base64",
                note=f"decoded from {len(blob)} base64 characters",
            )
        )
        evasion.append(
            {"kind": "base64", "span": [match.start(), match.end()], "decoded_length": len(decoded)}
        )

    unquoted = urllib.parse.unquote(text)
    if unquoted != text and "%" in text:
        views.append(
            View(
                text=unquoted,
                offsets=_approximate_offsets(text, unquoted),
                kind="url_decoded",
                note="percent-encoded",
            )
        )
        evasion.append({"kind": "url_encoded"})

    unescaped = html.unescape(text)
    if unescaped != text and "&" in text:
        views.append(
            View(
                text=unescaped,
                offsets=_approximate_offsets(text, unescaped),
                kind="html_decoded",
                note="HTML entities",
            )
        )
        evasion.append({"kind": "html_entity"})

    return views, evasion


def _approximate_offsets(original: str, decoded: str) -> list[int]:
    """Proportional mapping for whole-string decodes.

    Exact per-character mapping through a decoder is possible but not worth it here:
    decoding shortens text uniformly enough that a proportional map lands a detection
    within a few characters, and the span is only ever used to show a human where to
    look.
    """
    if not decoded:
        return []
    ratio = len(original) / len(decoded)
    return [min(len(original) - 1, int(i * ratio)) for i in range(len(decoded))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def normalize(text: str, *, aggressive: bool = True) -> Normalized:
    """Produce every reading of ``text`` a detector should consider.

    The first view is the safe normalisation — invisible characters removed,
    compatibility and confusables folded, separators and whitespace collapsed. It is
    conservative enough to be the default for any detector. Additional views cover
    transforms that are right often but not always: leetspeak, and anything that was
    encoded.
    """
    result = Normalized(original=text)
    if not text:
        result.views.append(View(text="", offsets=[], kind="normalized"))
        return result

    # Fast path. Ordinary content needs no transformation, and paying the
    # per-character cost to discover that would put a 32 KB retrieved document over
    # the whole pipeline's latency budget on this detector alone (NFR-1, X-7). A
    # governance layer that adds 50 ms to every request gets removed.
    if _is_plain(text):
        result.views.append(View(text=text, kind="normalized"))
        return result

    pairs = _chars(text)
    pairs, invisible = _strip_invisible(pairs)
    if invisible:
        result.transforms.append("invisible")
        result.evasion.append({"kind": "invisible_characters", "count": invisible})

    pairs, folded = _fold_compatibility(pairs)
    if folded:
        result.transforms.append("nfkc")
        result.evasion.append({"kind": "compatibility_characters", "count": folded})

    pairs, confused = _fold_confusables(pairs)
    if confused:
        result.transforms.append("confusables")
        result.evasion.append({"kind": "homoglyphs", "count": confused})

    # Structural obfuscation, checked on the folded text so that it reports only what
    # the table did not already resolve. This is the signal that does not depend on
    # knowing which lookalike was used — see `_mixed_script_words`.
    mixed = _mixed_script_words("".join(ch for ch, _ in pairs))
    if mixed:
        result.evasion.append({"kind": "mixed_script", "words": mixed})

    pairs, separated = _collapse_separators(pairs)
    if separated:
        result.transforms.append("separators")
        result.evasion.append({"kind": "character_separators", "runs": separated})

    pairs, _ = _collapse_whitespace(pairs)
    primary_text, primary_offsets = _render(pairs)
    result.views.append(View(text=primary_text, offsets=primary_offsets, kind="normalized"))

    # The unmodified text, always. Normalisation is lossy on purpose, and a pattern
    # written for the real thing — a non-English phrase, an exact token — must still
    # get a look at what was actually sent.
    if primary_text != text:
        result.views.append(
            View(text=text, offsets=list(range(len(text))), kind="raw", note="unmodified")
        )

    if aggressive:
        leet_pairs, leeted = _fold_leet(pairs)
        if leeted:
            leet_text, leet_offsets = _render(leet_pairs)
            result.views.append(View(text=leet_text, offsets=leet_offsets, kind="leet"))
            result.transforms.append("leet")

        decoded, decoded_evasion = _decoded_views(text)
        result.views.extend(decoded)
        result.evasion.extend(decoded_evasion)
        result.transforms.extend(sorted({v.kind for v in decoded}))

    return result


def evasion_score(result: Normalized) -> float:
    """How hard is this text trying not to be read?

    Obfuscation is evidence in its own right. Legitimate content is occasionally
    fullwidth or occasionally base64; it is rarely both, and almost never zero-width.
    """
    # Weighted by how anomalous the technique is in *legitimate* content, which is the
    # only thing that makes this usable as a signal. Zero-width characters and
    # homoglyphs essentially never occur by accident, so either alone is enough.
    # Base64 and percent-encoding are everywhere in ordinary tool results — an
    # attachment, a token, an image — and scoring them highly flagged a benign
    # attachment as an attack, which is the over-blocking that gets a guardrail
    # switched off.
    # `mixed_script` carries the same weight as `homoglyphs` because it is the same
    # evidence, seen structurally rather than through a table — a word that changes
    # script halfway through is a substituted lookalike whether or not we can name it.
    # It is reported only for the residue the table did not fold, so the two do not
    # double-count the same character.
    weights = {
        "invisible_characters": 0.6,
        "homoglyphs": 0.6,
        "mixed_script": 0.6,
        "character_separators": 0.5,
        "compatibility_characters": 0.2,
        "base64": 0.15,
        "url_encoded": 0.1,
        "html_entity": 0.1,
    }
    score = 0.0
    for signal in result.evasion:
        score += weights.get(signal.get("kind", ""), 0.0)
    return min(1.0, score)
