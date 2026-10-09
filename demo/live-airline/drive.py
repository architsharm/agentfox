"""Talk to the governed airline agents, streamed the way the app's chat endpoint runs them.

    .venv/bin/python drive.py "What is the status of my flight?" "It's PA441 today"

Each turn is reported as one dict: the agent that answered, its reply, each tool it
called with what came back, AgentFox's tool-call decisions, and why a turn was stopped
(an input or output guardrail, or the gateway refusing the model call).
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any

from common import use_upstream

use_upstream()

import main  # noqa: E402,F401  (the upstream app: wires AgentFox, governs the agents)
from agents import (  # noqa: E402
    InputGuardrailTripwireTriggered,
    OutputGuardrailTripwireTriggered,
    Runner,
)
from airline.agents import triage_agent  # noqa: E402
from airline.context import create_initial_context  # noqa: E402
from openai import APIError, APIStatusError  # noqa: E402


def _info(output_info: Any) -> dict[str, Any]:
    return output_info if isinstance(output_info, dict) else {"detail": str(output_info)[:200]}


def _gateway_refusal(exc: APIError) -> dict[str, Any]:
    body = exc.body if isinstance(exc.body, dict) else {"message": str(exc)}
    detail = body.get("detail", body)
    detail = detail if isinstance(detail, dict) else {"detail": detail}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    return {
        "status": getattr(exc, "status_code", None),
        "user_message": detail.get("user_message") or error.get("user_message"),
        "trace_id": detail.get("trace_id") or error.get("trace_id"),
        # A held call or message: the gateway asks for a person's approval.
        "verdict": detail.get("verdict") or error.get("verdict"),
        "approval_id": detail.get("approval_id") or error.get("approval_id"),
        "body": body,
    }


class Conversation:
    """One customer's conversation: the agent in charge, the history, the app's context."""

    def __init__(self) -> None:
        async def stream(_event: Any) -> None:  # the tools report progress; not shown here
            return None

        self.context = SimpleNamespace(
            state=create_initial_context(),
            thread=None,
            store=None,
            request_context={},
            stream=stream,
        )
        self.agent = triage_agent
        self.items: list[Any] = []

    async def say(self, text: str) -> dict[str, Any]:
        turn: dict[str, Any] = {"user": text}
        history = [*self.items, {"role": "user", "content": text}]
        try:
            result = Runner.run_streamed(self.agent, history, context=self.context, max_turns=12)
            async for _ in result.stream_events():
                pass
        except InputGuardrailTripwireTriggered as exc:
            turn["stopped"] = f"input guardrail {exc.guardrail_result.guardrail.get_name()}"
            turn["info"] = _info(exc.guardrail_result.output.output_info)
            self.items = history
            return turn
        except OutputGuardrailTripwireTriggered as exc:
            turn["stopped"] = f"output guardrail {exc.guardrail_result.guardrail.get_name()}"
            turn["info"] = _info(exc.guardrail_result.output.output_info)
            self.items = history
            return turn
        except APIError as exc:
            status = exc.status_code if isinstance(exc, APIStatusError) else "stream"
            turn["stopped"] = f"gateway refused the model call ({status})"
            turn["info"] = _gateway_refusal(exc)
            self.items = history
            return turn

        names = {}
        tools = []
        for item in result.new_items:
            raw = item.raw_item
            if item.type == "tool_call_item":
                call_id = getattr(raw, "call_id", None) or (
                    raw.get("call_id") if isinstance(raw, dict) else None
                )
                names[call_id] = getattr(raw, "name", None)
                tools.append({"tool": names[call_id], "call_id": call_id, "output": None})
            elif item.type == "tool_call_output_item":
                call_id = (
                    raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
                )
                for call in tools:
                    if call["call_id"] == call_id:
                        call["output"] = str(item.output)[:300]
        self.items = result.to_input_list()
        self.agent = result.last_agent
        turn["agent"] = result.last_agent.name
        turn["reply"] = str(result.final_output)[:400]
        turn["tools"] = [{"tool": t["tool"], "output": t["output"]} for t in tools]
        turn["decisions"] = [
            {k: info.get(k) for k in ("verdict", "approval_id", "trace_id", "user_message")}
            for info in (_info(r.output.output_info) for r in result.tool_input_guardrail_results)
        ]
        # What AgentFox said about each tool's result: a withheld result, a failed tool.
        turn["results"] = [
            {k: info.get(k) for k in ("verdict", "trace_id", "rules_fired")}
            for info in (
                _info(r.output.output_info)
                for r in getattr(result, "tool_output_guardrail_results", [])
            )
        ]
        return turn


async def converse(turns: list[str]) -> list[dict[str, Any]]:
    conversation = Conversation()
    return [await conversation.say(text) for text in turns]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    print(json.dumps(asyncio.run(converse(sys.argv[1:])), indent=1, default=str))
