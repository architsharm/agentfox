"""The attack test drives real LangChain / LangGraph and OpenAI Agents SDK agents with
every tool faked at the framework: module-level, class-based, async, factory-built,
late-defined and external-package tools all go to the recorder, and none of them
runs. Marker files prove it: each real tool writes one.

Needs LangChain (and, for its test, the Agents SDK); the main dev environment
deliberately has neither, so these skip there. No model is called: the agents run on
scripted fake models.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain.agents")

from agentfox.capabilities.onboarding import runner  # noqa: E402
from agentfox.capabilities.onboarding.attacks import build_suite  # noqa: E402

GULLIBLE = '''
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool


class Gullible(BaseChatModel):
    """Calls every tool it was given once, then repeats what they returned."""

    specs: list = []

    @property
    def _llm_type(self):
        return "gullible"

    def bind_tools(self, tools, **kwargs):
        return self.model_copy(
            update={"specs": [convert_to_openai_tool(t)["function"] for t in tools]}
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if not any(isinstance(m, ToolMessage) for m in messages):
            calls = [
                {
                    "name": s["name"],
                    "args": {p: "REC-4410" for p in s["parameters"].get("properties", {})},
                    "id": f"call-{i}",
                    "type": "tool_call",
                }
                for i, s in enumerate(self.specs)
            ]
            message = AIMessage(content="", tool_calls=calls)
        else:
            seen = [str(m.content) for m in messages if isinstance(m, ToolMessage)]
            message = AIMessage(content="Done: " + " | ".join(seen))
        return ChatResult(generations=[ChatGeneration(message=message)])
'''

EXTERNAL = '''
import pathlib
from langchain_core.tools import BaseTool

MARKS = pathlib.Path(__file__).parent.parent / "marks"


class VendorExport(BaseTool):
    """A tool that ships in someone else's package."""

    name: str = "vendor_export"
    description: str = "Export records to the vendor."

    def _run(self, record_id: str) -> str:
        (MARKS / "vendor_export").write_text("ran")
        return "exported"
'''

TOOLS = '''
import pathlib
from langchain_core.tools import BaseTool, tool
from langchain.agents import create_agent
from gullible import Gullible
from vendorpkg.tools import VendorExport

MARKS = pathlib.Path(__file__).parent / "marks"


def mark(name):
    (MARKS / name).write_text("ran")
    return "real"


@tool
def read_record(record_id: str) -> str:
    """Read a record."""
    return mark("read_record")


class DeleteRecord(BaseTool):
    name: str = "delete_record"
    description: str = "Delete a record."

    def _run(self, record_id: str) -> str:
        return mark("delete_record")


@tool
async def email_record(record_id: str) -> str:
    """Email a record to someone."""
    return mark("email_record")


def build_tools():
    @tool
    def archive_record(record_id: str) -> str:
        """Archive a record."""
        return mark("archive_record")

    return [archive_record]


def build_agent():
    tools = [read_record, DeleteRecord(), email_record, *build_tools(), VendorExport()]
    return create_agent(model=Gullible(), tools=tools)


agent = build_agent()


class Rebuilt:
    """An agent object that defines a brand-new tool class on every call."""

    def invoke(self, payload, config=None):
        class LateTool(BaseTool):
            name: str = "late_tool"
            description: str = "Change a record."

            def _run(self, record_id: str) -> str:
                return mark("late_tool")

        fresh = create_agent(model=Gullible(), tools=[read_record, LateTool()])
        return fresh.invoke(payload, config=config)


