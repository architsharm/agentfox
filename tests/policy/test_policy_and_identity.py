"""Pillars 2 and 6 — policy evaluation, least privilege, delegation, approvals."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.core.models import utcnow
from agentfox.identity import (
    check_capability,
    delegate,
    ensure_identity,
    expire_stale_approvals,
    grant_capability,
    issue_credential,
    request_approval,
    resolve_approval,
    rotate_credential,
    verify_credential,
)
from agentfox.policy import (
    NativePolicyEngine,
    PolicyDocument,
    PolicyInput,
    combine,
    compile_to_rego,
    save_policy,
    set_mode,
)
from agentfox.registry.service import register_agent

POLICY = """
key: test
mode: enforce
default_effect: allow
rules:
  - id: injection.block
    when: {detection: {entity_prefix: INJECTION, min_score: 0.8}}
    effect: block
    controls: [NOM-RTG-01]
  - id: pii.redact
    when: {surface: [output], detection: {entity_prefix: PII, min_score: 0.6}}
    effect: redact
  - id: taint.irreversible
    when: {tool_impact: [irreversible], taint_exceeds: user}
    effect: escalate
  - id: amount.cap
    when: {tool: "payments.*", argument: {path: amount, op: gte, value: 1000}}
    effect: block
"""


@pytest.fixture
def doc() -> PolicyDocument:
    return PolicyDocument.from_yaml(POLICY)


@pytest.fixture
def engine() -> NativePolicyEngine:
    return NativePolicyEngine()


# ---------------------------------------------------------------------------
# Policy evaluation (P6-1)
# ---------------------------------------------------------------------------


def test_detection_rule_fires(doc, engine):
    decision = engine.evaluate(
        doc,
        PolicyInput(detections=[{"entity_type": "INJECTION.OVERRIDE", "score": 0.9}]),
    )
    assert decision.verdict == "block"
    assert decision.rules_fired[0].rule_id == "injection.block"
    assert decision.rules_fired[0].controls == ["NOM-RTG-01"]


def test_score_below_threshold_does_not_fire(doc, engine):
    decision = engine.evaluate(
        doc, PolicyInput(detections=[{"entity_type": "INJECTION.OVERRIDE", "score": 0.5}])
    )
    assert decision.verdict == "allow"


def test_strongest_effect_wins(doc, engine):
    decision = engine.evaluate(
        doc,
        PolicyInput(
            surface="output",
            detections=[
                {"entity_type": "PII.EMAIL", "score": 0.9},
                {"entity_type": "INJECTION.OVERRIDE", "score": 0.9},
            ],
        ),
    )
    assert decision.verdict == "block"  # block outranks redact
    assert {r.rule_id for r in decision.rules_fired} == {"injection.block", "pii.redact"}


def test_argument_constraint(doc, engine):
    blocked = engine.evaluate(
        doc, PolicyInput(tool_key="payments.transfer", arguments={"amount": 5000})
    )
    allowed = engine.evaluate(
        doc, PolicyInput(tool_key="payments.transfer", arguments={"amount": 100})
    )
    assert blocked.verdict == "block"
    assert allowed.verdict == "allow"


def test_taint_condition(doc, engine):
    tainted = engine.evaluate(
        doc,
        PolicyInput(tool_impact="irreversible", taint={"max_source": "tool_result"}),
    )
    clean = engine.evaluate(
        doc, PolicyInput(tool_impact="irreversible", taint={"max_source": "user"})
    )
    assert tainted.verdict == "escalate"
    assert clean.verdict == "allow"


def test_argument_level_taint_counts_even_when_message_taint_is_clean(doc, engine):
    decision = engine.evaluate(
        doc,
        PolicyInput(
            tool_impact="irreversible",
            taint={"max_source": "user", "arguments": {"to": "tool_result"}},
        ),
    )
    assert decision.verdict == "escalate"


def test_observe_mode_records_counterfactual_without_blocking(doc, engine):
    """The R3 mitigation: installing the product must not start blocking traffic."""
    observing = doc.model_copy(deep=True)
    observing.mode = "observe"
    decision = engine.evaluate(
        observing,
        PolicyInput(detections=[{"entity_type": "INJECTION.OVERRIDE", "score": 0.9}]),
    )
    assert decision.verdict == "allow"
    assert decision.effective_verdict == "block"
    assert decision.rules_fired


def test_determinism(doc, engine):
    """X-4: same input + same policy version -> same decision."""
    pinput = PolicyInput(
        tool_key="payments.transfer",
        arguments={"amount": 5000},
        detections=[{"entity_type": "PII.EMAIL", "score": 0.9}],
        surface="output",
    )
    first = engine.evaluate(doc, pinput).to_json()
    for _ in range(20):
        assert engine.evaluate(doc, pinput).to_json() == first


def test_auto_generated_reason_is_meaningful(doc, engine):
    decision = engine.evaluate(
        doc, PolicyInput(detections=[{"entity_type": "INJECTION.OVERRIDE", "score": 0.9}])
    )
    reason = decision.rules_fired[0].reason
    assert "INJECTION.OVERRIDE" in reason


def test_expression_escape_hatch_cannot_execute_code(engine):
    """A policy language that can run Python is a privilege-escalation path."""
    doc = PolicyDocument.from_yaml(
        "key: x\nmode: enforce\nrules:\n"
        "  - id: evil\n    when: {expr: \"__import__('os').system('true')\"}\n"
        "    effect: block\n"
    )
    assert engine.evaluate(doc, PolicyInput()).verdict == "allow"


def test_expression_can_read_allowed_names(engine):
    doc = PolicyDocument.from_yaml(
        "key: x\nmode: enforce\nrules:\n"
        "  - id: many\n    when: {expr: 'n_detections > 2'}\n    effect: block\n"
    )
    decision = engine.evaluate(doc, PolicyInput(detections=[{"entity_type": "A", "score": 1}] * 3))
    assert decision.verdict == "block"


def test_combine_takes_strongest_across_policies():
    engine = NativePolicyEngine()
    blocker = PolicyDocument.from_yaml(
        "key: a\nmode: enforce\nrules:\n  - id: b\n    when: {}\n    effect: block\n"
    )
    allower = PolicyDocument.from_yaml("key: b\nmode: enforce\nrules: []\n")
    merged = combine(
        [engine.evaluate(allower, PolicyInput()), engine.evaluate(blocker, PolicyInput())]
    )
    assert merged.verdict == "block"


def test_rego_compilation_produces_a_module(doc):
    rego = compile_to_rego(doc)
    assert "package agentfox.policy.test" in rego
    assert "import rego.v1" in rego
    assert '"rule_id": "injection.block"' in rego
    assert "decision :=" in rego


def test_policy_versions_are_immutable(session):
    doc = PolicyDocument.from_yaml(POLICY)
    _policy, v1 = save_policy(session, doc, author="a")
    _policy, again = save_policy(session, doc, author="a")
    assert again.id == v1.id  # no-op edit does not manufacture a version

    doc.rules = doc.rules[:1]
    _policy, v2 = save_policy(session, doc, author="b")
    assert v2.version == v1.version + 1
    assert session.get(type(v1), v1.id).body != v2.body  # v1 unchanged


def test_changing_hierarchy_placement_alone_rebinds_without_a_new_version(session):
    """A save that only moves a policy in the org/team/agent/user hierarchy — same
    rules, different level/scope — must still take effect. The no-op-edit check
    above only guards against manufacturing an identical *version*; it must not
    also silently swallow a real binding change."""
    from agentfox.core.models import PolicyBinding

    doc = PolicyDocument.from_yaml(POLICY)
    _policy, v1 = save_policy(session, doc, author="a", level="org", scope_id="*")

    _policy, v2 = save_policy(session, doc, author="a", level="team", scope_id="finance")
    assert v2.id == v1.id  # still a no-op on the rules body — no new version

    binding = session.scalar(
        select(PolicyBinding).where(
            PolicyBinding.policy_version_id == v2.id,
            PolicyBinding.effective_to.is_(None),
        )
    )
    assert binding.level == "team"
    assert binding.scope_id == "finance"


def test_policies_can_be_filtered_by_the_agents_they_actually_govern(client):
    """A policy's real scope is its declared `scope.agents` glob, not a one-to-one
    assignment — one policy commonly governs many agents by pattern. The Policies
    page filter has to agree with what `active_policies` actually enforces."""
    from tests.conftest import as_user

    headers = as_user("marcus@example.com")
    scoped = """
