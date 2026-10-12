"""Ours, theirs, or both: our detectors against the ported Guardrails AI validators.

For each task the same texts go through every component once: one of our detectors,
or a ported validator. Unions are computed from those predictions, so "ours + theirs"
costs no extra run and is exactly what enabling both would flag. Precision, recall,
F1 and false-positive rate are reported with Wilson 95% intervals, plus median
latency per component.

Every dataset here is one nothing in the product was written against (see each
source's README). Results decide which checks a workspace is offered by default;
they are never used to edit a pattern.

    uv run python -m benchmarks.validators.fetch_toxicchat      # once; CC-BY-NC, not committed
    PYTHONPATH=src python -m benchmarks.validators.run_comparison --task injection
    PYTHONPATH=src python -m benchmarks.validators.run_comparison --task toxicity --limit 1500
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import statistics
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESULTS = HERE / "results"
SEED = 20261012


@dataclass(frozen=True)
class Row:
    text: str
    label: int  # 1 = should be flagged
    dataset: str


# --------------------------------------------------------------------------- data


def _json_rows(path: Path, name: str) -> list[Row]:
    return [Row(r["text"], int(r["label"]), name) for r in json.loads(path.read_text())]


def injection_rows() -> list[Row]:
    gen = ROOT / "benchmarks" / "generalization" / "data"
    return [
        *_json_rows(ROOT / "benchmarks" / "injection" / "data" / "test.json", "deepset_test"),
        *_json_rows(gen / "spml_sample.json", "spml"),
        *_json_rows(gen / "notinject.json", "notinject"),
        *_json_rows(gen / "trustairlab.json", "trustairlab"),
        *_json_rows(gen / "yanismiraoui.json", "yanismiraoui"),
    ]


def toxicity_rows() -> list[Row]:
    path = ROOT / "var" / "benchmarks" / "toxicchat_test.csv"
    if not path.exists():
        raise SystemExit("run `python -m benchmarks.validators.fetch_toxicchat` first")
    with path.open(newline="", encoding="utf-8") as fh:
        return [Row(r["user_input"], int(r["toxicity"]), "toxicchat") for r in csv.DictReader(fh)]


# --------------------------------------------------------------------------- components


def _detector(key: str) -> Callable[[str, str], float] | None:
    """A detector by key, as text -> max detection score (0 when nothing found)."""
    from agentfox.capabilities.detection import get_detector
    from agentfox.capabilities.detection.base import DetectionContext

    detector = get_detector(key)
    if detector is None:
        from agentfox.capabilities.detection.validators import get_validator
        from agentfox.capabilities.detection.validators.detector import ValidatorDetector

        name = key.removeprefix("validator.")
        validator = get_validator(name)
        if validator is None or not validator.standalone():
            return None
        detector = ValidatorDetector(validator)
    if not detector.available():
        return None
    detector.warm()

    def run(text: str, surface: str) -> float:
        result = detector.detect(text, DetectionContext(surface=surface))
        return max((d.score for d in result.detections), default=0.0)

    return run


TASKS: dict[str, dict] = {
    "injection": {
        "rows": injection_rows,
        "surface": "input",
        "ours": ["injection.heuristic", "injection.classifier"],
        "theirs": [
            "validator.detect_jailbreak",
            "validator.detect_prompt_injection",
            "validator.jailbreak",
        ],
    },
    "toxicity": {
        "rows": toxicity_rows,
        "surface": "input",
        "ours": ["safety.lexicon", "safety.granite"],
        "theirs": [
            "validator.toxic_language",
            "validator.bert_toxic",
            "validator.nsfw_text",
            "validator.profanity_free",
        ],
    },
}


# --------------------------------------------------------------------------- scoring


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def metrics(preds: list[bool], rows: list[Row]) -> dict:
    tp = sum(p and r.label for p, r in zip(preds, rows, strict=True))
    fp = sum(p and not r.label for p, r in zip(preds, rows, strict=True))
    fn = sum((not p) and r.label for p, r in zip(preds, rows, strict=True))
    tn = sum((not p) and not r.label for p, r in zip(preds, rows, strict=True))
    pos, neg = tp + fn, fp + tn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / pos if pos else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    pct = lambda x: None if x is None else round(100 * x, 1)  # noqa: E731
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": pct(precision),
        "recall": pct(recall),
        "recall_ci": wilson(tp, pos),
        "f1": pct(f1),
        "fpr": pct(fp / neg) if neg else None,
        "fpr_ci": wilson(fp, neg),
    }


def evaluate(
    task: str, rows: list[Row], components: dict[str, Callable[[str, str], float]], threshold: float
) -> dict:
    surface = TASKS[task]["surface"]
    scores: dict[str, list[float]] = {}
    latency: dict[str, float] = {}
    for name, fn in components.items():
        out, times = [], []
        for i, row in enumerate(rows, 1):
            t0 = time.perf_counter()
            try:
                out.append(fn(row.text, surface))
            except Exception:
                out.append(0.0)  # a component that cannot score a text misses it
            times.append((time.perf_counter() - t0) * 1000)
            if i % 500 == 0:
                print(f"  {name}: {i}/{len(rows)}", flush=True)
        scores[name] = out
        latency[name] = round(statistics.median(times), 2)
        print(f"  {name}: done, median {latency[name]} ms", flush=True)

    flagged = {n: [s >= threshold for s in v] for n, v in scores.items()}
    ours = [n for n in components if n in TASKS[task]["ours"]]
    theirs = [n for n in components if n in TASKS[task]["theirs"]]
    arms: dict[str, list[str]] = {n: [n] for n in components}
    for o, t in itertools.product(ours, theirs):
        arms[f"{o} + {t}"] = [o, t]
    if len(ours) > 1:
        arms[" + ".join(ours)] = ours
    if ours and theirs and len(ours) + len(theirs) > 2:
        arms["all ours + all theirs"] = ours + theirs

    datasets = sorted({r.dataset for r in rows})
    report: dict = {"task": task, "threshold": threshold, "latency_ms_median": latency, "arms": {}}
    for arm, members in arms.items():
        preds = [any(flagged[m][i] for m in members) for i in range(len(rows))]
        per = {}
        for ds in datasets:
            idx = [i for i, r in enumerate(rows) if r.dataset == ds]
            per[ds] = metrics([preds[i] for i in idx], [rows[i] for i in idx])
        report["arms"][arm] = {
            "members": members,
            "side": "ours"
            if set(members) <= set(ours)
            else "theirs"
            if set(members) <= set(theirs)
            else "both",
            "all": metrics(preds, rows),
            "by_dataset": per,
        }
    return report


def _sample(rows: list[Row], limit: int | None) -> list[Row]:
    """At most `limit` rows per dataset, stratified by label, seeded."""
    if not limit:
        return rows
    rng = random.Random(SEED)
    out: list[Row] = []
    for ds in sorted({r.dataset for r in rows}):
        group = [r for r in rows if r.dataset == ds]
        if len(group) <= limit:
            out += group
            continue
        pos = [r for r in group if r.label]
        neg = [r for r in group if not r.label]
        k = round(limit * len(pos) / len(group))
        out += rng.sample(pos, k) + rng.sample(neg, limit - k)
    return out


def print_table(report: dict) -> None:
    print(f"\n{report['task']} (threshold {report['threshold']})")
    print(f"{'arm':58} {'side':6} {'prec':>6} {'recall':>6} {'F1':>6} {'FPR':>6}")
    ranked = sorted(report["arms"].items(), key=lambda kv: -(kv[1]["all"]["f1"] or 0))
    for arm, r in ranked:
        a = r["all"]
        print(
            f"{arm[:58]:58} {r['side']:6} {a['precision']!s:>6} {a['recall']!s:>6} "
            f"{a['f1']!s:>6} {a['fpr']!s:>6}"
        )
    print("median ms:", report["latency_ms_median"])


def main(argv: Iterable[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=[*TASKS, "all"], default="all")
    ap.add_argument("--limit", type=int, default=None, help="max rows per dataset")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--components", nargs="*", help="only these component keys")
    args = ap.parse_args(list(argv) if argv is not None else None)

    RESULTS.mkdir(exist_ok=True)
    for task in TASKS if args.task == "all" else [args.task]:
        spec = TASKS[task]
        rows = _sample(spec["rows"](), args.limit)
        wanted = args.components or spec["ours"] + spec["theirs"]
        components: dict[str, Callable[[str, str], float]] = {}
        skipped: dict[str, str] = {}
        for key in wanted:
            fn = _detector(key)
            if fn is None:
                skipped[key] = "not registered or not available here"
            else:
                components[key] = fn
        print(f"{task}: {len(rows)} rows; running {list(components)}; skipped {list(skipped)}")
        report = evaluate(task, rows, components, args.threshold)
        report["rows"] = len(rows)
        report["limit_per_dataset"] = args.limit
        report["skipped"] = skipped
        out = RESULTS / f"comparison_{task}.json"
        out.write_text(json.dumps(report, indent=2) + "\n")
        print_table(report)
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
