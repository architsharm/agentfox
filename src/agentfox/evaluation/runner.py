"""Evaluation runner (P4-1, P4-2, P4-6, P4-8).

The native runner is the default. promptfoo (MIT, purpose-built for CI gating) is
wrapped as an alternative :class:`EvalRunner` — the catalog's recommendation — but it
is not on the critical path, because the runner has to do three things promptfoo does
not model: score with our silent-failure ensemble, write results into the governance
data model so controls can be computed from them (P6-4), and run the *same* scorers
online against sampled production traffic as offline against a dataset.

That last property is the one worth stating: a team whose offline suite and online
monitoring disagree about what "good" means has two systems, not one.
"""

from __future__ import annotations

import datetime as dt
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox import __version__
from agentfox.core.config import get_settings
from agentfox.core.models import EvalCase, EvalResult, EvalRun, EvalSuite, Trace, utcnow
from agentfox.evaluation.scorers import ScoreContext, get_scorer
from agentfox.evaluation.silent_failure import Envelope
from agentfox.providers import CompletionRequest, get_provider

DEFAULT_SCORERS = ("fuzzy_match", "groundedness", "task_completion", "silent_failure")

#: Scorers that need several generations of the same input.
_NEEDS_SAMPLES = {"self_consistency", "silent_failure"}


class EvalRunner(Protocol):
    name: str

    def run(
        self, session: Session, suite: EvalSuite, target: dict[str, Any], scorers: list[str]
    ) -> EvalRun: ...


@dataclass
class CaseOutcome:
    case_id: str
    output: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    passed: dict[str, bool] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    error: str | None = None


def _messages_for(case: EvalCase) -> list[dict[str, Any]]:
    data = case.input_json or {}
    if "messages" in data:
        return list(data["messages"])
    system = data.get("system")
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    context = (case.context_json or {}).get("retrieved")
    if context:
        text = context if isinstance(context, str) else "\n".join(str(c) for c in context)
        messages.append({"role": "tool", "content": text})
    messages.append({"role": "user", "content": str(data.get("prompt", ""))})
    return messages


class NativeEvalRunner:
    name = "native"

    def run(
        self,
        session: Session,
        suite: EvalSuite,
        target: dict[str, Any],
        scorers: list[str] | None = None,
        mode: str = "offline",
        baseline_run_id: str | None = None,
        envelope: Envelope | None = None,
    ) -> EvalRun:
        scorer_keys = list(scorers or DEFAULT_SCORERS)
        run = EvalRun(
            suite_id=suite.id,
            target_json=target,
            scorer_keys=scorer_keys,
            baseline_run_id=baseline_run_id,
            status="running",
            runner=self.name,
            mode=mode,
            started_at=utcnow(),
            code_version=__version__,
        )
        session.add(run)
        session.flush()

        provider = get_provider(target.get("provider"))
        model = str(target.get("model", "default"))
        sample_count = 3 if set(scorer_keys) & _NEEDS_SAMPLES else 1

        cases = list(session.scalars(select(EvalCase).where(EvalCase.suite_id == suite.id)))
        outcomes: list[CaseOutcome] = []

        for case in cases:
            outcome = CaseOutcome(case_id=case.id)
            messages = _messages_for(case)
            started = time.perf_counter()
            samples: list[str] = []
            try:
                for i in range(sample_count):
                    response = provider.complete(
                        CompletionRequest(
                            messages=messages,
                            model=model,
                            # Vary temperature across samples so self-consistency
                            # measures model stability rather than decoding luck.
                            temperature=0.0 if i == 0 else 0.7,
                        )
                    )
                    samples.append(response.text)
                outcome.output = samples[0]
                outcome.duration_ms = (time.perf_counter() - started) * 1000
            except Exception as exc:
                outcome.error = f"{type(exc).__name__}: {exc}"
                outcome.duration_ms = (time.perf_counter() - started) * 1000
                outcomes.append(outcome)
                continue

            ctx = ScoreContext(
                case_input=case.input_json or {},
                expected=case.expected_json or {},
                context={**(case.context_json or {}), "envelope": envelope},
                samples=samples,
                tool_calls=list((case.input_json or {}).get("tool_calls") or []),
                duration_ms=outcome.duration_ms,
            )

            for key in scorer_keys:
                scorer = get_scorer(key)
                if scorer is None:
                    continue
                result = scorer.score(outcome.output, ctx)
                outcome.scores[key] = result.score
                outcome.passed[key] = result.passed
                outcome.details[key] = result.detail
                session.add(
                    EvalResult(
                        run_id=run.id,
                        case_id=case.id,
                        scorer_key=key,
                        score=result.score,
                        passed=result.passed,
                        output_json={"output": outcome.output[:4000]},
                        detail_json=result.detail,
                        duration_ms=outcome.duration_ms,
                    )
                )
            outcomes.append(outcome)

        run.summary_json = summarise(outcomes, scorer_keys)
        run.status = "completed"
        run.finished_at = utcnow()
        session.flush()
        return run


