"""`agentfox scan` says one thing per count, and `--fail` says what it checked.

The third launch audit saw "can reach: 1 tool" above agents listed with five, "can
reach: 0 tools" over a folder of no source, and `scan --fail` exit 0 under a CRITICAL
lethal trifecta.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()

CREW = """
from crewai import Agent, Crew
from crewai_tools import SerperDevTool, ScrapeWebsiteTool
from crewai.tools import tool

@tool("lookup_booking")
def lookup_booking(ref: str) -> str:
    \"\"\"Look up a booking.\"\"\"
    return ""

scout = Agent(role="scout", goal="g", backstory="b",
              tools=[SerperDevTool(), ScrapeWebsiteTool(), lookup_booking])
crew = Crew(agents=[scout], tasks=[])
"""


def _scan(root: Path, *args: str):
    return runner.invoke(app, ["scan", str(root), "--no-submit", *args])


def test_can_reach_counts_every_tool_an_agent_is_handed(tmp_path):
    (tmp_path / "crew.py").write_text(textwrap.dedent(CREW))
    result = _scan(tmp_path)
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "can reach: 3 tools" in out
    assert "SerperDevTool" in out and "a library tool" in out


def test_a_folder_of_no_source_claims_no_reach(tmp_path):
    (tmp_path / "README.md").write_text("hi\n")
    result = _scan(tmp_path)
    assert result.exit_code == 0, result.output
    assert "can reach" not in result.output


TRIFECTA = """
from agents import Agent, function_tool
import agentfox

agentfox.auto("notes")

@function_tool
def read_customer_records(customer_id: str) -> str:
    \"\"\"Read the customer's private records from the CRM database.\"\"\"
    return ""

@function_tool
def fetch_web_page(url: str) -> str:
    \"\"\"Fetch any web page from the internet.\"\"\"
    return ""

@function_tool
def send_email(to: str, body: str) -> str:
    \"\"\"Send an email to any address.\"\"\"
    return ""

helper = Agent(name="Helper", instructions="help",
               tools=[read_customer_records, fetch_web_page, send_email])
"""


def test_fail_says_it_checks_ungoverned_calls_only(tmp_path):
    (tmp_path / "app.py").write_text(textwrap.dedent(TRIFECTA))
    result = _scan(tmp_path, "--fail")
    out = " ".join(result.output.split())
    assert "lethal trifecta" in out.lower(), out
    assert result.exit_code == 0
    assert "--fail passed" in out and "ungoverned model calls only" in out
