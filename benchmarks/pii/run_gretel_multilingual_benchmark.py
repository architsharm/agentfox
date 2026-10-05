"""Scores AgentFox's PII detectors against gretelai/synthetic_pii_finance_multilingual
(`data/gretel_multilingual_pii.json`, 5,594 rows, 7 languages, Apache-2.0).

    uv run python benchmarks/pii/run_gretel_multilingual_benchmark.py

Same three detector configurations, same direct-call/span-overlap methodology as
`run_presidio_research_benchmark.py` (see that script's docstring for the full
rationale) — differences specific to this dataset:

- **Full-length synthetic documents** (EDI messages, invoices, bank statements,
  contracts), not single sentences — a different, more realistic shape than
  dataset 1's short template sentences.
- **7 languages**: English, French, German, Dutch, Spanish, Italian, Swedish.
  `pii.presidio` is instantiated with `language="en"` throughout (its shipping
  default — nothing in the product auto-detects document language today), so
  this run also directly measures what a language mismatch costs, not just PII
  detection in the abstract.
- **A cleaner isolation of what used to be the DATE_TIME/DATE_OF_BIRTH taxonomy
  conflation** than dataset 1: this dataset separately labels `date_of_birth`
  from generic `date`/`time`/`date_time` mentions. `date_of_birth` is the only
  one mapped into scope here (`PII.DATE_OF_BIRTH`). Since the taxonomy fix in
  `adapters/presidio.py` (see README "Fixes applied"), Presidio's own generic
  `DATE_TIME` recognizer now emits `PII.DATE_TIME`, a different canonical type
  than this bucket — so `pii.presidio` no longer contributes any TP or FP here
  at all; only `pii.native`'s birthdate-shaped regex is scored against this
  ground-truth bucket now, which is the honest scope for what each engine
  actually claims to detect.
- **`password`/`api_key` labels exist in this dataset but are deliberately out of
  scope here** — those are secrets, not PII; scoring them against `pii.*`
  detectors would misrepresent what's being tested. They're listed in the output
  under `out_of_scope_entity_types_seen` and are flagged in the README as a
  candidate for a future *secrets*-detection benchmark against this same file,
  not folded into this one.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from agentfox.detection.adapters.presidio import DEFAULT_EXCLUDED, PresidioPiiDetector
from agentfox.detection.base import DetectionContext
from agentfox.detection.detectors.pii import NativePiiDetector

DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"

# gretelai label -> AgentFox PII.* canonical type. Only types AgentFox's
# detectors actually declare are included; everything else (street_address,
# company, generic date/time, swift_bic_code, customer_id, employee_id, bban,
# account_pin, credit_card_security_code, bank_routing_number, password,
# api_key, local_latlng, user_name) is out of scope and dropped from ground
# truth entirely — see module + README for why.
GT_ENTITY_MAP = {
    "email": "PII.EMAIL",
    "phone_number": "PII.US_PHONE",
    "credit_card_number": "PII.CREDIT_CARD",
    "ssn": "PII.US_SSN",
    "driver_license_number": "PII.US_DRIVER_LICENSE",
    "passport_number": "PII.US_PASSPORT",
    "iban": "PII.IBAN",
    "ipv4": "PII.IP_ADDRESS",
    "ipv6": "PII.IP_ADDRESS",
    "name": "PII.PERSON",
    "first_name": "PII.PERSON",
    "last_name": "PII.PERSON",
    "date_of_birth": "PII.DATE_OF_BIRTH",
}

OUT_OF_SCOPE_SEEN: set[str] = set()


def load_dataset() -> list[dict]:
    return json.loads((DATA_DIR / "gretel_multilingual_pii.json").read_text())


def gt_spans_for_row(row: dict) -> list[tuple[int, int, str]]:
    out = []
    for span in row["spans"]:
        canonical = GT_ENTITY_MAP.get(span["label"])
        if canonical is None:
            OUT_OF_SCOPE_SEEN.add(span["label"])
            continue
        out.append((span["start"], span["end"], canonical))
    return out


def street_address_spans_for_row(row: dict) -> list[tuple[int, int]]:
    """street_address ground-truth spans — out of scope (no AgentFox address
    detector) but often *contain* a real, separately-real city/country mention
    a LOCATION recognizer correctly finds. Same containment-exclusion rule as
    `run_presidio_research_benchmark.py`, verified there (66.5% of raw
    LOCATION false positives were confirmed-correct hits inside one of
    these) — see README "Fixes applied".
    """
    return [(s["start"], s["end"]) for s in row["spans"] if s["label"] == "street_address"]


def pred_spans(detections, canonical_types: set[str]) -> list[tuple[int, int, str]]:
    return [(d.start, d.end, d.entity_type) for d in detections if d.entity_type in canonical_types]


def score_row(
    gt, pred, containment_exclude: list[tuple[int, int]] = ()
) -> tuple[int, int, int, int, dict[str, list[int]]]:
    """See run_presidio_research_benchmark.py's score_row for the containment-
    exclusion rationale — a predicted span fully inside a street_address span
    is neither TP nor FP, tracked separately as `excluded`."""
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
            if ps < ge and gs < pe:
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


def merge_per_type(total, part) -> None:
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
    total_tp = total_fp = total_fn = total_excluded = 0
    per_type: dict[str, list[int]] = {}
    # language -> canonical_type -> [tp, fp, fn], for the DATE_OF_BIRTH-format
    # hypothesis and any other locale-coverage question.
    per_lang_type: dict[str, dict[str, list[int]]] = defaultdict(dict)

    for i, row in enumerate(rows):
        gt = gt_spans_for_row(row)
        street_addrs = street_address_spans_for_row(row)
        detections = detector.detect(row["text"], ctx)
        pred = pred_spans(detections.detections, canonical_types)
        tp, fp, fn, excluded, part = score_row(gt, pred, street_addrs)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_excluded += excluded
        merge_per_type(per_type, part)
        merge_per_type(per_lang_type[row["language"]], part)
        if (i + 1) % 500 == 0:
            print(f"  [{name}] {i + 1}/{len(rows)} rows")

    by_type = {t: summarize(*v) for t, v in sorted(per_type.items())}
    by_language = {
        lang: {t: summarize(*v) for t, v in sorted(types.items())}
        for lang, types in sorted(per_lang_type.items())
    }
    overall = summarize(total_tp, total_fp, total_fn)
    return {
        "config": name,
        **overall,
        "excluded_contained_in_street_address": total_excluded,
        "by_type": by_type,
        "by_language": by_language,
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_dataset()
    print(f"Loaded {len(rows)} rows")
    print("Language distribution:", Counter(r["language"] for r in rows))

    ctx = DetectionContext(surface="input")
    configs = [
        ("pii.native", NativePiiDetector()),
        ("pii.presidio.default", PresidioPiiDetector(language="en", excluded=DEFAULT_EXCLUDED)),
        ("pii.presidio.full", PresidioPiiDetector(language="en", excluded=set())),
    ]

    results = []
    for name, detector in configs:
        print(f"Running {name}...")
        results.append(run_config(name, detector, rows, ctx))

    summary = {
        "dataset": "gretelai/synthetic_pii_finance_multilingual (test split)",
        "rows": len(rows),
        "in_scope_gt_entity_types": sorted(GT_ENTITY_MAP.keys()),
        "out_of_scope_entity_types_seen": sorted(OUT_OF_SCOPE_SEEN),
        "results": results,
    }

    out_path = RESULTS_DIR / "gretel_multilingual_summary.json"
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
