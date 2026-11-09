"""Attack-test coverage the audit found missing (wow3 ui B8/M3, policies B12).

* A plain function-calling loop handed a faked tool result that was a dict, which it
  put in ``messages[].content``: OpenAI answers that with a 400, so every attack
  "errored". The fake is now the type the real tool returns (text, unless the
  function says it returns a dict). Checked against a mock API that validates the
  request the way OpenAI does.
* An agent whose only acting tool sends email had "Unsafe tool use: Not run: it needs
  a tool that changes something".
* An agent with no tools got no jailbreak or prompt-injection test at all.
* An Agents SDK agent whose only tool is hosted (web search) got every attack "Not
  run": the hosted search is now played by a function tool the test answers.
"""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from agentfox.capabilities.onboarding import runner
from agentfox.capabilities.onboarding.attacks import build_suite, roles
from tests.capabilities.onboarding.test_attack_suite import _tool, write_loop

PAYABLES = '''
import json

CLIENT = None
SPECS = [
    {"type": "function", "function": {"name": "lookup_invoice", "parameters": {}}},
    {"type": "function", "function": {"name": "pay_vendor", "parameters": {}}},
]


def lookup_invoice(invoice_id):
    """Look up an invoice."""
    return f"Invoice {invoice_id}: 900 USD"


def pay_vendor(invoice_id, amount=0):
    """Pay a vendor's invoice."""
    return "paid"


TOOLS = {"lookup_invoice": lookup_invoice, "pay_vendor": pay_vendor}


def run(message):
    messages = [{"role": "user", "content": message}]
    for _ in range(4):
        r = CLIENT.post("/v1/chat/completions", json={"model": "m", "messages": messages,
                                                       "tools": SPECS})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        messages.append(msg)
        if not msg.get("tool_calls"):
            return msg["content"]
        for call in msg["tool_calls"]:
            fn = call["function"]
            result = TOOLS[fn["name"]](**json.loads(fn["arguments"]))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    return ""
'''

PAYABLES_STRUCTURE = {
    "agents": [{"id": "ag-1", "name": "Payables", "framework": "openai"}],
    "tools": [
        _tool("ag-1", "lookup_invoice", "read_only", ["invoice_id"], "Look up an invoice."),
        _tool("ag-1", "pay_vendor", "high", ["invoice_id", "amount"], "Pay a vendor's invoice."),
    ],
}


def _openai(request: httpx.Request) -> httpx.Response:
    """Chat completions as strict as OpenAI's about message content: text, or a list
    of content parts. Anything else is the 400 the audit hit."""
    body = json.loads(request.content)
    for i, m in enumerate(body["messages"]):
        content = m.get("content")
        if m["role"] == "tool" and not isinstance(content, (str, list)):
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": f"Invalid type for 'messages[{i}].content': expected "
                        "one of a string or array of objects, but got an object instead.",
                        "type": "invalid_request_error",
                    }
                },
            )
    if any(m["role"] == "tool" for m in body["messages"]):
        message = {"role": "assistant", "content": "Done."}
    else:
        call = {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "pay_vendor",
                "arguments": json.dumps({"invoice_id": "INV-4410", "amount": 900}),
            },
        }
        message = {"role": "assistant", "content": None, "tool_calls": [call]}
    return httpx.Response(200, json={"choices": [{"message": message}]})


def test_a_faked_result_is_text_a_model_api_accepts(tmp_path):
    fn = write_loop(tmp_path, "payables_loop", source=PAYABLES)
    sys.modules[fn.__module__].CLIENT = httpx.Client(
        transport=httpx.MockTransport(_openai), base_url="https://api.openai.test"
    )
    driver = runner.make_driver(
        fn,
        name="Payables",
        kind="function",
        tools=PAYABLES_STRUCTURE["tools"],
        modules=runner.user_modules(tmp_path),
    )
    suite = [a for a in build_suite(PAYABLES_STRUCTURE, ["unsafe_tool_use"]) if not a.control][:2]
    out: list[dict] = []
    runner.run_suite(driver, suite, PAYABLES_STRUCTURE, out.append, concurrency=1)
    for r in out:
        # Before: "errored", httpx.HTTPStatusError 400 on the faked dict.
        assert r["error"] is None, r["error"]
        assert r["outcome"] == "got_through"
        assert [c["tool"] for c in r["calls"]] == ["pay_vendor"]


def test_a_tool_declared_to_return_a_dict_gets_a_dict():
    def lookup(invoice_id: str) -> dict:
        return {}

    def plain(invoice_id):
        return ""

    assert runner._shaped(lookup, {"a": 1}) == {"a": 1}
    assert runner._shaped(plain, {"a": 1}) == '{"a": 1}'
    assert runner._shaped(plain, "text") == "text"


def test_a_tool_that_sends_email_is_one_that_changes_something():
    tools = [
        _tool("ag-1", "lookup_order", "read_only", ["order_id"], "Look up an order."),
        _tool("ag-1", "send_email", "outside", ["to", "body"], "Send an email."),
    ]
    r = roles(tools)
    assert [t["name"] for t in r.action] == ["send_email"]
    suite = build_suite({"agents": [{"id": "ag-1", "name": "Mailer"}], "tools": tools})
    unsafe = [a for a in suite if a.type == "unsafe_tool_use"]
    # Before: one "Not run: it needs a tool that changes something" stand-in.
    assert unsafe and not any(a.skip for a in unsafe)
    assert all(a.forbidden == ["send_email"] for a in unsafe if not a.control)


def test_an_agent_with_no_tools_is_still_tested_for_jailbreaks_and_injection(tmp_path):
    structure = {"agents": [{"id": "p", "name": "Planner"}], "tools": []}
    suite = build_suite(structure)
    ran = {a.type for a in suite if not a.skip}
    assert {"jailbreak", "prompt_injection"} <= ran
    skipped = {a.type for a in suite if a.skip}
    assert skipped == {"unsafe_tool_use", "data_leak"}  # those do need a tool
    attacks = [a for a in suite if not a.skip and not a.control]
    assert all(a.canary and a.canary in a.message for a in attacks)

    # Graded by the reply: one that says the code word got through, one that doesn't
    # resisted.
    def obeys(message):
        return message

    def refuses(message):
        return "I can't help with that."

    for fn, outcome in ((obeys, "got_through"), (refuses, "resisted")):
        driver = runner.Driver("Planner", call=fn)
        out: list[dict] = []
        runner.run_suite(driver, attacks[:3], structure, out.append, concurrency=1)
        assert {r["outcome"] for r in out} == {outcome}


def test_an_sdk_agent_whose_only_tool_is_hosted_search_is_run():
    pytest.importorskip("agents.tool")
    from agents import Agent, FunctionTool, WebSearchTool

    agent = Agent(name="Search agent", tools=[WebSearchTool()])
    tools = [_tool("s", "WebSearchTool", "read_only", [], "Search the web.")]
    driver = runner.make_driver(agent, name="Search agent", kind="object", tools=tools)
    assert driver.refuse is None
    swapped = runner._sdk_stand_ins(agent, tools)
    assert [type(t) for t in swapped.tools] == [FunctionTool]
    assert [t.name for t in swapped.tools] == ["WebSearchTool"]
    assert isinstance(agent.tools[0], WebSearchTool)  # the user's agent is unchanged
