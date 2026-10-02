"""The configuration chosen on dev, scored once on held-out.

CHOSEN ON DEV, FROZEN BEFORE LOOKING AT HELD-OUT:

    code splits every rule by whether its text references another rule
        XREF = re.search(r"Rule\\s+\\d+", rule_text)
    flat rules  (62% of rows)   Jev >= 0.40  decides
    xref rules  (38% of rows)   Jev is not consulted; the rule is escalated

Why that split, and why it is not a reworded prompt. Three question-design
changes were tried on dev first and all failed: splitting commission from
omission, gating on a relevance question, and both together. The relevance
question is the instructive failure — it scores rules whose subject never came
up at 0.71, the same as real violations, so Jev cannot judge relevance for the
same reason it cannot judge the rule.

What worked is a property code can see for free. A rule that references another
rule is violated 7.7% of the time against 33.7% for a flat rule, and Jev's
precision on those is 24.8% — its positive signal there is close to worthless.
And the feature is not a proxy for difficulty: flat rules run 34.8% / 31.5% /
34.7% violated at L0 / L1 / L2, essentially constant. The whole level effect is
the changing *share* of cross-referencing rules, not harder judgment.

Parsimony, deliberately. `xref @ 0.9` scored F1 71.4 on dev and `xref never
flagged` scored 71.3 — indistinguishable — so the one-parameter version is the
one frozen. The single threshold sits on a broad plateau (0.35-0.45 within 0.3
F1 points), so it is not a grid artifact.

    python scripts/sp_final.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sp_corpus import load, parse_rules  # noqa: E402
from sp_improve import splits  # noqa: E402

HERE = pathlib.Path(__file__).parent
XREF = re.compile(r"Rule\s+\d+", re.I)
FLAT_THRESHOLD = 0.40


def build(ids: list[str]) -> list[dict]:
    cd = {c["id"]: c for c in load()}
    jev = {r["case_id"]: r for r in json.loads((HERE / "sp_jev_results.json").read_text())["rows"]}
    llm = {
        r["case_id"]: set(r["violated"])
        for r in json.loads((HERE / "sp_llmset_results.json").read_text())["rows"]
    }
    out = []
    for cid in ids:
        c = cd[cid]
        viol = set(c["ground_truth_violations"])
        rules = parse_rules(c["policy"])
        for n_s, p in jev[cid]["p"].items():
            n = int(n_s)
            out.append(
                {
                    "level": c["level"],
                    "domain": c["domain"],
                    "want": n in viol,
                    "jev": p,
                    "llm": 1.0 if n in llm[cid] else 0.0,
                    "xref": bool(XREF.search(rules[n])),
                }
            )
    return out


def tally(rows: list[dict], got: list[bool | None]) -> dict:
    tp = fp = fn = tn = esc = 0
    for r, g in zip(rows, got, strict=True):
        if g is None:
            esc += 1
            continue
        tp += g and r["want"]
        fp += g and not r["want"]
        fn += (not g) and r["want"]
        tn += (not g) and not r["want"]
    dec = tp + fp + fn + tn
    return {
        "acc": 100 * (tp + tn) / dec if dec else 0.0,
        "prec": 100 * tp / (tp + fp) if tp + fp else 0.0,
        "rec": 100 * tp / (tp + fn) if tp + fn else 0.0,
        "f1": 200 * tp / (2 * tp + fp + fn) if tp else 0.0,
        "breach": fn,
        "fblock": fp,
        "esc": esc,
        "n": len(rows),
    }


def row(label: str, rows: list[dict], got: list[bool | None]) -> None:
    s = tally(rows, got)
    e = f"{s['esc']:,} ({100 * s['esc'] / s['n']:.0f}%)" if s["esc"] else "-"
    print(
        f"  {label:42} {s['acc']:>6.1f}% {s['prec']:>9.1f}% {s['rec']:>7.1f}% "
        f"{s['f1']:>6.1f} {s['breach']:>7,} {s['fblock']:>8,} {e:>12}"
    )


# the frozen configuration, in two framings of what to do with an xref rule
def chosen_escalate(r: dict) -> bool | None:
    return None if r["xref"] else r["jev"] >= FLAT_THRESHOLD


def chosen_allow(r: dict) -> bool:
    return False if r["xref"] else r["jev"] >= FLAT_THRESHOLD


def main() -> int:
    dev, held = splits()
    hdr = (
        f"  {'configuration':42} {'acc':>7} {'precision':>10} {'recall':>8} "
        f"{'F1':>6} {'breach':>7} {'fblock':>8} {'escalated':>12}"
    )
    for name, ids in (("DEV (used for all tuning)", dev), ("HELD-OUT (scored once)", held)):
        R = build(ids)
        print("=" * 118)
        print(f"{name} — {len(R):,} rule judgments, {len(ids)} cases")
        print("=" * 118)
        print(hdr)
        print("-" * 118)
        row("always allow", R, [False] * len(R))
        row("baseline: jev @ 0.5 everywhere", R, [r["jev"] >= 0.5 for r in R])
        row("baseline: jev @ 0.8 everywhere", R, [r["jev"] >= 0.8 for r in R])
        row("baseline: LLM judge everywhere", R, [r["llm"] >= 0.5 for r in R])
        row(
            "baseline: both must agree, jev @ 0.8",
            R,
            [r["jev"] >= 0.8 and r["llm"] >= 0.5 for r in R],
        )
        row("CHOSEN: flat @ 0.40, xref -> allow", R, [chosen_allow(r) for r in R])
        row("CHOSEN: flat @ 0.40, xref -> escalate", R, [chosen_escalate(r) for r in R])
        print()

    # does it hold in every stratum of held-out, or only on average?
    R = build(held)
    print("=" * 118)
    print("HELD-OUT, broken down — the chosen configuration (xref escalated)")
    print("=" * 118)
    for key in ("level", "domain"):
        print(
            f"\n  {'by ' + key:28} {'n':>7} {'acc':>8} {'prec':>8} "
            f"{'rec':>7} {'F1':>7} {'escal':>7}"
        )
        for k in sorted({r[key] for r in R}):
            sub = [r for r in R if r[key] == k]
            s = tally(sub, [chosen_escalate(r) for r in sub])
            print(
                f"  {k:28} {len(sub):>7,} {s['acc']:>7.1f}% {s['prec']:>7.1f}% "
                f"{s['rec']:>6.1f}% {s['f1']:>7.1f} {100 * s['esc'] / s['n']:>6.0f}%"
            )

    print("\n" + "=" * 118)
    print("Cost: the chosen configuration never asks Jev about a cross-referencing rule")
    print("=" * 118)
    asked = sum(1 for r in R if not r["xref"])
    print(f"  questions asked: {asked:,} of {len(R):,}  ({100 * asked / len(R):.0f}%)")
    print(f"  Jev cost for 1,000 judgments: ${1000 * 0.0000065 * asked / len(R):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
