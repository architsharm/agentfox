"""Scores the real, shipping `analyse_sql()` (`src/agentfox/capabilities/detection/actions.py`)
against `data/action_safety.json`. No mock, no reimplementation — the exact function
`enforcement.py` calls on generated SQL artefacts.

    uv run python -m benchmarks.action_safety.run_action_safety_benchmark

Four categories, each scored against ground truth derived independently of the
detector (see `fetch_gretel_sql.py`'s docstring for how, and its stated limitation):

  - natural_dml / natural_ddl: real generated SQL, unmodified. `expect_blocked` is
    true wherever the statement is genuinely unbounded, stacked, or destructive DDL —
    by `actions.py`'s own stated rules, not an attack label. This measures whether
    the parser's classification is *correct*, and separately, what precision cost a
    zero-false-negative design pays on ordinary requests that happen to have this
    shape (e.g. "clear the whole table" is a real request, not an attack).
  - adversarial_unbounded / adversarial_tautology: WHERE-stripped and
    WHERE-replaced-with-1=1 variants of statements that were originally bounded.
    `expect_blocked` is always true — recall on the constructed attack shape.

`held_out` (the `test` split) is the number to trust, matching this project's
existing convention for the injection benchmarks — `train` case construction and
sampling parameters were tuned by looking at `train`, never `test`.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentfox.capabilities.detection.actions import analyse_sql

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"


def score_category(cases: list[dict]) -> tuple[dict, list[dict]]:
    tp = fp = tn = fn = 0
    parse_failures = 0
    predictions = []
    for case in cases:
        analysis = analyse_sql(case["sql"], dialect="postgres")
        predicted_blocked = analysis.blocked
        expected_blocked = case["expect_blocked"]
        if not analysis.parsed:
            parse_failures += 1
        if predicted_blocked and expected_blocked:
            tp += 1
        elif predicted_blocked and not expected_blocked:
            fp += 1
        elif not predicted_blocked and not expected_blocked:
            tn += 1
        else:
            fn += 1
        predictions.append(
            {
                **case,
                "predicted_blocked": predicted_blocked,
                "risk_codes": [r.code for r in analysis.risks],
                "parsed": analysis.parsed,
                "parse_error": analysis.parse_error,
            }
        )
    n = len(cases)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    summary = {
        "n": n,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "parse_failures": parse_failures,
        "parse_failure_rate": round(parse_failures / n, 4) if n else 0.0,
    }
    return summary, predictions


def main() -> None:
    data = json.loads((DATA_DIR / "action_safety.json").read_text())
    RESULTS_DIR.mkdir(exist_ok=True)

    summary = {"splits": {}}
    for split_name, categories in data.items():
        summary["splits"][split_name] = {}
        for category, cases in categories.items():
            cat_summary, predictions = score_category(cases)
            summary["splits"][split_name][category] = cat_summary
            (RESULTS_DIR / f"{split_name}_{category}_predictions.json").write_text(
                json.dumps(predictions, indent=2)
            )

    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
