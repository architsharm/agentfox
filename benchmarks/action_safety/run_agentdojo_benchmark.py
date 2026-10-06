"""Scores the real, shipping `analyse_arguments()` (`src/agentfox/capabilities/detection/actions.py`
— the actual public dispatcher: SQL/shell/URL fields by declared key name, plus the
generic wildcard/SQLi-fragment/path-traversal scope backstop on every other string
argument) against `data/agentdojo_calls.json`.

    uv run python -m benchmarks.action_safety.run_agentdojo_benchmark

Not a precision/recall benchmark against a binary label — see README.md for why.
AgentDojo's injection tasks are an *entitlement/taint* attack (a legitimate-shaped
`send_money` call whose argument values happen to route funds to an attacker), not a
*syntax* attack (an unbounded DELETE, a wildcard scope value) — the two are different
failure classes by design, and `analyse_arguments` has no reason to catch the former.
What this measures instead: the flag rate on each category, at real scale, and
whether anything in either category happens to *also* contain a syntax-level anomaly
`analyse_arguments` should catch regardless of the broader attack's shape.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from agentfox.capabilities.detection.actions import analyse_arguments

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"


def score(calls: list[dict]) -> tuple[dict, list[dict]]:
    flagged = 0
    risk_counts: Counter[str] = Counter()
    predictions = []
    for call in calls:
        analyses = analyse_arguments(call["args"])
        risks = [r.code for a in analyses for r in a.risks]
        if risks:
            flagged += 1
            risk_counts.update(risks)
        predictions.append({**call, "flagged": bool(risks), "risk_codes": risks})
    n = len(calls)
    summary = {
        "n": n,
        "flagged": flagged,
        "flag_rate": round(flagged / n, 4) if n else 0.0,
        "risk_codes": dict(risk_counts),
    }
    return summary, predictions


def main() -> None:
    data = json.loads((DATA_DIR / "agentdojo_calls.json").read_text())
    RESULTS_DIR.mkdir(exist_ok=True)

    summary = {}
    for kind in ("injection", "user"):
        cat_summary, predictions = score(data[kind])
        summary[kind] = cat_summary
        (RESULTS_DIR / f"agentdojo_{kind}_predictions.json").write_text(
            json.dumps(predictions, indent=2)
        )

    # Per-suite breakdown, since the four suites are unrelated tool domains and an
    # average across them could hide a suite-specific gap or false-positive cluster.
    by_suite: dict[str, dict[str, dict]] = {}
    for kind in ("injection", "user"):
        for row in data[kind]:
            suite = row["suite"]
            by_suite.setdefault(suite, {"injection": [], "user": []})
            by_suite[suite][kind].append(row)
    summary["by_suite"] = {}
    for suite, kinds in by_suite.items():
        summary["by_suite"][suite] = {}
        for kind, calls in kinds.items():
            cat_summary, _ = score(calls)
            summary["by_suite"][suite][kind] = cat_summary

    (RESULTS_DIR / "agentdojo_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
