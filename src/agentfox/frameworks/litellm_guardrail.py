"""LiteLLM proxy guardrail: every model call through LiteLLM is checked by AgentFox.

Add it to the proxy's ``config.yaml``; no change to the agents behind it::

    guardrails:
      - guardrail_name: agentfox
        litellm_params:
          guardrail: agentfox.frameworks.litellm_guardrail.AgentFoxGuardrail
          mode: [pre_call, post_call]
          default_on: true
          api_base: os.environ/AGENTFOX_URL        # your gateway
          api_key: os.environ/AGENTFOX_API_KEY

What it checks:

* **pre_call** — the newest user message and any tool results in the request, as
  inputs (prompt injection, secrets, PII). A redaction rewrites the message.
* **post_call** — each tool call the model asks for, against the agent's grants, with
  the request's messages, so an argument copied out of a tool result is marked
  untrusted (taint) without the agent declaring anything. Then the reply text, as
  an output. Streamed replies are held only once a tool call starts, and checked at
  the end of the stream.

A stopped call is refused with HTTP 400 and the rule's message. In observe mode the
gateway allows everything and records what it would have stopped.

The agent is ``agent`` from ``litellm_params``, else ``metadata.agentfox_agent`` on
the request, else the LiteLLM key's alias, else ``litellm``. When the gateway cannot
be reached the call is refused (``fail_open: true`` lets it through instead).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import httpx
from fastapi import HTTPException

from agentfox.runtime.enforcement.result import STOPPING_VERDICTS

log = logging.getLogger(__name__)

try:  # The proxy imports this module; outside it, the class still works for tests.
    from litellm.integrations.custom_guardrail import (
        CustomGuardrail,  # type: ignore[import-not-found]
    )
except Exception:  # pragma: no cover - exercised only without litellm installed

    class CustomGuardrail:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.guardrail_name = kwargs.get("guardrail_name")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """LiteLLM hands over pydantic objects or plain dicts depending on the path."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    return ""


class AgentFoxGuardrail(CustomGuardrail):
    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        agent: str | None = None,
        fail_open: bool = False,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        self.api_base = (
            api_base or os.environ.get("AGENTFOX_URL") or "http://localhost:8080"
        ).rstrip("/")
        self.api_key = (
            api_key or os.environ.get("AGENTFOX_API_KEY") or os.environ.get("AGENTFOX_API_TOKEN")
        )
        self.agent = agent
        self.fail_open = fail_open
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        super().__init__(**kwargs)

    # -- LiteLLM hooks ------------------------------------------------------
    async def async_pre_call_hook(
        self, user_api_key_dict: Any, cache: Any, data: dict, call_type: str
    ) -> dict:
        messages = data.get("messages") or []
        agent = self._agent(data, user_api_key_dict)
        # The newest user turn, and every tool result: earlier user turns were
        # checked when they were new.
        last_user = max(
            (i for i, m in enumerate(messages) if _get(m, "role") == "user"), default=None
        )
        for index, message in enumerate(messages):
            role = _get(message, "role")
            if not (index == last_user or role == "tool"):
                continue
            content = _text(_get(message, "content"))
            if not content:
                continue
            body = await self._post(
                "/v1/guard/input",
                {
                    "agent": agent,
                    "content": content,
                    "taint_source": "tool" if role == "tool" else "user",
                    **self._session(data),
                },
            )
            self._raise_if_stopped(body)
            if body.get("content") is not None and body["content"] != content:
                message["content"] = body["content"]
        return data

    async def async_post_call_success_hook(
        self, data: dict, user_api_key_dict: Any, response: Any
    ) -> Any:
        agent = self._agent(data, user_api_key_dict)
        for choice in _get(response, "choices") or []:
            message = _get(choice, "message")
            for call in _get(message, "tool_calls") or []:
                function = _get(call, "function") or {}
                await self._guard_tool(
                    data, agent, _get(function, "name") or "", _get(function, "arguments")
                )
            content = _text(_get(message, "content"))
            if content:
                body = await self._post(
                    "/v1/guard/output",
                    {
                        "agent": agent,
                        "content": content,
                        "surface": "output",
                        **self._session(data),
                    },
                )
                self._raise_if_stopped(body)
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict: Any, response: Any, request_data: dict
    ) -> AsyncGenerator[Any, None]:
        """Pass text through as it streams; once a tool call starts, hold the rest and
        check the assembled calls before releasing them."""
        agent = self._agent(request_data, user_api_key_dict)
        held: list[Any] = []
        calls: dict[int, dict[str, str]] = {}
        async for chunk in response:
            for choice in _get(chunk, "choices") or []:
                for delta_call in _get(_get(choice, "delta"), "tool_calls") or []:
                    slot = calls.setdefault(
                        _get(delta_call, "index", 0) or 0, {"name": "", "arguments": ""}
                    )
                    function = _get(delta_call, "function") or {}
                    slot["name"] += _get(function, "name") or ""
                    slot["arguments"] += _get(function, "arguments") or ""
            if calls:
                held.append(chunk)
            else:
                yield chunk
        for call in calls.values():
            await self._guard_tool(request_data, agent, call["name"], call["arguments"])
        for chunk in held:
            yield chunk

    # -- helpers ------------------------------------------------------------
    async def _guard_tool(self, data: dict, agent: str, tool: str, raw_arguments: Any) -> None:
        try:
            arguments = (
                json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            )
        except ValueError:
            arguments = {"_raw": raw_arguments}
        if not isinstance(arguments, dict):
            arguments = {"_value": arguments}
        body = await self._post(
            "/v1/guard/tool_call",
            {
                "agent": agent,
                "tool": tool,
                "arguments": arguments,
                # The conversation, so the gateway can tell which arguments came
                # from a tool result rather than from the user.
                "messages": [_plain(m) for m in data.get("messages") or []],
                # A client of the proxy cannot carry an approval id back: a person's
                # approval of this exact call is spent on the retry.
                "redeem_approved": True,
                **self._session(data),
            },
        )
        self._raise_if_stopped(body)

    def _agent(self, data: dict, user_api_key_dict: Any) -> str:
        metadata = data.get("metadata") or {}
        return (
            self.agent
            or metadata.get("agentfox_agent")
            or _get(user_api_key_dict, "key_alias")
            or "litellm"
        )

    @staticmethod
    def _session(data: dict) -> dict[str, str]:
        metadata = data.get("metadata") or {}
        session_id = metadata.get("session_id") or data.get("litellm_session_id")
        return {"session_id": str(session_id)} if session_id else {}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            response = await self._client.post(
                f"{self.api_base}{path}", json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            if self.fail_open:
                log.warning("AgentFox unreachable, letting the call through: %s", error)
                return {"verdict": "allow"}
            raise HTTPException(
                status_code=503, detail={"error": "AgentFox could not check this call"}
            ) from error

    @staticmethod
    def _raise_if_stopped(body: dict[str, Any]) -> None:
        if body.get("verdict") not in STOPPING_VERDICTS:
            return
        detail: dict[str, Any] = {
            "error": body.get("user_message") or body.get("reason") or "Stopped by AgentFox policy",
            "verdict": body["verdict"],
        }
        if body.get("approval_id"):
            detail["approval_id"] = body["approval_id"]
        raise HTTPException(status_code=400, detail=detail)


def _plain(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    dump = getattr(message, "model_dump", None)
    return dump() if callable(dump) else dict(message)
