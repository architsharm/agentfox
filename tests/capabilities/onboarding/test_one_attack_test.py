"""One attack test with one history (wow3 ui B4, agents C4, ui M8).

* Testing → Attack tests said "No attack tests yet" after the agent panel had run
  two, and its Run button ran a different test with different numbers. It now lists
  the panel's runs (``GET /api/onboarding/runs``) and starts the same test
  (``POST /api/onboarding/agents/{slug}/tests``).
* The panel is the project's test, but shown on each agent's page: one agent's page
  said another agent "couldn't be found". A run is now shown as the agent saw it.
* "20 not run: Not run: it needs ..." said the lead twice.
"""

from __future__ import annotations

from agentfox.capabilities.onboarding import runner, service
from tests.capabilities.onboarding.test_attack_policies import ME, _connect, _poll
from tests.capabilities.onboarding.test_attack_suite import LOOP_STRUCTURE, loop_driver

TWO = {
    "agents": [*LOOP_STRUCTURE["agents"], {"id": "ag-2", "name": "Planner", "framework": "openai"}],
    "tools": LOOP_STRUCTURE["tools"],
}


def _two_agents_tested(client, tmp_path):
    api = _connect(client, structure=TWO)
    job = _poll(api)
    structure = job["structure"]
    drivers = {
        "ag-1": loop_driver(tmp_path, "one_test_loop"),
        "ag-2": runner.Driver(
            "Planner", refuse="Not run: AgentFox couldn't find where Planner is created."
        ),
    }
    from agentfox.capabilities.onboarding.attacks import build_suite

    out: list[dict] = []
    runner.run_suite(drivers, build_suite(structure, job["sets"]), structure, out.append)
    api.post(f"/runner/runs/{job['runId']}/results", {"results": out, "done": True})
    return api, structure


def test_an_agents_page_shows_its_own_attacks(client, tmp_path):
    _api, structure = _two_agents_tested(client, tmp_path)
    slugs = {a["name"]: a["slug"] for a in structure["agents"]}

    whole = client.get("/api/onboarding/projects/people/tests", headers=ME).json()["first"]
    loop = client.get(
        f"/api/onboarding/projects/people/tests?agent={slugs['People Loop']}", headers=ME
    ).json()["first"]
    planner = client.get(
        f"/api/onboarding/projects/people/tests?agent={slugs['Planner']}", headers=ME
    ).json()["first"]
    assert loop["total"] + planner["total"] == whole["total"]
    # The loop's page doesn't carry the planner's "couldn't find" reason.
    assert not any("Planner" in (t.get("notRunReason") or "") for t in loop["byType"])
    assert loop["notRun"] == 0 and loop["ran"] > 0
    reasons = {t["notRunReason"] for t in planner["byType"] if t.get("notRunReason")}
    # The planner has no tools: two sets don't apply; the rest couldn't run. Each
    # reason is said once, without a second "Not run:" lead.
    assert "AgentFox couldn't find where Planner is created." in reasons
    assert not any(r.lower().startswith("not run") for r in reasons)


def test_testing_lists_the_panels_runs_and_runs_the_same_test(client, tmp_path):
    _api, structure = _two_agents_tested(client, tmp_path)
    slug = next(a["slug"] for a in structure["agents"] if a["name"] == "People Loop")

    listed = client.get("/api/onboarding/runs", headers=ME).json()["runs"]
    assert len(listed) == 1 and listed[0]["project"] == "people"
    assert {a["name"] for a in listed[0]["agents"]} == {"People Loop", "Planner"}
    mine = client.get(f"/api/onboarding/runs?agent={slug}", headers=ME).json()["runs"]
    assert [a["name"] for a in mine[0]["agents"]] == ["People Loop"]
    panel = client.get(f"/api/onboarding/projects/people/tests?agent={slug}", headers=ME).json()
    assert mine[0]["gotThrough"] == panel["first"]["gotThrough"]  # one set of numbers

    started = client.post(f"/api/onboarding/agents/{slug}/tests", headers=ME)
    assert started.status_code == 200, started.text
    assert started.json()["project"] == "people"
    again = client.get("/api/onboarding/runs", headers=ME).json()["runs"]
    assert len(again) == 2 and again[0]["status"] in ("queued", "running")
    assert client.post("/api/onboarding/agents/nobody/tests", headers=ME).status_code == 404


def test_init_says_each_not_run_reason_once(tmp_path):
    """Found live (agents C4): ~30 "N/296 NOT RUN Not run: ..." lines for sets that
    don't apply to tool-less agents. Each reason is said once, with its agent."""
    from io import StringIO

    from rich.console import Console

    from agentfox.capabilities.onboarding import client as init_client
    from agentfox.capabilities.onboarding.attacks import build_suite

    class Api:
        def __init__(self):
            self.results = []

        def post(self, path, body=None):
            self.results.extend((body or {}).get("results") or [])
            return {}

    structure = {"agents": [{"id": f"a{i}", "name": f"Writer{i}"} for i in range(3)], "tools": []}
    api, buf = Api(), StringIO()
    job = {"runId": "r-1", "phase": "before", "structure": structure}
    init_client._run_job(Console(file=buf, width=200), api, tmp_path, {}, job, {})
    said = buf.getvalue()
    assert "Not run: Not run" not in said and "NOT RUN  Not run" not in said
    lines = [line for line in said.splitlines() if "NOT RUN" in line]
    assert len(lines) == len(set(lines))
    # The agents can't be found: one line each, not one per attack.
    assert sum("couldn't find where Writer0" in line for line in lines) == 1
    assert len(api.results) == len(build_suite(structure))


def test_the_reason_beside_the_count_is_said_once():
    results = [
        {"id": f"a{i}", "type": "data_leak", "outcome": "not_run", "reason": why}
        for i, why in enumerate(
            ["Not run: it needs a tool that reads records, and this agent has none."] * 3
            + ["Not run: something rarer."]
        )
    ]
    assert service.not_run_reason(results) == (
        "it needs a tool that reads records, and this agent has none."
    )
