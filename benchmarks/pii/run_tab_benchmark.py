"""Scores AgentFox's PII detectors against the Text Anonymization Benchmark (TAB)'s
`echr_test.json` (`data/tab_echr_test.json`, 127 rows, real ECHR case law, MIT).

    uv run python benchmarks/pii/run_tab_benchmark.py

Same three detector configurations, same direct-call/span-overlap methodology as
the other two PII runs — see `run_presidio_research_benchmark.py`'s docstring for
the full rationale. What's different about this dataset:

- **Real text, not synthetic.** 127 actual European Court of Human Rights
  judgments (anonymization applied by the court itself, this dataset re-labels
  the original identifying mentions for anonymization research). This is the
  only dataset in this suite that stress-tests PERSON/LOCATION NER on natural
  legal prose instead of templated or generated text.
- **Multiple human annotators per document** (1-10, TAB is itself an
  inter-annotator-agreement study). Ground truth here is the **union** across
  annotators, deduplicated on exact `(start, end, entity_type)` — a disclosed
  simplification of TAB's own weighted risk-based evaluation protocol
  (`evaluation.py` in the source repo), not a reproduction of it. Where
  annotators genuinely disagree on span boundaries for the same real mention,
  each distinct boundary is kept as a separate ground-truth span; this is a
  real, acknowledged source of a slightly inflated false-negative count, not a
  hidden one.
- **`identifier_type` (DIRECT / QUASI / NO_MASK)** is TAB's own annotation of
  re-identification risk — DIRECT means "this mention alone identifies the
  person" (a name, a case number), QUASI means "identifying only in
  combination with other mentions," NO_MASK means "not actually
  identifying despite being a PERSON/ORG/etc. mention" (e.g. a judge referred
  to by their institutional role). Recall is broken out by this field
  specifically for DIRECT identifiers — the category that matters most for
  real anonymization/redaction use, separate from the aggregate number.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentfox.capabilities.detection.adapters.presidio import DEFAULT_EXCLUDED, PresidioPiiDetector
from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.detectors.pii import NativePiiDetector

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"

# TAB entity_type -> AgentFox PII.* canonical type. ORG, DEM, CODE, MISC,
# QUANTITY have no corresponding AgentFox detector and are dropped from ground
# truth entirely (see README for the full list and rationale).
GT_ENTITY_MAP = {
    "PERSON": "PII.PERSON",
    "LOC": "PII.LOCATION",
    # TAB's own label is generic "DATETIME" (any date mention in the judgment,
    # not specifically a birthdate) — mapped to PII.DATE_TIME to match the
    # taxonomy fix in adapters/presidio.py (was PII.DATE_OF_BIRTH; see
    # README "Fixes applied").
    "DATETIME": "PII.DATE_TIME",
}

OUT_OF_SCOPE_SEEN: set[str] = set()


def load_dataset() -> list[dict]:
    return json.loads((DATA_DIR / "tab_echr_test.json").read_text())


def gt_spans_for_row(row: dict) -> list[tuple[int, int, str, str]]:
    """Returns (start, end, canonical_type, identifier_type), deduped across annotators."""
    seen: set[tuple[int, int, str]] = set()
    out = []
    for annotator in row["annotations"].values():
        for mention in annotator["entity_mentions"]:
            canonical = GT_ENTITY_MAP.get(mention["entity_type"])
            if canonical is None:
                OUT_OF_SCOPE_SEEN.add(mention["entity_type"])
                continue
            key = (mention["start_offset"], mention["end_offset"], canonical)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                (
                    mention["start_offset"],
                    mention["end_offset"],
                    canonical,
                    mention.get("identifier_type", "UNKNOWN"),
                )
            )
    return out


def pred_spans(detections, canonical_types: set[str]) -> list[tuple[int, int, str]]:
    return [(d.start, d.end, d.entity_type) for d in detections if d.entity_type in canonical_types]


def score_row(gt, pred) -> tuple[int, int, int, dict[str, list[int]], dict[str, list[int]]]:
    per_type: dict[str, list[int]] = {}
    per_identifier: dict[str, list[int]] = {}

    def bucket(store: dict[str, list[int]], k: str) -> list[int]:
        return store.setdefault(k, [0, 0, 0])

    matched_pred: set[int] = set()
    tp = fp = fn = 0
    for gs, ge, gt_type, ident_type in gt:
        match_idx = None
        for i, (ps, pe, pt) in enumerate(pred):
            if i in matched_pred or pt != gt_type:
                continue
            if ps < ge and gs < pe:
                match_idx = i
                break
        if match_idx is not None:
            matched_pred.add(match_idx)
            tp += 1
            bucket(per_type, gt_type)[0] += 1
            bucket(per_identifier, ident_type)[0] += 1
        else:
            fn += 1
            bucket(per_type, gt_type)[2] += 1
            bucket(per_identifier, ident_type)[2] += 1
    for i, (_, _, pt) in enumerate(pred):
        if i not in matched_pred:
            fp += 1
            bucket(per_type, pt)[1] += 1
    return tp, fp, fn, per_type, per_identifier


def merge(total: dict[str, list[int]], part: dict[str, list[int]]) -> None:
    for t, (tp, fp, fn) in part.items():
        bucket = total.setdefault(t, [0, 0, 0])
        bucket[0] += tp
        bucket[1] += fp
        bucket[2] += fn


def prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def summarize(tp: int, fp: int, fn: int) -> dict:
    p, r, f = prf1(tp, fp, fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(p, 4),
        "recall": round(r, 4),
        "f1": round(f, 4),
    }


def run_config(name: str, detector, rows: list[dict], ctx: DetectionContext) -> dict:
    canonical_types = set(GT_ENTITY_MAP.values())
    total_tp = total_fp = total_fn = 0
    per_type: dict[str, list[int]] = {}
    per_identifier: dict[str, list[int]] = {}

    for i, row in enumerate(rows):
        gt = gt_spans_for_row(row)
        detections = detector.detect(row["text"], ctx)
        pred = pred_spans(detections.detections, canonical_types)
        tp, fp, fn, part_type, part_ident = score_row(gt, pred)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        merge(per_type, part_type)
        merge(per_identifier, part_ident)
        if (i + 1) % 25 == 0:
            print(f"  [{name}] {i + 1}/{len(rows)} rows")

    return {
        "config": name,
        **summarize(total_tp, total_fp, total_fn),
        "by_type": {t: summarize(*v) for t, v in sorted(per_type.items())},
        "by_identifier_type": {t: summarize(*v) for t, v in sorted(per_identifier.items())},
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_dataset()
    print(f"Loaded {len(rows)} rows")

    ctx = DetectionContext(surface="input")
    configs = [
        ("pii.native", NativePiiDetector()),
        ("pii.presidio.default", PresidioPiiDetector(excluded=DEFAULT_EXCLUDED)),
        ("pii.presidio.full", PresidioPiiDetector(excluded=set())),
    ]

    results = []
    for name, detector in configs:
        print(f"Running {name}...")
        results.append(run_config(name, detector, rows, ctx))

    summary = {
        "dataset": "text-anonymization-benchmark echr_test.json",
        "rows": len(rows),
        "in_scope_gt_entity_types": sorted(GT_ENTITY_MAP.keys()),
        "out_of_scope_entity_types_seen": sorted(OUT_OF_SCOPE_SEEN),
        "results": results,
    }

    out_path = RESULTS_DIR / "tab_summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}\n")

    print(f"{'config':<24}{'precision':<12}{'recall':<12}{'f1':<12}{'tp':<8}{'fp':<8}{'fn':<8}")
    for r in results:
        print(
            f"{r['config']:<24}{r['precision']:<12}{r['recall']:<12}{r['f1']:<12}"
            f"{r['tp']:<8}{r['fp']:<8}{r['fn']:<8}"
        )


if __name__ == "__main__":
    main()
