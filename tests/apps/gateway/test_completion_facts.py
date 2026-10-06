"""Completion facts can be reported over HTTP and the SDK (#47).

`/v1/guard/input` with `surface: "completion"` had no field for the facts the
`completion_requires` rules check, so every claim of being done was held by
`completion.unverified_claim`, however well verified.
"""

from __future__ import annotations

from agentfox.frameworks.sdk import AgentFox

CLAIM = "Your refund has been processed."


def _rules(body):
    return [r["rule_id"] for r in body["rules_fired"]]


def test_reported_facts_satisfy_the_completion_gate_over_http(client):
    body = {"agent": "support-triage", "content": CLAIM, "surface": "completion"}
    unverified = client.post("/v1/guard/input", json=body).json()
    assert "completion.unverified_claim" in _rules(unverified)

    verified = client.post(
        "/v1/guard/input", json={**body, "completion": {"work_verified": True}}
    ).json()
    assert "completion.unverified_claim" not in _rules(verified)
    assert verified["effective_verdict"] == "allow", verified

    reported_false = client.post(
        "/v1/guard/input", json={**body, "completion": {"work_verified": False}}
    ).json()
    assert "completion.unverified_claim" in _rules(reported_false)


def test_reported_facts_satisfy_the_completion_gate_in_the_sdk(seeded):
    fox = AgentFox("support-triage", session=seeded)
    assert "completion.unverified_claim" in _rules(fox.check(CLAIM, surface="completion"))
    verified = fox.check(CLAIM, surface="completion", completion={"work_verified": True})
    assert "completion.unverified_claim" not in _rules(verified)
