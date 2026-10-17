"""The ledger: the append-only audit chain, traces and spans, operator and system logs,
and findings.

Everything that records what happened lives here, below every capability, so any
capability can append to the chain or raise a finding. Building evidence packages
from it is an app (`agentfox.apps.report`); shipping spans elsewhere is an exporter.
"""

from agentfox.platform.ledger import chain, trace
from agentfox.platform.ledger.chain import (
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
from agentfox.platform.ledger.trace import (
    add_span,
    end_trace,
    full_trace,
    search_traces,
    span,
    start_trace,
)

__all__ = [
    "GENESIS",
    "ChainBreak",
    "VerificationResult",
    "add_span",
    "append",
    "chain",
    "chain_stats",
    "checkpoint_now",
    "end_trace",
    "full_trace",
    "redact_payload",
    "search_traces",
    "span",
    "start_trace",
    "trace",
    "verify",
    "verify_range",
]
