"""Content-safety classification (P3-5, NOM-RTG-05) — offline fallback.

Granite Guardian (IBM, Apache-2.0) is the intended primary classifier: it has the
cleanest licence of the safety-classifier group (Appendix A.1/A.4), which matters
for a commercial product. This lexicon detector is the zero-dependency floor so
that the safety surface is never simply absent when weights are not present.

It is deliberately conservative and **scored, not binary** — a lexicon cannot
resolve intent, so it reports a category signal that policy decides what to do with,
rather than pretending to be a classifier.
"""

from __future__ import annotations

import re

from agentfox.detection.base import BaseDetector, Detection, DetectionContext, snippet

CATEGORIES = ("harm", "harassment", "self_harm", "illicit", "extremism", "sexual")

_LEXICON: dict[str, list[re.Pattern[str]]] = {
    "harm": [
        re.compile(
            r"\bhow\s+(?:to|do\s+i)\s+(?:make|build|synthesi[sz]e)\s+"
            r"(?:a\s+)?(?:bomb|explosive|nerve\s+agent|bioweapon)\b",
            re.I,
        ),
        re.compile(r"\b(?:untraceable|undetectable)\s+(?:poison|weapon|toxin)\b", re.I),
    ],
    "self_harm": [
        re.compile(
            r"\b(?:how\s+to|best\s+way\s+to)\s+(?:kill\s+myself|end\s+my\s+life|"
            r"commit\s+suicide)\b",
            re.I,
        ),
        re.compile(r"\blethal\s+dose\s+of\b", re.I),
    ],
    "illicit": [
        re.compile(
            r"\bhow\s+to\s+(?:launder\s+money|evade\s+(?:tax|detection)|"
            r"hack\s+into|bypass\s+(?:2fa|authentication))\b",
            re.I,
        ),
        re.compile(
            r"\b(?:buy|sell|obtain)\s+(?:stolen|cloned)\s+"
            r"(?:credit\s+cards?|credentials|identities)\b",
            re.I,
        ),
    ],
    "harassment": [
        re.compile(
            r"\b(?:write|draft|compose)\s+(?:a\s+)?(?:threatening|abusive|"
            r"harassing)\s+(?:message|email|letter)\b",
            re.I,
        ),
        re.compile(r"\b(?:dox|doxx)\b", re.I),
    ],
    "extremism": [
        re.compile(
            r"\b(?:recruit(?:ment)?\s+(?:for|material)|propaganda)\b.{0,40}?"
            r"\b(?:terror|extremis)",
            re.I,
        ),
    ],
}


class SafetyLexiconDetector(BaseDetector):
    covers_threats = ("LLM09",)
    key = "safety.lexicon"
    version = "1.0"
    surfaces = (
        "input",
        "output",
        "retrieved",
        "tool_result",
        # A completion claim is content too, and for a deployment that only
        # gates the end of a run this is the last place anything reads it.
        "completion",
    )

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        out: list[Detection] = []
        for category, patterns in _LEXICON.items():
            for pattern in patterns:
                m = pattern.search(content)
                if not m:
                    continue
                out.append(
                    Detection(
                        entity_type=f"SAFETY.{category.upper()}",
                        # Capped below 0.8: a lexicon should not by itself be
                        # enough to block. Policy combines it with other signals.
                        score=0.7,
                        start=m.start(),
                        end=m.end(),
                        sample=snippet(content, m.start(), m.end()),
                        owasp_id="LLM09",
                        detail={"engine": "lexicon", "category": category},
                    )
                )
                break
        return out
