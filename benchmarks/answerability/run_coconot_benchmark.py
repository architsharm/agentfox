"""Scores `src/agentfox/grounding/answerability.py`'s over-refusal rate against CoCoNot's
`contrast` split (`data/coconot_contrast.json`, 379 rows, MIT).

    uv run python benchmarks/answerability/run_coconot_benchmark.py

Same boundary as `run_kuq_benchmark.py` — the system's own out-of-the-box
default (`answerable_types=["fact","aggregate","procedure"]`, no coverage/
topic/entity restriction) — applied to `classify_answerability()`. Every row
in this dataset is, by construction, a prompt a well-behaved assistant should
engage with, not refuse. Ground truth here is unanimous (all "should comply"),
so this is a pure false-positive / over-refusal measurement, not a precision/
recall pair — see the module docstring in `fetch_coconot.py` for why these
specific 379 prompts are a clean negative control for a knowledge-boundary
system even though CoCoNot itself is a safety/completeness benchmark, not an
answerability one.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from agentfox.grounding.answerability import AGGREGATE, FACT, PROCEDURE, classify_answerability, question_type
from agentfox.core.models import KnowledgeBoundary

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"

DEFAULT_ANSWERABLE_TYPES = [FACT, AGGREGATE, PROCEDURE]


def load_dataset() -> list[dict]:
    return json.loads((DATA_DIR / "coconot_contrast.json").read_text())


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_dataset()
    print(f"Loaded {len(rows)} rows")

    boundary = KnowledgeBoundary(answerable_types=list(DEFAULT_ANSWERABLE_TYPES), mode="enforce")

    total_fp = 0
    by_category: dict[str, Counter] = {}
    examples = []

    for row in rows:
        text = row["prompt"]
        verdict = classify_answerability(text, boundary)
        qtype = question_type(text)
        cat = row["category"]
        bucket = by_category.setdefault(cat, Counter())
        bucket["support"] += 1
        if not verdict.answerable:
            total_fp += 1
            bucket["fp"] += 1
            if len(examples) < 20:
                examples.append(
                    {
                        "prompt": text[:200],
                        "category": cat,
                        "subcategory": row["subcategory"],
                        "classified_as": qtype,
                        "abstention_kind": verdict.abstention_kind,
                    }
                )

    over_refusal_rate = total_fp / len(rows) if rows else 0.0

    summary = {
        "dataset": "coconot contrast/test (MIT)",
        "rows": len(rows),
        "boundary_answerable_types": DEFAULT_ANSWERABLE_TYPES,
        "over_refusal_rate": round(over_refusal_rate, 4),
        "false_positives": total_fp,
        "by_category": {
            cat: {"support": c["support"], "fp": c["fp"], "rate": round(c["fp"] / c["support"], 4)}
            for cat, c in by_category.items()
        },
        "examples": examples,
    }

    out_path = RESULTS_DIR / "coconot_summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}\n")
    print(f"Overall over-refusal rate: {over_refusal_rate:.4f} ({total_fp}/{len(rows)})")
    for cat, stats in summary["by_category"].items():
        print(f"  {cat:<35} {stats['fp']}/{stats['support']} = {stats['rate']}")


if __name__ == "__main__":
    main()
