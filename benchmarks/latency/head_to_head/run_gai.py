"""Guardrails AI + DetectJailbreak validator (venv-gai). CPU, local models (default use_local)."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import torch
from common import messages, run
from guardrails import Guard
from guardrails_ai.detect_jailbreak import DetectJailbreak

THREADS = os.environ.get("BENCH_TORCH_THREADS")
if THREADS:
    torch.set_num_threads(int(THREADS))
print("torch threads", torch.get_num_threads(), torch.__version__, flush=True)
guard = Guard().use(DetectJailbreak(device="cpu", on_fail="noop"))


def fn(text):
    out = guard.validate(text)
    return ("allow" if out.validation_passed else "flag"), {}


sub = int(os.environ.get("BENCH_SUBSAMPLE") or 0) or None
run("guardrails-ai-detect-jailbreak" + os.environ.get("BENCH_SUFFIX", ""), fn, messages(sub))
