"""Recompute headline numbers of the WAITI 2026 paper from the released rows. Standard library only.

    python3 benchmarks/releases/waiti2026/verify.py

Checks recomputed values against the paper's generated macros (paper_numbers.tex, a copy of the
paper's numbers.tex) and against the per-dataset cells of aggregates/camera_ready.json (the file
the paper's appendix tables are generated from). Exits non-zero on any mismatch.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAC = dict(re.findall(r"\\newcommand\{\\(\w+)\}\{(.*)\}", (HERE / "paper_numbers.tex").read_text()))
CR = json.loads((HERE / "aggregates" / "camera_ready.json").read_text())
FAIL: list[str] = []
N_OK = 0


def load(name: str) -> list[dict]:
    p = HERE / "rows" / f"{name}.jsonl"
    raw = (
        p.read_bytes()
        if p.exists()
        else gzip.decompress((HERE / "rows" / f"{name}.jsonl.gz").read_bytes())
    )
    return [json.loads(line) for line in raw.decode().splitlines()]


def check(what: str, got, want) -> None:
    global N_OK
    if str(got) == str(want):
        N_OK += 1
    else:
        FAIL.append(f"{what}: recomputed {got!r}, paper {want!r}")


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}"


def counts(rows, flag):
    pos = [r for r in rows if r["label"]]
    neg = [r for r in rows if not r["label"]]
    return sum(1 for r in pos if flag(r)), len(pos), sum(1 for r in neg if flag(r)), len(neg)


def auroc(scores, labels) -> float:
    pairs = sorted(zip(scores, labels, strict=True), key=lambda t: t[0])
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    rank_sum, i = 0.0, 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        rank_sum += (i + 1 + j) / 2 * sum(1 for _, y in pairs[i:j] if y)
        i = j
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def youden(rows) -> float:
    """Lowest grid threshold maximising TPR - FPR (as in the paper's scripts)."""

    def j(t):
        tp, pos, fp, neg = counts(rows, lambda r: r["jev_score"] >= t)
        return tp / pos - fp / neg

    return max((i / 100 for i in range(1, 100)), key=j)


def cell(ds: str, tier: str, rows, flag) -> None:
    """Compare tp/pos/fp/neg with a per-dataset cell of camera_ready.json."""
    c = CR["per_dataset"][ds][tier]
    tp, pos, fp, neg = counts(rows, flag)
    check(
        f"{ds} | {tier} tp/pos/fp/neg", (tp, pos, fp, neg), (c["tp"], c["pos"], c["fp"], c["neg"])
    )


jev = lambda r: r["jev_flag"]  # noqa: E731

# ------------------------------------------------------------------ SQL (Sections 3.1, Table 6)
sql = load("gretel_text_to_sql")
tp, pos, fp, neg = counts(sql, lambda r: r["code_parser_flag"])
check("SQLn", f"{len(sql):,}", MAC["SQLn"])
check("SQLcodeRecall", f"{tp}/{pos}", MAC["SQLcodeRecall"])
check("SQLcodeFP", f"{fp}/{neg}", MAC["SQLcodeFP"])
tp, pos, fp, neg = counts(sql, jev)
check("SQLjevFP", fp, MAC["SQLjevFP"])
check("SQLjevFPRfull", pct(fp, neg), MAC["SQLjevFPRfull"])
check(
    "SQLjevAUROC",
    f"{auroc([r['jev_score'] for r in sql], [r['label'] for r in sql]):.3f}",
    MAC["SQLjevAUROC"],
)
dev = [r for r in sql if r["calib_split"] == "dev"]
test = [r for r in sql if r["calib_split"] == "test"]
t = youden(dev)
check("SQLjevThr", f"{t:.2f}", MAC["SQLjevThr"])
check("SQLjevFPRhalf", pct(*counts(test, jev)[2:]), MAC["SQLjevFPRhalf"])
check("SQLjevFPRbest", pct(*counts(test, lambda r: r["jev_score"] >= t)[2:]), MAC["SQLjevFPRbest"])
cell("gretel text-to-SQL", "Code (parser)", sql, lambda r: r["code_parser_flag"])
cell("gretel text-to-SQL", "Judgment model", sql, jev)
pb = load("payload_box")
cell("payload-box", "Code (parser)", pb, lambda r: r["code_parser_flag"])
cell("payload-box", "Judgment model", pb, jev)

# ------------------------------------------------------------------ AgentDojo (Section 3.2)
ad = [r for r in load("agentdojo") if r["in_paper_unique_calls"]]
tp, pos, fp, neg = counts(ad, lambda r: r["code_parser_flag"])
check("ADn", len(ad), MAC["ADn"])
check("ADpos", pos, MAC["ADpos"])
check("ADparserRecall", f"{tp}/{pos}", MAC["ADparserRecall"])
tp, pos, fp, neg = counts(ad, jev)
check("ADjevRecall", f"{tp}/{pos}", MAC["ADjevRecall"])
check("ADjevFP", f"{fp}/{neg}", MAC["ADjevFP"])
check(
    "ADjevAUROC",
    f"{auroc([r['jev_score'] for r in ad], [r['label'] for r in ad]):.3f}",
    MAC["ADjevAUROC"],
)
check(
    "Agent actions dev Youden threshold",
    youden([r for r in ad if r["calib_split"] == "dev"]),
    CR["thresholds"]["Agent actions"]["t_youden"],
)

# ------------------------------------------------------------------ injection (Sections 3.3, Tables 3 and 4)
NAMES = {
    "deepset": "deepset",
    "spml": "SPML",
    "yanismiraoui": "yanismiraoui",
    "trustairlab": "TrustAIRLab",
    "notinject": "NotInject",
}
inj = {k: load(k) for k in NAMES}
for k, ds in NAMES.items():
    cell(ds, "Code (patterns)", inj[k], lambda r: r["code_patterns_flag"])
    cell(ds, "PIGuard", inj[k], lambda r: r["piguard_flag"])
    cell(ds, "ProtectAI", inj[k], lambda r: r["protectai_flag"])
ni = inj["notinject"]
check("INJni", len(ni), MAC["INJni"])
check("Table 3 PIGuard FP NotInject", f"{sum(r['piguard_flag'] for r in ni)}/339", "39/339")
check("Table 3 ProtectAI FP NotInject", f"{sum(r['protectai_flag'] for r in ni)}/339", "148/339")
dp, tr = inj["deepset"], inj["trustairlab"]
check("OVdeepN", len(dp), MAC["OVdeepN"])
check("OVdeepIn", sum(r["in_piguard_train"] for r in dp), MAC["OVdeepIn"])
unseen = [r for r in dp if not r["in_piguard_train"]]
check("OVdeepUnseen", len(unseen), MAC["OVdeepUnseen"])
check("OVdeepPigRec", pct(*counts(unseen, lambda r: r["piguard_flag"])[:2]), MAC["OVdeepPigRec"])
check("OVdeepPaiRec", pct(*counts(unseen, lambda r: r["protectai_flag"])[:2]), MAC["OVdeepPaiRec"])
check("OVtrustIn", sum(r["in_piguard_train"] for r in tr), MAC["OVtrustIn"])
check("OVtrustInPos", sum(r["in_piguard_train"] and r["label"] for r in tr), MAC["OVtrustInPos"])
check("OVtrustJack", sum(r["in_jackhhao_train"] for r in tr), MAC["OVtrustJack"])
u = [r for r in tr if not r["in_piguard_train"]]
c = counts(u, lambda r: r["piguard_flag"])
check("OVtrustPigRec", pct(c[0], c[1]), MAC["OVtrustPigRec"])
check("OVtrustPigFPR", pct(c[2], c[3]), MAC["OVtrustPigFPR"])
u = [r for r in tr if not r["in_jackhhao_train"]]
c = counts(u, lambda r: r["protectai_flag"])
check("OVtrustPaiRec", pct(c[0], c[1]), MAC["OVtrustPaiRec"])
check("OVtrustPaiFPR", pct(c[2], c[3]), MAC["OVtrustPaiFPR"])
adapt = load("adaptive_attempts")
esc = [r for r in adapt if r["escaped_shipped_detectors"]]
check("INJpos (escapes)", len(esc), MAC["INJpos"])
check("Table 3 patterns recall on escapes", sum(r["code_shipped_flag"] for r in esc), 0)
check("OVescIn", sum(r["in_piguard_train"] for r in esc), MAC["OVescIn"])
check("INJseeds", len({r["seed_id"] for r in esc}), MAC["INJseeds"])

# ------------------------------------------------------------------ answerability (KUQ; CoCoNot rows not released)
kuq = load("kuq")
cell("KUQ", "Code (rules)", kuq, lambda r: r["code_rules_flag"])
cell("KUQ", "Judgment model", kuq, jev)

# ------------------------------------------------------------------ PII (Section 3.4)
pii = load("presidio") + load("gretel_pii") + load("tab")
check("PIIn", f"{len(pii):,}", MAC["PIIn"])
clean = [r for r in pii if not r["label"] and not r["has_any_labelled_span"]]
check("PIIclean", len(clean), MAC["PIIclean"])
check(
    "PIIdirty",
    sum(1 for r in pii if not r["label"] and r["has_any_labelled_span"]),
    MAC["PIIdirty"],
)
tab = [r for r in pii if r["in_paper_table"]]
c = counts(tab, lambda r: r["code_native_flag"])
check("PIIcodeRecall", pct(c[0], c[1]), MAC["PIIcodeRecall"])
check("PIIcodeFPR", pct(c[2], c[3]), MAC["PIIcodeFPR"])
c = counts(tab, jev)
check("PIIjevRecall", pct(c[0], c[1]), MAC["PIIjevRecall"])
check("PIIjevFPR", pct(c[2], c[3]), MAC["PIIjevFPR"])
check(
    "PIIjevAUROC",
    f"{auroc([r['jev_score'] for r in tab], [r['label'] for r in tab]):.3f}",
    MAC["PIIjevAUROC"],
)
t = youden([r for r in tab if r["calib_split"] == "dev"])
tt = [r for r in tab if r["calib_split"] == "test"]
check("PIIjevFPRhalf", pct(*counts(tt, jev)[2:]), MAC["PIIjevFPRhalf"])
check("PIIjevFPRbest", pct(*counts(tt, lambda r: r["jev_score"] >= t)[2:]), MAC["PIIjevFPRbest"])
for name, ds in (("presidio", "presidio"), ("gretel_pii", "gretel PII"), ("tab", "TAB")):
    rr = [r for r in tab if r["dataset"] == name]
    cell(ds, "Code (native)", rr, lambda r: r["code_native_flag"])
    cell(ds, "Judgment model", rr, jev)

# ------------------------------------------------------------------ entitlement
pl = load("privacylens")
check("ENTn", len(pl), MAC["ENTn"])
check("ENTjevRecall", pct(*counts(pl, jev)[:2]), MAC["ENTjevRecall"])

# ------------------------------------------------------------------ policy rules (Section 3.5)
sp = load("safepyramid")
cell("SafePyramid (3,000 conv.)", "Judgment model", sp, jev)
s6 = [r for r in sp if r["in_600_subset"]]
check("SPn", f"{len(s6):,}", MAC["SPn"])
cell("SafePyramid (600 conv.)", "Judgment model", s6, lambda r: r["jev_score_600_run"] >= 0.5)
cell("SafePyramid (600 conv.)", "LLM", s6, lambda r: r["llm_flag"])
for lv, tag in (("L0", "Lzero"), ("L2", "Ltwo")):
    rr = [r for r in s6 if r["level"] == lv]
    check(
        f"SPjev{tag}",
        pct(sum((r["jev_score_600_run"] >= 0.5) == r["label"] for r in rr), len(rr)),
        MAC[f"SPjev{tag}"],
    )
    check(
        f"SPllm{tag}",
        pct(sum(r["llm_flag"] == r["label"] for r in rr), len(rr)),
        MAC[f"SPllm{tag}"],
    )
check(
    "Policy rules dev Youden threshold (conversation-grouped split)",
    youden([r for r in sp if r["calib_split"] == "dev"]),
    CR["thresholds"]["Policy rules"]["t_youden"],
)

# ------------------------------------------------------------------ trajectories (ATBench corpora; R-Judge rows not released)
for name, ds in (
    ("atbench", "ATBench"),
    ("atbench500", "ATBench500"),
    ("atbench_claw", "ATBench-Claw"),
):
    rr = load(name)
    cell(ds, "Judgment model", rr, jev)
    for q in ("unsafe", "unconfirmed", "wrong_action"):
        check(
            f"{ds} AUROC {q}",
            round(auroc([r["jev_scores"][q] for r in rr], [r["label"] for r in rr]), 3),
            CR["per_dataset"][ds]["auroc_by_question"][q]["auroc"],
        )
check(
    "TRatfiveUnsafe",
    f"AUROC {auroc([r['jev_score'] for r in load('atbench500')], [r['label'] for r in load('atbench500')]):.3f}",
    MAC["TRatfiveUnsafe"],
)

# ------------------------------------------------------------------ commitments
cell("refund replies (in-house)", "Judgment model", load("refund_replies"), jev)

print(f"{N_OK} checks passed, {len(FAIL)} failed")
for f in FAIL:
    print("  MISMATCH", f)
sys.exit(1 if FAIL else 0)
