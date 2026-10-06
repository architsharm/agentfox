"""Scores `src/agentfox/capabilities/grounding/answerability.py` against KUQ (`data/kuq.json`, 4,782
rows, MIT).

    uv run python benchmarks/answerability/run_kuq_benchmark.py

`answerability.py` is a **declared-boundary** system, not a generic unanswerable-
question classifier — `classify_answerability(text, boundary)` only refuses a
question type the operator hasn't declared answerable. This benchmark uses
exactly the boundary `declare_boundary()` itself defaults to when an operator
doesn't specify `answerable_types`: `["fact", "aggregate", "procedure"]` — i.e.
an out-of-the-box agent, not a specially-configured one. Under that boundary,
`coverage_months`/`out_of_scope_topics`/`entity_types` are all left unset, so
the *only* thing this run exercises is the deterministic `question_type()`
classifier (checked directly here, `answerability.py`'s only place price for
predicting recall/precision without a database or a boundary already declared).

Two things are scored:

  - **Recall** on `future_unknown` (does a future-tense question get classified
    `prediction`, which the default boundary never allows — F1.1/F1.4) and on
    `controversial` (does an opinion-soliciting question get classified
    `opinion` — same mechanism, different category).
  - **Over-refusal (false positive) rate** on `known` — ordinary, answerable
    factual questions. `answerability.py`'s own stated design goal is that
    over-refusal, not under-refusal, is the adoption-killing failure (F1.5) —
    so this number is reported with equal weight to recall, not as an
    afterthought.

`classify_answerability()`'s `answerable` boolean and the raw `question_type()`
output are scored together — for this specific boundary (no coverage/topic/
entity restriction, no `known_entities` supplied), they're mathematically the
same decision, so agreement is exact by construction; both are reported so the
per-category qtype breakdown is visible directly, not just pass/fail.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from agentfox.capabilities.grounding.answerability import (
    AGGREGATE,
    FACT,
    PROCEDURE,
    classify_answerability,
    question_type,
)
from agentfox.core.models import KnowledgeBoundary

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"

# The system's own out-of-the-box default (declare_boundary()'s fallback when
# answerable_types isn't specified) — not a boundary tuned for this benchmark.
DEFAULT_ANSWERABLE_TYPES = [FACT, AGGREGATE, PROCEDURE]

EXPECTED_QTYPE = {"future_unknown": "prediction", "controversial": "opinion"}


def load_dataset() -> list[dict]:
    return json.loads((DATA_DIR / "kuq.json").read_text())


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_dataset()
    print(f"Loaded {len(rows)} rows: {Counter(r['label'] for r in rows)}")

    boundary = KnowledgeBoundary(answerable_types=list(DEFAULT_ANSWERABLE_TYPES), mode="enforce")

    per_label = {"future_unknown": Counter(), "controversial": Counter(), "known": Counter()}
    qtype_confusion: dict[str, Counter] = {
        "future_unknown": Counter(),
        "controversial": Counter(),
        "known": Counter(),
    }
    examples: dict[str, list] = {
        "future_unknown_miss": [],
        "controversial_miss": [],
        "known_fp": [],
    }

    for row in rows:
        label = row["label"]
        text = row["question"]
        verdict = classify_answerability(text, boundary)
        qtype = question_type(text)
        qtype_confusion[label][qtype] += 1

        if label == "known":
            if verdict.answerable:
                per_label[label]["tn"] += 1
            else:
                per_label[label]["fp"] += 1
                if len(examples["known_fp"]) < 15:
                    examples["known_fp"].append({"question": text, "classified_as": qtype})
        else:
            expected = EXPECTED_QTYPE[label]
            if not verdict.answerable and qtype == expected:
                per_label[label]["tp"] += 1
            else:
                per_label[label]["fn"] += 1
                if len(examples[f"{label}_miss"]) < 15:
                    examples[f"{label}_miss"].append(
                        {"question": text, "classified_as": qtype, "answerable": verdict.answerable}
                    )

    summary = {
        "dataset": "KUQ knowns_unknowns.jsonl (MIT)",
        "rows": len(rows),
        "boundary_answerable_types": DEFAULT_ANSWERABLE_TYPES,
        "categories": {},
    }

    for label in ("future_unknown", "controversial"):
        c = per_label[label]
        support = c["tp"] + c["fn"]
        recall = c["tp"] / support if support else 0.0
        summary["categories"][label] = {
            "support": support,
            "recall": round(recall, 4),
            "tp": c["tp"],
            "fn": c["fn"],
            "qtype_distribution": dict(qtype_confusion[label]),
        }

    known = per_label["known"]
    known_support = known["tn"] + known["fp"]
    over_refusal_rate = known["fp"] / known_support if known_support else 0.0
    summary["categories"]["known"] = {
        "support": known_support,
        "over_refusal_rate": round(over_refusal_rate, 4),
        "tn": known["tn"],
        "fp": known["fp"],
        "qtype_distribution": dict(qtype_confusion["known"]),
    }

    summary["examples"] = examples

    out_path = RESULTS_DIR / "kuq_summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}\n")

    for label, stats in summary["categories"].items():
        if label == "known":
            print(
                f"known               support={stats['support']:<6} over_refusal_rate={stats['over_refusal_rate']}"
            )
        else:
            print(f"{label:<20}support={stats['support']:<6} recall={stats['recall']}")


if __name__ == "__main__":
    main()
