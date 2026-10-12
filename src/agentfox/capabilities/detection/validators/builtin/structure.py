"""Validators: structure. See `validators/builtin/__init__.py`.

Whether a text parses as what it claims to be (JSON, Python, HTML, a URL, an
OpenAPI document), whether it carries a URL at all, and two that ask the outside
world (is this address real, does this URL answer). Those two make network calls,
so they are unavailable unless the deployment has turned ``allow_egress`` on.
"""

from __future__ import annotations

import ast
import ipaddress
import json
import os
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from agentfox.capabilities.detection.validators import register_validator
from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    Validator,
    span_finding,
)

_TEXT_SURFACES = ("input", "output", "tool_args", "tool_result")


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _offset(text: str, line: int, col: int) -> int:
    """Character offset of a 1-based line and 0-based column, clipped to the text."""
    starts = _line_starts(text)
    line = max(1, min(line, len(starts)))
    return max(0, min(starts[line - 1] + col, len(text)))


def _egress_allowed() -> bool:
    from agentfox.core.config import get_settings

    return bool(get_settings().allow_egress)


# -------------------------------------------------------------------------- JSON


@register_validator
class ValidJson(Validator):
    """Adapted from guardrails-ai/valid_json (Apache-2.0)."""

    name = "valid_json"
    label = "Valid JSON"
    description = "The text must parse as JSON."
    entity_type = "FORMAT.JSON"
    surfaces = _TEXT_SURFACES
    upstream = "guardrails-ai/valid_json"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        # Upstream also failed when the parsed value was falsy (`not parsed`), so the
        # valid JSON documents 0, false, null, "", [] and {} were all rejected. Only a
        # parse error fails here.
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            reason = f"not valid JSON: {exc.msg}"
            if exc.pos >= len(text):
                return [Finding(reason=reason)]
            return [span_finding(text, exc.pos, len(text), reason)]
        return []


# ------------------------------------------------------------------------ Python


@register_validator
class ValidPython(Validator):
    """Adapted from guardrails-ai/valid_python_validator (Apache-2.0)."""

    name = "valid_python"
    label = "Valid Python"
    description = "The text must be syntactically valid Python (parsed, never run)."
    entity_type = "CODE.PYTHON_SYNTAX"
    surfaces = ("output", "tool_args")
    upstream = "guardrails-ai/valid_python_validator"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        try:
            ast.parse(text)
        except SyntaxError as exc:
            reason = f"Python syntax error: {exc.msg}"
            if not exc.lineno:
                return [Finding(reason=reason)]
            start = _offset(text, exc.lineno, max(0, (exc.offset or 1) - 1))
            end_line = exc.end_lineno or exc.lineno
            end_col = (exc.end_offset or exc.offset or 1) - 1
            end = _offset(text, end_line, end_col)
            if end <= start:
                end = min(len(text), start + 1)
            if end <= start:  # error at the very end of the text
                return [Finding(reason=reason, detail={"line": exc.lineno})]
            return [span_finding(text, start, end, reason, line=exc.lineno)]
        except ValueError as exc:  # null bytes in the source
            return [Finding(reason=f"not parseable as Python: {exc}")]
        return []


# -------------------------------------------------------------------------- URLs


@register_validator
class ValidUrl(Validator):
    """Adapted from guardrails-ai/valid_url (Apache-2.0)."""

    name = "valid_url"
    label = "Valid URL"
    description = "The text must be a URL with a scheme and a host."
    entity_type = "FORMAT.URL"
    surfaces = _TEXT_SURFACES
    upstream = "guardrails-ai/valid_url"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        try:
            result = urlparse(text)
        except ValueError:
            return [Finding(reason="not a valid URL")]
        if not result.scheme or not result.netloc:
            return [Finding(reason="not a valid URL (needs a scheme and a host)")]
        return []


# Upstream's pattern, unchanged: an optional http(s) scheme, one or more labels and
# a top-level domain of letters.
_FILE_EXTENSIONS = frozenset(
    "py js ts tsx jsx json md txt csv tsv html htm css yml yaml toml ini cfg sh log "
    "pdf png jpg jpeg gif svg zip tar gz xml sql rb go rs java kt swift c h cpp".split()
)
_HAS_URL = re.compile(r"(?i)\b((?:(?:https?://)?(?:[a-z0-9\-]+[.]){1,127}[a-z]{2,63}))")


@register_validator
class HasUrl(Validator):
    """Adapted from guardrails-ai/has_url (Apache-2.0).

    Inverted: upstream *required* a URL and failed without one. As a check on what
    an agent says or sends, it fails when a URL (or bare domain) is present.
    """

    name = "has_url"
    label = "Contains a URL"
    description = "Flags URLs and bare domain names (example.com) in the text."
    entity_type = "DISCLOSURE.URL"
    surfaces = ("output", "tool_args", "agent_message")
    upstream = "guardrails-ai/has_url"

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        out = []
        for m in _HAS_URL.finditer(text):
            found = m.group(1)
            # Upstream's pattern also matched file names ("main.py", "notes.txt"); a
            # bare name ending in a file extension is not a link.
            if "://" not in found and found.rsplit(".", 1)[-1].lower() in _FILE_EXTENSIONS:
                continue
            out.append(span_finding(text, m.start(1), m.end(1), "text contains a URL"))
        return out


