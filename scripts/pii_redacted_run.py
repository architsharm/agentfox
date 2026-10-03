"""Does redacting before egress destroy the thing remote judgment was for?

The gateway masks whatever the local detector finds before any payload leaves.
For PII work that looks circular — if we already found it locally, why ask? —
but the benchmark says the local default reaches 17.8% presence recall against
Jev's 97.9%. The value is in what local *misses*, and masking what it *found*
should leave that untouched.

"Should" is not a measurement, so this measures it: same texts, same questions,
but every span the local detector found is masked out first. If recall on the
types local missed holds up, the gateway's design is sound and remote judgment
can be offered without shipping the data it is judging.

    JEV_API_KEY=... python scripts/pii_redacted_run.py --limit 400
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from pii_run import PRESIDIO, q  # noqa: E402
from sp_run import JEV_URL, _errors, _post  # noqa: E402

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "benchmarks" / "pii" / "data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--workers", type=int, default=14)
    args = ap.parse_args()

    from agentfox.guardrails.base import DetectionContext
    from agentfox.guardrails.detectors.pii import NativePiiDetector
    from agentfox.judgment.egress import _Masker

    det, ctx = NativePiiDetector(), DetectionContext(surface="input")
    rows = json.loads((DATA / "synth_dataset_v2.json").read_text())[: args.limit]
    INV = {
        "PII.EMAIL": "EMAIL_ADDRESS",
        "PII.US_PHONE": "PHONE_NUMBER",
        "PII.CREDIT_CARD": "CREDIT_CARD",
        "PII.US_SSN": "US_SSN",
        "PII.US_DRIVER_LICENSE": "US_DRIVER_LICENSE",
        "PII.IBAN": "IBAN_CODE",
        "PII.IP_ADDRESS": "IP_ADDRESS",
        "PII.PERSON": "PERSON",
        "PII.DATE_TIME": "DATE_TIME",
        "PII.LOCATION": "GPE",
    }

    cases = []
    for i, r in enumerate(rows):
        text = r["full_text"]
        found = {
            INV[d.entity_type] for d in det.detect(text, ctx).detections if d.entity_type in INV
        }
        masker = _Masker(det, ctx)
        cases.append(
            {
                "i": i,
                "redacted": masker.text(text),
                "spans_masked": masker.count,
                "local_found": found,
                "present": {s["entity_type"] for s in r["spans"] if s["entity_type"] in PRESIDIO},
            }
        )

    def ask(c):
        body = json.dumps(
            {
                "model": "jev-latest",
                "state": {"text": c["redacted"]},
                "questions": {t: q(t) for t in PRESIDIO},
            },
            sort_keys=True,
            default=str,
        ).encode()
        a = _post(
            JEV_URL,
            body,
            {
                "Authorization": f"Bearer {os.environ.get('JEV_API_KEY', '')}",
                "Content-Type": "application/json",
            },
        )["answers"]
        return {"i": c["i"], "p": {t: float(a[t]["noul"]) for t in PRESIDIO}}

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        got = {r["i"]: r for r in pool.map(ask, cases)}
    print(
        f"  {len(cases)} redacted texts in {time.perf_counter() - t0:.0f}s"
        f"  ({sum(c['spans_masked'] for c in cases)} spans masked)"
    )

    # the question: on types the LOCAL detector missed, does Jev still find them?
    plain = {
        r["id"]: r
        for r in json.loads((HERE / "pii_jev_results.json").read_text())["rows"]
        if r["ds"] == "presidio"
    }
    for thr in (0.5, 0.8):
        tp = fn = 0
        ptp = pfn = 0
        for c in cases:
            missed = c["present"] - c["local_found"]
            for t in missed:
                tp += got[c["i"]]["p"][t] >= thr
                fn += got[c["i"]]["p"][t] < thr
                ptp += plain[f"presidio/{c['i']}"]["p"][t] >= thr
                pfn += plain[f"presidio/{c['i']}"]["p"][t] < thr
        n = tp + fn
        print(
            f"  @{thr}: on the {n} (text,type) pairs the LOCAL detector missed — "
            f"redacted recall {100 * tp / n:.1f}%  vs unredacted {100 * ptp / n:.1f}%"
        )
    if _errors:
        print(f"  transport: {dict(_errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
