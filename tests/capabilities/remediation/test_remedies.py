"""Acting on an issue from the issue: each action does the fix, is audited, and the
issue closes itself only when the condition it is about has actually cleared."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import (
    Agent,
    AuditEntry,
    Capability,
    Credential,
    Decision,
    EvalCase,
    Finding,
    GuardrailFeedback,
    Identity,
    Tool,
    Trace,
    utcnow,
)
from agentfox.platform.ledger.findings import raise_finding
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
DEV = as_user("priya@example.com")
AUDITOR = as_user("aisha@example.com")


def _remedies(client, finding_id: str, headers=ADMIN) -> dict[str, dict]:
    body = client.get(f"/api/findings/{finding_id}", headers=headers).json()
    return {r["key"]: r for r in body["remedies"]}


def _take(client, finding_id: str, key: str, inputs: dict | None = None, headers=ADMIN):
    return client.post(
        f"/api/findings/{finding_id}/remedies/{key}", json={"inputs": inputs or {}}, headers=headers
    )


def _finding(finding_id: str) -> Finding:
    with session_scope() as s:
        f = s.get(Finding, finding_id)
        s.expunge(f)
        return f


def _agent(session, slug: str, **kw) -> Agent:
    agent = Agent(slug=slug, name=slug, registered=True, status="active", **kw)
    session.add(agent)
    session.flush()
    return agent


def _remedied(finding_id: str) -> list[dict]:
    with session_scope() as s:
        return [
            e.payload_json
            for e in s.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == "operator.finding.remedied",
                    AuditEntry.subject_id == finding_id,
                )
            )
        ]


def _closed_automatically(finding_id: str) -> bool:
    """Closed by the re-check (the condition cleared), not by a person's say-so."""
    with session_scope() as s:
        return any(
            (e.payload_json or {}).get("automated") is True
            for e in s.scalars(
                select(AuditEntry).where(
                    AuditEntry.action == "finding.resolved", AuditEntry.subject_id == finding_id
                )
            )
        )


# --- identities -----------------------------------------------------------------


def _wildcard_identity(slug: str = "wild-bot") -> str:
    from agentfox.platform.identity import ensure_identity
    from agentfox.platform.identity.service import assess_posture, grant_capability

    with session_scope() as s:
        agent = _agent(s, slug, declared_tools=["kb.search"])
        identity = ensure_identity(s, agent)
        identity.last_used_at = utcnow()
        grant_capability(s, identity, "*", granted_by="test")
        s.add(Decision(agent_id=agent.id, surface="tool_args", tool_key="crm.lookup"))
        s.add(Decision(agent_id=agent.id, surface="tool_args", tool_key="redteam.exfil"))
        s.flush()
        assess_posture(s)
        return s.scalar(
            select(Finding.id).where(
                Finding.type == "over_privileged", Finding.subject_id == identity.id
            )
        )


def test_over_privileged_wildcard_is_replaced_by_the_tools_it_uses(client):
    fid = _wildcard_identity()
    remedies = _remedies(client, fid)
    assert remedies["narrow_wildcard"]["label"] == "Replace * with its 2 tools"
    assert remedies["narrow_wildcard"]["primary"] and remedies["narrow_wildcard"]["allowed"]

    r = _take(client, fid, "narrow_wildcard")
    assert r.status_code == 200, r.text
    assert r.json()["resolved"] is True

    with session_scope() as s:
        identity = s.scalar(select(Identity).where(Identity.principal == "agent:wild-bot"))
        grants = sorted(
            c.tool_key
            for c in s.scalars(select(Capability).where(Capability.identity_id == identity.id))
        )
    # The tools it used and declared, by name; never the red-team simulation; no `*`.
    assert grants == ["crm.lookup", "kb.search"]
    f = _finding(fid)
    assert f.status == "resolved" and _closed_automatically(fid)
    [entry] = _remedied(fid)
    assert entry["after"]["remedy"] == "narrow_wildcard"


def test_a_developer_may_not_change_grants(client):
    fid = _wildcard_identity("dev-wild-bot")
    assert _remedies(client, fid, headers=DEV)["narrow_wildcard"]["allowed"] is False
    assert _take(client, fid, "narrow_wildcard", headers=DEV).status_code == 403
    assert _finding(fid).status == "open"


