"""Network floor to api.openai.com: keep-alive round trip of requests the edge answers without a model."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import httpx
from common import MARKET

key = os.environ["OPENAI_API_KEY"]
out = {}
with httpx.Client(
    base_url="https://api.openai.com", headers={"Authorization": f"Bearer {key}"}, timeout=30
) as c:
    for name, (method, path) in {
        "404_unknown_path": ("GET", "/v1/__nonexistent__"),
        "models_get": ("GET", "/v1/models/omni-moderation-latest"),
        "moderation_1char": ("POST", "/v1/moderations"),
    }.items():
        kw = {"json": {"model": "omni-moderation-latest", "input": "a"}} if method == "POST" else {}
        for _ in range(5):
            c.request(method, path, **kw)
        xs = []
        for _ in range(40):
            t = time.perf_counter()
            r = c.request(method, path, **kw)
            xs.append((time.perf_counter() - t) * 1000)
        xs.sort()
        out[name] = {
            "status": r.status_code,
            "p50": round(xs[20], 1),
            "p90": round(xs[36], 1),
            "min": round(xs[0], 1),
        }
        print(name, out[name], flush=True)
(MARKET / "openai_network_baseline.json").write_text(json.dumps(out, indent=1))
