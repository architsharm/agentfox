"""A tool the agent was never given: one issue, not two, and granting it closes it."""

from __future__ import annotations

from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import Finding
from tests.conftest import as_user

ADMIN = as_user("admin@example.com")
AGENT = "support-triage"
TOOL = "refunds.lookup_policy"


def _containment() -> list[Finding]:
    with session_scope() as s:
        rows = list(s.scalars(select(Finding).where(Finding.type == "containment")))
        for r in rows:
            s.expunge(r)
        return [r for r in rows if (r.evidence_json or {}).get("tool") == TOOL]


def test_an_ungranted_tool_raises_one_medium_issue_and_granting_it_closes_it(client):
    out = client.post(
        "/v1/guard/tool_call", json={"agent": AGENT, "tool": TOOL, "arguments": {}}
    ).json()
    assert out["verdict"] == "block"
    [issue] = _containment()
    assert issue.evidence_json["cause"] == "no_permission", "not also 'undeclared'"
    assert issue.severity == "medium", "refused and contained: setup, not an incident"

    resp = client.post(
        f"/api/agents/{AGENT}/access",
        json={"tool_key": TOOL, "requires_approval": False},
        headers=ADMIN,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["issues_closed"] == 1
    assert [f.status for f in _containment()] == ["resolved"]


def test_a_call_held_for_its_sign_off_is_not_an_issue(client):
    client.post(
        f"/api/agents/{AGENT}/access",
        json={"tool_key": TOOL, "requires_approval": True},
        headers=ADMIN,
    ).raise_for_status()
    out = client.post(
        "/v1/guard/tool_call", json={"agent": AGENT, "tool": TOOL, "arguments": {}}
    ).json()
    assert out["verdict"] == "escalate"
    assert [f for f in _containment() if f.status == "open"] == []
