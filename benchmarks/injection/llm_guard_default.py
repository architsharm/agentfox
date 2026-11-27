"""LLM Guard's prompt-injection scanner, as shipped, on the two sets the site quotes.

Runs llm-guard's own `PromptInjection()` with every default (protectai/deberta-v3-base-
prompt-injection-v2, threshold 0.92, one pass truncated at 512 tokens) through
`benchmarks/head_to_head/scan_bridge.py`, in the scratch venv that holds llm-guard (it pins a
transformers version this project can't share). Scores:

  * NotInject (benchmarks/generalization/data/notinject.json): 339 harmless messages written to
    sound like attacks. Every flag is a false block.
  * deepset held-out (benchmarks/injection/data/test.json): recall on its 60 injections, and
    false blocks on its 56 benign rows.

    bash benchmarks/head_to_head/setup_venvs.sh                # once; prints H2H_SCANNER_PYTHON
    H2H_SCANNER_PYTHON=… python -m benchmarks.injection.llm_guard_default

Writes results/llm_guard_default_summary.json (bound in benchmarks/claims.yaml) and
results/llm_guard_default_predictions.json (sha256 of each text with its score and verdict).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
BRIDGE = BENCH / "head_to_head" / "scan_bridge.py"
RESULTS = HERE / "results"


def _rate(n: int, d: int) -> dict:
    return {"n": n, "d": d, "fraction": f"{n}/{d}", "pct": round(100 * n / d, 1)}


def main() -> None:
    python = os.environ.get("H2H_SCANNER_PYTHON")
    if not python:
        raise SystemExit("set H2H_SCANNER_PYTHON (bash benchmarks/head_to_head/setup_venvs.sh)")
    notinject = json.loads((BENCH / "generalization/data/notinject.json").read_text())
    deepset = json.loads((HERE / "data/test.json").read_text())
    rows = [("notinject", r) for r in notinject] + [("deepset_held_out", r) for r in deepset]
    run = subprocess.run(
        [python, str(BRIDGE), "llm_guard"],
        input=json.dumps([r["text"] for _, r in rows]),
        capture_output=True,
        text=True,
        check=True,
    )
    out = json.loads(run.stdout)
    preds = []
    for (dataset, row), rec in zip(rows, out["records"], strict=True):
        assert rec["sha256"] == hashlib.sha256(row["text"].encode()).hexdigest()
        preds.append(
            {
                "dataset": dataset,
                "label": row["label"],
                "sha256": rec["sha256"],
                "score": rec["score"],
                "flagged": rec["flagged_default"],
            }
        )

    def count(dataset: str, label: int) -> tuple[int, int]:
        sel = [p for p in preds if p["dataset"] == dataset and p["label"] == label]
        return sum(p["flagged"] for p in sel), len(sel)

    summary = {
        "scanner": "llm-guard PromptInjection() with every default",
        "meta": out["meta"],
        "notinject_false_blocks": _rate(*count("notinject", 0)),
        "deepset_held_out_recall": _rate(*count("deepset_held_out", 1)),
        "deepset_held_out_false_blocks": _rate(*count("deepset_held_out", 0)),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "llm_guard_default_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (RESULTS / "llm_guard_default_predictions.json").write_text(json.dumps(preds, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "meta"}, indent=2))


if __name__ == "__main__":
    main()
