"""OTLP ingestion.

The third integration surface, and the one that needs no integration at all: a team
already emitting OpenTelemetry gets the agent registry, shadow-agent detection and
traces by pointing their existing collector at us. No code change, no proxy, no
SDK — which keeps time-to-first-value to minutes.

Spans following OpenLLMetry / OTel GenAI semantic conventions map onto our
agent-native span model; anything else is retained as context rather than dropped,
because an unrecognised span is still part of the execution path an auditor will
ask about.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import zlib
from typing import Any

from sqlalchemy.orm import Session

from agentfox.core.models import Span, Trace, utcnow
from agentfox.platform.ledger.trace import ATTR_AGENT, start_trace

# Framework fingerprints for auto-discovery. Order matters: more specific first.
_FRAMEWORK_MARKERS: list[tuple[str, tuple[str, ...]]] = [
    ("langgraph", ("langgraph", "langgraph.node", "langgraph.graph")),
    ("langchain", ("langchain", "lc.", "langchain.chain")),
    ("llamaindex", ("llama_index", "llamaindex")),
    ("crewai", ("crewai", "crew.")),
    ("autogen", ("autogen", "ag2")),
    ("claude-agent-sdk", ("anthropic.agent", "claude_agent", "claude-agent-sdk")),
    ("google-adk", ("google.adk", "adk.agent")),
    ("openai-agents", ("openai.agents", "agentkit", "openai.agent")),
    ("semantic-kernel", ("semantic_kernel", "sk.")),
]


def _attr_value(value: dict[str, Any]) -> Any:
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            return value[key]
    if "arrayValue" in value:
        return [_attr_value(v) for v in value["arrayValue"].get("values", [])]
    return None


def flatten_attributes(attributes: list[dict[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for attr in attributes or []:
        key = attr.get("key")
        if key:
            out[key] = _attr_value(attr.get("value") or {})
    return out


def detect_framework(attributes: dict[str, Any], span_name: str = "") -> str | None:
    """Record what the agent is built on, for neutrality reporting."""
    haystack = " ".join([span_name.lower(), *(f"{k}={v}".lower() for k, v in attributes.items())])
    for framework, markers in _FRAMEWORK_MARKERS:
        if any(marker in haystack for marker in markers):
            return framework
    return None


def _span_kind(name: str, attributes: dict[str, Any]) -> str:
    if "gen_ai.tool.name" in attributes or name.startswith("tool"):
        return "tool"
    if any(k.startswith("gen_ai.") for k in attributes):
        return "llm"
    if "retriev" in name.lower() or "vector" in name.lower() or "embedding" in name.lower():
        return "retrieval"
    if "agent" in name.lower():
        return "agent"
    return "llm"


#: Ceiling on a decompressed OTLP body. A collector batch is a few MB at most; this
#: stops a small gzip body from expanding into memory without limit.
MAX_OTLP_BODY_BYTES = 32 * 1024 * 1024

PROTOBUF_CONTENT_TYPE = "application/x-protobuf"


class OtlpDecodeError(ValueError):
    """An OTLP body this endpoint cannot read. ``status`` is the HTTP status to answer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _decompress(body: bytes, content_encoding: str | None) -> bytes:
    encoding = (content_encoding or "identity").strip().lower()
    if encoding in ("", "identity"):
        return body
    if encoding not in ("gzip", "deflate"):
        raise OtlpDecodeError(
            415, f"unsupported Content-Encoding '{encoding}'; send gzip, deflate or none"
        )
    # wbits 47 accepts gzip and zlib headers alike; raw deflate needs -15.
    for wbits in (47,) if encoding == "gzip" else (47, -15):
        inflater = zlib.decompressobj(wbits)
        try:
            out = inflater.decompress(body, MAX_OTLP_BODY_BYTES + 1)
        except zlib.error:
            continue
        if len(out) > MAX_OTLP_BODY_BYTES or inflater.unconsumed_tail:
            raise OtlpDecodeError(413, "decompressed OTLP body exceeds 32 MiB")
        return out
    raise OtlpDecodeError(400, f"the body is not valid {encoding} data")


def _hex_id(value: Any) -> Any:
    """OTLP/JSON writes trace and span ids as hex; protobuf's JSON mapping as base64."""
    if not isinstance(value, str) or not value:
        return value
    try:
        return base64.b64decode(value, validate=True).hex()
    except (ValueError, TypeError):
        return value