# -------------------------------------------------------------------------- HTML

_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "keygen",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _HtmlProblem(Exception):
    def __init__(self, message: str, pos: tuple[int, int] | None) -> None:
        super().__init__(message)
        self.pos = pos


class _TagBalance(HTMLParser):
    """Upstream's stdlib fallback: every non-void tag closed, in order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, tuple[int, int]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _VOID_ELEMENTS:
            self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack:
            raise _HtmlProblem(f"closing tag </{tag}> with no matching opener", self.getpos())
        opener, _ = self.stack.pop()
        if opener != tag:
            raise _HtmlProblem(
                f"closing tag </{tag}> does not match the open <{opener}>", self.getpos()
            )


@register_validator
class ValidHtml(Validator):
    """Adapted from guardrails-ai/valid_html (Apache-2.0).

    Upstream parsed with html5lib when installed and otherwise with this same
    stdlib tag-balance check; only the stdlib path is kept.
    """

    name = "valid_html"
    label = "Valid HTML"
    description = "The text must be well-formed HTML: every tag closed, in order."
    entity_type = "FORMAT.HTML"
    surfaces = ("output", "tool_args", "tool_result")
    upstream = "guardrails-ai/valid_html"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        parser = _TagBalance()
        try:
            parser.feed(text)
            parser.close()
        except _HtmlProblem as exc:
            if exc.pos is None:
                return [Finding(reason=str(exc))]
            start = _offset(text, exc.pos[0], exc.pos[1])
            end = text.find(">", start)
            end = len(text) if end < 0 else end + 1
            return [span_finding(text, start, end, str(exc))]
        if parser.stack:
            tag, pos = parser.stack[-1]
            missing = ", ".join(f"</{t}>" for t, _ in reversed(parser.stack))
            start = _offset(text, pos[0], pos[1])
            end = text.find(">", start)
            end = len(text) if end < 0 else end + 1
            return [span_finding(text, start, end, f"unclosed tags: expected {missing}")]
        return []


# ----------------------------------------------------------------------- OpenAPI

#: Upstream validated against the full OpenAPI 3.1 meta-schema, shipped in a
#: module (`schemas.py`) that is not part of this port. This keeps its top-level
#: contract: an `openapi` 3.x version, an `info` object with a title and version,
#: and at least one of paths, components or webhooks, each an object.
OPENAPI_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["openapi", "info"],
    "properties": {
        "openapi": {"type": "string", "pattern": r"^3\.\d+\.\d+(-.+)?$"},
        "info": {
            "type": "object",
            "required": ["title", "version"],
            "properties": {
                "title": {"type": "string"},
                "version": {"type": "string"},
                "description": {"type": "string"},
            },
        },
        "servers": {"type": "array", "items": {"type": "object", "required": ["url"]}},
        "paths": {
            "type": "object",
            "propertyNames": {"pattern": "^/"},
            "additionalProperties": {"type": "object"},
        },
        "components": {"type": "object"},
        "webhooks": {"type": "object"},
        "tags": {"type": "array", "items": {"type": "object", "required": ["name"]}},
    },
    "anyOf": [
        {"required": ["paths"]},
        {"required": ["components"]},
        {"required": ["webhooks"]},
    ],
}


@register_validator
class ValidOpenApiSpec(Validator):
    """Adapted from guardrails-ai/valid_open_api_spec (Apache-2.0)."""

    name = "valid_open_api_spec"
    label = "Valid OpenAPI document"
    description = "The text must be an OpenAPI 3.x document, in JSON or YAML."
    entity_type = "SCHEMA.OPENAPI"
    surfaces = ("output", "tool_args", "tool_result")
    requires = ("jsonschema", "yaml")
    upstream = "guardrails-ai/valid_open_api_spec"
    scan_views = False

    def check(self, text: str, params: BaseModel, ctx: CheckContext) -> list[Finding]:
        import yaml
        from jsonschema import Draft202012Validator

        try:
            spec = json.loads(text)
        except ValueError:
            try:
                spec = yaml.safe_load(text)
            except yaml.YAMLError:
                spec = None
        fields: dict[str, list[str]] = {}
        for error in Draft202012Validator(OPENAPI_SCHEMA).iter_errors(spec):
            fields.setdefault(error.json_path, []).append(error.message)
        if not fields:
            return []
        return [
            Finding(
                reason="not a valid OpenAPI document: " + ", ".join(sorted(fields)),
                detail={"fields": fields},
            )
        ]


# --------------------------------------------------------------------- addresses


class ValidAddressParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_code: str = Field("US", min_length=2, max_length=2)


_IGNORED_COMPONENTS = frozenset({"postal_code", "postal_code_suffix", "country"})


@register_validator
class ValidAddress(Validator):
    """Adapted from guardrails-ai/valid_address (Apache-2.0).

    Sends the text to Google's Address Validation API, so it needs the `googlemaps`
    package, a `GOOGLE_MAPS_API_KEY` and `allow_egress` on.
    """

    name = "valid_address"
    label = "Real postal address"
    description = (
        "The text must be a postal address Google's Address Validation API confirms, "
        "with no unconfirmed, guessed or misspelt parts. Sends the text to Google."
    )
    entity_type = "FORMAT.ADDRESS"
    surfaces = ("output",)
    Params = ValidAddressParams
    requires = ("googlemaps",)
    upstream = "guardrails-ai/valid_address"
    timeout_ms = 5000
    requires_budget_ms = 6000
    scan_views = False

    def available(self) -> bool:
        return (
            super().available()
            and _egress_allowed()
            and bool(os.environ.get("GOOGLE_MAPS_API_KEY"))
        )

    def unavailable_reason(self) -> str:
        reason = super().unavailable_reason()
        if reason:
            return reason
        if not _egress_allowed():
            return "calls Google's Address Validation API; allow_egress is off"
        if not os.environ.get("GOOGLE_MAPS_API_KEY"):
            return "needs GOOGLE_MAPS_API_KEY"
        return ""

    @staticmethod
    def outcome(response: dict[str, Any]) -> list[Finding]:
        """Upstream's reading of an API response, separated so it can be tested."""
        result = response["result"]
        components = result["address"]["addressComponents"]
        if result["verdict"].get("hasUnconfirmedComponents", False):
            return [Finding(reason="address has unconfirmed components")]
        if any(
            c["componentType"] not in _IGNORED_COMPONENTS and c.get("inferred", False)
            for c in components
        ):
            return [
                Finding(
                    reason="address has important components inferred",
                    detail={"suggested": result["address"].get("formattedAddress")},
                )
            ]
        if any(c.get("spellCorrected", False) for c in components):
            return [
                Finding(
                    reason="address has misspelt components",
                    detail={"suggested": result["address"].get("formattedAddress")},
                )
            ]
        return []

    def check(self, text: str, params: ValidAddressParams, ctx: CheckContext) -> list[Finding]:
        if not self.available():
            raise RuntimeError(f"{self.name} is unavailable: {self.unavailable_reason()}")
        import googlemaps

        client = googlemaps.Client(key=os.environ["GOOGLE_MAPS_API_KEY"], timeout=5)
        response = client.addressvalidation([text.strip()], regionCode=params.region_code)
        return self.outcome(response)


