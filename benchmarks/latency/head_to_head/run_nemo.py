"""NeMo Guardrails self-check input rail (gpt-4.1-mini), input rails only (venv-nemo)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import messages, run
from nemoguardrails import LLMRails, RailsConfig

cfg = RailsConfig.from_path(os.path.join(os.path.dirname(__file__), "nemo_config"))
rails = LLMRails(cfg)
loop = asyncio.new_event_loop()


def fn(text):
    res = loop.run_until_complete(
        rails.generate_async(
            messages=[{"role": "user", "content": text}],
            options={"rails": ["input"], "log": {"activated_rails": True}},
        )
    )
    blocked = any(r.stop for r in (res.log.activated_rails or [])) if res.log else False
    return ("flag" if blocked else "allow"), {}


sub = int(os.environ.get("BENCH_SUBSAMPLE") or 0) or None
run("nemo-self-check-gpt-4.1-mini" + os.environ.get("BENCH_SUFFIX", ""), fn, messages(sub))
