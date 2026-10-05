"""The posture surface: what an admin may change, and what only a deploy may change.

The property under test throughout is one sentence: **posture may narrow what the
deployment permits and may never widen it.** Everything else here is a consequence of
it. The tests are written as the refusals rather than the happy path, because a
configuration page's happy path is the part nobody gets wrong.

Why this matters enough for its own file: the previous arrangement made every one of
these choices an environment variable, which is unreachable from a request and
therefore safe, and also has no author, no reason and no history. Making them editable
is the feature; making them editable *only downward* is what keeps the feature from
being a hole.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.core.config import get_settings, reset_settings_cache
from agentfox.core.models import AuditEntry
from agentfox.detection.judgment import posture as P
from agentfox.detection.judgment.capability import CapabilityRouter, DecisionKind, Tier
from agentfox.detection.judgment.egress import Backend, PiiEgress
from tests.conftest import as_user


@pytest.fixture
def egress_on(monkeypatch):
    """A deployment whose operator has permitted egress."""
    monkeypatch.setenv("NOMETRIA_ALLOW_EGRESS", "true")
    reset_settings_cache()
    yield
    reset_settings_cache()


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------


def test_a_remote_tier_cannot_be_enabled_on_a_deployment_with_egress_off(session):
    """The central refusal. Stored-and-ignored would be the dangerous alternative."""
    assert get_settings().allow_egress is False
    with pytest.raises(P.PostureRefused) as exc:
        P.save(
            session,
            P.Posture(tiers={Tier.JEV}),
            actor="admin@example.com",
            reason="we want better recall",
            confirm_egress=True,
        )
    assert "allow_egress" in str(exc.value).lower()
    # And nothing was written: a refused write that half-applied would be worse than
    # either outcome.
    assert P.load(session).egress_tiers == frozenset()


def test_confirming_egress_does_not_substitute_for_permitting_it(session):
    """`confirm_egress` says "I meant to"; it does not say "I am allowed to"."""
    with pytest.raises(P.PostureRefused):
        P.save(
            session,
            P.Posture(tiers={Tier.LLM}),
            actor="admin@example.com",
            reason="r",
            confirm_egress=True,
        )


def test_pii_handling_may_be_tightened_but_not_loosened(session):
    """The deployment's value is the loosest permitted, not the default to drift from."""
    assert get_settings().judgment_pii_egress == "redact"
    tightened = P.save(
        session,
        P.Posture(pii_egress=PiiEgress.BLOCK),
        actor="admin@example.com",
        reason="regulated data",
    )
    assert tightened.pii_egress is PiiEgress.BLOCK

    with pytest.raises(P.PostureRefused) as exc:
        P.save(
            session,
            P.Posture(pii_egress=PiiEgress.ALLOW),
            actor="admin@example.com",
            reason="too many redactions",
            confirm_egress=True,
        )
    assert "looser" in str(exc.value)


def test_fail_closed_cannot_be_turned_off_when_the_deployment_requires_it(session):
    with pytest.raises(P.PostureRefused) as exc:
        P.save(
            session,
            P.Posture(fail_closed=False),
            actor="admin@example.com",
            reason="outages are annoying",
        )
    assert "fail closed" in str(exc.value).lower()


def test_a_local_tier_needs_no_egress_permission(session):
    """Local judgment is the whole point of having a local tier.

    This is the half of the rule people forget: the ceiling constrains what *leaves*,
    not what runs. A deployment with egress off is still allowed to get better.
    """
    stored = P.save(
        session,
        P.Posture(tiers={Tier.LOCAL_MODEL, Tier.LOCAL_LLM}),
        actor="admin@example.com",
        reason="local model is available on this host",
    )
    assert Tier.LOCAL_MODEL in stored.tiers
    assert Tier.LOCAL_LLM in stored.tiers
    assert stored.sends_anything is False


# ---------------------------------------------------------------------------
# Revocation after the fact
# ---------------------------------------------------------------------------


def test_revoking_egress_narrows_rows_written_while_it_was_allowed(session, egress_on):
    """A row is a preference, not a permission. The ceiling is re-applied on read."""
    P.save(
        session,
        P.Posture(tiers={Tier.JEV}, pii_egress=PiiEgress.REDACT),
        actor="admin@example.com",
        reason="enabling remote judgment",
        confirm_egress=True,
    )
    assert Tier.JEV in P.load(session).tiers

    # The operator revokes egress at the process level — a deploy, not a request.
    reset_settings_cache()
    import os

    os.environ.pop("NOMETRIA_ALLOW_EGRESS", None)
    reset_settings_cache()

    narrowed = P.load(session)
    assert Tier.JEV not in narrowed.tiers
    assert narrowed.sends_anything is False


# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------


def test_starting_to_send_data_needs_a_second_say_so(session, egress_on):
    with pytest.raises(P.PostureRefused) as exc:
        P.save(
            session,
            P.Posture(tiers={Tier.JEV}),
            actor="admin@example.com",
            reason="enabling remote judgment",
        )
    assert "confirm_egress" in str(exc.value)

    stored = P.save(
        session,
        P.Posture(tiers={Tier.JEV}),
        actor="admin@example.com",
        reason="enabling remote judgment",
        confirm_egress=True,
    )
    assert Tier.JEV in stored.tiers


def test_turning_a_remote_tier_off_needs_no_confirmation(session, egress_on):
    """Confirmation guards the direction that leaks, not the direction that is safe."""
    P.save(
        session,
        P.Posture(tiers={Tier.JEV}),
        actor="admin@example.com",
        reason="on",
        confirm_egress=True,
    )
    off = P.save(session, P.Posture(), actor="admin@example.com", reason="off")
    assert off.egress_tiers == frozenset()


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


def test_a_posture_change_is_in_the_audit_chain_with_before_and_after(session):
    P.save(
        session,
        P.Posture(pii_egress=PiiEgress.BLOCK),
        actor="marcus@example.com",
        reason="regulated data in this tenant",
    )
    session.flush()
    entries = list(
        session.scalars(
            select(AuditEntry).where(AuditEntry.action == "operator.judgment_posture.changed")
        )
    )
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor_id == "marcus@example.com"
    payload = entry.payload_json or {}
    assert "regulated" in str(payload.get("reason", ""))
    assert payload.get("before", {}).get("pii_egress") == "redact"
    assert payload.get("after", {}).get("pii_egress") == "block"


def test_a_change_without_a_reason_is_refused(session):
    """`record()` refuses it, which is what makes the reason a field and not a hope."""
    from agentfox.prove.audit.operator_log import ReasonRequired

    with pytest.raises(ReasonRequired):
        P.save(session, P.Posture(), actor="admin@example.com", reason="   ")


def test_the_registry_knows_this_surface_must_record():
    """The structural check, not a runtime one — see operator_log's docstring."""
    from agentfox.prove.audit.operator_log import PRIVILEGED, unaudited

    assert any(a.target == "agentfox.detection.judgment.posture.save" for a in PRIVILEGED)
    assert unaudited() == []


# ---------------------------------------------------------------------------
# What the router actually does with it
# ---------------------------------------------------------------------------


def test_the_router_follows_the_active_posture_not_the_environment(egress_on):
    """Otherwise the page is decoration."""
    off = CapabilityRouter.from_settings().plan(DecisionKind.SEMANTIC)
    assert Tier.JEV not in off.deciders

    with P.use(P.Posture(tiers={Tier.JEV})):
        on = CapabilityRouter.from_settings().plan(DecisionKind.SEMANTIC)
    assert Tier.JEV in on.deciders


def test_posture_cannot_add_a_tier_the_routing_table_forbids(egress_on):
    """The measured exclusions outrank the operator's preference.

    Enabling JEV does not put JEV on `structural_parsed`: code scores 100.0% there
    against JEV's 98.3%, and a preference is not a measurement.
    """
    with P.use(P.Posture(tiers={Tier.JEV, Tier.LLM})):
        plan = CapabilityRouter.from_settings().plan(DecisionKind.STRUCTURAL_PARSED)
    assert list(plan.deciders) == [Tier.DETERMINISTIC]
    assert "98.3%" in plan.why(Tier.JEV)


def test_an_unset_posture_behaves_exactly_as_settings_did(session):
    """What keeps the published benchmark numbers comparable."""
    assert P.effective().to_json() == P.from_settings().to_json()


def test_the_egress_gate_reads_the_active_posture(egress_on):
    """A tenant tightened to `block` is obeyed by the gate, not just by the page."""
    from agentfox.detection.judgment.egress import JudgmentGateway

    with P.use(P.Posture(tiers={Tier.JEV}, pii_egress=PiiEgress.BLOCK)):
        assert JudgmentGateway(backend=Backend.REMOTE)._pii_mode() is PiiEgress.BLOCK
    with P.use(P.Posture(tiers={Tier.JEV}, pii_egress=PiiEgress.REDACT)):
        assert JudgmentGateway(backend=Backend.REMOTE)._pii_mode() is PiiEgress.REDACT


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


