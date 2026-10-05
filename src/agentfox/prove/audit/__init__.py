"""Pillar 5 — Audit, Observability & Traceability.

OpenTelemetry gives us spans. The evidentiary layer — the hash chain, the signed
checkpoints, the independently verifiable evidence package — is ours, because no
OSS project provides it (Appendix A.5) and because it cannot be retrofitted: the
entries you already wrote were never chained.
"""

from agentfox.prove.audit import chain, evidence, otel, siem, trace
from agentfox.prove.audit.chain import (
    GENESIS,
    ChainBreak,
    VerificationResult,
    append,
    chain_stats,
    checkpoint_now,
    redact_payload,
    verify,
    verify_range,
)
from agentfox.prove.audit.otel import detect_framework, ingest_otlp
from agentfox.prove.audit.trace import add_span, end_trace, full_trace, search_traces, span, start_trace

__all__ = [
    "GENESIS",
    "ChainBreak",
    "VerificationResult",
    "add_span",
    "append",
    "chain",
    "chain_stats",
    "checkpoint_now",
    "detect_framework",
    "end_trace",
    "evidence",
    "full_trace",
    "ingest_otlp",
    "otel",
    "redact_payload",
    "search_traces",
    "siem",
    "span",
    "start_trace",
    "trace",
    "verify",
    "verify_range",
]
