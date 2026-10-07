"""Reproducible prompt-injection detection benchmark.

    uv run python -m benchmarks.injection.run_prompt_injection_benchmark

Scores AgentFox's real, shipping detectors against `deepset/prompt-injections`
(Hugging Face, apache-2.0, 662 labeled examples, license/source in
`data/README.md`). The dataset was fetched once (see `fetch_dataset.py`) and is
committed under `data/`, so anyone can re-run this file and get the same numbers —
the classifier/similarity configs need `pip install agentfox[classifiers]` and
one-time model downloads (~350MB deberta, ~90MB MiniLM, both apache-2.0);
everything else is fully offline.

Configurations, because the honest answer to "how good is detection" depends which
one a deployment actually runs — each is opt-in on top of the default:

  - heuristic                        — `injection.heuristic` alone. Regex and
                                        structural signals. What ships enabled by
                                        default, zero extra dependencies,
                                        sub-millisecond.
  - heuristic_classifier             — adds `injection.classifier`
                                        (protectai/deberta-v3-base-prompt-injection-v2),
                                        a model trained specifically for this task.
  - heuristic_similarity             — adds `injection.similarity`, local
                                        cosine-similarity matching against a
                                        synthetic corpus of known attack/benign
                                        examples (sentence-transformers/all-MiniLM-L6-v2).
  - heuristic_classifier_similarity  — all three together.

Each of the classifier/similarity configs costs real per-call latency (tens of ms
on CPU) and a one-time download, which is why neither is the default — see
config.py's `prompt_injection_classifier_model` / `embedding_similarity_model`
docstrings for the trade-off.

Each configuration is scored on all three splits (held_out/train/combined), same
train/test discipline as before: `injection.heuristic`'s patterns were tuned by
reading train.json's false negatives only; the classifier is a pretrained model,
never fit to this dataset at all, so there's no tuning-leakage question for it —
but it's scored the same way for a clean comparison.
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

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"


def load_split(name: str) -> list[dict]:
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
        label = row["label"]  # dataset convention: 1 = injection, 0 = benign
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
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(rows) if rows else 0.0

    summary = {
        "n": len(rows),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "duration_ms": round(duration_ms, 1),
        "avg_ms_per_example": round(duration_ms / len(rows), 3) if rows else 0.0,
        # A detector that times out or errors mid-run is scored as "no detection" —
        # same as a genuine clean pass — unless this is disclosed. Non-zero here
        # means some fraction of tp/fp/tn/fn above was contention-masked, not a
        # true model judgment; see the thread-pool-exhaustion finding in REPORT.md.
        "degraded_examples": degraded_examples,
        "degraded_rate": round(degraded_examples / len(rows), 4) if rows else 0.0,
        "degraded_by_detector": degraded_by_detector,
        "errored_by_detector": errored_by_detector,
    }
    return summary, predictions


def score_all_splits(pipeline: DetectorPipeline, train_rows, test_rows) -> dict:
    held_out, held_out_predictions = score(test_rows, pipeline)
    train, train_predictions = score(train_rows, pipeline)
    combined, combined_predictions = score(train_rows + test_rows, pipeline)
    return {
        "held_out": held_out,
        "train": train,
        "combined": combined,
        "_predictions": {
            "held_out": held_out_predictions,
            "train": train_predictions,
            "combined": combined_predictions,
        },
    }


def main() -> None:
    train_rows = load_split("train.json")
    test_rows = load_split("test.json")

    heuristic = get_detector("injection.heuristic")
    assert heuristic is not None

    configs: dict[str, DetectorPipeline] = {
        "heuristic": DetectorPipeline(detectors=[heuristic]),
    }

    classifier = get_detector("injection.classifier")
    similarity = get_detector("injection.similarity")
    if (classifier is not None and classifier.available()) or (
        similarity is not None and similarity.available()
    ):
        warm_all()
        if classifier is not None and classifier.available():
            configs["heuristic_classifier"] = DetectorPipeline(detectors=[heuristic, classifier])
        if similarity is not None and similarity.available():
            configs["heuristic_similarity"] = DetectorPipeline(detectors=[heuristic, similarity])
        if (
            classifier is not None
            and classifier.available()
            and similarity is not None
            and similarity.available()
        ):
            configs["heuristic_classifier_similarity"] = DetectorPipeline(
                detectors=[heuristic, classifier, similarity]
            )
    else:
        print(
            "injection.classifier / injection.similarity unavailable (pip install "
            "agentfox[classifiers] and download the models) — only scoring the "
            "heuristic-only config.\n"
        )

    summary = {
        "dataset": "deepset/prompt-injections",
        "dataset_url": "https://huggingface.co/datasets/deepset/prompt-injections",
        "dataset_license": "apache-2.0",
        "methodology": "injection.heuristic's patterns were manually extended using "
        "train.json false negatives only; test.json held out and never inspected — "
        "'held_out' is the number to trust. injection.classifier is a pretrained "
        "model, never fit to this dataset. injection.similarity matches against a "
        "synthetic corpus (capabilities/detection/data/injection_corpus.json) authored "
        "independently of this benchmark's dataset.",
        "configs": {},
    }

    RESULTS_DIR.mkdir(exist_ok=True)
    for config_name, pipeline in configs.items():
        result = score_all_splits(pipeline, train_rows, test_rows)
        predictions = result.pop("_predictions")
        summary["configs"][config_name] = result
        for split_name, preds in predictions.items():
            (
                RESULTS_DIR / f"prompt_injection_{config_name}_{split_name}_predictions.json"
            ).write_text(json.dumps(preds, indent=2))

    (RESULTS_DIR / "prompt_injection_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
