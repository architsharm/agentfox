"""Run three agent domains through R1/R2/R3 and keep every raw probability.

Booleans are thrown away here on purpose. A verdict at 0.52 and a verdict at
0.99 are the same `True` once thresholded, and the whole question of where the
threshold belongs — or whether a case should be answered at all rather than
escalated — cannot be asked afterwards if only the boolean was stored.

So: store the probabilities, sweep thresholds and cascade bands offline in
jev_domains_sweep.py, and spend the API budget once.

    JEV_API_KEY=... python scripts/jev_domains_run.py [--sample N]
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from jev_domains import DOMAINS  # noqa: E402

URL = "https://api.typesafe.ai/v1/systemone"
KEY = os.environ.get("JEV_API_KEY", "")
_errors: collections.Counter = collections.Counter()
_lock = threading.Lock()


def ask(state: dict, questions: dict, attempts: int = 5) -> dict:
    body = json.dumps(
        {"model": "jev-latest", "state": state, "questions": questions},
        sort_keys=True,
        default=str,
    ).encode()
    for i in range(attempts):
        req = urllib.request.Request(
            URL,
            data=body,
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())["answers"]
        except urllib.error.HTTPError as e:
            with _lock:
                _errors[f"HTTP {e.code}"] += 1
            if e.code in (429, 500, 502, 503, 504) and i < attempts - 1:
                time.sleep((2**i) * 0.5 + random.random())
                continue
            raise
        except Exception as e:  # noqa: BLE001
            with _lock:
                _errors[type(e).__name__] += 1
            if i < attempts - 1:
                time.sleep((2**i) * 0.5 + random.random())
                continue
            raise
    raise RuntimeError("unreachable")


def _p(ans: dict, key: str) -> float:
    a = ans[key]
    if isinstance(a, dict):
        return float(a.get("noul", a.get("value")))
    return float(a)


def run_case(domain, case: dict) -> dict:
    row = {
        "id": case["id"],
        "template": case["template"],
        "expect": case["expect"],
        "probs": {},
    }

    # R1 — the whole policy, one judgment
    st1 = {"agent_policy": domain.policy, **case["state"]}
    a1 = ask(st1, domain.r1_question)
    row["probs"]["r1_exceeds"] = _p(a1, "exceeds")

    # R2 — one prose judgment per policy condition, code predicates included
    a2 = ask(st1, domain.r2_questions)
    for k in domain.r2_questions:
        row["probs"][f"r2_{k}"] = _p(a2, k)

    # R3 — code owns its predicates; Jev sees only the meaning questions,
    # and only the state those questions need.
    authorised, reason = domain.authorise(case["facts"])
    row["code_authorised"] = authorised
    row["code_reason"] = reason
    a3 = ask(dict(case["state"]), domain.r3_questions)
    for k in domain.r3_questions:
        row["probs"][f"r3_{k}"] = _p(a3, k)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    if not KEY:
        print("JEV_API_KEY not set", file=sys.stderr)
        return 2

    out: dict = {}
    for domain in DOMAINS.values():
        cases = domain.cases
        if args.sample:
            cases = random.Random(7).sample(cases, min(args.sample, len(cases)))
        t0, done = time.perf_counter(), 0
        rows: list[dict] = []
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for row in pool.map(lambda c, d=domain: run_case(d, c), cases):
                rows.append(row)
                done += 1
                if done % 40 == 0:
                    print(f"  {domain.key:14} {done}/{len(cases)}  {time.perf_counter() - t0:.0f}s")
        out[domain.key] = {
            "code_predicates": domain.code_predicates,
            "semantic_predicates": domain.semantic_predicates,
            "r2_keys": list(domain.r2_questions),
            "r3_keys": list(domain.r3_questions),
            "rows": rows,
        }
        print(f"  {domain.key:14} {len(rows)} cases in {time.perf_counter() - t0:.0f}s")

    dest = pathlib.Path(__file__).parent / "jev_domains_results.json"
    dest.write_text(json.dumps(out, indent=1, sort_keys=True))
    print(f"\nraw probabilities -> {dest.name}")
    if _errors:
        print(f"  transport: {dict(_errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
