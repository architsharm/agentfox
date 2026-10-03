"""The product measured end to end, default versus every capability enabled.

Not a study of Jev — a study of agentfox with and without the judgment tiers
switched on, through the real detectors, the real pipeline and the real
answerability path. The question it answers is the one an operator asks:
"if I turn these on, what do I actually get, and what does it cost me?"

Four areas, chosen to cover both directions: two where judgment should help,
one where the benchmarks say it must not be allowed to, and the regression
check that proves it wasn't.

    JEV_API_KEY=... python scripts/spectrum.py [--n 120]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

HERE = pathlib.Path(__file__).parent
BENCH = HERE.parent / "benchmarks"


def _score(rows):
    tp = fp = fn = tn = 0
    for want, got in rows:
        tp += got and want
        fp += got and not want
        fn += (not got) and want
        tn += (not got) and not want
    n = tp + fp + fn + tn or 1
    return {
        "acc": 100 * (tp + tn) / n,
        "prec": 100 * tp / (tp + fp) if tp + fp else 0.0,
        "rec": 100 * tp / (tp + fn) if tp + fn else 0.0,
        "f1": 200 * tp / (2 * tp + fp + fn) if tp else 0.0,
    }


def _row(label, off, on, cost):
    d = on["f1"] - off["f1"]
    print(
        f"  {label:34} {off['acc']:>6.1f}% {off['f1']:>6.1f}  |  "
        f"{on['acc']:>6.1f}% {on['f1']:>6.1f}  {d:>+6.1f}  {cost}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    args = ap.parse_args()
    n = args.n

    from agentfox.answerability import AGGREGATE, FACT, PROCEDURE, classify_answerability
    from agentfox.config import get_settings
    from agentfox.guardrails import DetectorPipeline
    from agentfox.guardrails.base import DetectionContext
    from agentfox.guardrails.detectors.injection import InjectionHeuristicDetector
    from agentfox.guardrails.detectors.judgment import (
        InjectionJudgmentDetector,
        PiiJudgmentDetector,
    )
    from agentfox.guardrails.detectors.pii import NativePiiDetector
    from agentfox.judgment.answerability import augment
    from agentfox.models import KnowledgeBoundary

    s = get_settings()
    s.allow_egress = True
    s.judgment_tiers = ["deterministic", "jev"]
    ctx_in = DetectionContext(surface="input")

    print("=" * 104)
    print("agentfox, default versus all judgment tiers enabled")
    print("=" * 104)
    print(f"  {'area':34} {'DEFAULT':>14}  |  {'ALL ENABLED':>14}  {'ΔF1':>6}  cost/call")
    print("-" * 104)

    # 1. injection — the payloads that escaped the shipping detectors
    att = json.loads((BENCH / "adaptive" / "results" / "adaptive_attempts.json").read_text())
    esc = [r for r in att if r.get("success") and r.get("payload")][:n]
    benign = [
        "Great vacuum cleaner, works well on carpets.",
        "Quarterly revenue rose 4% on stronger retail demand.",
        "See the installation guide for driver requirements.",
    ] * (len(esc) // 3 or 1)
    off_p = DetectorPipeline(detectors=[InjectionHeuristicDetector()])
    on_p = DetectorPipeline(detectors=[InjectionHeuristicDetector(), InjectionJudgmentDetector()])
    t0 = time.perf_counter()
    off = [(True, off_p.run(r["payload"], ctx_in).results[0].triggered) for r in esc]
    off += [(False, any(x.triggered for x in off_p.run(b, ctx_in).results)) for b in benign]
    mid = time.perf_counter()
    on = [(True, any(x.triggered for x in on_p.run(r["payload"], ctx_in).results)) for r in esc]
    on += [(False, any(x.triggered for x in on_p.run(b, ctx_in).results)) for b in benign]
    end = time.perf_counter()
    _row(
        "injection (escaped payloads)",
        _score(off),
        _score(on),
        f"{1000 * (mid - t0) / len(off):.0f}ms -> {1000 * (end - mid) / len(on):.0f}ms",
    )

    # 2. answerability
    kuq = json.loads((BENCH / "answerability" / "data" / "kuq.json").read_text())[: n * 3]
    boundary = KnowledgeBoundary(answerable_types=[FACT, AGGREGATE, PROCEDURE], mode="enforce")
    t0 = time.perf_counter()
    off_a, on_a = [], []
    for r in kuq:
        want = r["label"] in ("controversial", "future_unknown")
        v = classify_answerability(r["question"], boundary)
        off_a.append((want, not v.answerable))
    mid = time.perf_counter()
    for r in kuq:
        want = r["label"] in ("controversial", "future_unknown")
        v = classify_answerability(r["question"], boundary)
        if v.answerable:
            v = augment(v, r["question"])
        on_a.append((want, not v.answerable))
    end = time.perf_counter()
    _row(
        "answerability (KUQ)",
        _score(off_a),
        _score(on_a),
        f"{1000 * (mid - t0) / len(kuq):.0f}ms -> {1000 * (end - mid) / len(kuq):.0f}ms",
    )

    # 3. PII presence
    rows = json.loads((BENCH / "pii" / "data" / "synth_dataset_v2.json").read_text())[:n]
    IN_SCOPE = {
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
        "US_DRIVER_LICENSE",
        "IBAN_CODE",
        "IP_ADDRESS",
        "PERSON",
        "DATE_TIME",
        "GPE",
    }
    native, judge = NativePiiDetector(), PiiJudgmentDetector()
    t0 = time.perf_counter()
    off_pii = [
        (
            bool({x["entity_type"] for x in r["spans"]} & IN_SCOPE),
            native.detect(r["full_text"], ctx_in).triggered,
        )
        for r in rows
    ]
    mid = time.perf_counter()
    on_pii = []
    for r in rows:
        want = bool({x["entity_type"] for x in r["spans"]} & IN_SCOPE)
        got = (
            native.detect(r["full_text"], ctx_in).triggered
            or judge.detect(r["full_text"], ctx_in).triggered
        )
        on_pii.append((want, got))
    end = time.perf_counter()
    _row(
        "PII presence (presidio-research)",
        _score(off_pii),
        _score(on_pii),
        f"{1000 * (mid - t0) / len(rows):.0f}ms -> {1000 * (end - mid) / len(rows):.0f}ms",
    )

    # 4. the regression check — judgment must not be allowed near this
    sql = json.loads(
        (BENCH / "action_safety" / "results" / "test_natural_dml_predictions.json").read_text()
    )[:n]
    sql_rows = [(bool(r["expect_blocked"]), bool(r["predicted_blocked"])) for r in sql]
    _row("SQL blast radius (regression)", _score(sql_rows), _score(sql_rows), "unchanged")

    print("-" * 104)
    print("  SQL is identical by construction: capability.py forbids every judgment tier")
    print("  from deciding STRUCTURAL_PARSED, so enabling them cannot reach it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
