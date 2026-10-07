"""Score tool outputs with a third-party injection classifier, in its own interpreter.

This file has no `agentfox` imports. It runs inside a scratch venv that holds the
competitor's package and model, because `llm-guard` pins `transformers==4.51.3`, which
conflicts with this project's own pins (see `benchmarks/agent_security/llm_guard_bridge.py`).

    <scanner-venv>/bin/python benchmarks/head_to_head/scan_bridge.py SCANNER < texts.json > scores.json

Input: a JSON list of strings. Output: one record per input, in order:

    {"sha256", "chars", "score", "flagged_default", "latency_ms", ...}

`score` is the raw injection probability the vendor's code thresholds (so a threshold sweep
can be done afterwards without re-running the model). `flagged_default` is the vendor's own
verdict at its documented default. `latency_ms` is the wall time of the vendor's own scan
call for that one text, after a warm-up, on whatever device torch picked (CPU here).

Scanners:

  llm_guard          llm-guard `PromptInjection()` with every default: model
                     protectai/deberta-v3-base-prompt-injection-v2 (revision pinned by
                     llm-guard), `threshold=0.92`, `MatchType.FULL` (one pass, truncated at
                     512 tokens), torch (no ONNX). Flagged when `scan()` says `is_valid=False`.
  llm_guard_chunks   the same scanner with llm-guard's own `MatchType.CHUNKS` (256-character
                     overlapping windows, highest window score). Not the default; it answers
                     "what if the injection sat past the 512-token truncation".
  pg2_86m, pg2_22m   meta-llama/Llama-Prompt-Guard-2-{86M,22M}, scored exactly as LlamaFirewall's
                     `PromptGuardScanner` does (PurpleLlama @172c1074, `promptguard_utils.py`):
                     whitespace preprocessing, truncation at 512 tokens, softmax, last class,
                     BLOCK when `score >= 0.9` (LlamaFirewall's default `block_threshold`).
                     Also records `score_segmented`, the maximum over 512-token segments, which
                     is what the model card recommends for long inputs.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import sys
import time

DEVICE = os.environ.get("H2H_DEVICE", "cpu")


@contextlib.contextmanager
def _stdout_to_stderr():
    # llm-guard's structlog writes to fd 1; keep this script's JSON clean.
    saved = os.dup(1)
    os.dup2(2, 1)
    try:
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _llm_guard(texts: list[str], chunks: bool) -> tuple[list[dict], dict]:
    import llm_guard.transformers_helpers as helpers
    import llm_guard.util as util
    import torch
    from llm_guard.input_scanners import PromptInjection
    from llm_guard.input_scanners.prompt_injection import V2_MODEL, MatchType

    # llm-guard (and transformers' pipeline) pick CUDA, then Apple MPS, then CPU. Pin the
    # device so the latency figure says what it measured (H2H_DEVICE, default cpu).
    pinned = torch.device(DEVICE)
    util.device = helpers.device = lambda: pinned
    if DEVICE == "cpu":
        torch.backends.mps.is_available = lambda: False

    match = MatchType.CHUNKS if chunks else MatchType.FULL
    scanner = PromptInjection(match_type=match) if chunks else PromptInjection()
    if not str(scanner._pipeline.device).startswith(DEVICE):
        # transformers' own pipeline auto-selected an accelerator; move it.
        scanner._pipeline.model.to(pinned)
        scanner._pipeline.device = pinned
    threshold = scanner._threshold

    def raw(text: str) -> tuple[float, float]:
        # The same computation `scan()` does, without its early return or risk rescaling.
        # Returns (llm-guard's 2-decimal score, the unrounded probability). The sweep uses the
        # unrounded one, so thresholds between 0.99 and 1.0 are reachable.
        if text.strip() == "":
            return 0.0, 0.0
        best, best_raw = 0.0, 0.0
        for r in scanner._pipeline(scanner._match_type.get_inputs(text)):
            p = r["score"] if r["label"] == "INJECTION" else 1 - r["score"]
            best, best_raw = max(best, round(p, 2)), max(best_raw, p)
        return best, best_raw

    for t in texts[:5]:
        scanner.scan(t)  # warm-up
    out = []
    for text in texts:
        t0 = time.perf_counter()
        _, is_valid, risk = scanner.scan(text)
        ms = (time.perf_counter() - t0) * 1000
        score, score_raw = raw(text)
        flagged = not is_valid
        # scan() flags iff some window scores strictly above the threshold.
        assert flagged == (score > threshold), (flagged, score, threshold)
        out.append(
            {
                "sha256": _sha(text),
                "chars": len(text),
                "score": score,
                "score_raw": score_raw,
                "flagged_default": flagged,
                "risk_score": float(risk),
                "latency_ms": round(ms, 3),
            }
        )
    meta = {
        "model": V2_MODEL.path,
        "model_revision": V2_MODEL.revision,
        "threshold": threshold,
        "threshold_rule": "score > threshold (scores rounded to 2 decimals by llm-guard)",
        "match_type": match.value,
        "device": str(scanner._pipeline.device),
    }
    return out, meta


class _PromptGuard:
    """LlamaFirewall's PromptGuard scoring (PurpleLlama @172c1074, MIT), model id parameterised."""

    def __init__(self, model_id: str) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_id)
        self.model.eval()
        self.model.to(DEVICE)

    def preprocess(self, text: str) -> str:
        try:
            cleaned, index_map = "", []
            for i, ch in enumerate(text):
                if not ch.isspace():
                    cleaned += ch
                    index_map.append(i)
            result, last_end = [], 0
            for token in self.tokenizer.tokenize(cleaned):
                token_str = self.tokenizer.convert_tokens_to_string([token])
                start = cleaned.index(token_str, last_end)
                if index_map[start] > 0 and text[index_map[start] - 1].isspace():
                    result.append(" ")
                result.append(token_str)
                last_end = start + len(token_str)
            return "".join(result)
        except Exception:
            return text

    def _probs(self, text: str):
        inputs = self.tokenizer(
            text, return_tensors="pt", padding=True, truncation=True, max_length=512
        ).to(DEVICE)
        with self.torch.no_grad():
            logits = self.model(**inputs).logits
        return self.torch.softmax(logits, dim=-1)

    def score(self, text: str) -> float:
        return self._probs(self.preprocess(text))[0, -1].item()

    def score_segmented(self, text: str) -> float:
        ids = self.tokenizer(self.preprocess(text), add_special_tokens=False)["input_ids"]
        if len(ids) <= 510:
            return self.score(text)
        best = 0.0
        for i in range(0, len(ids), 510):
            seg = self.tokenizer.decode(ids[i : i + 510])
            best = max(best, self._probs(seg)[0, -1].item())
        return best


