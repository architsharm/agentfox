"""Score each supported prompt-injection model on the injection and generalization sets.

Each model runs as `injection.classifier` beside `injection.heuristic`, alone (the
secondary backstop off), at its own published default threshold (see
`INJECTION_MODELS` in detection/adapters/classifiers.py). Results go to a work
directory; `summarize` writes `results/summary.json` from it.

    AGENTFOX_ACCEPT_RESTRICTED_MODEL_LICENSES=1 AGENTFOX_MODEL_DEVICE=cpu \\
        python -m benchmarks.injection.model_choice.compare_models run var/model_choice
    python -m benchmarks.injection.model_choice.compare_models summarize var/model_choice

Prompt Guard 2 is gated: accept Meta's licence on Hugging Face and pull the weights
first (`agentfox admin detectors pull injection.classifier` with the model selected).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MODELS = {
    "piguard": "leolee99/PIGuard",
    "prompt_guard_2_22m": "meta-llama/Llama-Prompt-Guard-2-22M",
    "prompt_guard_2_86m": "meta-llama/Llama-Prompt-Guard-2-86M",
}
RESULTS = Path(__file__).resolve().parent / "results"


def _one(work: Path, which: str) -> None:
    """Run one benchmark in this process, writing to ``work``."""
    if which == "injection":
        import benchmarks.injection.run_prompt_injection_benchmark as bench

        sys.argv = [sys.argv[0]]
    else:
        import benchmarks.generalization.run_generalization_benchmark as bench

        sys.argv = [sys.argv[0], "--configs", "heuristic,heuristic_classifier"]
    bench.RESULTS_DIR = work
    work.mkdir(parents=True, exist_ok=True)
    bench.main()


def run(work: Path) -> None:
    for key, model in MODELS.items():
        env = {
            **os.environ,
            "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_MODEL": model,
            "AGENTFOX_PROMPT_INJECTION_CLASSIFIER_SECONDARY_MODEL": "",
        }
        for which in ("injection", "generalization"):
            target = work / key / which
            subprocess.run(
                [sys.executable, "-m", __spec__.name, "_one", str(target), which],
                env=env,
                check=True,
            )
        print(f"{key} done", flush=True)


def _pct(x: float | None) -> float | None:
    return None if x is None else round(100 * x, 1)


def summarize(work: Path) -> None:
    summary: dict = {
        "setup": "injection.heuristic + injection.classifier, secondary backstop off, each "
        "model at its published default threshold (PIGuard 0.5, Prompt Guard 2 0.9)",
        "models": {},
    }
    for key, model in MODELS.items():
        inj = json.loads((work / key / "injection" / "prompt_injection_summary.json").read_text())
        gen = json.loads((work / key / "generalization" / "summary.json").read_text())
        held = inj["configs"]["heuristic_classifier"]["held_out"]
        g = gen["configs"]["heuristic_classifier"]
        summary["models"][key] = {
            "model": model,
            "held_out_recall_pct": _pct(held["recall"]),
            "held_out_precision_pct": _pct(held["precision"]),
            "held_out_tp": held["tp"],
            "held_out_n_positive": held["tp"] + held["fn"],
            "spml_recall_pct": _pct(g["spml"]["recall"]),
            "yanismiraoui_recall_pct": _pct(g["yanismiraoui"]["recall"]),
            "notinject_fp": g["notinject"]["fp"],
            "notinject_n": g["notinject"]["n"],
            "notinject_fp_pct": round(100 * g["notinject"]["fp"] / g["notinject"]["n"], 1),
            "trustairlab_recall_pct": _pct(g["trustairlab"]["recall"]),
            "trustairlab_precision_pct": _pct(g["trustairlab"]["precision"]),
            "trustairlab_degraded_pct": round(100 * g["trustairlab"].get("degraded_rate", 0), 1),
        }
        for which, data in (("injection", inj), ("generalization", gen)):
            (RESULTS / f"{key}_{which}_summary.json").write_text(
                json.dumps({"model": model, "configs": data["configs"]}, indent=1)
            )
    base_inj = json.loads(
        (work / "piguard" / "injection" / "prompt_injection_summary.json").read_text()
    )["configs"]["heuristic"]["held_out"]
    base_gen = json.loads((work / "piguard" / "generalization" / "summary.json").read_text())[
        "configs"
    ]["heuristic"]
    summary["heuristic_only"] = {
        "held_out_recall_pct": _pct(base_inj["recall"]),
        "spml_recall_pct": _pct(base_gen["spml"]["recall"]),
        "yanismiraoui_recall_pct": _pct(base_gen["yanismiraoui"]["recall"]),
        "notinject_fp": base_gen["notinject"]["fp"],
        "trustairlab_recall_pct": _pct(base_gen["trustairlab"]["recall"]),
        "trustairlab_precision_pct": _pct(base_gen["trustairlab"]["precision"]),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    command, target = sys.argv[1], Path(sys.argv[2])
    if command == "_one":
        _one(target, sys.argv[3])
    elif command == "run":
        run(target)
    else:
        summarize(target)
