"""CSVs for the layers x repos x scenarios study.

Usage: MAP_REPORT=map_report.json python -m benchmarks.latency.report <work_dir> <out_dir> <run,run_l4>
"""

import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

S, OUT = Path(sys.argv[1]), Path(sys.argv[2])
RUNS = sys.argv[3].split(",")  # result dirs under S, e.g. study,study4
OUT.mkdir(parents=True, exist_ok=True)

rows, meta = [], {"repos": {}, "layers": {}}
for d in RUNS:
    rows += json.loads((S / d / "rows.json").read_text())
    m = json.loads((S / d / "meta.json").read_text())
    meta["repos"].update(m["repos"])
    meta["layers"].update(m["layers"])
skipped = json.loads((S / os.environ.get("MAP_REPORT", "map_report.json")).read_text())


def pct(v, p):
    v = sorted(v)
    if not v:
        return ""
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return round(v[f] + (v[c] - v[f]) * (k - f), 1)


def st(rs, key="server_ms"):
    v = [r[key] for r in rs]
    return {
        "calls": len(v),
        "p50_ms": pct(v, 0.5),
        "p90_ms": pct(v, 0.9),
        "p95_ms": pct(v, 0.95),
        "p99_ms": pct(v, 0.99),
        "mean_ms": round(statistics.mean(v), 1) if v else "",
    }


def deg(rs):
    return round(100 * sum(1 for r in rs if r["degraded"]) / len(rs), 1) if rs else ""


def write(name, data):
    if not data:
        return
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)


def group(keyf):
    g = defaultdict(list)
    for r in rows:
        for k in keyf(r):
            g[k].append(r)
    return g


# 01 repos
repo_rows = []
for name, m in sorted(meta["repos"].items()):
    info = skipped.get(name, {})
    repo_rows.append(
        {
            "repo": name,
            "url": info.get("url", ""),
            "commit": info.get("commit", ""),
            "source": info.get("source", ""),
            "repo_kind": m["kind"],
            "frameworks": "; ".join(f for f in m["frameworks"] if f),
            "agents": m["agents"],
            "tools": m["tools"],
            "handoffs": m["handoffs"],
            "calls_recorded": sum(1 for r in rows if r["repo"] == name),
            "note": "",
        }
    )
for name, info in sorted(skipped.items()):
    if name not in meta["repos"]:
        repo_rows.append(
            {
                "repo": name,
                "url": info.get("url", ""),
                "commit": info.get("commit", ""),
                "source": info.get("source", ""),
                "repo_kind": "not testable",
                "frameworks": "",
                "agents": 0,
                "tools": 0,
                "handoffs": 0,
                "calls_recorded": 0,
                "note": info.get("note", "0 agents found by the mapper"),
            }
        )
write("01_repos.csv", repo_rows)

# 02 layer x step
out = []
for (layer, step), rs in sorted(
    group(lambda r: [(r["layer"], r["step"]), (r["layer"], "ALL")]).items()
):
    s, c = st(rs), st(rs, "client_ms")
    out.append(
        {
            "layer": layer,
            "step": step,
            **{f"engine_{k}": v for k, v in s.items()},
            "http_local_p50_ms": c["p50_ms"],
            "http_local_p95_ms": c["p95_ms"],
            "degraded_pct": deg(rs),
        }
    )
write("02_by_layer_and_step.csv", out)

# 03 layer x scenario, per call and per agent turn
out = []
turns = defaultdict(list)
for r in rows:
    turns[(r["layer"], r["scenario"], r["session_id"], r["turn"])].append(r)
per_turn = defaultdict(list)
for (layer, sc, _sid, _t), rs in turns.items():
    per_turn[(layer, sc)].append(sum(x["server_ms"] for x in rs))
for (layer, sc), rs in sorted(group(lambda r: [(r["layer"], r["scenario"])]).items()):
    s = st(rs)
    pt = per_turn[(layer, sc)]
    out.append(
        {
            "layer": layer,
            "scenario": sc,
            "calls": s["calls"],
            "engine_p50_ms_per_call": s["p50_ms"],
            "engine_p95_ms_per_call": s["p95_ms"],
            "agent_turns": len(pt),
            "engine_p50_ms_per_agent_turn": pct(pt, 0.5),
            "engine_p95_ms_per_agent_turn": pct(pt, 0.95),
            "degraded_pct": deg(rs),
        }
    )
write("03_by_layer_and_scenario.csv", out)

# 04 multi-turn growth: does latency rise with the session's history?
out = []
for (layer, t), rs in sorted(
    group(lambda r: [(r["layer"], r["turn"])] if r["scenario"] == "multi_turn" else []).items()
):
    s = st(rs)
    out.append(
        {
            "layer": layer,
            "turn_in_session": t,
            "calls": s["calls"],
            "engine_p50_ms": s["p50_ms"],
            "engine_p95_ms": s["p95_ms"],
            "degraded_pct": deg(rs),
        }
    )