rebuilt = Rebuilt()
'''


def _t(name, risk, what):
    return {"name": name, "agentId": "ag-1", "risk": risk, "args": ["record_id"],
            "whatItDoes": what}  # fmt: skip


STRUCTURE = {
    "agents": [{"id": "ag-1", "name": "Records Bot"}],
    "tools": [
        _t("read_record", "read_only", "Read a record."),
        _t("delete_record", "high", "Delete a record."),
        _t("email_record", "outside", "Email a record to someone."),
        _t("archive_record", "high", "Archive a record."),
        _t("vendor_export", "high", "Export records to the vendor."),
        _t("late_tool", "high", "Change a record."),
    ],
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A user repository with a LangChain agent, plus a vendor package outside it."""
    root = tmp_path / "repo"
    (root / "marks").mkdir(parents=True)
    (root / "gullible.py").write_text(textwrap.dedent(GULLIBLE))
    name = f"records_{tmp_path.name.replace('-', '_')}"
    (root / f"{name}.py").write_text(textwrap.dedent(TOOLS))
    vendor = tmp_path / "site" / "vendorpkg"
    vendor.mkdir(parents=True)
    (vendor / "__init__.py").write_text("")
    (vendor / "tools.py").write_text(
        textwrap.dedent(EXTERNAL).replace(
            'pathlib.Path(__file__).parent.parent / "marks"', repr(str(root / "marks"))
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    for mod in ("gullible", "vendorpkg", "vendorpkg.tools"):
        sys.modules.pop(mod, None)
    return root, name


def _run(driver, ids, guards=None):
    suite = [a for a in build_suite(STRUCTURE) if a.id in ids]
    out = []
    runner.run_suite(driver, suite, STRUCTURE, out.append, guards=guards, concurrency=2)
    return {r["id"]: r for r in out}


def test_no_langchain_tool_runs_however_it_is_built(repo):
    root, name = repo
    agent = runner.load_agent(root, name, "agent")
    driver = runner.make_driver(agent, name="Records Bot", kind="object")
    got = _run(driver, {"unsafe_tool_use-001", "data_leak-001"})
    unsafe = got["unsafe_tool_use-001"]
    # Every tool was called through the framework, and recorded, never run.
    assert {c["tool"] for c in unsafe["calls"]} == {
        "read_record", "delete_record", "email_record", "archive_record", "vendor_export",
    }  # fmt: skip
    assert unsafe["outcome"] == "got_through"
    assert got["data_leak-001"]["outcome"] == "got_through"  # it repeated the faked record
    assert list((root / "marks").iterdir()) == []

    # Once the suite is over the tools are the user's own again.
    module = sys.modules[name]
    module.read_record.invoke({"record_id": "x"})
    module.DeleteRecord().invoke({"record_id": "x"})
    assert {p.name for p in (root / "marks").iterdir()} == {"read_record", "delete_record"}


def test_a_tool_class_defined_during_the_test_is_faked_too(repo):
    root, name = repo
    rebuilt = runner.load_agent(root, name, "rebuilt")
    driver = runner.make_driver(rebuilt, name="Records Bot", kind="object")
    got = _run(driver, {"unsafe_tool_use-002"})
    (result,) = got.values()
    assert {c["tool"] for c in result["calls"]} == {"read_record", "late_tool"}
    assert result["outcome"] == "got_through"
    assert list((root / "marks").iterdir()) == []


def test_a_factory_reference_is_called_to_build_the_agent(repo):
    root, name = repo
    factory = runner.load_agent(root, name, "build_agent")
    driver = runner.make_driver(factory, name="Records Bot", kind="factory")
    assert driver.refuse is None
    _run(driver, {"unsafe_tool_use-003"})
    assert list((root / "marks").iterdir()) == []


def test_the_after_test_applies_verdicts_to_a_langchain_agent(repo):
    """block on a tool call: the call is held and the attack is stopped; redact on the
    reply: the canary is rewritten out."""
    root, name = repo
    agent = runner.load_agent(root, name, "agent")
    driver = runner.make_driver(agent, name="Records Bot", kind="object")
    seen = []

    def guard(surface, payload):
        seen.append(surface)
        if surface == "tool_call" and payload["tool"] in ("delete_record", "archive_record",
                                                          "vendor_export"):  # fmt: skip
            return runner.Verdict("block", "enforce", [{"id": "no.deletes", "effect": "block"}],
                                  "Deleting needs a person.")  # fmt: skip
        if surface == "output":
            import re

            text = re.sub(r"[\w.]+@example\.com", "[email hidden]", payload["content"])
            return runner.Verdict("redact", "observe", [{"id": "pii", "effect": "redact"}],
                                  content=text)  # fmt: skip
        return runner.Verdict()

    got = _run(driver, {"unsafe_tool_use-001", "data_leak-001"}, guards=guard)
    unsafe = got["unsafe_tool_use-001"]
    assert unsafe["outcome"] == "stopped" and unsafe["stoppedBy"]["rule"] == "no.deletes"
    held = {c["tool"] for c in unsafe["calls"] if not c["executed"]}
    assert held == {"delete_record", "archive_record", "vendor_export"}
    leak = got["data_leak-001"]
    assert leak["outcome"] == "stopped" and leak["stoppedBy"]["surface"] == "output"
    assert leak["stoppedBy"]["watching"] is True
    assert {"input", "tool_call", "tool_result", "output"} <= set(seen)
    assert list((root / "marks").iterdir()) == []


# --- OpenAI Agents SDK --------------------------------------------------------------------

SDK = '''
import json
import pathlib

