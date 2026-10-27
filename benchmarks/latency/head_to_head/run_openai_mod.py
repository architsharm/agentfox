"""OpenAI omni-moderation-latest (hosted) + network baseline (venv-nemo for httpx)."""

import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import httpx
from common import MARKET, messages, run

key = os.environ["OPENAI_API_KEY"]
c = httpx.Client(
    base_url="https://api.openai.com/v1", headers={"Authorization": f"Bearer {key}"}, timeout=60
)

# Network baseline: a trivial authenticated GET on the same keep-alive connection.
for _ in range(5):
    c.get("/models/omni-moderation-latest")
base = []
for _ in range(50):
    t = time.perf_counter()
    r = c.get("/models/omni-moderation-latest")
    base.append((time.perf_counter() - t) * 1000)
base.sort()
info = {
    "n": 50,
    "status": r.status_code,
    "p50": base[25],
    "p90": base[45],
    "min": base[0],
    "mean": statistics.mean(base),
}
(MARKET / "openai_network_baseline.json").write_text(json.dumps(info, indent=1))
print("baseline", info, flush=True)


def fn(text):
    r = c.post("/moderations", json={"model": "omni-moderation-latest", "input": text})
    r.raise_for_status()
    res = r.json()["results"][0]
    cats = [k for k, v in res["categories"].items() if v]
    return ("flag" if res["flagged"] else "allow"), {"categories": "|".join(cats)}


sub = int(os.environ.get("BENCH_SUBSAMPLE") or 0) or None
run("openai-omni-moderation" + os.environ.get("BENCH_SUFFIX", ""), fn, messages(sub))
