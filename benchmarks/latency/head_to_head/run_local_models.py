"""Raw HF pipelines and LLM Guard (market venv). Usage: run_local_models.py <system>..."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import torch
import transformers.pipelines  # noqa: F401  (import before the patch below)
from common import messages, run
from transformers import pipeline


def _no_mps() -> bool:
    return False


# CPU only: llm-guard bakes device=mps into its scanners' pipeline kwargs at import time
# on this Mac, so MPS is reported unavailable before llm_guard is imported.
torch.backends.mps.is_available = _no_mps


THREADS = os.environ.get("BENCH_TORCH_THREADS")
if THREADS:
    torch.set_num_threads(int(THREADS))
print("torch threads", torch.get_num_threads(), "torch", torch.__version__, flush=True)

RAW = {
    "deberta-v2": ("protectai/deberta-v3-base-prompt-injection-v2", "INJECTION"),
    "pg2-86m": ("meta-llama/Llama-Prompt-Guard-2-86M", "LABEL_1"),
    "pg2-22m": ("meta-llama/Llama-Prompt-Guard-2-22M", "LABEL_1"),
}


def raw(key):
    mid, pos = RAW[key]
    pipe = pipeline("text-classification", model=mid, device="cpu", truncation=True, max_length=512)

    def fn(text):
        r = pipe(text)[0]
        return ("flag" if r["label"] == pos and r["score"] >= 0.5 else "allow"), {
            "score": round(r["score"], 4),
            "label": r["label"],
        }

    return fn


def llmguard(full: bool):
    from llm_guard import scan_prompt
    from llm_guard.input_scanners import PromptInjection

    if not full:
        scanners = [PromptInjection()]  # defaults: v2 model, threshold 0.92, MatchType.FULL
    else:
        import llm_guard.input_scanners.anonymize as anon
        from llm_guard.input_scanners import (
            Anonymize,
            BanCode,
            Gibberish,
            InvisibleText,
            Language,
            Secrets,
            TokenLimit,
            Toxicity,
        )
        from llm_guard.vault import Vault

        # English only: the default also lists "zh", whose spaCy model llm-guard would pip-download.
        anon.ALL_SUPPORTED_LANGUAGES = ["en"]
        # Sentiment is left out: it fetches NLTK's vader lexicon from GitHub at load time
        # (not PyPI / Hugging Face). BanTopics / BanCompetitors / Code need user config.
        scanners = [
            Anonymize(Vault()),
            BanCode(),
            Gibberish(),
            InvisibleText(),
            Language(valid_languages=["en"]),
            PromptInjection(),
            Secrets(),
            TokenLimit(),
            Toxicity(),
        ]

    def fn(text):
        _, valid, scores = scan_prompt(scanners, text, fail_fast=False)
        bad = [k for k, v in valid.items() if not v]
        return ("flag" if bad else "allow"), {"failed": "|".join(bad)}

    return fn


sub = int(os.environ.get("BENCH_SUBSAMPLE") or 0) or None
suffix = os.environ.get("BENCH_SUFFIX", "")
for system in sys.argv[1:]:
    if system in RAW:
        fn = raw(system)
    elif system == "llmguard-pi":
        fn = llmguard(False)
    elif system == "llmguard-default":
        fn = llmguard(True)
    run(system + suffix, fn, messages(sub))
