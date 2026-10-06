"""Native PII detection (NOM-RTG-02) — the offline fallback.

Presidio is the primary implementation (MIT, mature, de-facto
standard — rebuilding it would be pure duplicated work). This module exists so the
platform still enforces something useful with **no optional dependency installed**,
and so there is a reference implementation the Presidio adapter is
tested against.

Entity sets are grouped into *jurisdiction packs* so a policy can say "EU + UK"
rather than enumerating regexes.
"""

from __future__ import annotations

import re

from agentfox.capabilities.detection.base import (
    BaseDetector,
    Detection,
    DetectionContext,
    redact_sample,
)

OWASP = "LLM02"
ATLAS = "AML.T0057"

Rule = tuple[str, re.Pattern[str], float]

# --- Global -----------------------------------------------------------------
_GLOBAL: list[Rule] = [
    ("PII.EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b"), 0.9),
    ("PII.IP_ADDRESS", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), 0.5),
    ("PII.CREDIT_CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b"), 0.95),
    ("PII.IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"), 0.9),
    (
        # `.` added alongside `/`/`-`: German-locale dates in
        # benchmarks/pii/'s multilingual dataset are DD.MM.YYYY-separated and
        # were missed entirely (0% recall) without it.
        "PII.DATE_OF_BIRTH",
        re.compile(r"\b(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}\b"),
        0.4,
    ),
]

# --- Jurisdiction packs ------------------------------------------------------
_PACKS: dict[str, list[Rule]] = {
    "us": [
        ("PII.US_SSN", re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"), 0.95),
        ("PII.US_PHONE", re.compile(r"\b(?:\+1[ -]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b"), 0.6),
        ("PII.US_PASSPORT", re.compile(r"\b[A-Z]\d{8}\b"), 0.4),
        ("PII.US_MRN", re.compile(r"\bMRN[:\s#-]*\d{6,10}\b", re.I), 0.85),
    ],
    "uk": [
        (
            "PII.UK_NINO",
            re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b"),
            0.9,
        ),
        ("PII.UK_NHS", re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b"), 0.5),
    ],
    "eu": [
        ("PII.EU_VAT", re.compile(r"\b(?:AT|BE|DE|ES|FR|IT|NL|PL|PT)[A-Z0-9]{8,12}\b"), 0.5),
    ],
    "in": [
        ("PII.IN_AADHAAR", re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b"), 0.7),
        ("PII.IN_PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0.8),
    ],
}

DEFAULT_PACKS = ("us", "uk", "eu")


def _luhn(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total, parity = 0, len(nums) % 2
    for i, n in enumerate(nums):
        if i % 2 == parity:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class NativePiiDetector(BaseDetector):
    covers_threats = ("LLM02", "AML.T0057")
    key = "pii.native"
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

    def __init__(self, packs: tuple[str, ...] = DEFAULT_PACKS) -> None:
        self.packs = packs

    @property
    def _rules(self) -> list[Rule]:
        rules = list(_GLOBAL)
        for pack in self.packs:
            rules.extend(_PACKS.get(pack, []))
        return rules

    def _detect(self, content: str, context: DetectionContext) -> list[Detection]:
        if not content:
            return []
        packs = tuple(context.extra.get("pii_packs", self.packs))
        rules = list(_GLOBAL)
        for pack in packs:
            rules.extend(_PACKS.get(pack, []))

        out: list[Detection] = []
        seen: set[tuple[int, int]] = set()
        for entity, pattern, score in rules:
            for m in pattern.finditer(content):
                span = (m.start(), m.end())
                if span in seen:
                    continue
                value = m.group()

                # Luhn removes the bulk of credit-card false positives; without it
                # this rule matches every long digit run and the detector becomes
                # noise, which is how guardrails get switched off.
                if entity == "PII.CREDIT_CARD":
                    if not _luhn(value):
                        continue
                if entity == "PII.IP_ADDRESS":
                    if any(int(p) > 255 for p in value.split(".")):
                        continue
                    if value.startswith(("0.", "127.", "255.")):
                        continue

                seen.add(span)
                out.append(
                    Detection(
                        entity_type=entity,
                        score=score,
                        start=m.start(),
                        end=m.end(),
                        sample=redact_sample(value),
                        owasp_id=OWASP,
                        atlas_id=ATLAS,
                        detail={"engine": "native"},
                    )
                )
        return out


def redact_content(content: str, detections: list[Detection], mode: str = "mask") -> str:
    """Apply redaction to content, right-to-left so offsets stay valid.

    ``mode``: ``mask`` (fixed marker), ``tokenize`` (stable placeholder per entity
    type, so a downstream system can still correlate without seeing the value).
    """
    if not detections:
        return content
    ordered = sorted(detections, key=lambda d: d.start, reverse=True)
    counters: dict[str, int] = {}
    out = content
    for det in ordered:
        if det.end <= det.start:
            continue
        if mode == "tokenize":
            counters[det.entity_type] = counters.get(det.entity_type, 0) + 1
            marker = f"<{det.entity_type}_{counters[det.entity_type]}>"
        else:
            marker = f"[REDACTED:{det.entity_type}]"
        out = out[: det.start] + marker + out[det.end :]
    return out
