"""I-7 — Prometheus exposition. 4 of 11 already run Prometheus and Grafana.

The argument for this is adoption, not capability. A governance metric that only
exists in our dashboard competes for attention with the dashboard the team already
has open; the same metric on their Grafana board is seen. So this is deliberately a
*thin* export of numbers computed elsewhere, not a second metrics system.

Stdlib-only by design. The exposition format is a documented text protocol, and
taking `prometheus-client` as a dependency to emit forty lines of text would be a
poor trade for a package that promises to install offline. The optional extra exists
only for teams pushing to a gateway.

Metric naming follows Prometheus convention (`nometria_<subsystem>_<unit>`), and
counters carry the `_total` suffix, because a metric that does not follow the
convention does not compose with the alerting rules a team already wrote.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentfox.containment.escalation import escalation_report
from agentfox.core.models import (
    Decision,
    DetectorRun,
    Finding,
    Handoff,
    KnowledgeBoundary,
    Trace,
    utcnow,
)
from agentfox.runtime.reliability import BREAKER


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _line(name: str, labels: dict[str, Any], value: float) -> str:
    if labels:
        rendered = ",".join(f'{k}="{_escape(v)}"' for k, v in sorted(labels.items()) if v)
        return f"{name}{{{rendered}}} {value:g}"
    return f"{name} {value:g}"


class _Registry:
    """Accumulates metric families in exposition order."""

    def __init__(self) -> None:
        self.blocks: list[str] = []

    def add(
        self, name: str, kind: str, help_text: str, samples: list[tuple[dict[str, Any], float]]
    ) -> None:
        body = [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
        body.extend(_line(name, labels, value) for labels, value in samples)
        self.blocks.append("\n".join(body))

    def render(self) -> str:
        return "\n".join(self.blocks) + "\n"


def render_metrics(session: Session, *, window_hours: int = 24) -> str:
    """Everything an operator would alert on, in Prometheus exposition format."""
    since = utcnow() - dt.timedelta(hours=window_hours)
    registry = _Registry()

    # --- Decisions -------------------------------------------------------
    rows = session.execute(
        select(Decision.verdict, Decision.mode, func.count())
        .where(Decision.created_at >= since)
        .group_by(Decision.verdict, Decision.mode)
    ).all()
    registry.add(
        "agentfox_decisions_total",
        "counter",
        "Governance decisions by verdict and policy mode.",
        [({"verdict": v, "mode": m}, float(c)) for v, m, c in rows],
    )

    # Observe mode is reported separately rather than folded in, because a dashboard
    # showing "1,204 blocks" that were all counterfactual is actively misleading.
    observed = sum(c for _v, m, c in rows if m == "observe")
    enforced = sum(c for _v, m, c in rows if m == "enforce")
    registry.add(
        "agentfox_decisions_by_mode_total",
        "counter",
        "Decisions split by whether the policy was enforcing.",
        [({"mode": "observe"}, float(observed)), ({"mode": "enforce"}, float(enforced))],
    )

    # --- Latency (P3-13) -------------------------------------------------
    latency = session.execute(
        select(
            DetectorRun.detector_key,
            func.count(),
            func.avg(DetectorRun.duration_ms),
            func.max(DetectorRun.duration_ms),
        )
        .where(DetectorRun.created_at >= since)
        .group_by(DetectorRun.detector_key)
    ).all()
    registry.add(
        "agentfox_detector_runs_total",
        "counter",
        "Detector executions.",
        [({"detector": k}, float(c)) for k, c, _a, _m in latency],
    )
    registry.add(
        "agentfox_detector_duration_ms_avg",
        "gauge",
        "Mean detector duration. Alert on the max, not this — a mean hides the tail.",
        [({"detector": k}, float(a or 0)) for k, _c, a, _m in latency],
    )
    registry.add(
        "agentfox_detector_duration_ms_max",
        "gauge",
        "Slowest detector run in the window.",
        [({"detector": k}, float(m or 0)) for k, _c, _a, m in latency],
    )
    degraded = session.scalar(
        select(func.count())
        .select_from(DetectorRun)
        .where(
            DetectorRun.created_at >= since,
            DetectorRun.status.in_(("timeout", "error", "skipped_budget")),
        )
    )
    registry.add(
        "agentfox_detector_degraded_total",
        "counter",
        "Detector runs that timed out, errored or were shed for budget. "
        "A control that quietly stops running while reporting effective is the failure "
        "mode that makes compliance products worthless.",
        [({}, float(degraded or 0))],
    )

    # --- Findings --------------------------------------------------------
    findings = session.execute(
        select(Finding.type, Finding.severity, func.count())
        .where(Finding.status == "open")
        .group_by(Finding.type, Finding.severity)
    ).all()
    registry.add(
        "agentfox_open_findings",
        "gauge",
        "Open findings by type and severity.",
        [({"type": t, "severity": s}, float(c)) for t, s, c in findings],
    )

    # --- Escalation (P11) ------------------------------------------------
    report = escalation_report(session, since_hours=window_hours)
    registry.add(
        "agentfox_missed_escalation_rate",
        "gauge",
        "Share of qualifying conversations that never handed off. PRD target < 0.05.",
        [({}, float(report["missed_rate"]))],
    )
    registry.add(
        "agentfox_handoffs",
        "gauge",
        "Hand-offs by status.",
        [
            ({"status": status}, float(count))
            for status, count in session.execute(
                select(Handoff.status, func.count()).group_by(Handoff.status)
            ).all()
        ],
    )

    # --- Reliability (P15) -----------------------------------------------
    breaker_states = {"closed": 0, "open": 1, "half_open": 2}
    registry.add(
        "agentfox_circuit_breaker_state",
        "gauge",
        "Circuit breaker state per provider: 0 closed, 1 open, 2 half-open.",
        [
            ({"provider": key}, float(breaker_states.get(str(snapshot.get("state")), -1)))
            for key, snapshot in BREAKER.snapshot().items()
        ],
    )

    # --- Coverage --------------------------------------------------------
    registry.add(
        "agentfox_traces_total",
        "counter",
        "Governed traces in the window.",
        [
            (
                {},
                float(
                    session.scalar(
                        select(func.count()).select_from(Trace).where(Trace.started_at >= since)
                    )
                    or 0
                ),
            )
        ],
    )
    registry.add(
        "agentfox_knowledge_boundaries",
        "gauge",
        "Declared knowledge boundaries by enforcement mode (P7).",
        [
            ({"mode": mode}, float(count))
            for mode, count in session.execute(
                select(KnowledgeBoundary.mode, func.count()).group_by(KnowledgeBoundary.mode)
            ).all()
        ],
    )
    return registry.render()


def push_to_gateway(
    session: Session, *, url: str, job: str = "agentfox", window_hours: int = 24
) -> dict[str, Any]:  # pragma: no cover - needs a live gateway
    """Push for teams that cannot scrape. Requires the optional extra."""
    import httpx

    body = render_metrics(session, window_hours=window_hours)
    response = httpx.post(f"{url.rstrip('/')}/metrics/job/{job}", content=body, timeout=10.0)
    return {"status_code": response.status_code, "bytes": len(body)}
