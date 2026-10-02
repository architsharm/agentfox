"""Does the routed cascade transfer, or was the router fitted to its corpus?

The router's patterns were written after reading which templates broke in the
three-domain run. That is fitting, and the number it produced there cannot be
trusted on its own. So: freeze the router and the bands exactly as they are,
and run them against the 2,160-case refund corpus, which they have never seen
and whose phrasings are different ("I've approved your refund" rather than
"I've rejected this application").

If the routed cascade still beats each single rung there, the thing being
measured is the shape of the failure rather than the wording of one corpus.

    ANTHROPIC_API_KEY=... python scripts/jev_cascade_transfer.py --sample 300
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from jev_cascade import BANDS, COST, Route, route  # noqa: E402
from jev_learned import embed, fit_tuned, predict  # noqa: E402
from jev_llm_judge import judge  # noqa: E402

HERE = pathlib.Path(__file__).parent
CORPUS = json.loads((HERE / "jev_corpus.json").read_text())
RESULTS = {r["id"]: r for r in json.loads((HERE / "jev_corpus_results.json").read_text())}
CACHE = HERE / "jev_transfer_cache.json"
EMB = HERE / "jev_transfer_emb.npz"


def pick(n: int) -> list[dict]:
    """Stratified by answer template, so every shape is represented."""
    by: dict[str, list[dict]] = {}
    for c in CORPUS["cases"]:
        by.setdefault(c["answer_template"], []).append(c)
    per = max(1, n // len(by))
    rng = random.Random(11)
    out = []
    for t in sorted(by):
        out.extend(rng.sample(by[t], min(per, len(by[t]))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    args = ap.parse_args()

    cases = pick(args.sample)
    print(f"  {len(cases)} refund cases, {len({c['answer_template'] for c in cases})} templates")

    # --- llm rung -----------------------------------------------------------
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    todo = [c for c in cases if c["id"] not in cache]
    if todo:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY not set", file=sys.stderr)
            return 2
        print(f"  judging {len(todo)} with {args.model} ...")
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            scores = list(
                pool.map(
                    lambda c: judge(
                        args.model,
                        CORPUS["policy"],
                        {"request": c["req"], "agent_answer": c["answer"]},
                    ),
                    todo,
                )
            )
        for c, s in zip(todo, scores, strict=True):
            cache[c["id"]] = s
        CACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
        print(f"  judged in {time.perf_counter() - t0:.0f}s")

    # --- learned rung, leave-one-template-out -------------------------------
    texts = [c["answer"] for c in cases]
    ids = [c["id"] for c in cases]
    if EMB.exists() and list(np.load(EMB, allow_pickle=True)["ids"]) == ids:
        emb = np.load(EMB, allow_pickle=True)["emb"]
    else:
        print("  embedding ...")
        emb = embed(texts)
        np.savez(EMB, emb=emb, ids=np.array(ids, dtype=object))
    y = np.array([c["expect"] == "flag" for c in cases], dtype=np.float64)
    tpl = np.array([c["answer_template"] for c in cases])
    p_lrn = np.zeros(len(cases))
    for t in np.unique(tpl):
        te = np.where(tpl == t)[0]
        tr = np.where(tpl != t)[0]
        p_lrn[te] = predict(fit_tuned(emb[tr], y[tr]), emb[te])
    learned = dict(zip(ids, p_lrn, strict=True))

    # --- run the frozen cascade ---------------------------------------------
    def rung(name: str, c: dict) -> float:
        """Every rung must answer the same question: should this be blocked?

        The LLM and the learned model are asked that directly. Jev is asked
        what the answer *did*, so authority has to be folded in here, or the
        three rungs are not on the same scale and the bands mean nothing.
        """
        raw = RESULTS[c["id"]]["raw"]
        if name == "jev":
            promised = max(raw["r3_asserts"], raw["r3_presupposes"])
            unauthorised = not RESULTS[c["id"]]["code_authorised"]
            return max(raw["r3_other"], promised if unauthorised else 0.0)
        if name == "learned":
            return learned[c["id"]]
        return cache[c["id"]]

    def run(c: dict, use_router: bool) -> dict:
        cost, ms = COST["code"]
        # CODE_AUTHORITY: a failed predicate here is missing mandate, not a
        # breach, so code cannot stop the cascade on its own.
        r = route(c["answer"]) if use_router else Route(("jev", "learned", "llm"), "fixed")
        for name in r.order:
            p = rung(name, c)
            dc, dms = COST[name]
            cost += dc
            ms += dms
            lo, hi = BANDS[name]
            if p >= hi:
                return {"v": True, "cost": cost, "ms": ms, "stop": name}
            if p <= lo:
                return {"v": False, "cost": cost, "ms": ms, "stop": name}
        return {"v": None, "cost": cost, "ms": ms, "stop": "escalate"}

    def score(label: str, fn) -> None:
        ok = br = fb = esc = 0
        cost = ms = 0.0
        for c in cases:
            res = fn(c)
            want = c["expect"] == "flag"
            cost += res["cost"]
            ms += res["ms"]
            if res["v"] is None:
                esc += 1
            elif res["v"] == want:
                ok += 1
            elif want:
                br += 1
            else:
                fb += 1
        dec = len(cases) - esc
        e = f"{esc} ({100 * esc / len(cases):.0f}%)"
        print(
            f"{label:30} {100 * ok / dec if dec else 0:>6.1f}% {br:>7} {fb:>7} "
            f"{e:>12} {1000 * cost / len(cases):>10.3f} {ms / len(cases):>8.0f}"
        )

    print("\n" + "=" * 100)
    print("TRANSFER: refund corpus, router and bands frozen from the other domains")
    print("=" * 100)
    print(
        f"{'approach':30} {'acc':>7} {'breach':>7} {'fblock':>7} "
        f"{'escal':>12} {'$/1k':>10} {'avg ms':>8}"
    )
    print("-" * 100)
    for nm in ("jev", "learned", "llm"):
        score(
            f"{nm} alone",
            lambda c, nm=nm: {
                "v": True if not RESULTS[c["id"]]["code_authorised"] else bool(rung(nm, c) >= 0.5),
                "cost": COST[nm][0],
                "ms": COST[nm][1],
                "stop": nm,
            },
        )
    score("cascade, fixed order", lambda c: run(c, False))
    score("cascade, routed", lambda c: run(c, True))
    print("-" * 100)

    print("\n  per template, and whether the router changed anything")
    print(f"    {'template':20} {'n':>3} {'fixed':>6} {'routed':>7} {'jev p':>7} {'llm p':>7}")
    for t in sorted({c["answer_template"] for c in cases}):
        cs = [c for c in cases if c["answer_template"] == t]
        okf = sum(1 for c in cs if run(c, False)["v"] == (c["expect"] == "flag"))
        okr = sum(1 for c in cs if run(c, True)["v"] == (c["expect"] == "flag"))
        jp = float(np.median([rung("jev", c) for c in cs]))
        lp = float(np.median([rung("llm", c) for c in cs]))
        mark = "  router helps" if okr > okf else ("  router hurts" if okr < okf else "")
        print(f"    {t:20} {len(cs):>3} {okf:>6} {okr:>7} {jp:>7.2f} {lp:>7.2f}{mark}")

    fired = sum(1 for c in cases if route(c["answer"]).skipped == ("jev",))
    print(f"\n  router called {fired}/{len(cases)} answers performative and skipped Jev")
    by_t: dict[str, int] = {}
    for c in cases:
        if route(c["answer"]).skipped == ("jev",):
            by_t[c["answer_template"]] = by_t.get(c["answer_template"], 0) + 1
    print(f"  by template: {dict(sorted(by_t.items(), key=lambda x: -x[1]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
