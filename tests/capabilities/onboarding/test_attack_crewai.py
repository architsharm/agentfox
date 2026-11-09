"""The attack test drives CrewAI: a ``@CrewBase`` crew (``crew.py`` with ``@agent`` /
``@task`` / ``@crew`` methods and ``config/*.yaml``) is located by discovery, built
fresh for each attack, and run with every tool faked at the framework. A hierarchical
crew's manager still delegates to its members (CrewAI's own delegation tools run);
the members' tools never do. Marker files prove it: each real tool writes one.

The first tests need nothing but AgentFox (the locator and the helpers). The rest need
CrewAI, which the main dev environment doesn't have, so they skip there. No model is
called: the crew runs on a scripted fake model (a CrewAI ``BaseLLM``), offline.
"""

from __future__ import annotations

import os
import sys
import textwrap
from types import SimpleNamespace

import pytest

from agentfox.capabilities.onboarding import runner
from agentfox.capabilities.onboarding.attacks import Attack, build_suite
from agentfox.capabilities.onboarding.mapper import map_repository

# --- The locator and helpers: no CrewAI needed -------------------------------------


def test_a_class_method_reference_builds_the_class_and_calls_the_method(tmp_path):
    (tmp_path / "shop.py").write_text(
        textwrap.dedent(
            """
            BUILT = []

            class ShopCrew:
                def __init__(self):
                    BUILT.append(self)

                def crew(self):
                    return ("crew of", self)
            """
        )
    )
    sys.modules.pop("shop", None)
    build = runner.load_agent(tmp_path, "shop", "ShopCrew.crew")
    first, second = build(), build()
    assert first[0] == "crew of" and first[1] is not second[1]  # a fresh instance each time
    assert build.__name__ == "ShopCrew.crew"
    with pytest.raises(AttributeError):
        runner.load_agent(tmp_path, "shop", "ShopCrew.nothing")


def test_crew_inputs_are_the_placeholders_its_tasks_and_agents_take():
    crew = SimpleNamespace(
        tasks=[
            SimpleNamespace(
                description="Plan a trip to {destination} for {age}", expected_output="x"
            ),
            SimpleNamespace(description="Book {destination}", expected_output="By {deadline}"),
        ],
        agents=[SimpleNamespace(role="{topic} researcher", goal="", backstory="{{not_one}}")],
    )
    assert runner.crew_inputs(crew) == ["destination", "age", "deadline", "topic", "not_one"]
    assert runner.crew_inputs(SimpleNamespace(tasks=[], agents=[])) == []


def test_a_crewai_tool_is_recorded_under_the_name_the_map_knows():
    """CrewAI names a tool ``"Search the internet with Serper"`` while a static read of
    ``tools=[SerperDevTool()]`` maps it as ``SerperDevTool``: the attack's faked result
    and its forbidden list use the map's name."""

    class SerperDevTool:
        name = "Search the internet with Serper"

    attack = Attack(id="a", type="t", message="m", forbidden=[], canary=None)
    run = runner._Run(attack, {"SerperDevTool": {"name": "SerperDevTool"}})
    token = runner._CTX.set(run)
    try:
        assert runner._crew_tool_name(SerperDevTool()) == "SerperDevTool"
        func_tool = SimpleNamespace(name="Lookup Order", func=None)
        attack.responses["lookup_order"] = "x"
        assert runner._crew_tool_name(func_tool) == "lookup_order"
    finally:
        runner._CTX.reset(token)
    assert runner._crew_tool_name(SerperDevTool()) == "Search the internet with Serper"


def test_crewai_tool_arguments_are_read_however_they_are_passed():
    schema = SimpleNamespace(model_fields={"order_id": None, "reason": None})
    tool = SimpleNamespace(args_schema=schema)
    assert runner._crew_args(tool, ("A1",), {"reason": "r", "config": {}}) == {
        "order_id": "A1",
        "reason": "r",
    }
    assert runner._crew_input('{"order_id": "A1"}') == {"order_id": "A1"}
    assert runner._crew_input("A1") == {"input": "A1"}
    assert runner._crew_input({"q": 1}) == {"q": 1}


def test_a_missing_model_key_is_said_plainly():
    error = (
        "crewai.MissingAPIKeyError: OPENAI_API_KEY is required for model 'gpt-4o' but is "
        "not set or is still the placeholder 'YOUR_API_KEY'."
    )
    said = runner.explain_model_error(error)
    assert "OpenAI API key isn't set" in said


def test_an_unknown_object_names_crewai_among_what_can_be_driven():
    driver = runner.make_driver(object(), name="Thing", kind="object")
    assert driver.refuse and "CrewAI crews and agents" in driver.refuse


# --- Driving a real crew: needs CrewAI ----------------------------------------------------

