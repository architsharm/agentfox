"""The start checklist and the attention list say what is actually true.

Two ways they did not:

* "Turn enforcement on" ticked as soon as any decision had been recorded in enforce
  mode. The shipped tool-containment pack enforces from the first call, so the step
  read as done on day one while baseline — the policy the step is about — was still
  only observing.
* A draft agent proposed by a repo scan is unregistered by construction, and the
  attention list raised it as a high-severity "running and was never registered"
  item. It never ran; it is waiting for review, which the agents page already shows.
"""

from __future__ import annotations

from tests.conftest import as_user

ADMIN = as_user("admin@example.com")


def _step(client, step_id: str) -> dict:
    body = client.get("/api/onboarding", headers=ADMIN).json()
    return next(s for s in body["steps"] if s["id"] == step_id)


def test_enforce_step_is_not_done_while_baseline_observes(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Decision
    from agentfox.policy.store import active_layers

    with session_scope() as session:
        modes = {layer.document.key: layer.document.mode for layer in active_layers(session)}
        assert modes.get("baseline") == "observe"
        # What tool containment produces from the first call.
        session.add(
            Decision(surface="tool_call", tool_key="refund", mode="enforce", verdict="block")
        )

    assert _step(client, "enforce")["done"] is False


def test_enforce_step_is_done_once_baseline_enforces(client):
    from agentfox.core.db import session_scope
    from agentfox.policy.store import set_mode

    with session_scope() as session:
        set_mode(session, "baseline", "enforce")

    assert _step(client, "enforce")["done"] is True


def test_a_scan_proposed_draft_is_not_an_unregistered_agent(client):
    from agentfox.core.db import session_scope
    from agentfox.registry.service import register_agent

    with session_scope() as session:
        register_agent(session, slug="scan-found-bot", draft=True)

    body = client.get("/api/attention", headers=ADMIN).json()
    assert not [i for i in body["items"] if i["subject"] == "scan-found-bot"]


def test_an_agent_seen_in_traffic_without_registration_still_is(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    with session_scope() as session:
        session.add(Agent(slug="ghost-bot", registered=False, status="active"))

    body = client.get("/api/attention", headers=ADMIN).json()
    shadow = [i for i in body["items"] if i["subject"] == "ghost-bot"]
    assert shadow and shadow[0]["kind"] == "shadow_agent"
