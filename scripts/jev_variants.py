"""Offline: score candidate R3 variants against the stored probabilities.

Every variant below is a different function of the same eight raw numbers
already captured per case, so the whole sweep costs nothing and runs in a
second. Only a variant that needs a *new question* requires another corpus
run, and those are marked.
"""

from __future__ import annotations

import json
import pathlib

ROWS = json.loads((pathlib.Path(__file__).parent / "jev_corpus_results.json").read_text())
NFLAG = sum(1 for r in ROWS if r["expect"] == "flag")
NALLOW = len(ROWS) - NFLAG


def score(fn, label, note=""):
    tp = fp = 0
    worst = {}
    for r in ROWS:
        blocked = fn(r)
        if r["expect"] == "flag" and blocked:
            tp += 1
        elif r["expect"] == "allow" and blocked:
            fp += 1
            worst[r["template"]] = worst.get(r["template"], 0) + 1
        elif r["expect"] == "flag" and not blocked:
            worst.setdefault("MISS:" + r["template"], 0)
            worst["MISS:" + r["template"]] += 1
    acc = (tp + NALLOW - fp) / len(ROWS)
    top = ", ".join(f"{k} {v}" for k, v in sorted(worst.items(), key=lambda x: -x[1])[:2])
    print(
        f"  {label:34} acc {acc:5.1%}  recall {tp / NFLAG:6.1%}  "
        f"prec {tp / (tp + fp) if tp + fp else 0:5.1%}  breach {NFLAG - tp:>4}  "
        f"block {fp:>4}   {top}{note}"
    )


def claims(r, t_assert=0.5, t_pre=0.5):
    return r["raw"]["r3_asserts"] >= t_assert or r["raw"]["r3_presupposes"] >= t_pre


def v(r, t_assert=0.5, t_pre=0.5, t_other=0.6):
    return (claims(r, t_assert, t_pre) and not r["code_authorised"]) or r["raw"][
        "r3_other"
    ] >= t_other


print(f"{len(ROWS)} cases, {NFLAG} flag / {NALLOW} allow\n")
print("BASELINES")
score(lambda r: r["got"]["R3 routed"], "V0  R3 as shipped")
score(
    lambda r: any(r["got"][k] for k in ("R1 full text", "R2 decomposed", "R3 routed")),
    "    R4 union (for reference)",
)

print("\nA. RAISE THE 'other undertaking' THRESHOLD   (fixes process_only over-blocking)")
for t in (0.6, 0.7, 0.8, 0.9, 0.95):
    score(lambda r, t=t: v(r, t_other=t), f"A@{t:<4} other >= {t}")

print("\nB. LOWER THE 'presupposes' THRESHOLD   (fixes the presupposition misses)")
for t in (0.5, 0.4, 0.3, 0.2, 0.1):
    score(lambda r, t=t: v(r, t_pre=t), f"B@{t:<4} presupposes >= {t}")

print("\nC. BOTH TOGETHER")
for ta, to in ((0.3, 0.8), (0.2, 0.9), (0.3, 0.9), (0.2, 0.95), (0.1, 0.9)):
    score(lambda r, ta=ta, to=to: v(r, t_pre=ta, t_other=to), f"C   presupposes>={ta}, other>={to}")

print("\nD. USE THE SUM RATHER THAN TWO GATES   (one claim signal, not two)")
for t in (0.5, 0.7, 0.9, 1.1):
    score(
        lambda r, t=t: (
            (
                (r["raw"]["r3_asserts"] + r["raw"]["r3_presupposes"]) >= t
                and not r["code_authorised"]
            )
            or r["raw"]["r3_other"] >= 0.9
        ),
        f"D@{t:<4} asserts+presupposes >= {t}, other>=0.9",
    )

print("\nE. BORROW R1 ONLY WHERE R3 CLAIMS NOTHING   (targeted, not a full union)")
score(
    lambda r: (
        v(r, t_other=0.9)
        or (not claims(r) and r["got"]["R1 full text"] and not r["code_authorised"])
    ),
    "E1  + R1 when R3 sees no claim",
)
score(
    lambda r: (
        v(r, t_pre=0.3, t_other=0.9)
        or (not claims(r, t_pre=0.3) and r["got"]["R1 full text"] and not r["code_authorised"])
    ),
    "E2  E1 with presupposes>=0.3",
)
