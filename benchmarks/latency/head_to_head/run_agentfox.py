"""AgentFox via a fresh local gateway per layer (main repo venv, the harness's Gateway class).
Times the client round trip (HTTP on loopback included) and records the engine time the
response reports (`latency_ms`). Usage: run_agentfox.py <layer-key>..."""

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import httpx
from common import MARKET, messages, run

from benchmarks.latency.gateway import LAYERS, Gateway, guard

CPU = {"AGENTFOX_MODEL_DEVICE": "cpu"}
SYSTEMS = {
    "agentfox-L1": ({**LAYERS["L1 Deterministic"], **CPU}, None),
    "agentfox-L2": ({**LAYERS["L2n Default (cache off)"], **CPU}, None),
    "agentfox-L2-cache-on": ({**LAYERS["L2 Default (+ML classifier)"], **CPU}, None),
    "agentfox-L4-judge-inline": (
        {**LAYERS["L4b Full (judge always inline)"], "AGENTFOX_CLASSIFIER_CACHE_SIZE": "0", **CPU},
        300,
    ),
}
if __name__ == "__main__":
    work = MARKET / "gw"
    work.mkdir(exist_ok=True)
    for key in sys.argv[1:]:
        env, sub = SYSTEMS[key]
        sub = int(os.environ.get("BENCH_SUBSAMPLE") or 0) or sub
        with Gateway(key, env, work) as gw, httpx.Client(base_url=gw.base) as c:
            print(key, "gateway up in", round(gw.startup_s, 1), "s", flush=True)
            sid = f"mkt-{uuid.uuid4().hex[:8]}"

            def fn(text, key=key, sid=sid):
                # A fresh session per message: no history carried between unrelated inputs.
                _, d = guard(
                    c,
                    "/v1/guard/input",
                    {
                        "agent": "market-bench",
                        "session_id": f"{sid}-{uuid.uuid4().hex[:6]}",
                        "content": text,
                        "surface": "input",
                        "taint_source": "user",
                    },
                )
                if d.get("_status") != 200:
                    raise RuntimeError(f"{key}: HTTP {d.get('_status')} {d}")
                rules = d.get("rules_fired") or []
                return (d.get("effective_verdict") or d.get("verdict")), {
                    "server_ms": round(float(d.get("latency_ms") or 0), 3),
                    "applied": d.get("verdict") or d.get("applied_verdict"),
                    "rules": len(rules),
                    "degraded": ",".join(d.get("degraded") or []),
                }

            run(key + os.environ.get("BENCH_SUFFIX", ""), fn, messages(sub))
