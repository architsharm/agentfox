"""Production drift detection (P4-2, P4-7 / NOM-EVL-02, NOM-EVL-05).

Agents degrade silently after release — the provider swaps a model version, the
retrieval corpus shifts, a prompt is edited upstream. Offline evaluation cannot see
any of that, which is why 37% online-eval adoption is a governance problem and not
just an engineering gap.

Two standard statistics, both interpretable, both explainable to an auditor:

* **PSI** (population stability index) on binned score distributions — the industry
  convention in model risk management, so a bank's model-risk team already knows how
  to read it: <0.1 stable, 0.1–0.25 moderate, >0.25 significant.
* **KS** (two-sample Kolmogorov–Smirnov) as a distribution-shape check that does not
  depend on binning.

Deliberately not an ML anomaly detector: an alert that cannot explain itself is not
evidence, and this pillar's output has to survive an audit (X-4).
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.config import get_settings
from agentfox.core.models import SLO, DriftWindow, EvalResult, EvalRun, utcnow
from agentfox.prove.findings import auto_resolve, raise_finding

PSI_BANDS = ((0.1, "stable"), (0.25, "moderate"), (float("inf"), "significant"))


def psi(baseline: list[float], current: list[float], bins: int = 10) -> float:
    """Population stability index. 0 means identical distributions."""
    if len(baseline) < 2 or len(current) < 2:
        return 0.0
    lo = min(min(baseline), min(current))
    hi = max(max(baseline), max(current))
    if hi <= lo:
        return 0.0

    width = (hi - lo) / bins

    def distribution(values: list[float]) -> list[float]:
        counts = [0] * bins
        for v in values:
            idx = min(bins - 1, int((v - lo) / width)) if width else 0
            counts[idx] += 1
        n = len(values)
        # Floor at a small epsilon so an empty bin does not produce infinity.
        return [max(c / n, 1e-6) for c in counts]

    b, c = distribution(baseline), distribution(current)
    import math

    return sum((c[i] - b[i]) * math.log(c[i] / b[i]) for i in range(bins))


def ks_statistic(baseline: list[float], current: list[float]) -> float:
    """Two-sample KS statistic: the largest gap between the two empirical CDFs."""
    if not baseline or not current:
        return 0.0
    combined = sorted(set(baseline) | set(current))
    nb, nc = len(baseline), len(current)
    sorted_b, sorted_c = sorted(baseline), sorted(current)

    def cdf(values: list[float], n: int, x: float) -> float:
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            if values[mid] <= x:
                lo = mid + 1
            else:
                hi = mid
        return lo / n

    return max(abs(cdf(sorted_b, nb, x) - cdf(sorted_c, nc, x)) for x in combined)


def band(value: float) -> str:
    for limit, label in PSI_BANDS:
        if value < limit:
            return label
    return "significant"


@dataclass
class DriftReport:
    agent_slug: str
    scorer_key: str
    n_current: int
    n_baseline: int
    mean_current: float
    mean_baseline: float
    psi: float
    ks: float
    drifted: bool
    band: str

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": self.agent_slug,
            "scorer": self.scorer_key,
            "n_current": self.n_current,
            "n_baseline": self.n_baseline,
            "mean_current": round(self.mean_current, 4),
            "mean_baseline": round(self.mean_baseline, 4),
            "mean_delta": round(self.mean_current - self.mean_baseline, 4),
            "psi": round(self.psi, 4),
            "ks": round(self.ks, 4),
            "band": self.band,
            "drifted": self.drifted,
        }


def _scores(
    session: Session, agent_slug: str, scorer_key: str, start: dt.datetime, end: dt.datetime
) -> list[float]:
    runs = [
        r.id
        for r in session.scalars(
            select(EvalRun).where(
                EvalRun.mode == "online",
                EvalRun.created_at >= start,
                EvalRun.created_at <= end,
            )
        )
        if (r.target_json or {}).get("agent") == agent_slug
    ]
    if not runs:
        return []
    return [
        r.score
        for r in session.scalars(
            select(EvalResult).where(
                EvalResult.run_id.in_(runs), EvalResult.scorer_key == scorer_key
            )
        )
    ]


def compute(
    session: Session,
    agent_slug: str,
    scorer_key: str,
    *,
    window: dt.timedelta = dt.timedelta(days=1),
    baseline_window: dt.timedelta = dt.timedelta(days=7),
    threshold: float | None = None,
    persist: bool = True,
) -> DriftReport | None:
    """Compare the most recent window against the preceding baseline period."""
    threshold = get_settings().drift_psi_threshold if threshold is None else threshold
    now = utcnow()
    current_start = now - window
    baseline_start = current_start - baseline_window

    current = _scores(session, agent_slug, scorer_key, current_start, now)
    baseline = _scores(session, agent_slug, scorer_key, baseline_start, current_start)
    if len(current) < 2 or len(baseline) < 2:
        return None

    value = psi(baseline, current)
    ks = ks_statistic(baseline, current)
    report = DriftReport(
        agent_slug=agent_slug,
        scorer_key=scorer_key,
        n_current=len(current),
        n_baseline=len(baseline),
        mean_current=statistics.fmean(current),
        mean_baseline=statistics.fmean(baseline),
        psi=value,
        ks=ks,
        drifted=value >= threshold,
        band=band(value),
    )

    if persist:
        record = DriftWindow(
            agent_id=agent_slug,
            scorer_key=scorer_key,
            window_start=current_start,
            window_end=now,
            n=len(current),
            mean=report.mean_current,
            p50=statistics.median(current),
            p95=sorted(current)[max(0, int(len(current) * 0.95) - 1)],
            psi=value,
            ks=ks,
            drifted=report.drifted,
        )
        session.add(record)
        # One finding per (agent, scorer). Computing the view again while it is still
        # drifted counts an occurrence; a window that no longer drifts closes it.
        if report.drifted:
            raise_finding(
                session,
                type="drift",
                severity="high" if report.band == "significant" else "medium",
                title=f"{scorer_key} drifted for {agent_slug} (PSI {value:.3f}, {report.band})",
                subject_type="agent",
                subject_id=agent_slug,
                evidence=report.to_json(),
                control_keys=["NOM-EVL-02"],
                fingerprint_parts=(scorer_key,),
            )
        else:
            auto_resolve(
                session,
                type="drift",
                subject_type="agent",
                subject_id=agent_slug,
                fingerprint_parts=(scorer_key,),
                note=(
                    f"latest {scorer_key} window is within threshold "
                    f"(PSI {value:.3f} < {threshold:.3f})"
                ),
            )
        session.flush()
    return report


def set_slo(
    session: Session,
    *,
    agent_slug: str,
    scorer_key: str,
    objective: str = "",
    window: str = "7d",
    target: float = 0.9,
) -> SLO:
    """Declare (or edit) a reliability target for one agent+scorer pair.

    One row per (agent, scorer) — declaring the same pair again edits it rather
    than piling up duplicates that `evaluate_slos` would then have to reconcile.
    """
    slo = session.scalar(
        select(SLO).where(SLO.agent_id == agent_slug, SLO.scorer_key == scorer_key)
    )
    if slo is None:
        slo = SLO(agent_id=agent_slug, scorer_key=scorer_key)
        session.add(slo)
    slo.objective = objective
    slo.window = window
    slo.target = target
    session.flush()
    return slo


def evaluate_slos(session: Session, agent_slug: str | None = None) -> list[dict[str, Any]]:
    """Measure declared reliability targets and report error-budget burn (P4-7)."""
    query = select(SLO)
    if agent_slug:
        query = query.where(SLO.agent_id == agent_slug)

    out: list[dict[str, Any]] = []
    for slo in session.scalars(query):
        days = int(str(slo.window).rstrip("d") or 7)
        start = utcnow() - dt.timedelta(days=days)
        scores = _scores(session, slo.agent_id, slo.scorer_key, start, utcnow())
        if not scores:
            out.append(
                {
                    "slo_id": slo.id,
                    "agent": slo.agent_id,
                    "scorer": slo.scorer_key,
                    "status": "no_data",
                }
            )
            continue

        from agentfox.evaluation.scorers import get_scorer

        scorer = get_scorer(slo.scorer_key)
        higher_is_better = getattr(scorer, "higher_is_better", True)
        meeting = [s for s in scores if (s >= slo.target if higher_is_better else s <= slo.target)]
        attainment = len(meeting) / len(scores)
        allowed_failure = 1.0 - slo.target if higher_is_better else slo.target
        budget_remaining = (
            1.0 - ((1.0 - attainment) / allowed_failure) if allowed_failure > 0 else 1.0
        )

        slo.current = attainment
        slo.error_budget_remaining = max(-1.0, min(1.0, budget_remaining))
        out.append(
            {
                "slo_id": slo.id,
                "agent": slo.agent_id,
                "scorer": slo.scorer_key,
                "objective": slo.objective,
                "target": slo.target,
                "attainment": round(attainment, 4),
                "error_budget_remaining": round(slo.error_budget_remaining, 4),
                "n": len(scores),
                "status": "healthy" if slo.error_budget_remaining > 0 else "burned",
            }
        )
    session.flush()
    return out
