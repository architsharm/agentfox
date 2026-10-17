"""Span scoring shared by the PII benchmarks (`benchmarks/pii/`).

Character-span overlap, not exact-boundary match: a predicted span is a true positive
for a ground-truth span of the same canonical type if the two ranges overlap at all.
Matching is greedy and one-to-one per canonical type, so one prediction cannot count
against two ground-truth spans. Each script maps its own dataset's labels to
canonical types; only the arithmetic lives here.
"""

from __future__ import annotations

from collections.abc import Sequence


def pred_spans(detections, canonical_types: set[str]) -> list[tuple[int, int, str]]:
    return [(d.start, d.end, d.entity_type) for d in detections if d.entity_type in canonical_types]


def score_row_with_exclusions(
    gt: list[tuple[int, int, str]],
    pred: list[tuple[int, int, str]],
    containment_exclude: Sequence[tuple[int, int]] = (),
) -> tuple[int, int, int, int, dict[str, list[int]]]:
    """Greedy one-to-one span-overlap matching, per canonical type.

    An unmatched predicted span fully contained inside a `containment_exclude` span
    (STREET_ADDRESS ground truth in the presidio-research and Gretel sets) is neither a
    TP nor an FP: it's outside what the benchmark's ground truth can credit, not a
    detector error. Tracked separately as `excluded` so it never silently vanishes from
    the numbers.

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


def merge_counts(total: dict[str, list[int]], part: dict[str, list[int]]) -> None:
    """Add each key's [tp, fp, fn] in `part` into `total`."""
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
