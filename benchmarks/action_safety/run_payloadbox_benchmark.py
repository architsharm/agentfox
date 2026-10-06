"""Scores the real, shipping `analyse_arguments()` (`src/agentfox/capabilities/detection/actions.py`
— the public dispatcher `enforcement.py` actually calls, which routes SQL/shell/URL
-declared fields by key name and everything else through the generic
wildcard/SQLi-fragment/path-traversal `analyse_scope` backstop) against
`data/payloadbox_cases.json`.

    uv run python benchmarks/action_safety/run_payloadbox_benchmark.py

Every case places one raw payload-box fragment (or one hand-authored benign value)
as the value of an ordinary, non-SQL-declared argument — e.g. `{"order_id": "1 OR
1=1"}` — which is the scenario `analyse_scope`'s `_SQLI_FRAGMENT_RE` backstop exists
for, not `analyse_sql`'s AST parser (these are fragments, not full statements, and
mostly won't parse as SQL on their own).

Two numbers, mirroring the recall/false-positive-rate split of the injection
benchmarks (NotInject's role there is played here by the hand-authored `benign`
set):

  - recall on `malicious`: of the known SQL-injection-payload fragments, how many
    does analyse_arguments flag. Reported overall (globally deduped) and per
    source dialect file (a fragment counts toward every dialect file it actually
    appeared in, so dialect totals overlap where fragments are shared).
  - false-positive rate on `benign`: of the hand-authored ordinary values that
    superficially resemble a trigger shape, how many get flagged when they
    shouldn't.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from agentfox.capabilities.detection.actions import analyse_arguments

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"

SOURCE_FILES = [
    "mysql-payloads.txt",
    "postgresql-payloads.txt",
    "mssql-payloads.txt",
    "sqlite-payloads.txt",
    "oracle-payloads.txt",
    "burp-intruder-payloads.txt",
]


def score(cases: list[dict]) -> tuple[dict, list[dict]]:
    tp = fp = tn = fn = 0
    risk_counts: Counter[str] = Counter()
    predictions = []
    for case in cases:
        analyses = analyse_arguments({case["key"]: case["value"]})
        blocked = any(a.blocked for a in analyses)
        risks = [r.code for a in analyses for r in a.risks]
        risk_counts.update(risks)
        expected = case["expect_blocked"]
        if blocked and expected:
            tp += 1
        elif blocked and not expected:
            fp += 1
        elif not blocked and not expected:
            tn += 1
        else:
            fn += 1
        predictions.append({**case, "predicted_blocked": blocked, "risk_codes": risks})
    n = len(cases)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    fpr = fp / (fp + tn) if (fp + tn) else None
    summary = {
        "n": n,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "false_positive_rate": round(fpr, 4) if fpr is not None else None,
        "risk_codes": dict(risk_counts),
    }
    return summary, predictions


def main() -> None:
    data = json.loads((DATA_DIR / "payloadbox_cases.json").read_text())
    RESULTS_DIR.mkdir(exist_ok=True)

    summary: dict = {}
    for kind in ("malicious", "benign"):
        cat_summary, predictions = score(data[kind])
        summary[kind] = cat_summary
        (RESULTS_DIR / f"payloadbox_{kind}_predictions.json").write_text(
            json.dumps(predictions, indent=2)
        )

    # Per-dialect breakdown of the malicious set. A fragment counts toward every
    # dialect file it actually appeared in (globally-deduped cases can list more
    # than one source), so per-dialect n's overlap by design — this measures "how
    # many of THIS file's fragments get caught," not a disjoint partition.
    summary["by_source"] = {}
    for source in SOURCE_FILES:
        subset = [c for c in data["malicious"] if source in c["sources"]]
        if not subset:
            continue
        cat_summary, _ = score(subset)
        summary["by_source"][source] = cat_summary

    # Benign set broken down by the trigger-shape category it's probing.
    summary["benign_by_category"] = {}
    categories = sorted({c["category"] for c in data["benign"]})
    for category in categories:
        subset = [c for c in data["benign"] if c["category"] == category]
        cat_summary, _ = score(subset)
        summary["benign_by_category"][category] = cat_summary

    (RESULTS_DIR / "payloadbox_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