def summarise(outcomes: list[CaseOutcome], scorer_keys: list[str]) -> dict[str, Any]:
    total = len(outcomes)
    errors = [o for o in outcomes if o.error]
    per_scorer: dict[str, Any] = {}
    for key in scorer_keys:
        values = [o.scores[key] for o in outcomes if key in o.scores]
        passes = [o.passed[key] for o in outcomes if key in o.passed]
        if not values:
            continue
        per_scorer[key] = {
            "mean": round(sum(values) / len(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "pass_rate": round(sum(1 for p in passes if p) / len(passes), 4) if passes else None,
            "n": len(values),
        }
    failing_cases = [
        {
            "case_id": o.case_id,
            "failed": [k for k, p in o.passed.items() if not p],
            "scores": {k: round(v, 3) for k, v in o.scores.items()},
        }
        for o in outcomes
        if any(not p for p in o.passed.values())
    ]
    return {
        "cases": total,
        "errors": len(errors),
        "scorers": per_scorer,
        "failing_cases": failing_cases[:50],
        "failing_count": len(failing_cases),
    }


# ---------------------------------------------------------------------------
# Online evaluation (P4-2)
# ---------------------------------------------------------------------------


def sample_production(
    session: Session,
    agent_slug: str,
    *,
    scorers: list[str] | None = None,
    since: dt.datetime | None = None,
    rate: float | None = None,
    limit: int = 200,
) -> EvalRun | None:
    """Score a sample of live traffic with the same scorers as offline.

    Sampling rather than scoring everything is deliberate: online evaluation that
    doubles the cost of every request gets switched off, and a representative sample
    is what drift detection needs anyway.
    """
    settings = get_settings()
    rate = settings.online_eval_sample_rate if rate is None else rate
    scorer_keys = list(scorers or ("groundedness", "task_completion", "silent_failure"))

    query = select(Trace).where(Trace.agent_slug == agent_slug).order_by(Trace.started_at.desc())
    if since:
        query = query.where(Trace.started_at >= since)
    traces = list(session.scalars(query.limit(limit)))

    rng = random.Random(f"{agent_slug}:{since}")
    sampled = [t for t in traces if rng.random() <= rate]
    if not sampled:
        return None

    suite = session.scalar(select(EvalSuite).where(EvalSuite.key == f"online:{agent_slug}"))
    if suite is None:
        suite = EvalSuite(
            key=f"online:{agent_slug}",
            name=f"Online sample — {agent_slug}",
            description="Production traffic scored with the offline scorer set (P4-2).",
            tags=["online"],
        )
        session.add(suite)
        session.flush()

    run = EvalRun(
        suite_id=suite.id,
        target_json={"agent": agent_slug},
        scorer_keys=scorer_keys,
        status="running",
        runner="native",
        mode="online",
        started_at=utcnow(),
        code_version=__version__,
    )
    session.add(run)
    session.flush()

    from agentfox.prove.audit.trace import full_trace

    envelope = fit_envelope(session, agent_slug)
    outcomes: list[CaseOutcome] = []

    for trace in sampled:
        detail = full_trace(session, trace.id) or {}
        spans = detail.get("spans", [])
        output = ""
        retrieved: list[str] = []
        tool_calls: list[str] = []
        for span in spans:
            attrs = span.get("attributes") or {}
            if span.get("kind") == "llm" and attrs.get("agentfox.output"):
                output = str(attrs["agentfox.output"])
            if span.get("kind") == "retrieval" and attrs.get("agentfox.content"):
                retrieved.append(str(attrs["agentfox.content"]))
            if span.get("kind") == "tool":
                tool_calls.append(str(attrs.get("gen_ai.tool.name") or span.get("name")))
        if not output:
            continue

        case = EvalCase(
            suite_id=suite.id,
            input_json={"prompt": trace.intent or ""},
            context_json={"retrieved": retrieved},
            labels=["online"],
            split="production",
            source_trace_id=trace.id,
        )
        session.add(case)
        session.flush()

        ctx = ScoreContext(
            case_input=case.input_json,
            expected={},
            context={"retrieved": retrieved, "envelope": envelope},
            samples=[output],
            tool_calls=tool_calls,
            duration_ms=_trace_duration_ms(trace),
        )
        outcome = CaseOutcome(case_id=case.id, output=output)
        for key in scorer_keys:
            scorer = get_scorer(key)
            if scorer is None:
                continue
            result = scorer.score(output, ctx)
            outcome.scores[key] = result.score
            outcome.passed[key] = result.passed
            session.add(
                EvalResult(
                    run_id=run.id,
                    case_id=case.id,
                    scorer_key=key,
                    score=result.score,
                    passed=result.passed,
                    output_json={"trace_id": trace.id},
                    detail_json=result.detail,
                )
            )
        outcomes.append(outcome)

    run.summary_json = {
        **summarise(outcomes, scorer_keys),
        "sampled": len(outcomes),
        "sample_rate": rate,
        "population": len(traces),
    }
    run.status = "completed"
    run.finished_at = utcnow()
    session.flush()
    return run


def fit_envelope(session: Session, agent_slug: str, limit: int = 500) -> Envelope:
    """Learn the behavioural envelope from observed traffic (P4-3d)."""
    from agentfox.core.models import Span

    traces = list(
        session.scalars(
            select(Trace)
            .where(Trace.agent_slug == agent_slug)
            .order_by(Trace.started_at.desc())
            .limit(limit)
        )
    )
    lengths: list[int] = []
    latencies: list[float] = []
    tool_counts: list[int] = []
    for trace in traces:
        spans = list(session.scalars(select(Span).where(Span.trace_id == trace.id)))
        tool_counts.append(sum(1 for s in spans if s.kind == "tool"))
        latencies.append(sum(s.duration_ms for s in spans))
        for span in spans:
            output = (span.attributes_json or {}).get("agentfox.output")
            if isinstance(output, str):
                lengths.append(len(output))
    return Envelope.fit(lengths, latencies, tool_counts)


def _trace_duration_ms(trace: Trace) -> float:
    if trace.ended_at and trace.started_at:
        return (trace.ended_at - trace.started_at).total_seconds() * 1000
    return 0.0
