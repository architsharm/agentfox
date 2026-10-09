"""Govern the airline demo with AgentFox, without touching its agents or tools.

* Every model call goes through the AgentFox gateway (OpenAI-compatible proxy).
* Every agent gets AgentFox input and output guardrails.
* Every function tool gets an AgentFox tool-call guardrail (`airline.<tool>`).
"""

from __future__ import annotations

import os

from agents import (
    FunctionTool,
    set_default_openai_api,
    set_default_openai_client,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from agentfox.frameworks.openai_agents import (
    agentfox_input_guardrail,
    agentfox_output_guardrail,
    agentfox_tool_guardrail,
)
from agentfox.frameworks.sdk import AgentFox

GATEWAY = os.environ.get("AGENTFOX_GATEWAY", "http://127.0.0.1:8091")
AGENT = os.environ.get("AGENTFOX_AGENT", "airline-cs")

set_tracing_disabled(True)
set_default_openai_api("chat_completions")
set_default_openai_client(
    AsyncOpenAI(
        base_url=f"{GATEWAY}/v1",
        api_key=os.environ.get("AGENTFOX_API_KEY", "unused"),
        default_headers={"X-AgentFox-Agent": AGENT},
    )
)

fox = AgentFox(AGENT, base_url=GATEWAY, api_key=os.environ.get("AGENTFOX_API_KEY"))


def govern(*agents) -> None:
    for agent in agents:
        agent.input_guardrails = [*agent.input_guardrails, agentfox_input_guardrail(client=fox)]
        agent.output_guardrails = [*agent.output_guardrails, agentfox_output_guardrail(client=fox)]
        for tool in agent.tools:
            if isinstance(tool, FunctionTool):
                guard = agentfox_tool_guardrail(fox, tools={tool.name: f"airline.{tool.name}"})
                tool.tool_input_guardrails = [*(tool.tool_input_guardrails or []), guard]