def _pg2(texts: list[str], size: str) -> tuple[list[dict], dict]:
    from huggingface_hub import HfApi

    model_id = f"meta-llama/Llama-Prompt-Guard-2-{size}"
    pg = _PromptGuard(model_id)
    threshold = 0.9
    for t in texts[:5]:
        pg.score(t)
    out = []
    for text in texts:
        t0 = time.perf_counter()
        score = pg.score(text)
        ms = (time.perf_counter() - t0) * 1000
        out.append(
            {
                "sha256": _sha(text),
                "chars": len(text),
                "score": round(score, 6),
                "flagged_default": score >= threshold,
                "score_segmented": round(pg.score_segmented(text), 6),
                "latency_ms": round(ms, 3),
            }
        )
    try:
        sha = HfApi().model_info(model_id).sha
    except Exception:
        sha = None
    meta = {
        "model": model_id,
        "model_revision": sha,
        "threshold": threshold,
        "threshold_rule": "score >= threshold (LlamaFirewall PromptGuardScanner default)",
        "device": DEVICE,
        "scoring": "LlamaFirewall promptguard_utils.get_jailbreak_score, PurpleLlama@172c1074",
    }
    return out, meta


def main() -> None:
    scanner = sys.argv[1]
    texts: list[str] = json.loads(sys.stdin.read())
    with _stdout_to_stderr():
        import torch

        if scanner == "llm_guard":
            records, meta = _llm_guard(texts, chunks=False)
        elif scanner == "llm_guard_chunks":
            records, meta = _llm_guard(texts, chunks=True)
        elif scanner in ("pg2_86m", "pg2_22m"):
            records, meta = _pg2(texts, scanner.split("_")[1].upper())
        else:
            raise SystemExit(f"unknown scanner {scanner!r}")
        import importlib.metadata as md

        versions = {}
        for pkg in ("llm-guard", "transformers", "torch", "tokenizers"):
            with contextlib.suppress(md.PackageNotFoundError):
                versions[pkg] = md.version(pkg)
        meta.update(
            {
                "scanner": scanner,
                "packages": versions,
                "torch_threads": torch.get_num_threads(),
                "machine": platform.machine(),
                "platform": platform.platform(),
                "python": platform.python_version(),
            }
        )
    json.dump({"meta": meta, "records": records}, sys.stdout)


if __name__ == "__main__":
    main()
