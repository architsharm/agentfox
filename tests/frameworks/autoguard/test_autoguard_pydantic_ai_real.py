"""`agentfox.auto()` and a real pydantic-ai agent with an ``output_type``, over a mock
HTTP transport (no network, no key). Skipped where pydantic-ai is not installed.

Found by the 2026-11-08 re-audit (pydantic-ai's bank_support example): the agent
answers through its ``final_result`` output tool, which was decided as a tool call and
reported as "tried to final_result without permission" on every run.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pydantic_ai")
openai = pytest.importorskip("openai")
httpx = pytest.importorskip("httpx")

from pydantic import BaseModel  # noqa: E402

from agentfox.core.db import session_scope  # noqa: E402
from agentfox.core.models import Decision, Finding, Span, Tool  # noqa: E402
from agentfox.frameworks.autoguard import auto, off  # noqa: E402


class SupportOutput(BaseModel):
    support_advice: str
    block_card: bool
    risk: int


def _completion(*calls: tuple[str, dict]) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args)},
                        }
                        for i, (name, args) in enumerate(calls)
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@pytest.fixture(autouse=True)
def _reset():
    yield
    off()


def _agent(*replies: dict):
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    script = list(replies)

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=script.pop(0))

    client = openai.AsyncOpenAI(
        api_key="sk-test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    model = OpenAIChatModel("gpt-4o-mini", provider=OpenAIProvider(openai_client=client))
    agent = Agent(model, output_type=SupportOutput, instructions="You are a bank's support.")

    @agent.tool_plain
    def customer_balance() -> str:
        """Returns the customer's current account balance."""
        return "$123.45"

    return agent


def test_the_output_tool_is_the_answer_and_a_real_tool_is_still_decided(isolated_db):
    advice = {"support_advice": "Your balance is $123.45", "block_card": False, "risk": 1}
    agent = _agent(
        _completion(("customer_balance", {})),
        _completion(("final_result", advice)),
    )
    from agentfox.platform.identity.service import ensure_identity, grant_capability
    from agentfox.platform.registry.service import register_agent

    with session_scope() as session:  # as `agentfox up` grants the agent's own tools
        registered = register_agent(session, "support-agent", name="support-agent")
        grant_capability(session, ensure_identity(session, registered), "customer_balance")
    governed = auto(agent="support-agent", quiet=True)

    result = agent.run_sync("What is my balance?")
    assert result.output.support_advice == "Your balance is $123.45"
    assert governed.calls_blocked == 0
    with session_scope() as session:
        decided = [d.tool_key for d in session.query(Decision).filter_by(surface="tool_args")]
        assert decided == ["customer_balance"]
        assert session.query(Tool).filter_by(key="final_result").count() == 0
        assert session.query(Finding).filter(Finding.type == "containment").count() == 0
        outputs = [
            s.attributes_json.get("agentfox.output", "")
            for s in session.query(Span).filter(Span.kind == "llm")
        ]
        assert any("Your balance is $123.45" in text for text in outputs)
