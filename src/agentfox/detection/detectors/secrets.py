"""Secret and credential leakage detection (NOM-RTG-03).

Built natively rather than wrapped: this is cheap, high-precision regex + entropy
work where an OSS dependency buys little and costs a supply-chain surface.

Precision matters more than recall here. A secrets detector that fires on every
long hex string trains people to ignore it, and an ignored guardrail is an absent
one. Entropy alone is therefore never sufficient — it must be paired with
a contextual assignment cue.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from agentfox.detection.base import BaseDetector, Detection, DetectionContext, redact_sample

OWASP = "LLM02"
ATLAS = "AML.T0055"

# High-confidence provider-specific formats. These are safe to score near-certain.
_KNOWN: list[tuple[str, re.Pattern[str], float]] = [
    ("SECRET.OPENAI_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"), 0.97),
    ("SECRET.ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"), 0.97),
    ("SECRET.AWS_ACCESS_KEY", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"), 0.97),
    ("SECRET.GITHUB_TOKEN", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), 0.97),
    ("SECRET.SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), 0.97),
    ("SECRET.GOOGLE_API_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), 0.95),
    ("SECRET.STRIPE_KEY", re.compile(r"\b[rs]k_(?:live|test)_[A-Za-z0-9]{20,}\b"), 0.97),
    (
        "SECRET.PRIVATE_KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        0.99,
    ),
    (
        "SECRET.JWT",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        0.9,
    ),
    ("SECRET.NOMETRIA_KEY", re.compile(r"\bnom_(?:agt|api)_[A-Za-z0-9]{16,}\b"), 0.99),
    (
        "SECRET.CONNECTION_STRING",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://"
            r"[^\s:@/]+:[^\s:@/]+@[^\s/]+",
            re.I,
        ),
        0.9,
    ),
]

# Generic "assignment of a high-entropy value to a secret-looking name".
_ASSIGNMENT = re.compile(
    r"(?P<name>[A-Za-z0-9_.\-]*(?:api[_-]?key|secret|token|passwd|password|credential|"
    r"access[_-]?key|private[_-]?key|auth)[A-Za-z0-9_.\-]*)"
    r"\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9_\-+/=.]{12,})[\"']?",
    re.I,
)

_HEX_OR_B64 = re.compile(r"^[A-Fa-f0-9]{24,}$|^[A-Za-z0-9+/=_-]{24,}$")


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


class SecretsDetector(BaseDetector):
    covers_threats = ("LLM02", "AML.T0055")
    key = "secrets.native"
    version = "1.1"
    surfaces = (
        "input",
        "output",
        "tool_args",
        "tool_result",
        "retrieved",
        "memory_write",
        "agent_message",
        # A completion claim is content too, and for a deployment that only
        # gates the end of a run this is the last place anything reads it.
        "completion",
        # The model's own reasoning: a detection here means the payload
        # was adopted, not merely present.
        "reasoning",
    )

    #: Below this, a generic high-entropy string is treated as ordinary data.
    entropy_threshold = 3.6

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        out: list[Detection] = []
        claimed: list[tuple[int, int]] = []

        for entity, pattern, score in _KNOWN:
            for m in pattern.finditer(content):
                claimed.append((m.start(), m.end()))
                out.append(
                    Detection(
                        entity_type=entity,
                        score=score,
                        start=m.start(),
                        end=m.end(),
                        sample=redact_sample(m.group(), keep=6),
                        owasp_id=OWASP,
                        atlas_id=ATLAS,
                        detail={"signal": "known_format"},
                    )
                )

        for m in _ASSIGNMENT.finditer(content):
            start, end = m.span("value")
            if any(s <= start < e for s, e in claimed):
                continue
            value = m.group("value")
            entropy = shannon_entropy(value)
            # Both cues required: a secret-shaped *name* and a high-entropy *value*.
            if entropy < self.entropy_threshold or not _HEX_OR_B64.match(value):
                continue
            out.append(
                Detection(
                    entity_type="SECRET.GENERIC",
                    score=min(0.9, 0.5 + (entropy - self.entropy_threshold) / 2),
                    start=start,
                    end=end,
                    sample=redact_sample(value, keep=4),
                    owasp_id=OWASP,
                    atlas_id=ATLAS,
                    detail={
                        "signal": "entropy+assignment",
                        "name": m.group("name")[:60],
                        "entropy": round(entropy, 2),
                    },
                )
            )
        return out
