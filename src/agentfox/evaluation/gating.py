"""CI regression gating (P4-1, NOM-EVL-01, and SOC 2 CC8.1).

The Phase-0 feature that a platform engineer adopts without asking anyone: a command
that fails the build when the agent got worse. It is also, quietly, a change-management
control — which is how the Tier-A wedge turns into Tier-B compliance evidence.

Two outputs beyond the exit code, because a gate nobody can read gets `|| true`'d:
JUnit XML (every CI system renders it) and SARIF (GitHub code scanning renders it
inline on the PR).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentfox.core.models import Baseline, EvalResult, EvalRun
from agentfox.evaluation.scorers import get_scorer

#: Default tolerance: a scorer mean may drop this much before it is a regression.
#: Non-zero on purpose — a zero-tolerance gate on a non-deterministic system fails
#: constantly and gets disabled, which is worse than a slightly loose gate.
DEFAULT_TOLERANCE = 0.05


@dataclass
class Regression:
    scorer_key: str
    baseline: float
    current: float
    delta: float
    tolerance: float
    kind: str = "mean"  # mean | pass_rate | case
    case_id: str | None = None

    @property
    def message(self) -> str:
        return (
            f"{self.scorer_key} {self.kind} regressed {abs(self.delta):.3f} "
            f"(baseline {self.baseline:.3f} → {self.current:.3f}, "
            f"tolerance {self.tolerance:.3f})"
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "scorer": self.scorer_key,
            "kind": self.kind,
            "case_id": self.case_id,
            "baseline": round(self.baseline, 4),
            "current": round(self.current, 4),
            "delta": round(self.delta, 4),
            "tolerance": self.tolerance,
            "message": self.message,
        }


@dataclass
class GateResult:
    passed: bool = True
    run_id: str = ""
    baseline_run_id: str | None = None
    regressions: list[Regression] = field(default_factory=list)
    absolute_failures: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "run_id": self.run_id,
            "baseline_run_id": self.baseline_run_id,
            "regressions": [r.to_json() for r in self.regressions],
            "absolute_failures": self.absolute_failures,
            "summary": self.summary,
        }

    @property
    def exit_code(self) -> int:
        return 0 if self.passed else 1


def _means(session: Session, run_id: str) -> dict[str, float]:
    results = list(session.scalars(select(EvalResult).where(EvalResult.run_id == run_id)))
    by_scorer: dict[str, list[float]] = {}
    for r in results:
        by_scorer.setdefault(r.scorer_key, []).append(r.score)
    return {k: sum(v) / len(v) for k, v in by_scorer.items() if v}


def _pass_rates(session: Session, run_id: str) -> dict[str, float]:
    results = list(session.scalars(select(EvalResult).where(EvalResult.run_id == run_id)))
    by_scorer: dict[str, list[bool]] = {}
    for r in results:
        by_scorer.setdefault(r.scorer_key, []).append(r.passed)
    return {k: sum(1 for p in v if p) / len(v) for k, v in by_scorer.items() if v}


def gate(
    session: Session,
    run: EvalRun,
    baseline_run_id: str | None = None,
    thresholds: dict[str, float] | None = None,
    min_pass_rate: float | None = None,
) -> GateResult:
    """Compare a run against its baseline and decide whether the build may ship."""
    result = GateResult(run_id=run.id, summary=run.summary_json or {})
    thresholds = thresholds or {}

    baseline_id = baseline_run_id or run.baseline_run_id
    if baseline_id is None:
        record = session.scalars(
            select(Baseline)
            .where(Baseline.suite_id == run.suite_id)
            .order_by(Baseline.created_at.desc())
        ).first()
        if record is not None:
            baseline_id = record.run_id
            thresholds = {**(record.thresholds_json or {}), **thresholds}
    result.baseline_run_id = baseline_id

    current_means = _means(session, run.id)
    current_rates = _pass_rates(session, run.id)

    # Absolute floors apply with or without a baseline — the first run of a new
    # suite should still be able to fail.
    if min_pass_rate is not None:
        for scorer_key, rate in current_rates.items():
            if rate < min_pass_rate:
                result.absolute_failures.append(
                    {
                        "scorer": scorer_key,
                        "pass_rate": round(rate, 4),
                        "min_pass_rate": min_pass_rate,
                        "message": (
                            f"{scorer_key} pass rate {rate:.1%} below floor {min_pass_rate:.1%}"
                        ),
                    }
                )

    if baseline_id:
        baseline_means = _means(session, baseline_id)
        baseline_rates = _pass_rates(session, baseline_id)

        for scorer_key, baseline_value in baseline_means.items():
            if scorer_key not in current_means:
                continue
            current_value = current_means[scorer_key]
            tolerance = thresholds.get(scorer_key, DEFAULT_TOLERANCE)
            scorer = get_scorer(scorer_key)
            higher_is_better = getattr(scorer, "higher_is_better", True)

            # Direction matters: for `silent_failure` and `latency`, a *rise* is the
            # regression. Getting this backwards would gate on the wrong thing.
            delta = (
                (current_value - baseline_value)
                if higher_is_better
                else (baseline_value - current_value)
            )
            if delta < -tolerance:
                result.regressions.append(
                    Regression(
                        scorer_key=scorer_key,
                        baseline=baseline_value,
                        current=current_value,
                        delta=delta,
                        tolerance=tolerance,
                    )
                )

        for scorer_key, baseline_rate in baseline_rates.items():
            if scorer_key not in current_rates:
                continue
            tolerance = thresholds.get(f"{scorer_key}.pass_rate", DEFAULT_TOLERANCE)
            delta = current_rates[scorer_key] - baseline_rate
            if delta < -tolerance:
                result.regressions.append(
                    Regression(
                        scorer_key=scorer_key,
                        baseline=baseline_rate,
                        current=current_rates[scorer_key],
                        delta=delta,
                        tolerance=tolerance,
                        kind="pass_rate",
                    )
                )

    result.passed = not result.regressions and not result.absolute_failures
    return result


def set_baseline(
    session: Session, run: EvalRun, label: str = "main", thresholds: dict[str, float] | None = None
) -> Baseline:
    baseline = Baseline(
        suite_id=run.suite_id,
        run_id=run.id,
        label=label,
        thresholds_json=thresholds or {},
    )
    session.add(baseline)
    session.flush()
    return baseline


# ---------------------------------------------------------------------------
# CI report formats
# ---------------------------------------------------------------------------


def to_junit(result: GateResult, suite_name: str = "agentfox-eval") -> str:
    failures = len(result.regressions) + len(result.absolute_failures)
    scorers = result.summary.get("scorers") or {}
    testsuite = ET.Element(
        "testsuite",
        name=suite_name,
        tests=str(max(len(scorers), 1)),
        failures=str(failures),
        errors="0",
    )
    for scorer_key, stats in scorers.items():
        case = ET.SubElement(testsuite, "testcase", classname=suite_name, name=scorer_key)
        for regression in result.regressions:
            if regression.scorer_key == scorer_key:
                failure = ET.SubElement(
                    case, "failure", type="regression", message=regression.message
                )
                failure.text = json.dumps(regression.to_json(), indent=2)
        for absolute in result.absolute_failures:
            if absolute.get("scorer") == scorer_key:
                failure = ET.SubElement(
                    case, "failure", type="threshold", message=str(absolute.get("message"))
                )
                failure.text = json.dumps(absolute, indent=2)
        ET.SubElement(case, "system-out").text = json.dumps(stats)
    if not scorers:
        case = ET.SubElement(testsuite, "testcase", classname=suite_name, name="no-scorers")
        ET.SubElement(case, "skipped")
    return ET.tostring(testsuite, encoding="unicode")


def to_sarif(result: GateResult, tool_version: str = "0.1.0") -> str:
    """SARIF so GitHub renders regressions on the PR rather than in a log."""
    rules: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(rule_id: str, message: str, level: str, properties: dict[str, Any]) -> None:
        if rule_id not in seen:
            seen.add(rule_id)
            rules.append(
                {
                    "id": rule_id,
                    "name": rule_id,
                    "shortDescription": {"text": f"Evaluation regression: {rule_id}"},
                    "fullDescription": {
                        "text": "An agent change degraded a measured quality signal "
                        "beyond its tolerance (control NOM-EVL-01)."
                    },
                    "defaultConfiguration": {"level": level},
                }
            )
        findings.append(
            {
                "ruleId": rule_id,
                "level": level,
                "message": {"text": message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": "evals/"},
                            "region": {"startLine": 1},
                        }
                    }
                ],
                "properties": properties,
            }
        )

    for regression in result.regressions:
        add(
            f"regression/{regression.scorer_key}", regression.message, "error", regression.to_json()
        )
    for absolute in result.absolute_failures:
        add(f"threshold/{absolute.get('scorer')}", str(absolute.get("message")), "error", absolute)

    return json.dumps(
        {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "AgentFox",
                            "version": tool_version,
                            "informationUri": "https://agentfox.example/docs",
                            "rules": rules,
                        }
                    },
                    "results": findings,
                }
            ],
        },
        indent=2,
    )
