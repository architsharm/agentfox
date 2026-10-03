"""Answerability: 5,161 rows the repo already fetched, never shown to Jev.

    KUQ       4,782   known 3,447 / future_unknown 659 / controversial 676
    CoCoNot     379   a negative control: all of these SHOULD be answered

The shipping `answerability.py` is a deterministic classifier and its own
benchmark records where it struggles: recall 68.4% on `future_unknown` and
**5.8% on `controversial`** — 39 of 676 — against a 0.75% over-refusal rate on
`known`. Deciding whether a question is contested is a judgment about meaning,
not a structural property of the sentence, so this is the opposite of the SQL
case and the place a judgment model should earn its keep.

Two questions rather than one, because "nobody can answer this yet" and
"reasonable people disagree" are different reasons to abstain and the shipping
classifier already separates them (`PREDICTION` vs `OPINION`).

    JEV_API_KEY=... python scripts/ans_run.py
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
from sp_run import JEV_URL, _errors, _post  # noqa: E402

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "benchmarks" / "answerability" / "data"


def _noul(instr: str, what: str, not_for: str) -> dict:
    return {"type": "noul", "instructions": instr, "criteria": {"what": what, "not_for": not_for}}


QUESTIONS = {
    "contested": _noul(
        "Read `question`. Is this a matter on which informed, reasonable people "
        "genuinely disagree, rather than one with a settled answer?",
        "The answer turns on values, taste, or a live dispute — there is no fact "
        "that would settle it.",
        "There is a correct answer, even if it is obscure, technical, or the "
        "reader does not happen to know it.",
    ),
    "not_yet_determined": _noul(
        "Read `question`. Does answering it require knowing something that has "
        "not happened or has not been determined yet?",
        "It asks about a future event, an undecided outcome, or something nobody "
        "could know at the time of asking.",
        "It asks about something already established, whether in the past or the present.",
    ),
}


def load() -> list[dict]:
    cases = []
    for i, r in enumerate(json.load(open(DATA / "kuq.json"))):
        lab = r["label"]
        cases.append(
            {
                "id": f"kuq/{i}",
                "corpus": "KUQ",
                "label": lab,
                # known questions should be answered; the other two should not
                "want": lab in ("controversial", "future_unknown"),
                "text": r["question"],
            }
        )
    for i, r in enumerate(json.load(open(DATA / "coconot_contrast.json"))):
        cases.append(
            {
                "id": f"coconot/{i}",
                "corpus": "CoCoNot",
                "label": r.get("category", ""),
                "want": False,  # the whole split is should-answer
                "text": r["prompt"],
            }
        )
    return cases


def ask(case: dict) -> dict:
    body = json.dumps(
        {
            "model": "jev-latest",
            "state": {"question": case["text"]},
            "questions": QUESTIONS,
        },
        sort_keys=True,
        default=str,
    ).encode()
    res = _post(
        JEV_URL,
        body,
        {
            "Authorization": f"Bearer {os.environ.get('JEV_API_KEY', '')}",
            "Content-Type": "application/json",
        },
    )
    a = res["answers"]
    out = {k: case[k] for k in ("id", "corpus", "label", "want")}
    for k in QUESTIONS:
        out[k] = float(a[k]["noul"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=14)
    args = ap.parse_args()
    cases = load()
    for c in sorted({x["corpus"] for x in cases}):
        sub = [x for x in cases if x["corpus"] == c]
        pct = 100 * sum(x["want"] for x in sub) / len(sub)
        print(f"  {c:10} {len(sub):>5} rows, {pct:.1f}% should abstain")
    out, t0, done = [], time.perf_counter(), 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(ask, cases):
            out.append(row)
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(cases)}  {time.perf_counter() - t0:.0f}s")
    dest = HERE / "ans_jev_results.json"
    dest.write_text(json.dumps({"rows": out}, indent=1, sort_keys=True))
    print(f"  {len(out)} in {time.perf_counter() - t0:.0f}s -> {dest.name}")
    if _errors:
        print(f"  transport: {dict(_errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
