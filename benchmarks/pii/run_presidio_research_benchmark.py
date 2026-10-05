"""Scores AgentFox's PII detectors against presidio-research's span-labeled
synthetic dataset (`data/synth_dataset_v2.json`, 1,500 rows, MIT).

    uv run python benchmarks/pii/run_presidio_research_benchmark.py

Three detector configurations are scored, all called directly on the detector
object (`.detect(text, context)`), not through `DetectorPipeline` — the pipeline's
shared per-call timeout budget marks `pii.presidio` "degraded" on its first
(model-loading) call even after `warm_all()`, the same latency-ceiling
measurement artifact documented in `benchmarks/REPORT.md`. A direct call avoids
that budget entirely; the model loads once (~3s) on the first row and every
subsequent call is single-digit-to-low-double-digit milliseconds:

  - pii.native            — regex-only detector, no NER, no PERSON/LOCATION.
  - pii.presidio (default) — Presidio NER, PERSON/LOCATION/DATE_TIME excluded
                              by policy default (`DEFAULT_EXCLUDED` in
                              adapters/presidio.py) as "noisy in agent traffic".
  - pii.presidio (full)    — same engine, nothing excluded. The gap between this
                              row and the default-policy row is the honest,
                              directly-measured cost of that default exclusion.

Scoping — this dataset labels many entity types AgentFox's detectors never claim
to cover at all (STREET_ADDRESS, ORGANIZATION, TITLE, AGE, NRP, ZIP_CODE,
DOMAIN_NAME). Those spans are excluded from ground truth entirely; scoring a
detector as "wrong" for not detecting a category it was never built for would
misrepresent the detector, not evaluate it. `GT_ENTITY_MAP` below is the explicit,
disclosed scope: every dataset entity type that maps onto AgentFox's declared
`PII.*` taxonomy, one direct mapping each, plus one deliberate proxy — dataset
`GPE` (geo-political entity, e.g. a country/city name) is mapped to `PII.LOCATION`
since presidio-research doesn't use a separate LOCATION label and GPE is the
closest thing it has. That proxy is a real scope decision, not a hidden one.

Scoring method — character-span overlap, not exact-boundary match: a predicted
span counts as a true positive for a ground-truth span of the same canonical type
if the two character ranges overlap at all (standard for PII/NER evaluation,
where "found the SSN" matters more than "found exactly byte-identical
boundaries"). Matching is greedy one-to-one per (document, canonical type) so one
predicted span can't double-count against two ground-truth spans. Unmatched
ground-truth spans are false negatives; unmatched predicted spans (of an in-scope
canonical type) are false positives.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentfox.detection.adapters.presidio import DEFAULT_EXCLUDED, PresidioPiiDetector
from agentfox.detection.base import DetectionContext
from agentfox.detection.detectors.pii import NativePiiDetector

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"

# Dataset entity_type -> AgentFox PII.* canonical type. Only types AgentFox's
# detectors actually declare are included; everything else is out of scope
# (see module docstring) and dropped from ground truth entirely.
GT_ENTITY_MAP = {
    "EMAIL_ADDRESS": "PII.EMAIL",
    "PHONE_NUMBER": "PII.US_PHONE",
    "CREDIT_CARD": "PII.CREDIT_CARD",
    "US_SSN": "PII.US_SSN",
    "US_DRIVER_LICENSE": "PII.US_DRIVER_LICENSE",
    "IBAN_CODE": "PII.IBAN",
    "IP_ADDRESS": "PII.IP_ADDRESS",
    "PERSON": "PII.PERSON",
    # This dataset's own label is generic "DATE_TIME" (any date-shaped
    # mention), not specifically a birthdate — mapped to PII.DATE_TIME to
    # match the taxonomy fix in adapters/presidio.py (was PII.DATE_OF_BIRTH;
    # that mapping is what the fix corrected, see README "Fixes applied").
    "DATE_TIME": "PII.DATE_TIME",
    "GPE": "PII.LOCATION",  # proxy — see module docstring
}

OUT_OF_SCOPE_SEEN: set[str] = set()


def load_dataset() -> list[dict]:
    return json.loads((DATA_DIR / "synth_dataset_v2.json").read_text())


def gt_spans_for_row(row: dict) -> list[tuple[int, int, str]]:
    out = []
    for span in row["spans"]:
        et = span["entity_type"]
        canonical = GT_ENTITY_MAP.get(et)
        if canonical is None:
            OUT_OF_SCOPE_SEEN.add(et)
            continue
        out.append((span["start_position"], span["end_position"], canonical))
    return out


def street_address_spans_for_row(row: dict) -> list[tuple[int, int]]:
    """STREET_ADDRESS ground-truth spans — out of scope (no AgentFox address
    detector) but often *contain* a real, separately-real city/country mention
    a LOCATION recognizer correctly finds. See `score_row`'s containment
    exclusion and README "Fixes applied" — verified directly: 66.5% of raw
    LOCATION false positives (157/236) were confirmed-correct hits landing
    inside one of these spans, not detector errors.
    """
    return [
        (s["start_position"], s["end_position"])
        for s in row["spans"]
        if s["entity_type"] == "STREET_ADDRESS"
    ]


def pred_spans(detections, canonical_types: set[str]) -> list[tuple[int, int, str]]:
    return [(d.start, d.end, d.entity_type) for d in detections if d.entity_type in canonical_types]


def score_row(
    gt: list[tuple[int, int, str]],
    pred: list[tuple[int, int, str]],
    containment_exclude: list[tuple[int, int]] = (),
) -> tuple[int, int, int, int, dict[str, list[int]]]:
    """Greedy one-to-one span-overlap matching, per canonical type.

    An unmatched predicted span fully contained inside a
    `containment_exclude` span (STREET_ADDRESS ground truth here — see
    `street_address_spans_for_row`) is neither a TP nor an FP: it's outside
    what this benchmark's ground truth can credit, not a detector error.
    Tracked separately as `excluded` so it never silently vanishes from the
    numbers.

    Returns (tp, fp, fn, excluded, per_type) where per_type[canonical_type] = [tp, fp, fn].
    """
    per_type: dict[str, list[int]] = {}

    def bucket(t: str) -> list[int]:
        return per_type.setdefault(t, [0, 0, 0])

    matched_pred: set[int] = set()
    tp = fp = fn = excluded = 0
    for gs, ge, gt_type in gt:
        match_idx = None
        for i, (ps, pe, pt) in enumerate(pred):
            if i in matched_pred or pt != gt_type:
                continue
            if ps < ge and gs < pe:  # overlap
                match_idx = i
                break
        if match_idx is not None:
            matched_pred.add(match_idx)
            tp += 1
            bucket(gt_type)[0] += 1
        else:
            fn += 1
            bucket(gt_type)[2] += 1
    for i, (ps, pe, pt) in enumerate(pred):
        if i in matched_pred:
            continue
        if any(a_s <= ps and pe <= a_e for a_s, a_e in containment_exclude):
            excluded += 1
            continue
        fp += 1
        bucket(pt)[1] += 1
    return tp, fp, fn, excluded, per_type


def merge_per_type(total: dict[str, list[int]], part: dict[str, list[int]]) -> None:
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


def run_config(name: str, detector, rows: list[dict], ctx: DetectionContext) -> dict:
    canonical_types = set(GT_ENTITY_MAP.values())
    total_tp = total_fp = total_fn = total_excluded = 0
    per_type: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        gt = gt_spans_for_row(row)
        street_addrs = street_address_spans_for_row(row)
        detections = detector.detect(row["full_text"], ctx)
        pred = pred_spans(detections.detections, canonical_types)
        tp, fp, fn, excluded, part = score_row(gt, pred, street_addrs)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_excluded += excluded
        merge_per_type(per_type, part)
        if (i + 1) % 250 == 0:
            print(f"  [{name}] {i + 1}/{len(rows)} rows")

    precision, recall, f1 = prf1(total_tp, total_fp, total_fn)
    by_type = {}
    for t, (tp, fp, fn) in sorted(per_type.items()):
        p, r, f = prf1(tp, fp, fn)
        by_type[t] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f, 4),
        }
    return {
        "config": name,
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn,
        "excluded_contained_in_street_address": total_excluded,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "by_type": by_type,
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
        "dataset": "presidio-research/synth_dataset_v2.json",
        "rows": len(rows),
        "in_scope_gt_entity_types": sorted(GT_ENTITY_MAP.keys()),
        "out_of_scope_entity_types_seen": sorted(OUT_OF_SCOPE_SEEN),
        "results": results,
    }

    out_path = RESULTS_DIR / "summary.json"
    out_path.write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {out_path}\n")

    print(
        f"{'config':<24}{'precision':<12}{'recall':<12}{'f1':<12}{'tp':<8}{'fp':<8}{'fn':<8}{'excl':<6}"
    )
    for r in results:
        print(
            f"{r['config']:<24}{r['precision']:<12}{r['recall']:<12}{r['f1']:<12}"
            f"{r['tp']:<8}{r['fp']:<8}{r['fn']:<8}{r['excluded_contained_in_street_address']:<6}"
        )


if __name__ == "__main__":
    main()
