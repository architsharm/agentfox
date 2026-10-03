"""PII at presence level: Jev against all three shipping detector configs.

The committed PII benchmark scores *spans* — it asks whether the detector found
the right characters. Jev classifies, so it cannot be scored that way. The
comparison here is reshaped to presence: for each text and each in-scope entity
type, does a span of that type exist, and does the detector/model say so.
1,500 texts x 10 types = 15,000 judgments, identical rows for every row below.

Both production configs are run, because the difference between them is a
policy decision rather than a capability one: `DEFAULT_EXCLUDED` removes the
NER-backed types (PERSON, LOCATION, DATE_TIME), which happen to dominate this
dataset's ground truth. Scoring only the default would understate the product.

    python scripts/pii_compare.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "benchmarks" / "pii" / "data"

GT = {
    "EMAIL_ADDRESS": "PII.EMAIL",
    "PHONE_NUMBER": "PII.US_PHONE",
    "CREDIT_CARD": "PII.CREDIT_CARD",
    "US_SSN": "PII.US_SSN",
    "US_DRIVER_LICENSE": "PII.US_DRIVER_LICENSE",
    "IBAN_CODE": "PII.IBAN",
    "IP_ADDRESS": "PII.IP_ADDRESS",
    "PERSON": "PII.PERSON",
    "DATE_TIME": "PII.DATE_TIME",
    "GPE": "PII.LOCATION",
}
INV = {v: k for k, v in GT.items()}
TYPES = list(GT)


def score(pairs) -> dict:
    tp = fp = fn = tn = 0
    for want, got in pairs:
        for t in TYPES:
            w, g = t in want, t in got
            tp += g and w
            fp += g and not w
            fn += (not g) and w
            tn += (not g) and not w
    n = tp + fp + fn + tn
    return {
        "acc": 100 * (tp + tn) / n,
        "prec": 100 * tp / (tp + fp) if tp + fp else 0.0,
        "rec": 100 * tp / (tp + fn) if tp + fn else 0.0,
        "f1": 200 * tp / (2 * tp + fp + fn) if tp else 0.0,
    }


def line(label: str, pairs) -> None:
    s = score(pairs)
    print(f"  {label:36} {s['acc']:>7.1f}% {s['prec']:>7.1f}% {s['rec']:>7.1f}% {s['f1']:>7.1f}")


def main() -> int:
    from agentfox.guardrails.adapters.presidio import DEFAULT_EXCLUDED, PresidioPiiDetector
    from agentfox.guardrails.base import DetectionContext
    from agentfox.guardrails.detectors.pii import NativePiiDetector

    rows = json.loads((DATA / "synth_dataset_v2.json").read_text())
    J = {
        r["id"]: r
        for r in json.loads((HERE / "pii_jev_results.json").read_text())["rows"]
        if r["ds"] == "presidio"
    }
    ctx = DetectionContext(surface="input")

    def presence(det):
        out = []
        for r in rows:
            got = {
                INV[d.entity_type]
                for d in det.detect(r["full_text"], ctx).detections
                if d.entity_type in INV
            }
            want = {s["entity_type"] for s in r["spans"] if s["entity_type"] in GT}
            out.append((want, got))
        return out

    print("PRESENCE-LEVEL, presidio-research: 1,500 texts x 10 types = 15,000 judgments")
    print(f"  {'approach':36} {'acc':>8} {'prec':>8} {'recall':>8} {'F1':>7}")
    print("-" * 74)
    store = {}
    for nm, det in (
        ("pii.native (regex only)", NativePiiDetector()),
        ("pii.presidio.default (ships)", PresidioPiiDetector(excluded=DEFAULT_EXCLUDED)),
        ("pii.presidio.full (all types on)", PresidioPiiDetector(excluded=set())),
    ):
        try:
            store[nm] = presence(det)
            line(nm, store[nm])
        except Exception as e:  # noqa: BLE001
            print(f"  {nm:36} unavailable: {type(e).__name__}")
    for t in (0.5, 0.8):
        pairs = [
            (
                set(J[f"presidio/{i}"]["present"]),
                {ty for ty, p in J[f"presidio/{i}"]["p"].items() if p >= t},
            )
            for i in range(len(rows))
        ]
        store[f"jev @{t}"] = pairs
        line(f"jev @{t}", pairs)
    full = store.get("pii.presidio.full (all types on)")
    if full:
        j = store["jev @0.8"]
        line("UNION full OR jev@0.8", [(w, a | b) for (w, a), (_, b) in zip(full, j, strict=True)])
        line("BOTH  full AND jev@0.8", [(w, a & b) for (w, a), (_, b) in zip(full, j, strict=True)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