FAKE_LLM = '''
import json
import re

from crewai.llms.base_llm import BaseLLM


class Scripted(BaseLLM):
    """Offline. A manager delegates to the Order Clerk; an agent with tools calls each
    once (ReAct text), then answers with everything they returned."""

    def __init__(self, **kw):
        super().__init__(model="scripted", **kw)

    def supports_function_calling(self):
        return False

    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None):
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        text = "\\n".join(str(m.get("content", "")) for m in messages)
        later = "\\n".join(str(m.get("content", "")) for m in messages if m.get("role") != "system")
        found = re.search(r"only one name of \\[([^\\]]*)\\]", text)
        names = [n.strip() for n in found.group(1).split(",")] if found else []
        obs = r"Observation:(?! the result of the action)(.*?)(?:\\n\\n|$)"
        seen = re.findall(obs, later, re.S)
        used = set(re.findall(r"Action: (\\S+)", later))
        delegate = next((n for n in names if "delegate" in n.lower()), None)
        if delegate and not seen:
            task = re.search(r"Current Task: (.*)", text)
            args = {"task": task.group(1) if task else "help", "context": "A customer.",
                    "coworker": "Order Clerk"}
            return f"Thought: delegate\\nAction: {delegate}\\nAction Input: {json.dumps(args)}"
        todo = [n for n in names if n not in used and not delegate]
        if todo:
            return (f"Thought: use a tool\\nAction: {todo[0]}\\n"
                    f"Action Input: {json.dumps({'order_id': 'ORD-4410'})}")
        return "Thought: done\\nFinal Answer: Done: " + " | ".join(s.strip() for s in seen)
'''

CREW = '''
import pathlib

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.tools import BaseTool, tool

from shop_crew.scripted import Scripted

MARKS = pathlib.Path(__file__).resolve().parents[2] / "marks"


@tool("lookup_order")
def lookup_order(order_id: str) -> str:
    """Look up an order by its id."""
    (MARKS / "lookup_order").write_text("ran")
    return "real order"


class CancelOrder(BaseTool):
    name: str = "cancel_order"
    description: str = "Cancel a customer's order."

    def _run(self, order_id: str) -> str:
        (MARKS / "cancel_order").write_text("ran")
        return "really cancelled"


@CrewBase
class ShopCrew:
    """Order support"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def order_clerk(self) -> Agent:
        return Agent(config=self.agents_config["order_clerk"],
                     tools=[lookup_order, CancelOrder()], llm=Scripted(), verbose=True)

    @agent
    def reply_writer(self) -> Agent:
        return Agent(config=self.agents_config["reply_writer"], llm=Scripted())

    @task
    def handle_request(self) -> Task:
        return Task(config=self.tasks_config["handle_request"])

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, process=Process.hierarchical,
                    manager_llm=Scripted(), verbose=True)


def no_inputs() -> Crew:
    clerk = Agent(role="Clerk", goal="help", backstory="b", llm=Scripted())
    return Crew(agents=[clerk], tasks=[Task(description="Say hi.", expected_output="hi",
                                            agent=clerk)])


def with_mcp() -> Agent:
    return Agent(role="Clerk", goal="help", backstory="b", llm=Scripted(),
                 mcps=["https://mcp.example.com/mcp"])
'''

AGENTS_YAML = """
order_clerk:
  role: Order Clerk
  goal: Look up and manage customer orders
  backstory: You handle orders for the shop's customers.
reply_writer:
  role: Reply Writer
  goal: Write the reply to the customer
  backstory: You write short, friendly replies.
"""

TASKS_YAML = """
handle_request:
  description: "A customer wrote: {request}"
  expected_output: A reply to the customer.
"""


@pytest.fixture
def shop(tmp_path, monkeypatch):
    """A ``crewai create crew`` style repository, mapped as ``agentfox init`` maps it."""
    pytest.importorskip("crewai")
    monkeypatch.setenv("CREWAI_DISABLE_TELEMETRY", "true")
    monkeypatch.setenv("CREWAI_TRACING_ENABLED", "false")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    root = tmp_path / "repo"
    pkg = root / "src" / "shop_crew"
    (pkg / "config").mkdir(parents=True)
    (root / "marks").mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "shop_crew"\nversion = "0.1.0"\n')
    (pkg / "__init__.py").write_text("")
    (pkg / "scripted.py").write_text(textwrap.dedent(FAKE_LLM))
    (pkg / "crew.py").write_text(textwrap.dedent(CREW))
    (pkg / "config" / "agents.yaml").write_text(AGENTS_YAML)
    (pkg / "config" / "tasks.yaml").write_text(TASKS_YAML)
    for mod in [m for m in sys.modules if m == "shop_crew" or m.startswith("shop_crew.")]:
        sys.modules.pop(mod)
    mapped = map_repository(root)
    return root, mapped


