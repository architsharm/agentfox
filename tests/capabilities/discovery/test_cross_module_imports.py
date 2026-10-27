"""Names an agent takes from another module are followed through its imports.

A repository often defines the same name in several places: a `TOOLS` list per
package, an `agent` per module, a `MODEL` per config. A name defined in exactly one
file was always found; these fixtures define each twice, so only the import says
which one the agent means. Absolute, relative, aliased, module-attribute and
package re-export imports are all followed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from agentfox.capabilities.discovery.repo import scan


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, source in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source).lstrip())


def _by_name(report):
    return {a.name: a for a in report.agents}


def _tools_module(prefix: str) -> str:
    return f"""
        from agents import function_tool

        @function_tool
        def {prefix}_lookup(ref: str) -> str:
            "Look a {prefix} record up."
            return ref

        @function_tool
        def {prefix}_update(ref: str) -> str:
            "Change a {prefix} record."
            return ref

        TOOLS = [{prefix}_lookup, {prefix}_update]

        def get_tools():
            return [{prefix}_lookup]
        """


def test_a_relative_import_picks_its_own_packages_tool_list(tmp_path):
    _write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/billing/__init__.py": "",
            "app/billing/tools.py": _tools_module("invoice"),
            "app/support/__init__.py": "",
            "app/support/tools.py": _tools_module("ticket"),
            "app/support/agent.py": """
                from agents import Agent
                from .tools import TOOLS

                support = Agent(name="Support", instructions="Help.", tools=TOOLS)
                """,
        },
    )
    support = _by_name(scan(tmp_path))["Support"]
    assert support.tools == ["ticket_lookup", "ticket_update"]


def test_an_aliased_absolute_import_of_a_helper(tmp_path):
    _write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/billing/__init__.py": "",
            "app/billing/tools.py": _tools_module("invoice"),
            "app/support/__init__.py": "",
            "app/support/tools.py": _tools_module("ticket"),
            "app/main.py": """
                from agents import Agent
                from app.billing.tools import get_tools as billing_tools

                billing = Agent(name="Billing", instructions="Bill.", tools=billing_tools())
                """,
        },
    )
    billing = _by_name(scan(tmp_path))["Billing"]
    assert billing.tools == ["invoice_lookup"]


def test_a_module_attribute_names_that_modules_list(tmp_path):
    _write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/billing/__init__.py": "",
            "app/billing/tools.py": _tools_module("invoice"),
            "app/support/__init__.py": "",
            "app/support/tools.py": _tools_module("ticket"),
            "app/main.py": """
                from agents import Agent
                from app.support import tools as support_tools
                import app.billing.tools as billing_tools

                support = Agent(name="Support", instructions="Help.", tools=support_tools.TOOLS)
                billing = Agent(
                    name="Billing", instructions="Bill.", tools=[billing_tools.invoice_update]
                )
                """,
        },
    )
    agents = _by_name(scan(tmp_path))
    assert agents["Support"].tools == ["ticket_lookup", "ticket_update"]
    assert agents["Billing"].tools == ["invoice_update"]


def test_a_package_that_re_exports_a_name(tmp_path):
    _write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/billing/__init__.py": "from .tools import TOOLS\n",
            "app/billing/tools.py": _tools_module("invoice"),
            "app/support/__init__.py": "from .tools import TOOLS\n",
            "app/support/tools.py": _tools_module("ticket"),
            "app/main.py": """
                from agents import Agent
                from app.billing import TOOLS

                billing = Agent(name="Billing", instructions="Bill.", tools=TOOLS)
                """,
        },
    )
    assert _by_name(scan(tmp_path))["Billing"].tools == ["invoice_lookup", "invoice_update"]


def test_a_handoff_to_an_agent_variable_two_modules_share(tmp_path):
    _write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/billing.py": """
                from agents import Agent
                agent = Agent(name="Billing", instructions="Bill.")
                """,
            "app/support.py": """
                from agents import Agent
                agent = Agent(name="Support", instructions="Help.")
                """,
            "app/triage.py": """
                from agents import Agent
                from .billing import agent as billing_agent
                from . import support

                triage = Agent(
                    name="Triage", instructions="Route.", handoffs=[billing_agent, support.agent]
                )
                """,
        },
    )
    report = scan(tmp_path)
    keys = {a.key: a.name for a in report.agents}
    edges = {(keys[e.parent], keys[e.child], e.relation) for e in report.agent_edges}
    assert edges == {("Triage", "Billing", "handoff"), ("Triage", "Support", "handoff")}


def test_a_model_constant_comes_from_the_imported_config(tmp_path):
    _write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/fast.py": 'MODEL = "gpt-4.1-mini"\n',
            "app/smart.py": 'MODEL = "gpt-4.1"\n',
            "app/agent.py": """
                from agents import Agent
                from app.smart import MODEL

                planner = Agent(name="Planner", instructions="Plan.", model=MODEL)
                """,
        },
    )
    assert _by_name(scan(tmp_path))["Planner"].model == "gpt-4.1"


def test_a_project_rooted_below_the_repository(tmp_path):
    # `backend/app/...` imported as `app....`: the module path matches by its tail.
    _write(
        tmp_path,
        {
            "backend/app/__init__.py": "",
            "backend/app/billing/tools.py": _tools_module("invoice"),
            "backend/app/support/tools.py": _tools_module("ticket"),
            "backend/app/main.py": """
                from agents import Agent
                from app.support.tools import TOOLS

                support = Agent(name="Support", instructions="Help.", tools=TOOLS)
                """,
        },
    )
    assert _by_name(scan(tmp_path))["Support"].tools == ["ticket_lookup", "ticket_update"]
