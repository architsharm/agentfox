"""Concurrency, measured 3 times per client count per layer; medians reported.

Usage: python -m benchmarks.latency.run_concurrency <maps_dir> <out_dir>
"""

import json
import statistics
import sys
from pathlib import Path

import httpx

from agentfox.capabilities.onboarding.attacks import build_suite
from benchmarks.latency.gateway import LAYERS, Gateway, concurrency, guard

maps = Path(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
msgs = []
for f in sorted(maps.glob("*.json"))[:40]:
    m = json.loads(f.read_text())
    if m["structure"].get("agents"):
        # Runnable items only: a skipped item has an empty message, which every layer
        # answers in a few milliseconds and would pass for throughput.
        runnable = [a for a in build_suite(m["structure"]) if not a.skip and a.message]
        msgs += [{"message": a.message} for a in runnable[:10]]
results = {}
for name in [
    "L1 Deterministic",
    "L2 Default (+ML classifier)",
    "L2n Default (cache off)",
    "L3 Extended (+similarity)",
]:
    with Gateway(name, LAYERS[name], out) as gw:
        with httpx.Client(base_url=gw.base) as c:
            for _ in range(10):
                guard(c, "/v1/guard/input", {"agent": "warm", "content": "hello"})
        rows = {}
        for w in (1, 4, 8, 16):
            runs = [concurrency(gw.base, msgs, w, 200) for _ in range(3)]
            rows[w] = {
                "clients": w,
                "throughput_rps": statistics.median(r["throughput_rps"] for r in runs),
                "p50_ms": statistics.median(r["p50_ms"] for r in runs),
                "p95_ms": statistics.median(r["p95_ms"] for r in runs),
                "p99_ms": statistics.median(r["p99_ms"] for r in runs),
                "runs": runs,
            }
            print(name, w, {k: v for k, v in rows[w].items() if k != "runs"}, flush=True)
        results[name] = rows
(out / "concurrency.json").write_text(json.dumps(results, indent=1))
