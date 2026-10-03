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
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

HERE = pathlib.Path(__file__).parent
BENCH = ROOT / "benchmarks"
SCRIPTS = ROOT / "scripts"
N = int(os.environ.get("JUDGMENT_BENCH_N", "500"))
#: Every judgment is a network round trip, so the runner is I/O bound and
#: sequential execution is what caps N, not cost — at 350ms a call, 2,000
#: decisions is twenty minutes of waiting and a few cents of spend.
WORKERS = int(os.environ.get("JUDGMENT_BENCH_WORKERS", "12"))


def pmap(fn, items):
    """Thread-pooled map that preserves order."""
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return list(pool.map(fn, items))


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
    s_tiers = list(s.judgment_tiers)
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
    # NotInject: 339 purpose-built *over-defense* negatives — benign text that
    # contains injection-adjacent vocabulary ("can I ignore this warning?"),
    # across English and other languages. An earlier version of this runner
    # used three hand-written sentences repeated 55 times, which meant the
    # false-positive rate was one sentence's verdict multiplied by 55 and the
    # F1 rested on three distinct examples.
    notinject = json.loads((BENCH / "data_generalization" / "notinject.json").read_text())
    # all 339, not N of them: the over-defense set is the whole point here
    benign = [r["text"] for r in notinject if not r.get("label")]

    off = DetectorPipeline(detectors=[InjectionHeuristicDetector()])
    on = DetectorPipeline(detectors=[InjectionHeuristicDetector(), InjectionJudgmentDetector()])
    texts = [r["payload"] for r in escaped] + benign
    wants = [True] * len(escaped) + [False] * len(benign)

    fired_off = pmap(lambda t: any(x.triggered for x in off.run(t, ctx).results), texts)
    t0 = time.perf_counter()
    # One judged pass. The previous version made a third, separate pass to
    # count what was caught, and because Jev is not deterministic the two
    # disagreed — 160 by the recall column and 161 by the counter, with the
    # published claim quoting the counter.
    fired_on = pmap(lambda t: any(x.triggered for x in on.run(t, ctx).results), texts)
    elapsed = time.perf_counter() - t0

    rows_off = list(zip(wants, fired_off, strict=True))
    rows_on = list(zip(wants, fired_on, strict=True))
    caught = sum(1 for w, f in rows_on if w and f)
    out["areas"]["injection"] = {
        "dataset": "adaptive escaped payloads vs NotInject over-defense negatives",
        "note": "every positive defeated injection.heuristic by construction",
        "negatives": f"NotInject, {len(benign)} distinct rows",
        "off": score(rows_off),
        "on": score(rows_on),
        "escaped_payloads_caught": f"{caught}/{len(escaped)}",
        "ms_per_call_on": round(1000 * elapsed / max(1, len(rows_on)), 1),
    }

    # --- answerability ----------------------------------------------------
    # Every row. kuq.json is sorted by label — all 1,335 positives first, then
    # 3,447 known — so taking the first N*3 silently meant "every positive plus
    # the first 165 of the negatives", and those 165 are a contiguous,
    # unrepresentative block. The measured over-refusal rate on the full known
    # set is 5.37%; seeing 0 in 165 of them has probability about 1 in 9,000,
    # which is the tell that the slice was not a sample.
    kuq = json.loads((BENCH / "answerability" / "data" / "kuq.json").read_text())
    boundary = KnowledgeBoundary(answerable_types=[FACT, AGGREGATE, PROCEDURE], mode="enforce")
    by_label: dict[str, list] = collections.defaultdict(list)

    def one_answerability(r):
        want = r["label"] in ("controversial", "future_unknown")
        v = classify_answerability(r["question"], boundary)
        v2 = augment_answerability(v, r["question"]) if v.answerable else v
        return r["label"], want, not v.answerable, not v2.answerable

    a_off, a_on = [], []
    for label, want, off_abstain, on_abstain in pmap(one_answerability, kuq):
        a_off.append((want, off_abstain))
        a_on.append((want, on_abstain))
        by_label[label].append((want, off_abstain, on_abstain))
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

    def one_pii(r):
        want = bool({x["entity_type"] for x in r["spans"]} & in_scope)
        base = native.detect(r["full_text"], ctx).triggered
        return want, base, base or judge.detect(r["full_text"], ctx).triggered

    p_off, p_on = [], []
    for want, base, both in pmap(one_pii, pii_rows):
        p_off.append((want, base))
        p_on.append((want, both))
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
    from agentfox.judgment import panel
    from agentfox.judgment.commitments import QUESTIONS as C_Q

    def one_commitment(c):
        want = bool(c["promises_refund"] or c["other_undertaking"])
        base = detect_commitments(c["answer"])
        if base:
            # The deterministic layer fired; no tier is consulted at all, which
            # is the cheapest path and the one the cascade is built around.
            return want, True, True, False
        used_llm = False
        try:
            r = panel.ask(DecisionKind.PERFORMATIVE, {"reply": c["answer"]}, C_Q)
            used_llm = Tier.LLM in r.consulted
        except Exception:  # noqa: BLE001
            pass
        return want, False, bool(augment_commitments(base, c["answer"])), used_llm

    c_off, c_on, llm_calls = [], [], 0
    for want, off_hit, on_hit, used in pmap(one_commitment, sample):
        c_off.append((want, off_hit))
        c_on.append((want, on_hit))
        llm_calls += used
    out["areas"]["commitments"] = {
        "dataset": "generated refund-reply corpus (scripts/jev_corpus.json)",
        "off": score(c_off),
        "on": score(c_on),
        "llm_calls_per_100": round(100 * llm_calls / max(1, len(sample))),
    }

    # --- the control: judgment must not be able to touch this -------------
    # The previous version read one saved predictions file and reported it as
    # both the "off" and the "on" column. That is not a control: it never ran
    # the judgment tier, so it could not have detected a routing failure, and
    # the file it used has only 8 positives in 365 rows.
    #
    # This one calls analyse_sql live with every judgment tier enabled, over a
    # balanced set, and checks two independent things: that the verdicts are
    # byte-identical to code alone, and that the router itself refuses to seat
    # any judgment tier for STRUCTURAL_PARSED.
    from agentfox.guardrails.actions import analyse_sql
    from agentfox.judgment.capability import CapabilityRouter

    sql_cases = []
    for split in ("test_natural_dml", "test_adversarial_tautology", "test_natural_ddl"):
        path = BENCH / "action_safety" / "results" / f"{split}_predictions.json"
        sql_cases += json.loads(path.read_text())
    sql_rows_on = pmap(
        lambda c: (
            bool(c["expect_blocked"]),
            bool(analyse_sql(c["sql"], dialect="postgres").blocked),
        ),
        sql_cases,
    )
    # the stored verdicts, produced before any of this existed
    sql_rows_off = [(bool(c["expect_blocked"]), bool(c["predicted_blocked"])) for c in sql_cases]
    identical = sql_rows_on == sql_rows_off

    plan = CapabilityRouter.from_settings().plan(DecisionKind.STRUCTURAL_PARSED)
    seated = [t.value for t in plan.deciders]
    out["areas"]["sql_blast_radius_control"] = {
        "dataset": "gretelai/synthetic_text_to_sql — natural_dml + adversarial_tautology + natural_ddl",
        "note": "analyse_sql re-run live with every judgment tier enabled",
        "positives": sum(1 for w, _ in sql_rows_off if w),
        "verdicts_identical_to_code_alone": identical,
        "tiers_enabled": list(s_tiers),
        "tiers_seated_for_this_kind": seated,
        "judgment_tiers_excluded": {
            t.value: plan.why(t) for t in plan.excluded_tiers() if t.value != "deterministic"
        },
        "off": score(sql_rows_off),
        "on": score(sql_rows_on),
    }

    dest = HERE / "results" / "judgment_results.json"
    dest.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(f"-> {dest.relative_to(ROOT)}")
    for area, data in out["areas"].items():
        print(f"  {area:28} F1 {data['off']['f1'] * 100:>5.1f} -> {data['on']['f1'] * 100:>5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
