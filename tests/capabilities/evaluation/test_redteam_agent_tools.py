"""`agentfox test redteam` attacks the agent through its own tools.

On the Agents SDK seat-booking agent it ran 22 generic probes (SQL, refunds), none
using the agent's own ``update_seat``, and counted blocks by watching rules as blocked.
The probes are now written from the agent's declared tools by the attack library the
dashboard's attack test uses, and the report says what live traffic gets."""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.capabilities.evaluation.redteam import (
    AGENT_TOOLS,
    BUILTIN_PROBES,
    agent_tool_probes,
    run_campaign,
)

STRUCTURE = {
    "agents": [{"id": "ag-1", "name": "Seat Booking Agent", "slug": "seat-booking-agent"}],
    "tools": [
        {
            "id": "t1",
            "name": "update_seat",
            "agentId": "ag-1",
            "risk": "high",
            "args": ["confirmation_number", "new_seat"],
            "whatItDoes": "Update the seat for a given confirmation number.",
        },
        {
            "id": "t2",
            "name": "lookup_booking",
            "agentId": "ag-1",
            "risk": "read_only",
            "args": ["confirmation_number"],
            "whatItDoes": "Look up a booking.",
        },
    ],
    "systems": [],
}


def _seat_agent(session):
    from agentfox.core.models import OnboardingProject
    from agentfox.platform.registry.service import register_agent

    register_agent(
        session,
        slug="seat-booking-agent",
        name="Seat Booking Agent",
        declared_tools=["update_seat", "lookup_booking"],
    )
    session.add(OnboardingProject(project="airline", structure=STRUCTURE))
    session.flush()


def test_probes_are_written_from_the_agents_own_tools(seeded):
    _seat_agent(seeded)
    probes, not_run = agent_tool_probes(seeded, "seat-booking-agent")
    assert probes and not not_run
    generic = {p.key for p in BUILTIN_PROBES}
    assert not generic & {p.key for p in probes}
    assert all((p.target_class or "").startswith(AGENT_TOOLS) for p in probes)
    # The unsafe-use attacks name its own tool; its call is probed as a tool call.
    unsafe = [p for p in probes if p.category == "unsafe_tool_use" and p.kind == "content"]
    assert unsafe and all("update_seat" in p.payload for p in unsafe)
    calls = [p for p in probes if p.kind == "tool_call"]
    assert [c.tool_key for c in calls] == ["update_seat"]
    assert set(calls[0].arguments) == {"confirmation_number", "new_seat"}
    assert not calls[0].provision  # the real tool and grants, nothing provisioned
    # An injection is the record it reads; a leak is the reply that hands data over.
    assert {p.surface for p in probes if p.category == "prompt_injection"} >= {"tool_result"}
    leaks = [p for p in probes if p.category == "data_leak"]
    assert leaks and {p.surface for p in leaks} == {"output"}
    assert all("@example.com" in p.payload for p in leaks)
    # Ordinary requests, which the guardrails must let through.
    controls = [p for p in probes if not p.expect_blocked]
    assert controls and all(p.category == "benign_control" for p in controls)


def test_a_read_only_agent_says_which_sets_dont_apply(seeded):
    from agentfox.core.models import OnboardingProject
    from agentfox.platform.registry.service import register_agent

    register_agent(seeded, slug="faq-agent", name="FAQ Agent", declared_tools=["faq_lookup"])
    seeded.add(
        OnboardingProject(
            project="faq",
            structure={
                "agents": [{"id": "f", "name": "FAQ Agent", "slug": "faq-agent"}],
                "tools": [{"name": "faq_lookup", "agentId": "f", "risk": "read_only"}],
            },
        )
    )
    seeded.flush()
    probes, not_run = agent_tool_probes(seeded, "faq-agent")
    assert probes
    assert [s["type"] for s in not_run] == ["unsafe_tool_use"]
    assert not [p for p in probes if p.kind == "tool_call"]


def test_the_campaign_counts_what_live_traffic_gets(seeded):
    _seat_agent(seeded)
    probes, _ = agent_tool_probes(seeded, "seat-booking-agent", ["jailbreak"])
    campaign = run_campaign(seeded, "seat-booking-agent", builtin=False, extra_probes=probes)
    s = campaign.summary_json
    assert set(campaign.probes) == {p.key for p in probes}
    assert s["tool_probes"] == len(probes)
    assert s["attacks_stopped_live"] + s["attacks_watching"] == s["attacks_blocked"]
    assert s["attacks_through_live"] == s["attacks_run"] - s["attacks_stopped_live"]


def test_the_cli_attacks_through_its_tools_and_ends_with_a_verdict(seeded):
    _seat_agent(seeded)
    seeded.commit()
    out = CliRunner().invoke(
        app, ["test", "redteam", "seat-booking-agent", "--allow-escapes"], env={"COLUMNS": "200"}
    )
    assert out.exit_code == 0, out.output
    text = " ".join(out.output.split())
    assert "probes written from its 2 tools (attacks aim at update_seat)" in text
    assert "watched" in text and "got through" in text  # the per-set columns
    assert "normal requests" in text
    assert "Verdict:" in text and "attacks get through today" in text
    # The generic library only on request.
    assert "injection.direct_override" not in text


def test_an_agent_with_no_known_tools_falls_back_to_the_generic_probes(seeded):
    from agentfox.platform.registry.service import register_agent

    register_agent(seeded, slug="bare-agent", name="Bare")
    seeded.commit()
    out = CliRunner().invoke(app, ["test", "redteam", "bare-agent", "--allow-escapes"])
    assert out.exit_code == 0, out.output
    assert "it declares no tools and holds no tool grants" in " ".join(out.output.split())