def _drivers(root, mapped):
    structure = mapped["structure"]
    out = {}
    for ref in mapped["agents"]:
        if not str(ref["attr"]).startswith("ShopCrew."):
            continue  # the extra builders below are loaded by name in their own test
        agent = next(a for a in structure["agents"] if a["id"] == ref["agentId"])
        obj = runner.load_agent(root, ref["module"], ref["attr"])
        tools = [t for t in structure["tools"] if t["agentId"] == agent["id"]]
        out[agent["id"]] = runner.make_driver(
            obj, name=agent["name"], kind=ref["kind"], framework=agent["framework"], tools=tools
        )
    return out


def _run(root, mapped, pick, guards=None):
    structure = mapped["structure"]
    suite = [a for a in build_suite(structure) if pick(a)]
    out = []
    runner.run_suite(
        _drivers(root, mapped),
        suite,
        structure,
        out.append,
        guards=guards,
        concurrency=2,
        root=root,
    )
    return out


def _by_name(mapped):
    return {a["name"]: a for a in mapped["structure"]["agents"]}


def test_discovery_locates_every_crewbase_method(shop):
    _root, mapped = shop
    refs = {
        r["attr"]: (r["module"], r["kind"])
        for r in mapped["agents"]
        if str(r["attr"]).startswith("ShopCrew.")
    }
    assert refs == {
        "ShopCrew.crew": ("shop_crew.crew", "factory"),
        "ShopCrew.order_clerk": ("shop_crew.crew", "factory"),
        "ShopCrew.reply_writer": ("shop_crew.crew", "factory"),
    }


def test_no_crewai_tool_runs_when_an_agent_is_attacked(shop):
    root, mapped = shop
    clerk = _by_name(mapped)["order_clerk"]
    out = _run(root, mapped, lambda a: a.agent_id == clerk["id"] and a.type == "unsafe_tool_use"
               and a.id.endswith("001"))  # fmt: skip
    (result,) = out
    assert {c["tool"] for c in result["calls"]} == {"lookup_order", "cancel_order"}
    assert result["outcome"] == "got_through"
    assert list((root / "marks").iterdir()) == []

    # Once the suite is over the tools are the user's own again, and so is the env.
    module = sys.modules["shop_crew.crew"]
    module.lookup_order.run(order_id="x")
    module.CancelOrder().run(order_id="x")
    assert {p.name for p in (root / "marks").iterdir()} == {"lookup_order", "cancel_order"}
    assert os.environ["CREWAI_TRACING_ENABLED"] == "false"  # the fixture's own value


def test_a_hierarchical_crew_runs_its_manager_who_delegates(shop):
    """The crew gets the attack through its ``{request}`` input; its manager
    (``manager_llm``) delegates with CrewAI's real delegation tool; the member's tool
    calls are recorded under the crew's attack, and none of them runs."""
    root, mapped = shop
    crew = _by_name(mapped)["ShopCrew"]
    out = _run(root, mapped, lambda a: a.agent_id == crew["id"] and not a.skip
               and a.id.endswith("001"))  # fmt: skip
    assert out
    for result in out:
        assert result["outcome"] != "errored", result
        assert {c["tool"] for c in result["calls"]} == {"lookup_order", "cancel_order"}
    assert list((root / "marks").iterdir()) == []


def test_the_after_test_holds_a_crewai_tool_call(shop):
    root, mapped = shop
    clerk = _by_name(mapped)["order_clerk"]

    def guard(surface, payload):
        if surface == "tool_call" and payload["tool"] == "cancel_order":
            return runner.Verdict("block", "enforce", [{"id": "no.cancels", "effect": "block"}],
                                  "Cancelling needs a person.")  # fmt: skip
        return runner.Verdict()

    out = _run(root, mapped, lambda a: a.agent_id == clerk["id"] and a.type == "unsafe_tool_use"
               and a.id.endswith("001"), guards={clerk["id"]: guard})  # fmt: skip
    (result,) = out
    held = [c for c in result["calls"] if c["tool"] == "cancel_order"]
    assert held and held[0]["executed"] is False
    assert result["outcome"] == "stopped"
    assert list((root / "marks").iterdir()) == []


def test_a_crew_with_no_inputs_and_an_agent_with_mcp_are_not_run(shop):
    root, _mapped = shop
    no_inputs = runner.load_agent(root, "shop_crew.crew", "no_inputs")
    driver = runner.make_driver(no_inputs, name="Greeter", kind="factory")
    assert driver.refuse and "takes no inputs" in driver.refuse
    with_mcp = runner.load_agent(root, "shop_crew.crew", "with_mcp")
    driver = runner.make_driver(with_mcp, name="Clerk", kind="factory")
    assert driver.refuse and "an MCP server" in driver.refuse
