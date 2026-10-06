"""Hosted model providers — OpenAI and Anthropic.

Both are adapters of the same weight behind the same protocol; neither is privileged
in core. That symmetry is the neutrality claim made structural rather than asserted:
there is no code path that works better because the customer chose one vendor.

Egress is gated. With ``AGENTFOX_ALLOW_EGRESS=false`` (the default) these
providers report themselves unavailable rather than quietly making a network call
from inside a customer's regulated boundary.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from agentfox.core.config import get_settings
from agentfox.providers.base import (
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    register_provider,
)

#: Indicative USD per 1M tokens, for budget enforcement and cost reporting.
#: Deliberately conservative and clearly labelled — the platform must never present
#: a stale price list as an authoritative spend figure in a compliance report.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-opus-4": (15.00, 75.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4": (0.80, 4.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    for prefix, (inp, out) in _PRICING.items():
        if model.startswith(prefix):
            return (input_tokens * inp + output_tokens * out) / 1_000_000
    return 0.0


def _sse_lines(response) -> Iterator[str]:
    """Yield `data:` payloads from an SSE response, skipping keep-alives."""
    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw.decode() if isinstance(raw, bytes) else raw
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                yield payload


class _HttpProvider:
    key = "http"
    timeout_s = 60.0

    def supports_native_streaming(self) -> bool:
        return True

    def _settings(self):
        return get_settings()

    def available(self) -> bool:
        settings = self._settings()
        return bool(settings.allow_egress) and bool(self._api_key())

    def _api_key(self) -> str | None:
        raise NotImplementedError

    def judge(self, output: str, rubric: str, model: str = "default") -> dict[str, Any]:
        """LLM-as-judge. The model is pinned by the caller and recorded."""
        if not self.available():
            from agentfox.providers.echo import EchoProvider

            return EchoProvider().judge(output, rubric, model)
        prompt = (
            "You are an evaluation judge. Score the OUTPUT against the RUBRIC from 0.0 "
            'to 1.0. Reply with JSON only: {"score": <float>, "rationale": "<why>"}.\n\n'
            f"RUBRIC:\n{rubric}\n\nOUTPUT:\n{output}"
        )
        response = self.complete(
            CompletionRequest(messages=[{"role": "user", "content": prompt}], model=model)
        )
        try:
            parsed = json.loads(
                response.text[response.text.find("{") : response.text.rfind("}") + 1]
            )
            return {
                "score": float(parsed.get("score", 0.0)),
                "rationale": str(parsed.get("rationale", "")),
                "judge_model": model,
            }
        except Exception:
            return {
                "score": 0.0,
                "rationale": "judge returned unparseable output",
                "judge_model": model,
            }


class OpenAIProvider(_HttpProvider):
    key = "openai"

    def _api_key(self) -> str | None:
        return self._settings().openai_api_key

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        settings = self._settings()
        body: dict[str, Any] = {
            "model": request.model or "gpt-4o-mini",
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        if request.tools:
            body["tools"] = request.tools

        r = httpx.post(
            f"{settings.openai_base_url}/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self._api_key()}"},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        model = data.get("model", body["model"])
        return CompletionResponse(
            text=message.get("content") or "",
            model=model,
            provider=self.key,
            tool_calls=message.get("tool_calls") or [],
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            cost_usd=estimate_cost(model, input_tokens, output_tokens),
            raw=data,
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamChunk]:  # pragma: no cover
        settings = self._settings()
        body: dict[str, Any] = {
            "model": request.model or "gpt-4o-mini",
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        if request.tools:
            body["tools"] = request.tools

        with httpx.stream(
            "POST",
            f"{settings.openai_base_url}/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self._api_key()}"},
            timeout=self.timeout_s,
        ) as response:
            response.raise_for_status()
            for payload in _sse_lines(response):
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                usage = data.get("usage") or {}
                for choice in data.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content") or ""
                    yield StreamChunk(
                        delta=delta,
                        finish_reason=choice.get("finish_reason"),
                        usage={
                            "input_tokens": int(usage.get("prompt_tokens", 0)),
                            "output_tokens": int(usage.get("completion_tokens", 0)),
                        }
                        if usage
                        else {},
                        raw=data,
                    )
                if usage and not data.get("choices"):
                    yield StreamChunk(
                        delta="",
                        usage={
                            "input_tokens": int(usage.get("prompt_tokens", 0)),
                            "output_tokens": int(usage.get("completion_tokens", 0)),
                        },
                        raw=data,
                    )


class AnthropicProvider(_HttpProvider):
    key = "anthropic"

    def _api_key(self) -> str | None:
        return self._settings().anthropic_api_key

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        settings = self._settings()
        system = request.system_prompt()
        messages = [m for m in request.messages if m.get("role") not in ("system", "developer")]
        body: dict[str, Any] = {
            "model": request.model or "claude-sonnet-4",
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
            "temperature": request.temperature,
        }
        if system:
            body["system"] = system
        if request.tools:
            body["tools"] = request.tools

        r = httpx.post(
            f"{settings.anthropic_base_url}/v1/messages",
            json=body,
            headers={
                "x-api-key": self._api_key() or "",
                "anthropic-version": "2023-06-01",
            },
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        tool_calls = [
            {
                "id": b.get("id"),
                "type": "function",
                "function": {"name": b.get("name"), "arguments": json.dumps(b.get("input", {}))},
            }
            for b in blocks
            if b.get("type") == "tool_use"
        ]
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0))
        output_tokens = int(usage.get("output_tokens", 0))
        model = data.get("model", body["model"])
        return CompletionResponse(
            text=text,
            model=model,
            provider=self.key,
            tool_calls=tool_calls,
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            cost_usd=estimate_cost(model, input_tokens, output_tokens),
            raw=data,
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamChunk]:  # pragma: no cover
        settings = self._settings()
        system = request.system_prompt()
        messages = [m for m in request.messages if m.get("role") not in ("system", "developer")]
        body: dict[str, Any] = {
            "model": request.model or "claude-sonnet-4",
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
            "temperature": request.temperature,
            "stream": True,
        }
        if system:
            body["system"] = system
        if request.tools:
            body["tools"] = request.tools

        with httpx.stream(
            "POST",
            f"{settings.anthropic_base_url}/v1/messages",
            json=body,
            headers={
                "x-api-key": self._api_key() or "",
                "anthropic-version": "2023-06-01",
            },
            timeout=self.timeout_s,
        ) as response:
            response.raise_for_status()
            for payload in _sse_lines(response):
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                kind = data.get("type")
                if kind == "content_block_delta":
                    yield StreamChunk(delta=(data.get("delta") or {}).get("text", ""), raw=data)
                elif kind == "message_delta":
                    usage = data.get("usage") or {}
                    yield StreamChunk(
                        delta="",
                        finish_reason=(data.get("delta") or {}).get("stop_reason"),
                        usage={"output_tokens": int(usage.get("output_tokens", 0))},
                        raw=data,
                    )


register_provider(OpenAIProvider())
register_provider(AnthropicProvider())
