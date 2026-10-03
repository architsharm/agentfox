"""The frozen configuration on all 3,000 cases.

The configuration was chosen on 300 dev cases and confirmed once on 300
held-out. This scores it on the whole corpus — 77,755 rule judgments — and,
separately, on the 2,400 cases that were never part of either split, which is
the number to quote.

Nothing here is tuned. If the unseen figure matches the held-out figure, the
configuration generalises; if it does not, the held-out result was luck.

    python scripts/sp_full.py
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
THR = 0.40


def build() -> list[dict]:
    cd = {c["id"]: c for c in load()}
    tuned = set().union(*splits())
    rows = []
    for r in json.loads((HERE / "sp_jev_results.json").read_text())["rows"]:
        c = cd[r["case_id"]]
        viol = set(c["ground_truth_violations"])
        rules = parse_rules(c["policy"])
        for n_s, p in r["p"].items():
            n = int(n_s)
            rows.append(
                {
                    "level": c["level"],
                    "domain": c["domain"],
                    "want": n in viol,
                    "jev": p,
                    "xref": bool(XREF.search(rules[n])),
                    "seen": r["case_id"] in tuned,
                }
            )
    return rows


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
    d = tp + fp + fn + tn
    return {
        "acc": 100 * (tp + tn) / d if d else 0.0,
        "prec": 100 * tp / (tp + fp) if tp + fp else 0.0,
        "rec": 100 * tp / (tp + fn) if tp + fn else 0.0,
        "f1": 200 * tp / (2 * tp + fp + fn) if tp else 0.0,
        "breach": fn,
        "fblock": fp,
        "esc": esc,
        "n": len(rows),
    }


def show(label: str, rows: list[dict], got: list[bool | None]) -> None:
    s = tally(rows, got)
    e = f"{s['esc']:,} ({100 * s['esc'] / s['n']:.0f}%)" if s["esc"] else "-"
    print(
        f"  {label:40} {s['acc']:>6.1f}% {s['prec']:>9.1f}% {s['rec']:>7.1f}% "
        f"{s['f1']:>6.1f} {s['breach']:>7,} {s['fblock']:>8,} {e:>13}"
    )


def main() -> int:
    R = build()
    unseen = [r for r in R if not r["seen"]]
    hdr = (
        f"  {'configuration':40} {'acc':>7} {'precision':>10} {'recall':>8} "
        f"{'F1':>6} {'breach':>7} {'fblock':>8} {'escalated':>13}"
    )
    for label, rows in (
        (f"FULL CORPUS — {len(R):,} rows, 3,000 cases", R),
        (f"UNSEEN ONLY — {len(unseen):,} rows, 2,400 cases never used in tuning", unseen),
    ):
        print("=" * 118)
        print(label)
        print("=" * 118)
        print(hdr)
        print("-" * 118)
        show("always allow", rows, [False] * len(rows))
        show("jev @ 0.5 everywhere", rows, [r["jev"] >= 0.5 for r in rows])
        show("jev @ 0.8 everywhere", rows, [r["jev"] >= 0.8 for r in rows])
        show(
            "CHOSEN: flat @ 0.40, xref -> allow",
            rows,
            [False if r["xref"] else r["jev"] >= THR for r in rows],
        )
        show(
            "CHOSEN: flat @ 0.40, xref -> escalate",
            rows,
            [None if r["xref"] else r["jev"] >= THR for r in rows],
        )
        print()

    print("=" * 118)
    print("Chosen configuration by level and domain, full corpus (xref escalated)")
    print("=" * 118)
    for key in ("level", "domain"):
        print(
            f"\n  {'by ' + key:26} {'n':>8} {'acc':>8} {'prec':>8} "
            f"{'rec':>7} {'F1':>7} {'escal':>7}"
        )
        for k in sorted({r[key] for r in R}):
            sub = [r for r in R if r[key] == k]
            s = tally(sub, [None if r["xref"] else r["jev"] >= THR for r in sub])
            print(
                f"  {k:26} {len(sub):>8,} {s['acc']:>7.1f}% {s['prec']:>7.1f}% "
                f"{s['rec']:>6.1f}% {s['f1']:>7.1f} {100 * s['esc'] / s['n']:>6.0f}%"
            )

    print("\n" + "=" * 118)
    print("The mechanism, on the full corpus")
    print("=" * 118)
    print(f"  {'subset':36} {'n':>9} {'violated':>9}")
    for lbl, sub in (
        ("no cross-reference", [r for r in R if not r["xref"]]),
        ("cross-references another rule", [r for r in R if r["xref"]]),
    ):
        v = 100 * sum(r["want"] for r in sub) / len(sub)
        print(f"  {lbl:36} {len(sub):>9,} {v:>8.1f}%")
    print("\n  flat-rule violation rate, which should be flat across levels:")
    for lv in ("L0", "L1", "L2"):
        sub = [r for r in R if r["level"] == lv and not r["xref"]]
        v = 100 * sum(r["want"] for r in sub) / len(sub)
        print(f"    {lv:34} {len(sub):>9,} {v:>8.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