# --------------------------------------------------------------------- endpoints


def _public_host(host: str) -> bool:
    """False when the host resolves to a loopback, private or link-local address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # unresolvable: let the request fail as unreachable
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not ip.is_global:
            return False
    return True


class EndpointIsReachableParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_s: float = Field(3.0, gt=0, le=10)


@register_validator
class EndpointIsReachable(Validator):
    """Adapted from guardrails-ai/endpoint_is_reachable (Apache-2.0)."""

    name = "endpoint_is_reachable"
    label = "URL answers"
    description = (
        "The text must be an http(s) URL that answers a GET with status 200. Makes a "
        "request to that URL."
    )
    entity_type = "FORMAT.URL_REACHABLE"
    surfaces = ("output",)
    Params = EndpointIsReachableParams
    upstream = "guardrails-ai/endpoint_is_reachable"
    timeout_ms = 10_000
    requires_budget_ms = 11_000
    scan_views = False

    def available(self) -> bool:
        return _egress_allowed()

    def unavailable_reason(self) -> str:
        return "" if _egress_allowed() else "requests the URL; allow_egress is off"

    def check(
        self, text: str, params: EndpointIsReachableParams, ctx: CheckContext
    ) -> list[Finding]:
        import urllib.error
        import urllib.request

        if not self.available():
            raise RuntimeError(f"{self.name} is unavailable: {self.unavailable_reason()}")
        url = text.strip()
        parsed = urlparse(url)
        # Upstream handed the text to `requests.get`, which only speaks http(s).
        # urllib would also open file:// and ftp://, so refuse anything else, and
        # refuse hosts inside the network: an output is not allowed to make the
        # gateway fetch its own metadata service.
        if parsed.scheme not in ("http", "https"):
            return [Finding(reason="not an http(s) URL")]
        if not parsed.hostname:
            return [Finding(reason="URL has no host")]
        if not _public_host(parsed.hostname):
            return [Finding(reason="URL points inside the network; not requested")]
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=params.timeout_s) as resp:
                status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return [Finding(reason="URL could not be reached")]
        if status != 200:
            return [Finding(reason=f"URL returned status {status}", detail={"status": status})]
        return []