key: hr-only
mode: observe
default_effect: allow
scope:
  agents: ["hr-*"]
rules:
  - id: injection.block
    when: {detection: {entity_prefix: INJECTION, min_score: 0.8}}
    effect: block
"""
    created = client.post("/api/policies", json={"body": scoped}, headers=headers)
    assert created.status_code == 201

    hr = client.get("/api/policies?agent=hr-screening", headers=headers).json()
    assert any(p["key"] == "hr-only" for p in hr["policies"])

    triage = client.get("/api/policies?agent=support-triage", headers=headers).json()
    assert not any(p["key"] == "hr-only" for p in triage["policies"])
    # The seeded baseline policy scopes to "*" — it governs every agent, so it
    # should still show up for an agent the new policy doesn't cover.
    assert any(p["key"] == "baseline" for p in triage["policies"])


def test_mode_promotion_is_recorded(session):
    save_policy(session, PolicyDocument.from_yaml(POLICY), author="a", bind_mode="observe")
    binding = set_mode(session, "test", "enforce")
    assert binding is not None and binding.mode == "enforce"


# ---------------------------------------------------------------------------
# Identity & least privilege (P2-1, P2-2)
# ---------------------------------------------------------------------------


def test_credential_roundtrip(session):
    agent = register_agent(session, "svc", owner_email="a@example.com")
    identity = ensure_identity(session, agent)
    _credential, raw = issue_credential(session, identity)
    assert verify_credential(session, raw) is not None
    assert verify_credential(session, "nom_agt_wrongkeywrongkeywrongkey") is None


def test_rotation_keeps_old_key_alive_during_overlap(session):
    agent = register_agent(session, "svc")
    identity = ensure_identity(session, agent)
    _c, old = issue_credential(session, identity)
    _c2, new = rotate_credential(session, identity, overlap_hours=24)
    assert verify_credential(session, new) is not None
    assert verify_credential(session, old) is not None, "rotation must not be an outage"


def test_default_deny(session):
    agent = register_agent(session, "svc")
    identity = ensure_identity(session, agent)
    decision = check_capability(session, identity, "payments.transfer")
    assert not decision.granted
    assert decision.state == "denied"
    assert "no capability grants" in decision.reasons[0]


def test_no_identity_is_denied(session):
    assert not check_capability(session, None, "anything").granted


def test_argument_constraints_enforced(session):
    agent = register_agent(session, "svc")
    identity = ensure_identity(session, agent)
    grant_capability(
        session,
        identity,
        "payments.transfer",
        constraints={"amount": {"lt": 1000}, "currency": {"in": ["USD"]}},
    )

    assert check_capability(
        session, identity, "payments.transfer", arguments={"amount": 500, "currency": "USD"}
    ).granted
    over = check_capability(
        session, identity, "payments.transfer", arguments={"amount": 5000, "currency": "USD"}
    )
    assert not over.granted and over.constraint_violations
    wrong = check_capability(
        session, identity, "payments.transfer", arguments={"amount": 5, "currency": "EUR"}
    )
    assert not wrong.granted


def test_taint_above_capability_escalates_rather_than_denying(session):
    """Provenance is a reason for a human to look, not proof of an attack."""
    agent = register_agent(session, "svc")
    identity = ensure_identity(session, agent)
    grant_capability(session, identity, "email.send", max_taint="user")
    decision = check_capability(
        session,
        identity,
        "email.send",
        arguments={"to": "x@y.example"},
        argument_taint={"to": "tool_result"},
    )
    assert decision.granted and decision.requires_approval
    assert decision.taint_violation


def test_most_specific_grant_wins(session):
    agent = register_agent(session, "svc")
    identity = ensure_identity(session, agent)
    grant_capability(session, identity, "payments.*", requires_approval=True)
    grant_capability(session, identity, "payments.refund", requires_approval=False)
    decision = check_capability(session, identity, "payments.refund")
    assert decision.granted and not decision.requires_approval


# ---------------------------------------------------------------------------
# Delegation (P2-5)
# ---------------------------------------------------------------------------


def test_delegation_narrowing_allowed(session):
    parent_agent = register_agent(session, "parent")
    child_agent = register_agent(session, "child")
    parent = ensure_identity(session, parent_agent)
    child = ensure_identity(session, child_agent)
    grant_capability(session, parent, "tickets.*", max_taint="tool_result")
    grant_capability(session, child, "tickets.create", max_taint="user")
    edge = delegate(session, parent, child)
    assert edge.id


def test_delegation_widening_rejected_at_write_time(session):
    parent_agent = register_agent(session, "parent")
    child_agent = register_agent(session, "child")
    parent = ensure_identity(session, parent_agent)
    child = ensure_identity(session, child_agent)
    grant_capability(session, parent, "tickets.create")
    grant_capability(session, child, "payments.transfer")
    with pytest.raises(ValueError, match="widen"):
        delegate(session, parent, child)


def test_child_cannot_broaden_a_glob(session):
    parent_agent = register_agent(session, "parent")
    child_agent = register_agent(session, "child")
    parent = ensure_identity(session, parent_agent)
    child = ensure_identity(session, child_agent)
    grant_capability(session, parent, "tickets.*")
    grant_capability(session, child, "*")
    with pytest.raises(ValueError, match="widen"):
        delegate(session, parent, child)


def test_child_cannot_accept_more_dangerous_provenance(session):
    parent_agent = register_agent(session, "parent")
    child_agent = register_agent(session, "child")
    parent = ensure_identity(session, parent_agent)
    child = ensure_identity(session, child_agent)
    grant_capability(session, parent, "tickets.create", max_taint="user")
    grant_capability(session, child, "tickets.create", max_taint="tool_result")
    with pytest.raises(ValueError, match="widen"):
        delegate(session, parent, child)


def test_child_cannot_drop_an_approval_requirement(session):
    parent_agent = register_agent(session, "parent")
    child_agent = register_agent(session, "child")
    parent = ensure_identity(session, parent_agent)
    child = ensure_identity(session, child_agent)
    grant_capability(session, parent, "email.send", requires_approval=True)
    grant_capability(session, child, "email.send", requires_approval=False)
    with pytest.raises(ValueError, match="widen"):
        delegate(session, parent, child)


# ---------------------------------------------------------------------------
# Approvals (P2-3)
# ---------------------------------------------------------------------------


def test_approval_lifecycle(session):
    request = request_approval(
        session,
        agent_id=None,
        tool_key="payments.transfer",
        arguments={"amount": 1},
        reason="tainted argument",
    )
    assert request.status == "pending"
    resolved = resolve_approval(session, request.id, True, "usr_1", "verified with customer")
    assert resolved.status == "approved"
    assert resolved.resolution_rationale == "verified with customer"


def test_unanswered_approval_fails_closed(session):
    import datetime as dt

    request = request_approval(
        session,
        agent_id=None,
        tool_key="email.send",
        arguments={},
        reason="x",
    )
    request.expires_at = utcnow() - dt.timedelta(minutes=1)
    session.flush()
    assert expire_stale_approvals(session) == 1
    session.refresh(request)
    assert request.status == "expired"


def test_a_single_polled_approval_expires_without_the_bulk_list_route(client, session):
    """The SDK polls `GET /api/approvals/{id}`, never the bulk list — a stale
    approval must not read "pending" forever just because nothing else happened to
    call `GET /api/approvals` first (NOM-IAM-03: unanswered fails closed)."""
    import datetime as dt

    from tests.conftest import as_user

    headers = as_user("marcus@example.com")
    request = request_approval(
        session,
        agent_id=None,
        tool_key="payments.transfer",
        arguments={"amount": 1},
        reason="tainted argument",
    )
    request.expires_at = utcnow() - dt.timedelta(minutes=1)
    session.commit()

    body = client.get(f"/api/approvals/{request.id}", headers=headers).json()
    assert body["status"] == "expired"
