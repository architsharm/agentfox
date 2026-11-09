"""The run page links the issue the run raised (it used to stop at the verdict)."""

from __future__ import annotations

from agentfox.core.models import Trace, utcnow
from agentfox.platform.ledger import finding_types
from agentfox.platform.ledger.findings import raise_finding
from tests.conftest import as_user


def test_a_run_lists_the_issues_it_raised(client, session):
    finding_types.register(
        finding_types.FindingType("test_run_issue", "Test", "low", "A fixture.", "tests")
    )
    session.add(Trace(id="tr_with_issue", agent_slug="bot", started_at=utcnow()))
    session.add(Trace(id="tr_other", agent_slug="bot", started_at=utcnow()))
    finding, _ = raise_finding(
        session,
        type="test_run_issue",
        title="Would have blocked bot calling refund",
        subject_id="bot",
        evidence={"trace_id": "tr_with_issue"},
    )
    session.commit()

    headers = as_user("dana@example.com")
    body = client.get("/api/traces/tr_with_issue", headers=headers).json()
    assert [f["id"] for f in body["findings"]] == [finding.id]
    assert client.get("/api/traces/tr_other", headers=headers).json()["findings"] == []
