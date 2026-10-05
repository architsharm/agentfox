"""A general model as a judge, through the neutral provider interface.

Jev answers a question with a probability and nothing else. A general model
has to be *asked* for one, and will happily return prose instead, so this is
mostly parsing discipline and prompt shape rather than cleverness.

**It goes through `providers.get_provider`, not an SDK.** X-2 in
`providers/base.py` is explicit that no feature may exist that only works on
one vendor, and a judge wired directly to one API would be exactly that. The
same class therefore serves the hosted tier and the self-hosted one: a LiteLLM
or vLLM endpoint on loopback is `Tier.LOCAL_LLM` and never leaves the box, the
same endpoint on a vendor's host is `Tier.LLM` and is gated like any other
egress.

**Where it earns its place**, from the measurements:

    performative   LLM 85% against Jev's 7%. "Shall I send the rejection
                   wording" settles a decision while asking a question, and
                   Jev reads it literally. This is the one kind where the
                   general model is clearly the right instrument.
    semantic       LLM 75.4% against Jev's 93.3%. Worse, and ~200x the cost.
                   Permitted so it can union, never preferred.
    pattern_open   unions usefully; no tier dominates.
    structural     forbidden outright, like every judgment tier.

Batching matters for cost here in a way it does not for Jev: one completion
answers every question, so the prompt is built once and the answers are
parsed out by id.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from agentfox.providers.base import is_local_endpoint
from agentfox.detection.judgment.capability import Tier
from agentfox.detection.judgment.jev import JevAnswer, JevResult, JevUnavailable

log = logging.getLogger(__name__)

PROMPT = """You are scoring questions about some content. Answer each one with a probability.

<content>
{state}
</content>

{questions}

Reply with one line per question, in the form `id: NN` where NN is 0-100, the
probability that the answer to that question is yes. No other text, no
explanation. Every id must appear exactly once."""


class LlmJudge:
    """Answers judgment questions with any registered model provider."""

    def __init__(self, provider_key: str | None = None, *, timeout_s: float = 20.0) -> None:
        self._key = provider_key
        self._timeout = timeout_s

    # -- identity ---------------------------------------------------------
    def _settings(self):
        from agentfox.core.config import get_settings

        return get_settings()

    def provider_key(self) -> str:
        s = self._settings()
        return self._key or getattr(s, "judgment_llm_provider", "") or s.default_provider

    def tier(self) -> Tier:
        """LOCAL_LLM when the endpoint is on loopback, otherwise LLM.

        Fails safe: anything not provably local is treated as egress, so a
        misconfigured endpoint is gated rather than quietly exempted.
        """
        s = self._settings()
        url = getattr(s, "litellm_base_url", None)
        return Tier.LOCAL_LLM if is_local_endpoint(url) else Tier.LLM

    def available(self) -> bool:
        try:
            from agentfox.providers import get_provider

            provider = get_provider(self.provider_key())
        except Exception:  # noqa: BLE001 - unknown key, import failure
            return False
        # `echo` is deterministic and keyless; it exists so the stack runs with
        # no account anywhere, and it cannot judge anything.
        if provider.key == "echo":
            return False
        return bool(provider.available())

    # -- judging ----------------------------------------------------------
    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> JevResult:
        if not questions:
            return JevResult()
        from agentfox.providers import get_provider
        from agentfox.providers.base import CompletionRequest

        provider = get_provider(self.provider_key())
        if not provider.available():
            raise JevUnavailable(f"provider '{provider.key}' is not available")

        rendered = "\n".join(
            f"{qid}: {q.get('instructions', '')} "
            f"(yes means: {(q.get('criteria') or {}).get('what', '')})"
            for qid, q in questions.items()
        )
        body = PROMPT.format(state=_render(state), questions=rendered)
        started = time.perf_counter()
        try:
            response = provider.complete(
                CompletionRequest(
                    messages=[{"role": "user", "content": body}],
                    # "" lets each adapter fall back to its own default; the
                    # dataclass default of "default" is not a model name.
                    model=getattr(self._settings(), "judgment_llm_model", "") or "",
                    temperature=0.0,
                )
            )
        except Exception as exc:  # noqa: BLE001 - network, auth, quota
            raise JevUnavailable(f"{type(exc).__name__}: {exc}") from exc

        answers = _parse(response.text or "", questions)
        if not answers:
            raise JevUnavailable("judge returned no parseable scores")
        return JevResult(
            answers=answers,
            model=response.model or provider.key,
            input_tokens=(response.usage or {}).get("prompt_tokens", 0),
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def _render(state: Any) -> str:
    if isinstance(state, str):
        return state
    if isinstance(state, dict):
        return "\n".join(f"{k}: {v}" for k, v in sorted(state.items()))
    return str(state)


def _parse(text: str, questions: dict[str, dict[str, Any]]) -> dict[str, JevAnswer]:
    """Pull `id: NN` out of whatever the model actually sent.

    Models add preambles, bullets and code fences no matter how the prompt is
    worded, so this looks for each question's own id rather than trusting the
    shape of the reply. A question the model skipped is simply absent, which
    callers already treat as "no answer" rather than as zero.
    """
    out: dict[str, JevAnswer] = {}
    for qid in questions:
        match = re.search(
            rf"(?:^|\n)\s*[-*\s]*{re.escape(qid)}\s*[:=]\s*(\d{{1,3}})",
            text,
            re.I,
        )
        if not match:
            continue
        value = min(100, max(0, int(match.group(1)))) / 100.0
        out[qid] = JevAnswer(qid, "noul", value, abs(2 * value - 1))
    return out
