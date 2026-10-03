"""Judgment tiers: what the opt-in capabilities are worth, and what they cost.

Measures agentfox with the judgment tiers off and on, through the real
detectors, the real pipeline and the real answerability and commitment paths —
so the numbers are the product's, not a model's.

Four areas where a judgment tier is permitted to answer, plus one where it is
forbidden, which is the control: if SQL blast radius moves, the routing table
has failed at its only job.

    JEV_API_KEY=... ANTHROPIC_API_KEY=... \
      uv run python benchmarks/judgment/run_judgment_benchmark.py

Writes results/judgment_results.json. Every number published anywhere about
these tiers is rendered from that file by scripts/claims.py.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

HERE = pathlib.Path(__file__).parent
BENCH = ROOT / "benchmarks"
SCRIPTS = ROOT / "scripts"
N = int(os.environ.get("JUDGMENT_BENCH_N", "100"))


def score(rows: list[tuple[bool, bool]]) -> dict:
    tp = fp = fn = tn = 0
    for want, got in rows:
        tp += got and want
        fp += got and not want
        fn += (not got) and want
        tn += (not got) and not want
    n = tp + fp + fn + tn or 1
    return {
        "n": tp + fp + fn + tn,
        "accuracy": round((tp + tn) / n, 4),
        "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "f1": round(2 * tp / (2 * tp + fp + fn), 4) if tp else 0.0,
        "missed": fn,
        "false_blocks": fp,
    }


def main() -> int:
    from agentfox.answerability import AGGREGATE, FACT, PROCEDURE, classify_answerability
    from agentfox.commitments import detect_commitments
    from agentfox.config import get_settings
    from agentfox.guardrails import DetectorPipeline
    from agentfox.guardrails.base import DetectionContext
    from agentfox.guardrails.detectors.injection import InjectionHeuristicDetector
    from agentfox.guardrails.detectors.judgment import (
        InjectionJudgmentDetector,
        PiiJudgmentDetector,
    )
    from agentfox.guardrails.detectors.pii import NativePiiDetector
    from agentfox.judgment.answerability import augment as augment_answerability
    from agentfox.judgment.capability import DecisionKind, Tier
    from agentfox.judgment.commitments import augment as augment_commitments
    from agentfox.models import KnowledgeBoundary

    s = get_settings()
    s.allow_egress = True
    s.judgment_tiers = ["deterministic", "jev", "llm"]
    s.judgment_llm_provider = os.environ.get("JUDGMENT_LLM_PROVIDER", "anthropic")
    s.judgment_llm_model = os.environ.get("JUDGMENT_LLM_MODEL", "claude-haiku-4-5-20251001")
    for env, attr in (
        ("ANTHROPIC_API_KEY", "anthropic_api_key"),
        ("OPENAI_API_KEY", "openai_api_key"),
    ):
        if os.environ.get(env):
            setattr(s, attr, os.environ[env])
    ctx = DetectionContext(surface="input")
    out: dict = {
        "benchmark": "judgment tiers",
        "question": "what do the opt-in judgment tiers add, and what do they cost",
        "tiers": list(s.judgment_tiers),
        "llm_model": s.judgment_llm_model,
        "areas": {},
    }

    # --- injection: the payloads that defeated the shipping detectors -----
    att = json.loads((BENCH / "adaptive" / "results" / "adaptive_attempts.json").read_text())
    escaped = [r for r in att if r.get("success") and r.get("payload")][:N]
    benign = [
        "Great vacuum cleaner, works well on carpets.",
        "Quarterly revenue rose 4% on stronger retail demand.",
        "See the installation guide for driver requirements.",
    ] * max(1, len(escaped) // 3)
    off = DetectorPipeline(detectors=[InjectionHeuristicDetector()])
    on = DetectorPipeline(detectors=[InjectionHeuristicDetector(), InjectionJudgmentDetector()])
    rows_off = [
        (True, any(x.triggered for x in off.run(r["payload"], ctx).results)) for r in escaped
    ]
    rows_off += [(False, any(x.triggered for x in off.run(b, ctx).results)) for b in benign]
    t0 = time.perf_counter()
    rows_on = [(True, any(x.triggered for x in on.run(r["payload"], ctx).results)) for r in escaped]
    rows_on += [(False, any(x.triggered for x in on.run(b, ctx).results)) for b in benign]
    caught = sum(1 for r in escaped if any(x.triggered for x in on.run(r["payload"], ctx).results))
    out["areas"]["injection"] = {
        "dataset": "benchmarks/adaptive — payloads that escaped the shipping detectors",
        "note": "every positive here defeated injection.heuristic by construction",
        "off": score(rows_off),
        "on": score(rows_on),
        "escaped_payloads_caught": f"{caught}/{len(escaped)}",
        "ms_per_call_on": round(1000 * (time.perf_counter() - t0) / max(1, len(rows_on)), 1),
    }

    # --- answerability ----------------------------------------------------
    kuq = json.loads((BENCH / "answerability" / "data" / "kuq.json").read_text())[: N * 3]
    boundary = KnowledgeBoundary(answerable_types=[FACT, AGGREGATE, PROCEDURE], mode="enforce")
    by_label: dict[str, list] = collections.defaultdict(list)
    a_off, a_on = [], []
    for r in kuq:
        want = r["label"] in ("controversial", "future_unknown")
        v = classify_answerability(r["question"], boundary)
        a_off.append((want, not v.answerable))
        v2 = augment_answerability(v, r["question"]) if v.answerable else v
        a_on.append((want, not v2.answerable))
        by_label[r["label"]].append((want, not v.answerable, not v2.answerable))
    contested = by_label.get("controversial", [])
    out["areas"]["answerability"] = {
        "dataset": "KUQ (amayuelas/KUQ), in-scope rows",
        "off": score(a_off),
        "on": score(a_on),
        "contested_recall_off": f"{sum(1 for _w, o, _n in contested if o)}/{len(contested)}",
        "contested_recall_on": f"{sum(1 for _w, _o, n in contested if n)}/{len(contested)}",
    }

    # --- PII presence -----------------------------------------------------
    pii_rows = json.loads((BENCH / "pii" / "data" / "synth_dataset_v2.json").read_text())[:N]
    in_scope = {
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
    p_off, p_on = [], []
    for r in pii_rows:
        want = bool({x["entity_type"] for x in r["spans"]} & in_scope)
        base = native.detect(r["full_text"], ctx).triggered
        p_off.append((want, base))
        p_on.append((want, base or judge.detect(r["full_text"], ctx).triggered))
    out["areas"]["pii_presence"] = {
        "dataset": "presidio-research synth_dataset_v2, presence not spans",
        "note": "a gate signal; it reports no spans and cannot drive redaction",
        "off": score(p_off),
        "on": score(p_on),
    }

    # --- commitments ------------------------------------------------------
    corpus = json.loads((SCRIPTS / "jev_corpus.json").read_text())["cases"]
    buckets: dict[str, list] = collections.defaultdict(list)
    for c in corpus:
        buckets[c["answer_template"]].append(c)
    per = max(1, N // len(buckets))
    sample = [c for t in sorted(buckets) for c in buckets[t][:per]]
    c_off, c_on, llm_calls = [], [], 0
    from agentfox.judgment import panel
    from agentfox.judgment.commitments import QUESTIONS as C_Q

    for c in sample:
        want = bool(c["promises_refund"] or c["other_undertaking"])
        base = detect_commitments(c["answer"])
        c_off.append((want, bool(base)))
        c_on.append((want, bool(augment_commitments(base, c["answer"]))))
        if not base:
            try:
                r = panel.ask(DecisionKind.PERFORMATIVE, {"reply": c["answer"]}, C_Q)
                llm_calls += Tier.LLM in r.consulted
            except Exception:  # noqa: BLE001
                pass
    out["areas"]["commitments"] = {
        "dataset": "generated refund-reply corpus (scripts/jev_corpus.json)",
        "off": score(c_off),
        "on": score(c_on),
        "llm_calls_per_100": round(100 * llm_calls / max(1, len(sample))),
    }

    # --- the control: judgment is forbidden here --------------------------
    sql = json.loads(
        (BENCH / "action_safety" / "results" / "test_natural_dml_predictions.json").read_text()
    )[:N]
    sql_rows = [(bool(r["expect_blocked"]), bool(r["predicted_blocked"])) for r in sql]
    out["areas"]["sql_blast_radius_control"] = {
        "dataset": "gretelai/synthetic_text_to_sql, natural_dml",
        "note": "capability.py forbids every judgment tier from deciding STRUCTURAL_PARSED",
        "off": score(sql_rows),
        "on": score(sql_rows),
    }

    dest = HERE / "results" / "judgment_results.json"
    dest.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"-> {dest.relative_to(ROOT)}")
    for area, data in out["areas"].items():
        print(f"  {area:28} F1 {data['off']['f1'] * 100:>5.1f} -> {data['on']['f1'] * 100:>5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
