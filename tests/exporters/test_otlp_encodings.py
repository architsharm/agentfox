"""OTLP/HTTP ingest accepts what OpenTelemetry exporters actually send (#38).

The SDK's OTLP/HTTP exporter sends binary protobuf by default, often gzip-compressed.
`/v1/traces` only ever called `request.json()`, so every such export was a 500 and
only hand-written JSON worked.
"""

from __future__ import annotations

import gzip
import json

import pytest

pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (  # noqa: E402
    ExportTraceServiceRequest,
)

TRACE_ID = bytes.fromhex("0af7651916cd43dd8448eb211c80319c")
SPAN_ID = bytes.fromhex("b7ad6b7169203331")

JSON_PAYLOAD = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [{"key": "service.name", "value": {"stringValue": "otlp-json-bot"}}]
            },
            "scopeSpans": [
                {
                    "scope": {"name": "manual"},
                    "spans": [
                        {
                            "name": "chat gpt-4o",
                            "traceId": TRACE_ID.hex(),
                            "spanId": SPAN_ID.hex(),
                            "startTimeUnixNano": "1700000000000000000",
                            "endTimeUnixNano": "1700000001000000000",
                            "attributes": [
                                {"key": "gen_ai.system", "value": {"stringValue": "openai"}}
                            ],
                        }
                    ],
                }
            ],
        }
    ]
}


def _protobuf(service: str = "otlp-proto-bot", status_code: int = 0) -> bytes:
    request = ExportTraceServiceRequest()
    resource_span = request.resource_spans.add()
    attr = resource_span.resource.attributes.add()
    attr.key = "service.name"
    attr.value.string_value = service
    scope_span = resource_span.scope_spans.add()
    scope_span.scope.name = "opentelemetry.instrumentation.openai"
    span = scope_span.spans.add()
    span.name = "chat gpt-4o"
    span.trace_id = TRACE_ID
    span.span_id = SPAN_ID
    span.start_time_unix_nano = 1_700_000_000_000_000_000
    span.end_time_unix_nano = 1_700_000_001_500_000_000
    span.status.code = status_code
    model = span.attributes.add()
    model.key = "gen_ai.request.model"
    model.value.string_value = "gpt-4o"
    return request.SerializeToString()


def _spans(service: str):
    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.core.models import Span, Trace

    with session_scope() as s:
        return [
            (span.name, span.status, span.duration_ms, dict(span.attributes_json))
            for span in s.scalars(
                select(Span)
                .join(Trace, Span.trace_id == Trace.id)
                .where(Trace.agent_slug == service)
            )
        ]


def test_protobuf_body_is_ingested(client):
    response = client.post(
        "/v1/traces",
        content=_protobuf(status_code=2),
        headers={"Content-Type": "application/x-protobuf"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-protobuf")
    spans = _spans("otlp-proto-bot")
    assert len(spans) == 1
    name, status, duration, attrs = spans[0]
    assert name == "chat gpt-4o"
    assert status == "error"
    assert duration == pytest.approx(1500.0)
    assert attrs["gen_ai.request.model"] == "gpt-4o"
    # Ids read as hex, the same as an OTLP/JSON export would carry them.
    assert attrs["otel.span_id"] == SPAN_ID.hex()


def test_gzipped_protobuf_body_is_ingested(client):
    response = client.post(
        "/v1/traces",
        content=gzip.compress(_protobuf("otlp-gzip-proto")),
        headers={"Content-Type": "application/x-protobuf", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 200, response.text
    assert len(_spans("otlp-gzip-proto")) == 1


def test_gzipped_json_body_is_ingested(client):
    response = client.post(
        "/v1/traces",
        content=gzip.compress(json.dumps(JSON_PAYLOAD).encode()),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["spans_ingested"] == 1
    assert len(_spans("otlp-json-bot")) == 1


@pytest.mark.parametrize(
    "body,headers,status",
    [
        (b"not gzip", {"Content-Type": "application/json", "Content-Encoding": "gzip"}, 400),
        (b"{}", {"Content-Type": "application/json", "Content-Encoding": "br"}, 415),
        (b"<xml/>", {"Content-Type": "application/xml"}, 415),
        (b"{not json", {"Content-Type": "application/json"}, 400),
        (b"\xff\xff\xff", {"Content-Type": "application/x-protobuf"}, 400),
    ],
)
def test_unreadable_bodies_are_client_errors_not_500(client, body, headers, status):
    response = client.post("/v1/traces", content=body, headers=headers)
    assert response.status_code == status, response.text
    assert response.json()["detail"]


def test_a_gzip_bomb_is_refused():
    from agentfox.exporters.otel import MAX_OTLP_BODY_BYTES, OtlpDecodeError, decode_otlp_body

    bomb = gzip.compress(b"\0" * (MAX_OTLP_BODY_BYTES + 1024))
    with pytest.raises(OtlpDecodeError) as exc:
        decode_otlp_body(bomb, content_type="application/json", content_encoding="gzip")
    assert exc.value.status == 413
