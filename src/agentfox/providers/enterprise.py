"""The providers enterprises actually deploy on.

The CV evidence is blunt about this: **6 of 11 engineers run Azure OpenAI**, 4 run
Bedrock, 3 run Vertex. A governance product that only speaks to `api.openai.com` is
unusable at exactly the companies that need governance, because those companies made
a deliberate decision *not* to send prompts to a vendor endpoint. Supporting only OpenAI
and Anthropic would be neutrality as an assertion; this is neutrality as a code path.

Three adapters plus LiteLLM, each honest about what it needs:

* **Azure OpenAI** is the important one and the cheapest: the wire format is OpenAI's,
  so only auth, URL shape and the deployment-vs-model distinction differ. That last
  one matters — in Azure the "model" a caller names is a *deployment*, and pinning
  the model version for reproducibility means reading it back from the response
  rather than trusting the request.
* **Bedrock** needs SigV4, which needs botocore. Rather than reimplement request
  signing — a thing that is easy to get subtly wrong and catastrophic when you do —
  the adapter reports itself unavailable without it.
* **Vertex** needs a Google credential. Same rule.
* **LiteLLM** is the pragmatic one: 2 of 11 already run it as their routing layer, and
  it speaks the OpenAI wire format, so we govern *through* it rather than competing
  with it. Their routing and our enforcement are different jobs at the same point.

All four inherit the egress gate. With ``AGENTFOX_ALLOW_EGRESS=false`` they report
unavailable rather than making a network call from inside a regulated boundary.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx

from agentfox.providers.base import (
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    is_local_endpoint,
    register_provider,
)
from agentfox.providers.remote import OpenAIProvider, _HttpProvider, _sse_lines, estimate_cost

log = logging.getLogger(__name__)


class AzureOpenAIProvider(OpenAIProvider):
    """Azure OpenAI — the most-deployed enterprise surface (6/11).

    Inherits OpenAI's wire format and overrides only what Azure changes. The
    inheritance is the point: a bug fixed in the OpenAI path is fixed here too, which
    is not true of a copy-pasted adapter.
    """

    key = "azure-openai"

    def _api_key(self) -> str | None:
        return self._settings().azure_openai_api_key

    def available(self) -> bool:
        settings = self._settings()
        return bool(settings.allow_egress and self._api_key() and settings.azure_openai_endpoint)

    def _url(self, deployment: str) -> str:
        settings = self._settings()
        return (
            f"{settings.azure_openai_endpoint.rstrip('/')}/openai/deployments/{deployment}"
            f"/chat/completions?api-version={settings.azure_openai_api_version}"
        )

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        settings = self._settings()
        # In Azure the caller names a *deployment*, not a model. Recording the
        # deployment as if it were the model would make the trace unreproducible
        # against a different subscription.
        deployment = request.model or settings.azure_openai_deployment or "gpt-4o-mini"
        body: dict[str, Any] = {
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        if request.tools:
            body["tools"] = request.tools

        r = httpx.post(
            self._url(deployment),
            json=body,
            headers={"api-key": self._api_key() or ""},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens", 0))
        output_tokens = int(usage.get("completion_tokens", 0))
        # The underlying model comes back in the response; the deployment name does not
        # identify it.
        model = data.get("model") or deployment
        return CompletionResponse(
            text=message.get("content") or "",
            model=model,
            provider=self.key,
            tool_calls=message.get("tool_calls") or [],
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            cost_usd=estimate_cost(model, input_tokens, output_tokens),
            raw={**data, "azure_deployment": deployment},
        )

    def stream(self, request: CompletionRequest) -> Iterator[StreamChunk]:  # pragma: no cover
        settings = self._settings()
        deployment = request.model or settings.azure_openai_deployment or "gpt-4o-mini"
        body: dict[str, Any] = {
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        with httpx.stream(
            "POST",
            self._url(deployment),
            json=body,
            headers={"api-key": self._api_key() or ""},
            timeout=self.timeout_s,
        ) as response:
            response.raise_for_status()
            for payload in _sse_lines(response):
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for choice in data.get("choices") or []:
                    yield StreamChunk(
                        delta=(choice.get("delta") or {}).get("content") or "",
                        finish_reason=choice.get("finish_reason"),
                        raw=data,
                    )


class LiteLLMProvider(OpenAIProvider):
    """Govern *through* the routing layer teams already run (2/11).

    LiteLLM speaks the OpenAI wire format, so this is a base-URL change and a
    different key. Deliberately not a competitor: their routing and our enforcement
    are different jobs that happen at the same point, and a team that has already
    solved routing should not have to unpick it to get governance.
    """

    key = "litellm"

    def _api_key(self) -> str | None:
        return self._settings().litellm_api_key

    def available(self) -> bool:
        settings = self._settings()
        # A self-hosted LiteLLM proxy commonly runs without a master key, so the key
        # is not required — only a configured base URL, and egress *unless the URL
        # is loopback*. Reaching localhost crosses no network the customer does not
        # control, so the egress gate has nothing to gate there; requiring it would
        # keep a fully self-hosted model from a deployment that has correctly turned
        # egress off — the deployment most likely to want one.
        url = settings.litellm_base_url
        if not url:
            return False
        return bool(settings.allow_egress) or is_local_endpoint(url)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        settings = self._settings()
        body: dict[str, Any] = {
            "model": request.model or "gpt-4o-mini",
            "messages": request.messages,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        headers = {}
        if self._api_key():
            headers["Authorization"] = f"Bearer {self._api_key()}"
        r = httpx.post(
            f"{settings.litellm_base_url.rstrip('/')}/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        usage = data.get("usage") or {}
        model = data.get("model", body["model"])
        return CompletionResponse(
            text=(choice.get("message") or {}).get("content") or "",
            model=model,
            provider=self.key,
            tool_calls=(choice.get("message") or {}).get("tool_calls") or [],
            usage={
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            },
            # LiteLLM computes its own cost and is closer to the real price list than
            # our indicative table, so prefer it when present.
            cost_usd=float(data.get("response_cost") or 0.0)
            or estimate_cost(
                model,
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
            ),
            raw=data,
        )


class BedrockProvider(_HttpProvider):
    """AWS Bedrock (4/11). Requires botocore for SigV4.

    We do not reimplement request signing. It is easy to get subtly wrong, and the
    failure mode of getting it wrong is an authentication error at best and a
    credential leak at worst — so without botocore this adapter reports unavailable
    rather than improvising.
    """

    key = "bedrock"

    def _api_key(self) -> str | None:  # not used; auth is SigV4
        return None

    def available(self) -> bool:
        settings = self._settings()
        if not settings.allow_egress:
            return False
        try:
            import boto3  # noqa: F401
        except ImportError:
            return False
        return bool(settings.aws_region)

    def _client(self):
        import boto3

        return boto3.client("bedrock-runtime", region_name=self._settings().aws_region)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not self.available():
            raise RuntimeError(
                "bedrock provider unavailable: needs AGENTFOX_ALLOW_EGRESS=1, a region, "
                "and boto3 (pip install 'agentfox[bedrock]')"
            )
        model = request.model or self._settings().bedrock_model
        # Bedrock's Converse API normalises across model families, which keeps this
        # adapter from growing one branch per vendor hosted on Bedrock.
        messages, system = _split_system(request.messages)
        kwargs: dict[str, Any] = {
            "modelId": model,
            "messages": [
                {"role": m["role"], "content": [{"text": str(m.get("content") or "")}]}
                for m in messages
            ],
            "inferenceConfig": {"temperature": request.temperature},
        }
        if system:
            kwargs["system"] = [{"text": system}]
        if request.max_tokens:
            kwargs["inferenceConfig"]["maxTokens"] = request.max_tokens

        data = self._client().converse(**kwargs)
        blocks = (data.get("output") or {}).get("message", {}).get("content") or []
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("inputTokens", 0))
        output_tokens = int(usage.get("outputTokens", 0))
        return CompletionResponse(
            text="".join(b.get("text", "") for b in blocks),
            model=model,
            provider=self.key,
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            cost_usd=estimate_cost(model, input_tokens, output_tokens),
            raw=data,
        )


class VertexProvider(_HttpProvider):
    """Google Vertex AI (3/11). Requires a Google credential.

    Same rule as Bedrock: no improvised auth. The adapter reports unavailable without
    `google-auth` rather than pretending to a capability it does not have.
    """

    key = "vertex"

    def _api_key(self) -> str | None:
        return None

    def available(self) -> bool:
        settings = self._settings()
        if not (settings.allow_egress and settings.vertex_project and settings.vertex_location):
            return False
        try:
            import google.auth  # noqa: F401
        except ImportError:
            return False
        return True

    def _token(self) -> str:
        import google.auth
        import google.auth.transport.requests

        credentials, _project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
        return credentials.token

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not self.available():
            raise RuntimeError(
                "vertex provider unavailable: needs AGENTFOX_ALLOW_EGRESS=1, a project and "
                "location, and google-auth (pip install 'agentfox[vertex]')"
            )
        settings = self._settings()
        model = request.model or settings.vertex_model
        messages, system = _split_system(request.messages)
        body: dict[str, Any] = {
            "contents": [
                {
                    "role": "user" if m["role"] != "assistant" else "model",
                    "parts": [{"text": str(m.get("content") or "")}],
                }
                for m in messages
            ],
            "generationConfig": {"temperature": request.temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if request.max_tokens:
            body["generationConfig"]["maxOutputTokens"] = request.max_tokens

        url = (
            f"https://{settings.vertex_location}-aiplatform.googleapis.com/v1/projects/"
            f"{settings.vertex_project}/locations/{settings.vertex_location}/publishers/google/"
            f"models/{model}:generateContent"
        )
        r = httpx.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {self._token()}"},
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        candidate = (data.get("candidates") or [{}])[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        usage = data.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount", 0))
        output_tokens = int(usage.get("candidatesTokenCount", 0))
        return CompletionResponse(
            text="".join(p.get("text", "") for p in parts),
            model=model,
            provider=self.key,
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            cost_usd=estimate_cost(model, input_tokens, output_tokens),
            raw=data,
        )


def _split_system(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Both Bedrock and Vertex carry the system prompt outside the message list."""
    system = " ".join(
        str(m.get("content") or "") for m in messages if str(m.get("role")) == "system"
    )
    rest = [m for m in messages if str(m.get("role")) != "system"]
    return rest, system.strip()


register_provider(AzureOpenAIProvider())
register_provider(LiteLLMProvider())
register_provider(BedrockProvider())
register_provider(VertexProvider())