def _protobuf_to_json(body: bytes) -> dict[str, Any]:
    try:
        from google.protobuf.json_format import MessageToDict
        from google.protobuf.message import DecodeError
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )
    except ImportError as exc:
        raise OtlpDecodeError(
            415,
            "OTLP protobuf needs the opentelemetry-proto package, which is not installed "
            "on this server: install `agentfox[otel]`, or configure the exporter to send "
            "JSON (OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/json).",
        ) from exc
    request = ExportTraceServiceRequest()
    try:
        request.ParseFromString(body)
    except DecodeError as exc:
        raise OtlpDecodeError(400, f"the body is not a valid OTLP protobuf message: {exc}") from exc
    payload = MessageToDict(request, use_integers_for_enums=True)
    for resource_span in payload.get("resourceSpans", []):
        for scope_span in resource_span.get("scopeSpans", []):
            for span in scope_span.get("spans", []):
                for key in ("traceId", "spanId", "parentSpanId"):
                    if key in span:
                        span[key] = _hex_id(span[key])
    return payload


def decode_otlp_body(
    body: bytes, *, content_type: str | None, content_encoding: str | None
) -> dict[str, Any]:
    """Turn an OTLP/HTTP request body into the OTLP/JSON shape `ingest_otlp` reads.

    Accepts both encodings the OTLP/HTTP spec defines — binary protobuf (what the
    OpenTelemetry SDK exporters send by default) and JSON — each optionally gzip
    compressed. Raises `OtlpDecodeError` with the status to answer, never a 500.
    """
    raw = _decompress(body, content_encoding)
    media = (content_type or "application/json").split(";", 1)[0].strip().lower()
    if media == PROTOBUF_CONTENT_TYPE:
        return _protobuf_to_json(raw)
    if media in ("application/json", "") or media.endswith("+json"):
        try:
            payload = json.loads(raw or b"{}")
        except (ValueError, UnicodeDecodeError) as exc:
            raise OtlpDecodeError(400, f"the body is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise OtlpDecodeError(400, "an OTLP/JSON body is an object with resourceSpans")
        return payload
    raise OtlpDecodeError(
        415,
        f"unsupported Content-Type '{media}'; send {PROTOBUF_CONTENT_TYPE} or application/json",
    )


def ingest_otlp(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Ingest an OTLP/JSON trace export.

    Returns a summary including any agent slugs observed, so the caller can run
    shadow-agent detection over them.
    """
    ingested_spans = 0
    traces_touched: dict[str, Trace] = {}
    agents_seen: set[str] = set()
    frameworks: dict[str, str] = {}

    for resource_span in payload.get("resourceSpans", []):
        resource_attrs = flatten_attributes((resource_span.get("resource") or {}).get("attributes"))
        for scope_span in resource_span.get("scopeSpans", []):
            scope_name = (scope_span.get("scope") or {}).get("name", "")
            for otel_span in scope_span.get("spans", []):
                attrs = {**resource_attrs, **flatten_attributes(otel_span.get("attributes"))}
                name = otel_span.get("name", "span")

                agent_slug = str(
                    attrs.get(ATTR_AGENT)
                    or attrs.get("service.name")
                    or attrs.get("gen_ai.agent.name")
                    or "unknown"
                )
                agents_seen.add(agent_slug)

                framework = detect_framework(attrs, f"{name} {scope_name}")
                if framework:
                    frameworks[agent_slug] = framework

                otel_trace_id = str(otel_span.get("traceId") or "")
                key = f"{agent_slug}:{otel_trace_id}"
                trace = traces_touched.get(key)
                if trace is None:
                    trace = start_trace(
                        session,
                        agent_id=None,
                        agent_slug=agent_slug,
                        session_id=otel_trace_id or None,
                        environment=str(attrs.get("deployment.environment", "production")),
                        model=attrs.get("gen_ai.request.model"),
                        provider=attrs.get("gen_ai.system"),
                    )
                    traces_touched[key] = trace

                start_ns = int(otel_span.get("startTimeUnixNano") or 0)
                end_ns = int(otel_span.get("endTimeUnixNano") or start_ns)
                started = (
                    dt.datetime.fromtimestamp(start_ns / 1e9, dt.UTC) if start_ns else utcnow()
                )
                session.add(
                    Span(
                        trace_id=trace.id,
                        parent_span_id=None,
                        kind=_span_kind(name, attrs),
                        name=name,
                        started_at=started,
                        ended_at=(
                            dt.datetime.fromtimestamp(end_ns / 1e9, dt.UTC) if end_ns else None
                        ),
                        duration_ms=max(0.0, (end_ns - start_ns) / 1e6),
                        attributes_json={
                            **attrs,
                            "otel.scope": scope_name,
                            "otel.span_id": otel_span.get("spanId"),
                        },
                        status="error"
                        if (otel_span.get("status") or {}).get("code") == 2
                        else "ok",
                    )
                )
                ingested_spans += 1

    for trace in traces_touched.values():
        trace.ended_at = utcnow()
    session.flush()

    return {
        "spans_ingested": ingested_spans,
        "traces": [t.id for t in traces_touched.values()],
        "agents_seen": sorted(agents_seen),
        "frameworks": frameworks,
    }
