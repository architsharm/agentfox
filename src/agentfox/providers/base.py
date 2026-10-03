"""Model-provider abstraction (X-2 — neutrality by construction).

Neutrality is not a marketing property here, it is the moat: a model provider's
evaluation or guardrail product that "also supports competitors" is a conflict of
interest they will never fully commit to. So the architecture forbids a
single-provider dependency — adding a provider must not touch core, and no feature
may exist that only works on one vendor.

Every provider is an adapter behind this protocol. The default is ``echo``, which is
deterministic, offline, and keyless — which is what makes the whole enforcement path
demonstrable with no account anywhere (X-3, NFR-9).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CompletionRequest:
    messages: list[dict[str, Any]] = field(default_factory=list)
    model: str = "default"
    temperature: float = 0.0
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def last_user_message(self) -> str:
        for message in reversed(self.messages):
            if message.get("role") == "user":
                content = message.get("content")
                return content if isinstance(content, str) else _flatten(content)
        return ""

    def system_prompt(self) -> str:
        for message in self.messages:
            if message.get("role") in ("system", "developer"):
                content = message.get("content")
                return content if isinstance(content, str) else _flatten(content)
        return ""


@dataclass
class StreamChunk:
    """One incremental piece of a streamed completion.

    Providers differ wildly in their SSE shapes; this is the normalised form the
    enforcement path and the gateway both work against, so streaming support is added
    once rather than per provider (X-2).
    """

    delta: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionResponse:
    text: str = ""
    model: str = ""
    provider: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0

    def to_openai(self, request_model: str = "") -> dict[str, Any]:
        """Render as an OpenAI chat-completions body, for gateway compatibility."""
        message: dict[str, Any] = {"role": "assistant", "content": self.text}
        if self.tool_calls:
            message["tool_calls"] = self.tool_calls
        return {
            "id": f"chatcmpl-{abs(hash(self.text)) % (10**12):012d}",
            "object": "chat.completion",
            "model": self.model or request_model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if self.tool_calls else "stop",
                }
            ],
            "usage": {
                "prompt_tokens": self.usage.get("input_tokens", 0),
                "completion_tokens": self.usage.get("output_tokens", 0),
                "total_tokens": sum(self.usage.values()),
            },
        }

    def to_anthropic(self, request_model: str = "") -> dict[str, Any]:
        return {
            "id": f"msg_{abs(hash(self.text)) % (10**12):012d}",
            "type": "message",
            "role": "assistant",
            "model": self.model or request_model,
            "content": [{"type": "text", "text": self.text}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": self.usage.get("input_tokens", 0),
                "output_tokens": self.usage.get("output_tokens", 0),
            },
        }


class ModelProvider(Protocol):
    key: str

    #: False when the provider needs a key or network that is not configured.
    def available(self) -> bool: ...

    def complete(self, request: CompletionRequest) -> CompletionResponse: ...

    def stream(self, request: CompletionRequest) -> Iterator[StreamChunk]:
        """Yield the completion incrementally.

        Every provider must implement this. A provider that cannot stream natively
        should fall back to :func:`stream_from_complete` rather than leaving the
        method absent — silently degrading a streaming caller to a non-streaming
        response is the defect this interface exists to prevent (PL-1).
        """
        ...

    def supports_native_streaming(self) -> bool:
        """False when :meth:`stream` is emulated from :meth:`complete`."""
        ...

    def judge(self, output: str, rubric: str, model: str = "default") -> dict[str, Any]:
        """Score an output against a rubric. Used by the LLM-judge scorer."""
        ...


def stream_from_complete(
    provider: ModelProvider, request: CompletionRequest
) -> Iterator[StreamChunk]:
    """Emulate streaming for a provider that has no native stream.

    Emits the whole body as one chunk. Honest rather than clever: the caller still
    receives a well-formed stream, and `supports_native_streaming()` tells the truth
    about first-token latency.
    """
    response = provider.complete(request)
    yield StreamChunk(
        delta=response.text,
        finish_reason="tool_calls" if response.tool_calls else "stop",
        usage=response.usage,
        tool_calls=response.tool_calls,
        raw={"emulated": True},
    )


def _flatten(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


_REGISTRY: dict[str, ModelProvider] = {}


def register_provider(provider: ModelProvider) -> ModelProvider:
    _REGISTRY[provider.key] = provider
    return provider


#: Hosts that are inside the customer's own boundary. Calling one of these is
#: not egress: nothing crosses a network the customer does not control, so
#: `allow_egress` (NFR-4) has nothing to gate. Defined here, once, because the
#: provider layer and the judgment layer both decide things on it and a second
#: copy that drifted would mean a self-hosted model being treated as a vendor
#: by one of them and not the other.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"})


def is_local_endpoint(url: str | None) -> bool:
    """True when `url` points inside this deployment.

    Fails safe: anything not provably loopback is treated as remote, so a
    malformed or unexpected URL is gated rather than quietly exempted.
    """
    if not url:
        return False
    from urllib.parse import urlparse

    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS or host.endswith(".localhost")


def get_provider(key: str | None = None) -> ModelProvider:
    from ..config import get_settings

    key = key or get_settings().default_provider
    provider = _REGISTRY.get(key)
    if provider is None:
        raise KeyError(f"unknown provider '{key}'; registered: {sorted(_REGISTRY)}")
    return provider


def all_providers() -> dict[str, ModelProvider]:
    return dict(_REGISTRY)


def available_providers() -> dict[str, ModelProvider]:
    return {k: p for k, p in _REGISTRY.items() if p.available()}