def test_a_developer_may_not_change_what_leaves_the_building(client):
    response = client.put(
        "/api/judgment/posture",
        json={"tiers": ["local_model"], "reason": "trying something"},
        headers=as_user("priya@example.com"),
    )
    assert response.status_code == 403
    assert "judgment_posture" in response.json()["detail"]


def test_security_may(client):
    response = client.put(
        "/api/judgment/posture",
        json={"tiers": ["local_model"], "reason": "local model is available here"},
        headers=as_user("marcus@example.com"),
    )
    assert response.status_code == 200, response.text
    assert "local_model" in response.json()["posture"]["tiers"]


def test_an_auditor_may_read_the_posture_and_not_change_it(client):
    assert (
        client.get("/api/judgment/posture", headers=as_user("aisha@example.com")).status_code == 200
    )
    denied = client.put(
        "/api/judgment/posture",
        json={"tiers": [], "reason": "r"},
        headers=as_user("aisha@example.com"),
    )
    assert denied.status_code == 403


def test_the_api_refuses_a_ceiling_breach_with_409_and_says_who_to_ask(client):
    """409 rather than 400: the request is fine, the deployment is the problem."""
    response = client.put(
        "/api/judgment/posture",
        json={"tiers": ["jev"], "reason": "better recall", "confirm_egress": True},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "NOMETRIA_ALLOW_EGRESS" in detail
    assert "not from here" in detail


def test_the_api_requires_a_reason(client):
    response = client.put(
        "/api/judgment/posture",
        json={"tiers": [], "reason": ""},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 422


def test_the_read_says_what_cannot_be_chosen_and_why(client):
    body = client.get("/api/judgment/posture", headers=as_user("admin@example.com")).json()
    assert body["ceiling"]["allow_egress"] is False
    jev = next(t for t in body["tiers"] if t["tier"] == "jev")
    assert jev["selectable"] is False
    assert "NOMETRIA_ALLOW_EGRESS" in jev["blocked_reason"]
    deterministic = next(t for t in body["tiers"] if t["tier"] == "deterministic")
    assert deterministic["enabled"] is True
    assert deterministic["selectable"] is False
    # `allow` is below the deployment's `redact`, so it is not on offer either.
    allow = next(o for o in body["pii_egress_options"] if o["value"] == "allow")
    assert allow["selectable"] is False


def test_the_read_explains_each_kind_with_the_measurement_behind_it(client):
    body = client.get("/api/judgment/posture", headers=as_user("admin@example.com")).json()
    structural = body["kinds"]["structural_parsed"]
    assert structural["deciders"] == ["deterministic"]
    assert "98.3%" in structural["refused"]["jev"]
    assert structural["measured"]["deterministic"]["accuracy"] == 100.0
    # A band is only meaningful under CASCADE.
    assert structural["band"] is None
    assert body["kinds"]["semantic"]["band"] == [0.3, 0.7]


def test_an_unknown_tier_is_a_400_that_lists_the_known_ones(client):
    response = client.put(
        "/api/judgment/posture",
        json={"tiers": ["gpt5"], "reason": "r"},
        headers=as_user("admin@example.com"),
    )
    assert response.status_code == 400
    assert "deterministic" in response.json()["detail"]


def test_one_tenants_posture_is_not_another_tenants(monkeypatch):
    """The reason posture is a row and not a writable `Settings`.

    `get_settings()` is `lru_cache`'d and process-global, so a posture stored there
    would let one tenant's egress choice decide another tenant's behaviour in the same
    process. Isolation here is the session filter's, not this module's — the test
    exists because that is a property worth failing loudly rather than assuming.
    """
    from agentfox.core.db import session_scope
    from agentfox.core.tenancy import tenant

    monkeypatch.setenv("NOMETRIA_ALLOW_EGRESS", "true")
    reset_settings_cache()
    try:
        with tenant("org_acme"), session_scope() as s:
            P.save(
                s,
                P.Posture(tiers={Tier.JEV}),
                actor="admin@acme.example",
                reason="acme accepts remote judgment",
                confirm_egress=True,
            )
        with tenant("org_globex"), session_scope() as s:
            P.save(
                s,
                P.Posture(pii_egress=PiiEgress.BLOCK),
                actor="admin@globex.example",
                reason="globex handles regulated data",
            )

        with tenant("org_acme"), session_scope() as s:
            acme = P.load(s)
        with tenant("org_globex"), session_scope() as s:
            globex = P.load(s)

        assert Tier.JEV in acme.tiers
        assert Tier.JEV not in globex.tiers
        assert globex.pii_egress is PiiEgress.BLOCK
        assert acme.pii_egress is PiiEgress.REDACT
    finally:
        reset_settings_cache()
