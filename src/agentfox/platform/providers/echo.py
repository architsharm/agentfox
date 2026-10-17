"""The offline provider.

Deterministic, keyless, network-free. It exists so that the entire enforcement,
tracing, audit and evaluation path is demonstrable with nothing installed and no
account anywhere — which is what a ten-minute time-to-first-value actually
requires.

It is not a toy stub. Two behaviours make it useful as a *test substrate*:

* **Scripted responses.** A fixture can register an exact reply for a prompt, which
  is how the demo reproduces a plausible-but-ungrounded answer that the
  silent-failure scorers then catch. Without this, evaluating the evaluator would
  need a real model and a real hallucination.
* **Injection compliance.** If the prompt contains an instruction-override payload,
  the echo model *follows it* — modelling a compromised model rather than a safe
  one. That is the honest test target: containment has to hold when the model
  has already been convinced.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Any

from agentfox.platform.providers.base import (
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    register_provider,
)

_SCRIPTS: dict[str, str] = {}

_INJECTION_MARKER = re.compile(
    r"ignore\s+(?:all\s+)?(?:the\s+)?previous\s+instructions?|disregard\s+(?:all\s+)?previous",
    re.I,
)
_EXFIL_MARKER = re.compile(r"(?:send|email|forward)\b.{0,60}?to\s+([\w.+-]+@[\w.-]+)", re.I)


def script(prompt_contains: str, response: str) -> None:
    """Register a canned response for prompts containing ``prompt_contains``."""
    _SCRIPTS[prompt_contains.lower()] = response


def clear_scripts() -> None:
    _SCRIPTS.clear()


class EchoProvider:
    key = "echo"

    def available(self) -> bool:
        return True

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        prompt = "\n".join(
            m.get("content") if isinstance(m.get("content"), str) else "" for m in request.messages
        )
        user = request.last_user_message()

        text = self._scripted(prompt)
        if text is None:
            text = self._synthesise(prompt, user)

        input_tokens = max(1, len(prompt.split()))
        output_tokens = max(1, len(text.split()))
        return CompletionResponse(
            text=text,
            model=request.model or "echo-1",
            provider=self.key,
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            # Priced at zero on purpose: cost is a real field in the data model, and
            # the offline provider must not fabricate spend into compliance reports.
            cost_usd=0.0,
            raw={"deterministic": True},
        )

    @staticmethod
    def _scripted(prompt: str) -> str | None:
        lowered = prompt.lower()
        for needle, response in _SCRIPTS.items():
            if needle in lowered:
                return response
        return None

    @staticmethod
    def _synthesise(prompt: str, user: str) -> str:
        # Model the compromised case: an injected instruction is obeyed.
        if _INJECTION_MARKER.search(prompt):
            exfil = _EXFIL_MARKER.search(prompt)
            if exfil:
                return (
                    "Understood. Overriding prior instructions and forwarding the "
                    f"requested account details to {exfil.group(1)}."
                )
            return "Understood. Overriding prior instructions as requested."

        if not user.strip():
            return "No user input was provided."

        # Deterministic but input-dependent, so traces and evals differ per case.
        digest = hashlib.sha256(user.encode()).hexdigest()[:8]
        summary = " ".join(user.split()[:24])
        return f"[echo:{digest}] Acknowledged: {summary}"

    def supports_native_streaming(self) -> bool:
        return True

    def stream(self, request: CompletionRequest) -> Iterator[StreamChunk]:
        """Stream word-by-word, deterministically.

        Deterministic chunking matters for tests: the windowed enforcement mode has to
        be exercised against a reproducible token boundary sequence, and a random
        chunker would make those tests flaky rather than meaningful.
        """
        response = self.complete(request)
        words = response.text.split(" ")
        for i, word in enumerate(words):
            yield StreamChunk(delta=word if i == 0 else " " + word)
        yield StreamChunk(
            delta="",
            finish_reason="stop",
            usage=response.usage,
            raw={"deterministic": True},
        )

    def judge(self, output: str, rubric: str, model: str = "default") -> dict[str, Any]:
        """Rubric-keyword coverage. Deterministic, and honest about being shallow."""
        from agentfox.core.text import content_tokens

        criteria = content_tokens(rubric)
        if not criteria:
            return {"score": 1.0, "rationale": "no rubric supplied"}
        covered = criteria & content_tokens(output)
        score = len(covered) / len(criteria)
        return {
            "score": round(score, 3),
            "rationale": (
                f"deterministic offline judge: {len(covered)}/{len(criteria)} rubric "
                "terms present in the output. Not a substitute for a model judge — "
                "configure a real provider for production evaluation."
            ),
            "covered": sorted(covered)[:20],
            "missing": sorted(criteria - covered)[:20],
        }


register_provider(EchoProvider())