from agents import Agent, function_tool
from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

MARKS = pathlib.Path(__file__).parent / "marks"


def mark(name):
    (MARKS / name).write_text("ran")
    return "real"


@function_tool
def read_record(record_id: str) -> str:
    """Read a record."""
    return mark("read_record")


@function_tool
async def delete_record(record_id: str) -> str:
    """Delete a record."""
    return mark("delete_record")


def make_tool():
    @function_tool
    def archive_record(record_id: str) -> str:
        """Archive a record."""
        return mark("archive_record")

    return archive_record


class Gullible(Model):
    """Calls every tool once, then repeats what they returned."""

    async def get_response(self, system_instructions, input, model_settings, tools,
                           output_schema, handoffs, tracing, **kwargs):
        items = input if isinstance(input, list) else []
        outputs = [
            i for i in items if isinstance(i, dict) and i.get("type") == "function_call_output"
        ]
        if not outputs:
            calls = [
                ResponseFunctionToolCall(
                    type="function_call", call_id=f"c{n}", name=t.name,
                    arguments=json.dumps({"record_id": "REC-4410"}), id=f"fc{n}",
                    status="completed",
                )
                for n, t in enumerate(tools)
            ]
            return ModelResponse(output=calls, usage=Usage(), response_id=None)
        text = "Done: " + " | ".join(str(o.get("output")) for o in outputs)
        message = ResponseOutputMessage(
            id="m1", type="message", role="assistant", status="completed",
            content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
        )
        return ModelResponse(output=[message], usage=Usage(), response_id=None)

    def stream_response(self, *args, **kwargs):
        raise NotImplementedError


agent = Agent(name="Records Bot", instructions="Help.", model=Gullible(),
              tools=[read_record, delete_record, make_tool()])
'''

SDK_STRUCTURE = {
    "agents": [{"id": "ag-1", "name": "Records Bot"}],
    "tools": [
        _t("read_record", "read_only", "Read a record."),
        _t("delete_record", "high", "Delete a record."),
        _t("archive_record", "high", "Archive a record."),
    ],
}


def test_no_openai_agents_sdk_tool_runs(tmp_path):
    pytest.importorskip("agents.tool")
    from agents import set_tracing_disabled

    set_tracing_disabled(True)
    root = tmp_path / "sdkrepo"
    (root / "marks").mkdir(parents=True)
    name = f"sdk_{tmp_path.name.replace('-', '_')}"
    (root / f"{name}.py").write_text(textwrap.dedent(SDK))
    agent = runner.load_agent(root, name, "agent")
    driver = runner.make_driver(agent, name="Records Bot", kind="object")
    assert driver.refuse is None
    suite = [a for a in build_suite(SDK_STRUCTURE) if a.id in ("unsafe_tool_use-001",
                                                               "data_leak-001")]  # fmt: skip
    out = []
    runner.run_suite(driver, suite, SDK_STRUCTURE, out.append, concurrency=2)
    got = {r["id"]: r for r in out}
    unsafe = got["unsafe_tool_use-001"]
    assert unsafe["error"] is None, unsafe["error"]
    assert {c["tool"] for c in unsafe["calls"]} == {
        "read_record", "delete_record", "archive_record",
    }  # fmt: skip
    assert unsafe["outcome"] == "got_through"
    assert got["data_leak-001"]["outcome"] == "got_through"
    assert list((root / "marks").iterdir()) == []


def test_an_sdk_agent_with_a_hosted_tool_is_not_run(tmp_path):
    pytest.importorskip("agents.tool")
    from agents import Agent, WebSearchTool

    agent = Agent(name="Searcher", tools=[WebSearchTool()])
    driver = runner.make_driver(agent, name="Searcher", kind="object")
    assert driver.refuse and "can't fake" in driver.refuse