write("04_multi_turn_by_turn_number.csv", out)

# 05 repo kind
out = []
for (layer, kind), rs in sorted(group(lambda r: [(r["layer"], r["repo_kind"])]).items()):
    s = st(rs)
    out.append(
        {
            "layer": layer,
            "repo_kind": kind,
            "repos": len({r["repo"] for r in rs}),
            **s,
            "degraded_pct": deg(rs),
        }
    )
write("05_by_repo_kind.csv", out)

# 06 repo x layer
out = []
for (repo, layer), rs in sorted(group(lambda r: [(r["repo"], r["layer"])]).items()):
    s, c = st(rs), st(rs, "client_ms")
    out.append(
        {
            "repo": repo,
            "repo_kind": rs[0]["repo_kind"],
            "layer": layer,
            "calls": s["calls"],
            "engine_p50_ms": s["p50_ms"],
            "engine_p95_ms": s["p95_ms"],
            "http_local_p50_ms": c["p50_ms"],
            "http_local_p95_ms": c["p95_ms"],
            "avg_chars": round(statistics.mean(r["chars"] for r in rs)),
            "blocked": sum(1 for r in rs if r["verdict"] == "block"),
            "would_act_once_enforcing": sum(1 for r in rs if r["verdict"] != r["would_be"]),
            "degraded_pct": deg(rs),
        }
    )
write("06_by_repo.csv", out)


# 07 content size
def bucket(n):
    return (
        "a <200" if n < 200 else "b 200-600" if n < 600 else "c 600-1500" if n < 1500 else "d 1500+"
    )


out = []
for (layer, b), rs in sorted(group(lambda r: [(r["layer"], bucket(r["chars"]))]).items()):
    out.append({"layer": layer, "content_chars": b[2:], **st(rs), "degraded_pct": deg(rs)})
write("07_by_content_size.csv", out)

# 08 startup, first call, production network (concurrency: run_concurrency.py)
out = []
for layer, m in sorted(meta["layers"].items()):
    out += [
        {"layer": layer, "measure": "gateway startup to healthy (s)", "value": m["startup_s"]},
        {
            "layer": layer,
            "measure": "first guard call after startup (ms)",
            "value": m["cold_first_call_ms"],
        },
        {
            "layer": layer,
            "measure": "wall time for the layer's run (min)",
            "value": m.get("wall_min"),
        },
    ]
# Optional: `curl -w "%{time_connect} %{time_starttransfer} %{time_total}\\n"` lines against a
# hosted gateway's /health, the first one cold.
rtt = S / "prod_rtt.txt"
tot = [list(map(float, line.split()))[2] * 1000 for line in open(rtt)] if rtt.exists() else []
out += (
    []
    if not tot
    else [
        {
            "layer": "production gateway (Vercel, function in iad1)",
            "measure": "first request: serverless cold start (ms)",
            "value": round(tot[0]),
        },
        {
            "layer": "production gateway (Vercel, function in iad1)",
            "measure": "warm /health round trip from Bengaluru p50 (ms)",
            "value": pct(tot[1:], 0.5),
        },
        {
            "layer": "production gateway (Vercel, function in iad1)",
            "measure": "warm /health round trip from Bengaluru p95 (ms)",
            "value": pct(tot[1:], 0.95),
        },
    ]
)
write("08_startup_and_network.csv", out)

# 09 every call
fields = [
    "layer",
    "repo",
    "repo_kind",
    "scenario",
    "session_id",
    "turn",
    "agent",
    "attack_id",
    "attack_type",
    "control",
    "step",
    "chars",
    "server_ms",
    "client_ms",
    "verdict",
    "would_be",
    "rules",
    "degraded",
    "status",
]
write("09_recorded_sessions_all_calls.csv", [{k: r.get(k) for k in fields} for r in rows])

print(
    len(rows),
    "calls,",
    len(meta["repos"]),
    "repos tested,",
    len(skipped) - len(meta["repos"]),
    "not testable",
)

# 10 framework, default layer with the cache off; a repo counts once, under the first
# framework 01_repos.csv lists for it
main_fw = {r["repo"]: r["frameworks"].split("; ")[0] for r in repo_rows}
by_fw = defaultdict(list)
for r in rows:
    if r["layer"] == "L2n Default (cache off)":
        by_fw[main_fw.get(r["repo"], "")].append(r)
out = []
for fw, rs in sorted(by_fw.items(), key=lambda kv: -len(kv[1])):
    s = st(rs)
    out.append(
        {
            "framework": fw,
            "repos": len({r["repo"] for r in rs}),
            "calls": s["calls"],
            "p50_ms": s["p50_ms"],
            "p95_ms": s["p95_ms"],
        }
    )
write("10_by_framework_default_cache_off.csv", out)