def test_retiring_a_stale_identity_revokes_keys_and_grants(client):
    from agentfox.platform.identity import ensure_identity
    from agentfox.platform.identity.service import (
        assess_posture,
        grant_capability,
        issue_credential,
    )

    with session_scope() as s:
        agent = _agent(s, "old-bot")
        identity = ensure_identity(s, agent)
        identity.last_used_at = utcnow() - dt.timedelta(days=400)
        grant_capability(s, identity, "crm.lookup", granted_by="test")
        issue_credential(s, identity)
        assess_posture(s)
        fid = s.scalar(
            select(Finding.id).where(
                Finding.type == "stale_identity", Finding.subject_id == identity.id
            )
        )
        identity_id = identity.id
    assert set(_remedies(client, fid)) == {"revoke_grants", "retire_identity"}

    r = _take(client, fid, "retire_identity")
    assert r.status_code == 200, r.text
    with session_scope() as s:
        identity = s.get(Identity, identity_id)
        assert identity.status == "retired"
        assert not s.scalars(select(Capability).where(Capability.identity_id == identity_id)).all()
        assert all(
            c.revoked_at is not None
            for c in s.scalars(select(Credential).where(Credential.identity_id == identity_id))
        )
    assert _finding(fid).status == "resolved"


# --- agents -----------------------------------------------------------------------


