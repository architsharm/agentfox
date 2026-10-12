"""Validators: web. See `validators/builtin/__init__.py`.

Markup that would run in a browser if an output were rendered as HTML, and
hostnames a workspace keeps internal.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentfox.capabilities.detection.validators import register_validator
from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    Validator,
    span_finding,
)

# Each pattern names what makes the markup executable. Matched case-insensitively,
# with the whitespace and slashes browsers accept between a tag name and its
# attributes ("<img/onerror=...>").
_XSS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("script tag", re.compile(r"<\s*script\b[^>]*>?", re.I)),
    (
        "event-handler attribute",
        re.compile(r"<[a-z][^>]*?[\s/\"']on[a-z]+\s*=", re.I),
    ),
    ("javascript: URL", re.compile(r"\bj\s*a\s*v\s*a\s*s\s*c\s*r\s*i\s*p\s*t\s*:", re.I)),
    ("vbscript: URL", re.compile(r"\bvbscript\s*:", re.I)),
    ("data:text/html URL", re.compile(r"\bdata\s*:\s*text/html\b", re.I)),
    ("embedded frame or object", re.compile(r"<\s*(?:iframe|frame|object|embed|applet)\b", re.I)),
    ("srcdoc attribute", re.compile(r"[\s/\"']srcdoc\s*=", re.I)),
    ("CSS expression()", re.compile(r"\bexpression\s*\(", re.I)),
)

# CSS `expression(` only means something inside a style; on its own it is an
# English word followed by a parenthesis.
_STYLE_CONTEXT = re.compile(r"(?:style\s*=|<\s*style\b|\{)[^<]{0,500}$", re.I)


@register_validator
class WebSanitization(Validator):
    """Adapted from guardrails-ai/web_sanitization (Apache-2.0).

    Upstream failed whenever `bleach.clean` changed the text, which also fires on
    any `<b>` or bare `&`. Without bleach, this looks for the constructs that
    actually execute: script tags, event handlers, script URLs, frames and objects,
    srcdoc and CSS expressions.
    """

    name = "web_sanitization"
    label = "Browser-executable markup"
    description = (
        "Flags markup that would run script if rendered as HTML: <script>, on*= "
        "handlers, javascript:/vbscript:/data:text/html URLs, iframes and objects, "
        "srcdoc and CSS expression()."
    )
    entity_type = "CODE.XSS"
    surfaces = ("output", "tool_result", "retrieved", "agent_message")
    upstream = "guardrails-ai/web_sanitization"
    owasp_id = "LLM05"
    detector = True

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        out: list[Finding] = []
        for what, pattern in _XSS_PATTERNS:
            for m in pattern.finditer(text):
                if what == "CSS expression()" and not _STYLE_CONTEXT.search(text, 0, m.start()):
                    continue
                out.append(span_finding(text, m.start(), m.end(), f"{what} in output", kind=what))
        out.sort(key=lambda f: (f.start, f.end))
        return out


# A URL or a bare hostname: optional scheme and user info, the host, an optional
# port and path. The look-behind keeps a match from starting mid-word.
_HOST = re.compile(
    r"(?<![\w.\-])"
    r"(?:[a-z][a-z0-9+.\-]*://)?"
    r"(?:[^\s/@:\"'<>]+(?::[^\s/@\"'<>]*)?@)?"
    r"(?P<host>[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)*)"
    r"(?::\d{1,5})?"
    r"(?:[/?#][^\s\"'<>]*)?",
    re.I,
)
_TRAILING = ".,;:!?)]}"


class InternalDomainsParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    internal_domains: list[str] = Field(min_length=1, max_length=500)

    @field_validator("internal_domains")
    @classmethod
    def _normalise(cls, value: list[str]) -> list[str]:
        out = []
        for d in value:
            d = d.strip().strip(".").lower()
            if "://" in d:
                d = d.split("://", 1)[1]
            d = d.split("/", 1)[0]
            if not d:
                raise ValueError("empty domain")
            out.append(d)
        return out


@register_validator
class InternalDomains(Validator):
    """Adapted from guardrails-ai/internal_domains (Apache-2.0).

    Upstream matched the domain as a raw substring, so "internal.example.com" also
    hit "notinternal.example.com" and "internal.example.company". Here the host
    must equal the domain or be a subdomain of it.
    """

    name = "internal_domains"
    label = "Internal domains"
    description = (
        "Flags URLs and hostnames on internal domains: the domain itself or any subdomain of it."
    )
    entity_type = "DISCLOSURE.INTERNAL_DOMAIN"
    surfaces = ("output", "tool_args", "agent_message")
    Params = InternalDomainsParams
    upstream = "guardrails-ai/internal_domains"

    def check(self, text: str, params: InternalDomainsParams, ctx: CheckContext) -> list[Finding]:
        out: list[Finding] = []
        for m in _HOST.finditer(text):
            host = m.group("host").lower()
            domain = next(
                (d for d in params.internal_domains if host == d or host.endswith("." + d)),
                None,
            )
            if domain is None:
                continue
            end = m.end()
            while end > m.end("host") and text[end - 1] in _TRAILING:
                end -= 1
            out.append(span_finding(text, m.start(), end, "internal domain in text", domain=domain))
        return out
