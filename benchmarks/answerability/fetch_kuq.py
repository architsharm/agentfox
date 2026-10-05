"""Fetches amayuelas/KUQ's `knowns_unknowns.jsonl` (MIT — verified via the HF API's
`cardData.license`) and writes a filtered, flat JSON file to `data/kuq.json`.

    uv run python benchmarks/answerability/fetch_kuq.py

Source: https://huggingface.co/datasets/amayuelas/KUQ
File:   knowns_unknowns.jsonl (6,884 rows) — a Turk-curated set of questions each
        labeled `unknown: bool`, and, when unknown, a `category` (controversial,
        future unknown, ambiguous, counterfactual, false assumption, unsolved
        problem). `unknowns_all.jsonl` (a larger GPT-augmented expansion of the
        same categories) exists in the same repo but isn't fetched here — the
        smaller, originally Turk-curated file is the cleaner primary source; the
        larger file is noted as available for a bigger future run.

Three categories kept, all others dropped — see run_kuq_benchmark.py's docstring
for why only these three are in scope for `src/agentfox/grounding/answerability.py`:

  - `future_unknown` (`category == "future unknown"`, `unknown == True`) — tests
    whether `question_type()` correctly classifies future-tense questions as
    PREDICTION (F1.1/F1.4).
  - `controversial` (`category == "controversial"`, `unknown == True`) — tests
    OPINION classification.
  - `known` (`unknown == False`) — ordinary, answerable factual questions; the
    over-refusal / false-positive control for both of the above.

Dropped as out of scope (no mechanism in `answerability.py` models these):
`ambiguous`, `counterfactual`, `false assumption`, `unsolved problem` — these are
about a question's own epistemic shape (contains a false premise, is impossible
to resolve even in principle), not about whether the *system* holds the answer,
which is the entire and only thing `answerability.py`'s declared-boundary design
claims to check.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
URL = "https://huggingface.co/datasets/amayuelas/KUQ/resolve/main/knowns_unknowns.jsonl"

IN_SCOPE_UNKNOWN_CATEGORIES = {"future unknown": "future_unknown", "controversial": "controversial"}


def _fetch(url: str) -> str:
    result = subprocess.run(
        ["curl", "-sL", "--fail", url], capture_output=True, text=True, check=True
    )
    return result.stdout


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    raw = _fetch(URL)
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    print(f"Fetched {len(rows)} rows from KUQ knowns_unknowns.jsonl")

    out = []
    dropped_categories: dict[str, int] = {}
    for row in rows:
        if row.get("unknown") is False:
            out.append({"question": row["question"], "label": "known"})
            continue
        category = row.get("category")
        label = IN_SCOPE_UNKNOWN_CATEGORIES.get(category)
        if label is None:
            dropped_categories[category] = dropped_categories.get(category, 0) + 1
            continue
        out.append({"question": row["question"], "label": label})

    print(f"Kept {len(out)} in-scope rows")
    print(f"Dropped (out of scope): {dropped_categories}")

    out_path = DATA_DIR / "kuq.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