def test_registering_a_shadow_agent_closes_the_issue(client):
    from agentfox.platform.registry.service import observe_agent, unowned_agents

    with session_scope() as s:
        agent, _ = observe_agent(s, "ghost-bot", model="gpt-x")
        unowned_agents(s)
        fid = s.scalar(
            select(Finding.id).where(Finding.type == "shadow_agent", Finding.subject_id == agent.id)
        )
        unowned = s.scalar(
            select(Finding.id).where(
                Finding.type == "unowned_agent", Finding.subject_id == agent.id
            )
        )
    assert set(_remedies(client, fid)) == {"register", "block_agent"}

    r = _take(client, fid, "register", {"owner_email": "o@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["resolved"] is True
    with session_scope() as s:
        agent = s.scalar(select(Agent).where(Agent.slug == "ghost-bot"))
        assert agent.registered and agent.owner_email == "o@example.com"
        assert agent.declared_models == ["gpt-x"]
    # Registering it with an owner also answered "no owner".
    assert _finding(unowned).status == "resolved" and _closed_automatically(unowned)


def test_blocking_needs_a_reason_and_stops_the_agent(client):
    from agentfox.platform.registry.control import state_of
    from agentfox.platform.registry.service import observe_agent

    with session_scope() as s:
        agent, _ = observe_agent(s, "rogue-bot")
        fid = s.scalar(
            select(Finding.id).where(Finding.type == "shadow_agent", Finding.subject_id == agent.id)
        )
    assert _take(client, fid, "block_agent").status_code == 400
    r = _take(client, fid, "block_agent", {"reason": "nobody knows what it is"})
    assert r.status_code == 200, r.text
    with session_scope() as s:
        assert state_of(s, "rogue-bot") == "killed"
    assert _finding(fid).status == "resolved"


def test_assigning_an_owner_closes_an_unowned_issue(client):
    from agentfox.platform.registry.service import unowned_agents

    with session_scope() as s:
        agent = _agent(s, "orphan-bot")
        unowned_agents(s)
        fid = s.scalar(
            select(Finding.id).where(
                Finding.type == "unowned_agent", Finding.subject_id == agent.id
            )
        )
    assert _take(client, fid, "assign_owner", {"owner_email": "not-an-email"}).status_code == 400
    r = _take(client, fid, "assign_owner", {"owner_email": "lead@example.com", "owner_team": "Ops"})
    assert r.status_code == 200, r.text
    assert _finding(fid).status == "resolved"


# --- tool calls -------------------------------------------------------------------


def _containment(slug: str, cause: str, tool: str = "billing.refund") -> str:
    with session_scope() as s:
        agent = _agent(s, slug)
        finding, _ = raise_finding(
            s,
            type="containment",
            severity="high",
            title=f"{slug} tried to {tool} without permission to use it (contained)",
            subject_type="agent",
            subject_id=agent.id,
            fingerprint_parts=(tool, "capability.denied", True),
            evidence={"tool": tool, "rule_id": "capability.denied", "cause": cause},
        )
        return finding.id


def test_a_refused_tool_can_be_granted_with_approval(client):
    fid = _containment("refund-bot", "no_permission")
    remedies = _remedies(client, fid)
    assert {"grant", "grant_with_approval"} <= set(remedies)

    r = _take(client, fid, "grant_with_approval")
    assert r.status_code == 200, r.text
    assert r.json()["resolved"] is True
    with session_scope() as s:
        identity = s.scalar(select(Identity).where(Identity.principal == "agent:refund-bot"))
        [cap] = s.scalars(select(Capability).where(Capability.identity_id == identity.id)).all()
        assert cap.tool_key == "billing.refund" and cap.requires_approval
        # Granted tools are registered, so the grant is not held as undeclared.
        assert s.scalar(select(Tool).where(Tool.key == "billing.refund")) is not None


def test_an_unknown_tool_is_declared_with_the_chosen_impact(client):
    fid = _containment("maker-bot", "unknown_tool", tool="ops.reboot")
    remedies = _remedies(client, fid)
    assert remedies["declare_tool"]["fields"][0]["name"] == "impact"

    assert _take(client, fid, "declare_tool", {"impact": "sideways"}).status_code == 400
    r = _take(client, fid, "declare_tool", {"impact": "irreversible"})
    assert r.status_code == 200, r.text
    with session_scope() as s:
        tool = s.scalar(select(Tool).where(Tool.key == "ops.reboot"))
        assert tool.impact == "irreversible"
        agent = s.scalar(select(Agent).where(Agent.slug == "maker-bot"))
        assert "ops.reboot" in agent.declared_tools
    assert _finding(fid).status == "resolved"


# --- detections -------------------------------------------------------------------


def _detection(slug: str) -> tuple[str, str]:
    with session_scope() as s:
        agent = _agent(s, slug)
        trace = Trace(agent_slug=slug, agent_id=agent.id, intent="what is my balance")
        s.add(trace)
        s.flush()
        decision = Decision(trace_id=trace.id, agent_id=agent.id, surface="input", verdict="block")
        s.add(decision)
        s.flush()
        finding, _ = raise_finding(
            s,
            type="guardrail_detection",
            severity="high",
            title="Blocked on input: INJECTION.DIRECT",
            subject_type="agent",
            subject_id=agent.id,
            fingerprint_parts=("input", "block", "INJECTION.DIRECT"),
            evidence={
                "trace_id": trace.id,
                "decision_id": decision.id,
                "detections": [{"entity_type": "INJECTION.DIRECT", "score": 0.9}],
            },
        )
        return finding.id, trace.id


def test_a_caught_attack_can_be_added_to_tests_and_stays_open(client):
    fid, trace_id = _detection("attacked-bot")
    remedies = _remedies(client, fid)
    assert remedies["add_to_tests"]["primary"]
    assert remedies["view_run"]["href"] == f"/app/traces/{trace_id}"

    for _ in range(2):
        r = _take(client, fid, "add_to_tests")
        assert r.status_code == 200, r.text
    with session_scope() as s:
        # Idempotent: the same run is one case.
        assert (
            len(s.scalars(select(EvalCase).where(EvalCase.source_trace_id == trace_id)).all()) == 1
        )
    # Adding a test does not fix anything, so the issue stays open.
    assert _finding(fid).status == "open"


def test_not_a_problem_records_a_false_positive_and_closes(client):
    fid, _ = _detection("noisy-bot")
    r = _take(client, fid, "false_positive", {"note": "a quoted example"}, headers=DEV)
    assert r.status_code == 200, r.text
    f = _finding(fid)
    assert f.status == "resolved" and f.resolved_by == "priya@example.com"
    with session_scope() as s:
        [fb] = s.scalars(select(GuardrailFeedback)).all()
        assert fb.label == "false_positive" and fb.actor == "priya@example.com"
    # An auditor observes the controls and may not label them.
    fid2, _ = _detection("noisy-bot-2")
    assert _take(client, fid2, "false_positive", headers=AUDITOR).status_code == 403


# --- the catalogue's edges -------------------------------------------------------


def test_an_action_that_does_not_apply_is_refused(client):
    fid, _ = _detection("edge-bot")
    assert _take(client, fid, "narrow_wildcard").status_code == 409
    assert _take(client, fid, "view_run").status_code == 409  # a link, not an action


def test_a_closed_issue_offers_links_only(client):
    fid, _ = _detection("closed-bot")
    client.patch(
        f"/api/findings/{fid}", json={"status": "resolved", "note": "fixed"}, headers=ADMIN
    )
    remedies = _remedies(client, fid)
    assert remedies and all(r["kind"] == "link" for r in remedies.values())
    assert _take(client, fid, "add_to_tests").status_code == 409
