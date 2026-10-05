"""OTLP ingestion (X-1c, P5-1).

The third integration surface, and the one that needs no integration at all: a team
already emitting OpenTelemetry gets Pillar 1 (registry, shadow-agent detection) and
Pillar 5 (traces) by pointing their existing collector at us. No code change, no
proxy, no SDK — which matters for NFR-8's ten-minute time-to-first-value.

Spans following OpenLLMetry / OTel GenAI semantic conventions map onto our
agent-native span model; anything else is retained as context rather than dropped,
because an unrecognised span is still part of the execution path an auditor will
ask about.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from agentfox.core.models import Span, Trace, utcnow
from agentfox.prove.audit.trace import ATTR_AGENT, start_trace

# Framework fingerprints for P1-6 auto-discovery. Order matters: more specific first.
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
    """P1-6 — record what the agent is built on, for neutrality reporting."""
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


def ingest_otlp(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Ingest an OTLP/JSON trace export.

    Returns a summary including any agent slugs observed, so the caller can run
    shadow-agent detection over them (P1-2).
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
