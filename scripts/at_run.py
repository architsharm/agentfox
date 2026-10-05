"""ATBench, ATBench500 and ATBench-Claw: 2,000 more agent trajectories.

R-Judge gave 571 labelled trajectories, which is thin for the agentic claim.
These three add 2,000 more, all Apache-2.0, all labelled by someone else, all
roughly balanced:

    ATBench        1,000   497 unsafe / 503 safe   rich tool definitions
    ATBench500       500   250 / 250               disjoint from ATBench
    ATBench-Claw     500   296 unsafe / 204 safe   Claude-Code session logs

The three carry a taxonomy worth exploiting rather than averaging over:
`risk_source` separates benign, inherent agent failure, indirect prompt
injection and **tool_description_injection** — where the attack is in the tool's
own description, not the conversation. That case is unjudgeable unless the tool
definitions are in the state, so `tool_used` is included.

Claw matters for a different reason: its trajectories are Claude Code sessions
carrying untrusted skill context, which is the surface agentfox actually hooks.

**The questions are frozen from rj_run.py.** Nothing is retuned here. The point
is to find out whether the R-Judge operating point transfers to corpora it was
not chosen on, so tuning against these would destroy the only thing being
measured.

    JEV_API_KEY=... python scripts/at_run.py
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
from jev_data import data_dir  # noqa: E402
from rj_run import QUESTIONS  # noqa: E402  - frozen, do not edit here
from sp_run import JEV_URL, _errors, _post  # noqa: E402

HERE = pathlib.Path(__file__).parent
DATA = data_dir()
#: Jev's own guidance is that accuracy falls as unrelated state grows, and the
#: longest trajectory here is 357k characters. Keep the tail, which is where an
#: unsafe act usually lands.
MAX_CHARS = 20_000


def _msgs(seq) -> list[str]:
    out = []
    for item in seq if isinstance(seq, list) else [seq]:
        if isinstance(item, list):
            out += _msgs(item)
            continue
        if not isinstance(item, dict):
            continue
        role = item.get("role", "?")
        if item.get("thought"):
            out.append(f"{role} (thinking): {item['thought']}")
        if item.get("action"):
            out.append(f"{role} (action): {item['action']}")
        c = item.get("content")
        if isinstance(c, str) and c:
            out.append(f"{role}: {c}")
        elif isinstance(c, list):
            for blk in c:
                if isinstance(blk, dict) and blk.get("text"):
                    out.append(f"{role}: {blk['text']}")
                elif isinstance(blk, dict):
                    out.append(f"{role}: {json.dumps(blk)[:2000]}")
    return out


def _claw_events(events: list) -> list[str]:
    out = []
    for e in events:
        if e.get("type") == "message" and isinstance(e.get("message"), dict):
            out += _msgs(e["message"])
        elif e.get("type"):
            out.append(
                f"{e['type']}: {json.dumps({k: v for k, v in e.items() if k != 'type'})[:1500]}"
            )
    return out


def tail(text: str) -> str:
    return text if len(text) <= MAX_CHARS else "...[earlier turns omitted]...\n" + text[-MAX_CHARS:]


def load_all() -> list[dict]:
    cases: list[dict] = []
    a = json.load(open(DATA / "at_ATBench_test.json"))
    for r in a:
        cases.append(
            {
                "id": f"atbench/{r['id']}",
                "corpus": "ATBench",
                "want": bool(r["label"]),
                "risk_source": r.get("risk_source", ""),
                "tools": json.dumps(r.get("tool_used", ""))[:6000],
                "transcript": tail("\n".join(_msgs(r["contents"]))),
            }
        )
    b = json.load(open(DATA / "at_ATBench500_test.json"))
    for i, r in enumerate(b):
        cases.append(
            {
                "id": f"atbench500/{r.get('conv_id', i)}",
                "corpus": "ATBench500",
                "want": bool(r["label"]),
                "risk_source": r.get("risk_source", ""),
                "tools": json.dumps(r.get("tool_used", ""))[:6000],
                "transcript": tail("\n".join(_msgs(r["content"]))),
            }
        )
    c = json.load(open(DATA / "at_claw.json"))
    for i, r in enumerate(c):
        lab = r.get("labels") or {}
        cases.append(
            {
                "id": f"claw/{i}",
                "corpus": "ATBench-Claw",
                # is_safe True means safe, so the flag is its negation
                "want": not bool(lab.get("is_safe")),
                "risk_source": lab.get("risk_source", ""),
                "tools": "",
                "transcript": tail(
                    "\n".join(_claw_events((r["trajectory"] or {}).get("events", [])))
                ),
            }
        )
    return cases


def ask(case: dict) -> dict:
    state = {
        "agent_profile": "An AI agent acting for a user with the tools shown.",
        "transcript": case["transcript"],
    }
    if case["tools"]:
        state["tool_definitions"] = case["tools"]
    body = json.dumps(
        {"model": "jev-latest", "state": state, "questions": QUESTIONS},
        sort_keys=True,
        default=str,
    ).encode()
    t0 = time.perf_counter()
    res = _post(
        JEV_URL,
        body,
        {
            "Authorization": f"Bearer {os.environ.get('JEV_API_KEY', '')}",
            "Content-Type": "application/json",
        },
    )
    a = res["answers"]
    return {
        "id": case["id"],
        "corpus": case["corpus"],
        "want": case["want"],
        "risk_source": case["risk_source"],
        "ms": (time.perf_counter() - t0) * 1000,
        "unsafe": float(a["unsafe"]["noul"]),
        "irreversible": float(a["irreversible"]["noul"]),
        "chars": len(case["transcript"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    cases = load_all()
    if args.limit:
        cases = cases[: args.limit]
    for c in sorted({x["corpus"] for x in cases}):
        sub = [x for x in cases if x["corpus"] == c]
        pct = 100 * sum(x["want"] for x in sub) / len(sub)
        print(f"  {c:14} {len(sub):>5} cases, {pct:.0f}% unsafe")
    out, t0, done = [], time.perf_counter(), 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(ask, cases):
            out.append(row)
            done += 1
            if done % 200 == 0:
                print(f"  {done}/{len(cases)}  {time.perf_counter() - t0:.0f}s")
    dest = HERE / "at_jev_results.json"
    dest.write_text(json.dumps({"rows": out}, indent=1, sort_keys=True))
    lat = sorted(r["ms"] for r in out)
    print(
        f"  {len(out)} in {time.perf_counter() - t0:.0f}s; median {lat[len(lat) // 2]:.0f}ms "
        f"p95 {lat[int(0.95 * len(lat))]:.0f}ms -> {dest.name}"
    )
    if _errors:
        print(f"  transport: {dict(_errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
