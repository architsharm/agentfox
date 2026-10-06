"""Out-of-distribution check: does detection generalize past the one dataset it
was tuned against, or does it just know `deepset/prompt-injections` by heart?

    uv run python benchmarks/run_generalization_benchmark.py

Four independent public datasets (`data_generalization/README.md` has sources,
licenses, and why each was picked), none of which `injection.heuristic`'s
patterns or `injection.similarity`'s corpus were ever tuned against:

  - spml         — SPML Chatbot Prompt Injection (500-row stratified sample).
                    Different attack shape than deepset: full alternate persona
                    definitions smuggled into a user turn, not short commands.
                    Has both positive and negative labels — precision AND recall.
  - yanismiraoui — 1,034 known injection phrasings, 7 languages. No negatives,
                    so recall-only — there's no precision claim to make from a
                    file with no benign examples in it.
  - notinject    — 339 entirely benign prompts, purpose-built to trigger
                    keyword-matching guardrails ("Can I *ignore* this warning in
                    my code?"). Every detection here is a false positive by
                    construction — this is the file that tests whether recall
                    gains from earlier rounds came at precision's expense.
  - trustairlab  — 2,810 real, organic prompts scraped from jailbreak-focused
                    Discord/Reddit/etc. communities (1,405 confirmed jailbreaks,
                    1,405 same-community prompts not flagged as one). The
                    hardest negative set of the four: "not flagged as jailbreak
                    by the source community" is not the same claim as "verified
                    benign" (NotInject's) — expect more label noise here than
                    the other three, and read the precision number with that in
                    mind (see `data_generalization/README.md`).

Same three configs as the primary benchmark (heuristic / +classifier /
+classifier+similarity), scored with the exact same shipping code.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from agentfox.capabilities.detection import (
    DetectionContext,
    DetectorPipeline,
    get_detector,
    warm_all,
)

DATA_DIR = Path(__file__).parent / "data_generalization"
RESULTS_DIR = Path(__file__).parent / "results_generalization"


def load(name: str) -> list[dict]:
    return json.loads((DATA_DIR / name).read_text())


def score(rows: list[dict], pipeline: DetectorPipeline) -> tuple[dict, list[dict]]:
    predictions = []
    tp = fp = tn = fn = 0
    degraded_examples = 0
    degraded_by_detector: dict[str, int] = {}
    errored_by_detector: dict[str, int] = {}
    started = time.perf_counter()

    for row in rows:
        text = row["text"]
        label = row["label"]
        result = pipeline.run(text, DetectionContext(surface="input"))
        predicted = int(any(d.entity_type.startswith("INJECTION") for d in result.detections))
        degraded = list(result.degraded)
        errored = list(result.errored)
        if degraded or errored:
            degraded_examples += 1
            for key in degraded:
                degraded_by_detector[key] = degraded_by_detector.get(key, 0) + 1
            for key in errored:
                errored_by_detector[key] = errored_by_detector.get(key, 0) + 1
        predictions.append(
            {
                "text": text,
                "label": label,
                "predicted": predicted,
                "degraded": degraded,
                "errored": errored,
            }
        )
        if predicted == 1 and label == 1:
            tp += 1
        elif predicted == 1 and label == 0:
            fp += 1
        elif predicted == 0 and label == 0:
            tn += 1
        else:
            fn += 1

    duration_ms = (time.perf_counter() - started) * 1000
    precision = tp / (tp + fp) if (tp + fp) else None  # undefined with no positives predicted
    recall = tp / (tp + fn) if (tp + fn) else None  # undefined with no positive examples
    summary = {
        "n": len(rows),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "duration_ms": round(duration_ms, 1),
        "avg_ms_per_example": round(duration_ms / len(rows), 3) if rows else 0.0,
        # See run_prompt_injection_benchmark.py's score() for why this matters —
        # a degraded/errored detector call is scored as "no detection", identical
        # to a genuine clean pass, unless disclosed here.
        "degraded_examples": degraded_examples,
        "degraded_rate": round(degraded_examples / len(rows), 4) if rows else 0.0,
        "degraded_by_detector": degraded_by_detector,
        "errored_by_detector": errored_by_detector,
    }
    return summary, predictions


def main() -> None:
    datasets = {
        "spml": load("spml_sample.json"),
        "yanismiraoui": load("yanismiraoui.json"),
        "notinject": load("notinject.json"),
        "trustairlab": load("trustairlab.json"),
    }

    heuristic = get_detector("injection.heuristic")
    assert heuristic is not None
    # A timed-out detector call's worker thread keeps running to completion —
    # Python cannot pre-empt it (pipeline.py's own docstring) — and every
    # concurrent straggler holds its input tensors and activations in memory
    # until it finishes. `trustairlab`'s longer prompts push far more calls
    # past their per-detector timeout than the other three datasets ever did
    # (see REPORT.md's latency-ceiling section), so a full `max_workers=8`
    # pool lets far more stragglers accumulate concurrently than a shorter
    # dataset ever would — observed directly as swap climbing 0 -> 5GB in
    # under 9 minutes at the default worker count. `max_workers=2` bounds how
    # many stragglers can be in flight at once, at the cost of a slower run,
    # not a smaller one — this is a benchmark-script mitigation, not a fix to
    # the underlying accumulation, which is a real production-pipeline
    # concern under sustained long-input load and is flagged as such rather
    # than silently worked around.
    configs: dict[str, DetectorPipeline] = {
        "heuristic": DetectorPipeline(detectors=[heuristic], max_workers=2)
    }

    classifier = get_detector("injection.classifier")
    similarity = get_detector("injection.similarity")
    if classifier is not None and classifier.available():
        warm_all()
        configs["heuristic_classifier"] = DetectorPipeline(
            detectors=[heuristic, classifier], max_workers=2
        )
        if similarity is not None and similarity.available():
            configs["heuristic_classifier_similarity"] = DetectorPipeline(
                detectors=[heuristic, classifier, similarity], max_workers=2
            )
    else:
        print("injection.classifier unavailable — only scoring the heuristic-only config.\n")

    summary = {
        "datasets": {
            "spml": "reshabhs/SPML_Chatbot_Prompt_Injection (MIT, 500-row stratified sample)",
            "yanismiraoui": "yanismiraoui/prompt_injections (apache-2.0, recall-only, 7 languages)",
            "notinject": "leolee99/NotInject (MIT, all-benign, false-positive stress test)",
        },
        "note": "None of these datasets informed injection.heuristic's patterns or "
        "injection.similarity's corpus — this measures generalization, not fit.",
        "configs": {},
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    for config_name, pipeline in configs.items():
        summary["configs"][config_name] = {}
        for ds_name, rows in datasets.items():
            ds_summary, predictions = score(rows, pipeline)
            summary["configs"][config_name][ds_name] = ds_summary
            (RESULTS_DIR / f"{config_name}_{ds_name}_predictions.json").write_text(
                json.dumps(predictions, indent=2)
            )
        # `ThreadPoolExecutor.shutdown(wait=False)` doesn't kill a straggler
        # already running (Python can't pre-empt it — same reason a single
        # detector call can outlive its own timeout, see pipeline.py) — but it
        # does stop each config's pipeline from leaving its pools around to
        # pile up underneath the *next* config's pools for the rest of this
        # process's life. Skipping this let round 6's addition of a
        # much-longer-average-length dataset (`trustairlab`, mean 2,156 chars
        # vs. the others' short prompts) generate enough concurrent stragglers
        # that CPU contention cascaded into every detector call timing out —
        # for the rest of that dataset, and for every dataset in every config
        # after it, including ones that would otherwise have run cleanly. See
        # REPORT.md's "generalization" section for the full story and how it
        # was caught.
        pipeline.shutdown()

    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
