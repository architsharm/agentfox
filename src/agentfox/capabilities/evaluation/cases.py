"""Turning a production run into a regression test case.

The shortest path from "this went wrong in production" to "this can never ship
again" is the feature that makes an eval suite grow instead of rot. The eval route
and an issue's "Add to tests" both come here, so a case promoted from either reads
the same.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import EvalCase, EvalSuite, Trace
from agentfox.platform.ledger import chain

#: The suite an issue's "Add to tests" files into when no suite is named.
REGRESSIONS_SUITE = "regressions"


def ensure_suite(session: Session, key: str, *, name: str = "", description: str = "") -> EvalSuite:
    suite = session.scalar(select(EvalSuite).where(EvalSuite.key == key))
    if suite is None:
        suite = EvalSuite(key=key, name=name or key, description=description)
        session.add(suite)
        session.flush()
    return suite


def promote_trace(session: Session, suite: EvalSuite, trace_id: str, *, actor: str) -> EvalCase:
    """A regression case from one recorded run, audited. ``LookupError`` if no such run.

    One case per (suite, run): promoting the same run again returns the case it made.
    """
    from agentfox.capabilities.detection.tuning import explain_recorded
    from agentfox.platform.ledger.trace import full_trace

    trace = session.get(Trace, trace_id)
    if trace is None:
        raise LookupError("unknown trace")
    existing = session.scalar(
        select(EvalCase).where(EvalCase.suite_id == suite.id, EvalCase.source_trace_id == trace_id)
    )
    if existing is not None:
        return existing
    detail = full_trace(session, trace_id, explain=explain_recorded) or {}

    retrieved: list[str] = []
    output = ""
    for span in detail.get("spans", []):
        attrs = span.get("attributes") or {}
        if attrs.get("agentfox.output"):
            output = str(attrs["agentfox.output"])
        if span.get("kind") == "retrieval" and attrs.get("agentfox.content"):
            retrieved.append(str(attrs["agentfox.content"]))

    case = EvalCase(
        suite_id=suite.id,
        input_json={"prompt": trace.intent or ""},
        expected_json={"goal": trace.intent or ""},
        context_json={"retrieved": retrieved, "observed_output": output},
        labels=["from-production", f"verdict:{trace.verdict}"],
        split="regression",
        source_trace_id=trace_id,
    )
    session.add(case)
    session.flush()
    chain.append(
        session,
        "eval.case_promoted",
        actor_type="user",
        actor_id=actor,
        subject_type="eval_case",
        subject_id=case.id,
        payload={"suite": suite.key, "trace_id": trace_id},
    )
    return case


__all__ = ["REGRESSIONS_SUITE", "ensure_suite", "promote_trace"]
