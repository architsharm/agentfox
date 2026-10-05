"""P10 — entitlement and disclosure control (F4).

The Copilot research names the failure exactly: *"a governance failure rather than a
security breach — every permission check passed."* The agent runs under its own
service identity and inherits the union of everything that identity can reach, so one
prompt surfaces everything the service account can read and every ACL in the path
returns allow — because nobody asked what **this requesting human** was entitled to.

The fixture below is that scenario: one index, three callers, three answers.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from agentfox.cli.main import app
from agentfox.core.db import session_scope
from agentfox.core.models import DisclosureEvent
from agentfox.grounding.entitlement import (
    DEFAULT_K_ANONYMITY,
    NativeAclEngine,
    aggregation_risk,
    filter_retrieval,
    get_engine,
    grant,
    inference_risk,
    over_permission_report,
    record_disclosure,
    upsert_principal,
)
from tests.conftest import as_user

runner = CliRunner()

#: One index the agent's service account can read in full.
CHUNKS = [
    {"source": "kb/refund-policy", "text": "Refunds within 30 days."},
    {"source": "hr/salaries-2026", "text": "Head of Eng: 210,000."},
    {"source": "legal/ma-project-x", "text": "Acquisition of Globex, closing Q4."},
    {"source": "kb/shipping", "text": "Ships in two days."},
]


@pytest.fixture
def estate(isolated_db):
    """Three people with genuinely different need-to-know."""
    with session_scope() as session:
        grant(session, "kb/*", principal="all-staff")
        grant(session, "hr/*", principal="hr-team", classes=["pii_sensitive"])
        grant(session, "legal/*", principal="deal-team", classes=["mnpi"])
        upsert_principal(session, "alice@acme.com", groups=["all-staff"])
        upsert_principal(
            session,
            "bob@acme.com",
            groups=["all-staff", "hr-team"],
            clearances=["pii_sensitive"],
        )
        upsert_principal(
            session,
            "carol@acme.com",
            groups=["all-staff", "deal-team"],
            clearances=["mnpi"],
        )
    yield


def _principal(subject: str):
    from sqlalchemy import select

    from agentfox.core.models import EndUserPrincipal

    with session_scope() as session:
        return session.scalars(
            select(EndUserPrincipal).where(EndUserPrincipal.subject == subject)
        ).one()


def _visible(subject: str, chunks=None, **kwargs) -> list[str]:
    with session_scope() as session:
        decision = filter_retrieval(session, _principal(subject), chunks or CHUNKS, **kwargs)
    return [c["source"] for c in decision.visible]


# ---------------------------------------------------------------------------
# The failure this exists to prevent
# ---------------------------------------------------------------------------


def test_one_index_three_callers_three_answers(estate):
    """Every permission check passes for all three. The difference is need-to-know."""
    assert _visible("alice@acme.com") == ["kb/refund-policy", "kb/shipping"]
    assert "hr/salaries-2026" in _visible("bob@acme.com")
    assert "legal/ma-project-x" in _visible("carol@acme.com")


def test_hr_cannot_see_the_deal_and_the_deal_team_cannot_see_salaries(estate):
    assert "legal/ma-project-x" not in _visible("bob@acme.com")
    assert "hr/salaries-2026" not in _visible("carol@acme.com")


def test_no_principal_discloses_nothing(estate):
    """An agent answering with no idea who is asking is the Copilot failure. Allowing
    it silently would make this control decorative."""
    with session_scope() as session:
        decision = filter_retrieval(session, None, CHUNKS)
    assert decision.visible == []
    assert decision.reasons == {"no_principal": len(CHUNKS)}
    assert decision.over_permission == 1.0


def test_an_ungranted_resource_is_invisible_by_default(estate):
    """Default-allow would silently disclose anything nobody remembered to protect."""
    chunks = [*CHUNKS, {"source": "forgotten/secret-plan", "text": "..."}]
    assert "forgotten/secret-plan" not in _visible("alice@acme.com", chunks)


# ---------------------------------------------------------------------------
# Restricted classes need a clearance, not a grant
# ---------------------------------------------------------------------------


def test_a_grant_alone_does_not_open_a_restricted_class(estate):
    """ "They could technically read the folder" is not the question anyone is asking
    about material non-public information."""
    with session_scope() as session:
        upsert_principal(session, "dave@acme.com", groups=["all-staff", "deal-team"])
    assert "legal/ma-project-x" not in _visible("dave@acme.com")


def test_the_matching_clearance_opens_it(estate):
    assert "legal/ma-project-x" in _visible("carol@acme.com")


# ---------------------------------------------------------------------------
# Purpose limitation and residency
# ---------------------------------------------------------------------------


def test_purpose_limitation_is_enforced_when_declared(isolated_db):
    """GDPR Art. 5(1)(b): support data reused for marketing."""
    with session_scope() as session:
        grant(session, "tickets/*", principal="staff", purposes=["support"])
        upsert_principal(session, "eve@acme.com", groups=["staff"])
    chunks = [{"source": "tickets/1234", "text": "customer complained"}]
    assert _visible("eve@acme.com", chunks, purpose="support") == ["tickets/1234"]
    assert _visible("eve@acme.com", chunks, purpose="marketing") == []


def test_a_resource_with_no_declared_purpose_is_unconstrained(isolated_db):
    """Requiring every resource to declare purposes up front would mean nobody ever
    turns the control on."""
    with session_scope() as session:
        grant(session, "kb/*", principal="staff")
        upsert_principal(session, "eve@acme.com", groups=["staff"])
    chunks = [{"source": "kb/faq", "text": "..."}]
    assert _visible("eve@acme.com", chunks, purpose="anything") == ["kb/faq"]


def test_residency_is_enforced_per_record(isolated_db):
    """F4.8 was previously deployment-level only — a whole-deployment setting cannot
    express "this EU subject may not be answered from US-resident data"."""
    with session_scope() as session:
        grant(session, "eu/*", principal="staff", residency="eu")
        grant(session, "us/*", principal="staff", residency="us")
        upsert_principal(session, "frank@acme.eu", groups=["staff"], residency="eu")
    chunks = [{"source": "eu/record", "text": "..."}, {"source": "us/record", "text": "..."}]
    assert _visible("frank@acme.eu", chunks) == ["eu/record"]


# ---------------------------------------------------------------------------
# The drop count is the metric
# ---------------------------------------------------------------------------


def test_withholding_is_recorded_not_silent(estate):
    """A pre-filter that quietly returns fewer chunks tells nobody anything."""
    with session_scope() as session:
        decision = filter_retrieval(session, _principal("alice@acme.com"), CHUNKS)
        record_disclosure(session, decision)
    with session_scope() as session:
        event = session.query(DisclosureEvent).one()
    assert event.withheld == 2
    assert event.candidates == 4
    assert event.principal_subject == "alice@acme.com"


def test_nothing_is_recorded_when_nothing_was_withheld(estate):
    with session_scope() as session:
        decision = filter_retrieval(session, _principal("alice@acme.com"), [CHUNKS[0]])
        assert record_disclosure(session, decision) is None
    with session_scope() as session:
        assert session.query(DisclosureEvent).count() == 0


def test_the_over_permission_report_works_with_no_entitlement_model(isolated_db):
    """The diagnostic that motivates the work: a customer with zero grants sees 1.0
    and understands the exercise immediately."""
    with session_scope() as session:
        principal = upsert_principal(session, "grace@acme.com", groups=[])
        decision = filter_retrieval(session, principal, CHUNKS)
        record_disclosure(session, decision)
        report = over_permission_report(session)
    assert report["over_permission"] == 1.0
    assert report["requests"] == 1


def test_the_report_says_so_when_nothing_has_been_measured(isolated_db):
    with session_scope() as session:
        report = over_permission_report(session)
    assert report["requests"] == 0
    assert "until the agent is told who's asking" in report["note"]


# ---------------------------------------------------------------------------
# The two disclosures no access check can catch
# ---------------------------------------------------------------------------


def test_an_aggregate_over_too_few_people_identifies_them():
    """Salary band plus a headcount of one is one person's salary, and it passes every
    access check because no individual record was disclosed."""
    assert aggregation_risk("Average salary is 180k", contributors=2) is not None
    assert aggregation_risk("Average salary is 180k", contributors=50) is None


def test_aggregation_is_silent_when_the_count_is_unknown():
    """Guessing would flag every aggregate in the product."""
    assert aggregation_risk("Average salary is 180k") is None


def test_the_k_threshold_is_configurable():
    assert aggregation_risk("x", contributors=DEFAULT_K_ANONYMITY) is None
    assert aggregation_risk("x", contributors=2, k=10) is not None


def test_an_inferred_attribute_was_never_retrieved_so_nothing_governs_it():
    risk = inference_risk(
        "She is likely pregnant based on her leave pattern.", "leave records for Q3"
    )
    assert risk is not None and "pregnan" in risk["attributes"]


def test_reporting_an_attribute_the_context_contains_is_disclosure_not_inference():
    """A field present in the retrieved record is governed by the entitlement filter;
    treating it as an inference would double-report and train people to ignore it."""
    assert (
        inference_risk("Their disability status is recorded as X.", "disability status: X") is None
    )


# ---------------------------------------------------------------------------
# The engine seam
# ---------------------------------------------------------------------------


def test_the_native_engine_is_the_default(isolated_db):
    assert get_engine().key == "native"
    assert isinstance(get_engine(), NativeAclEngine)


def test_openfga_reports_unavailable_rather_than_guessing(isolated_db, monkeypatch):
    """A permissions engine that improvises is worse than one honestly absent."""
    from agentfox.core.config import get_settings

    monkeypatch.setattr(get_settings(), "entitlement_engine", "openfga")
    assert get_engine().key == "native", "falls back rather than failing open"


# ---------------------------------------------------------------------------
# The enforcement path
# ---------------------------------------------------------------------------


def test_quoting_a_withheld_chunk_in_the_answer_is_critical(seeded, enforcer):
    """The oversharing failure itself, rather than a near miss."""
    from agentfox.core.models import Agent, Finding

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    grant(seeded, "kb/*", principal="all-staff")
    principal = upsert_principal(seeded, "alice@acme.com", groups=["all-staff"])
    enforcer.evidence = {
        "principal": principal,
        "chunks": [
            {"source": "kb/faq", "text": "Refunds within 30 days."},
            {"source": "hr/salaries", "text": "Head of Eng earns 210,000 per year."},
        ],
    }
    result = enforcer.evaluate(
        agent=agent,
        identity=None,
        content="Head of Eng earns 210,000 per year.",
        surface="output",
    )
    assert result.taint["disclosure"]["withheld"] == 1
    findings = seeded.query(Finding).filter_by(type="entitlement_disclosure").all()
    assert findings and findings[0].severity == "critical"


def test_no_principal_supplied_means_no_disclosure_checks(seeded, enforcer):
    """The filter belongs to whoever performs retrieval; with no principal there is
    nothing to compare against and inventing one would be worse than abstaining."""
    from agentfox.core.models import Agent

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    enforcer.evidence = {}
    result = enforcer.evaluate(agent=agent, identity=None, content="anything", surface="output")
    assert "disclosure" not in result.taint


# ---------------------------------------------------------------------------
# API and CLI
# ---------------------------------------------------------------------------


def test_gateway_completion_with_a_principal_records_a_disclosure_event(client):
    """Before this, `principal`/`retrieved` had nowhere to go: `run_completion`
    accepted an `evidence=` kwarg but nothing in the HTTP path ever populated it, so a
    real integrator calling the gateway directly could never make the Entitlement page
    non-empty. This is the fix, exercised end to end through the actual route."""
    headers = as_user("marcus@example.com")
    client.post(
        "/api/entitlement/grants",
        json={"resource": "kb/*", "principal": "all-staff"},
        headers=headers,
    )
    client.put(
        "/api/entitlement/principals",
        json={"subject": "alice@acme.com", "groups": ["all-staff"]},
        headers=headers,
    )
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "echo-1",
            "messages": [{"role": "user", "content": "hello"}],
            "principal": {"subject": "alice@acme.com"},
            "retrieved": [
                {"source": "kb/faq", "text": "Refunds within 30 days."},
                {"source": "hr/salaries-2026", "text": "Head of Eng: 210,000."},
            ],
        },
        headers={"X-Nometria-Agent": "support-triage"},
    )
    assert response.status_code == 200
    with session_scope() as session:
        event = session.query(DisclosureEvent).one()
    assert event.principal_subject == "alice@acme.com"
    assert event.candidates == 2
    assert event.withheld == 1


def test_the_filter_endpoint_returns_only_what_the_caller_may_see(client):
    headers = as_user("marcus@example.com")
    client.post(
        "/api/entitlement/grants",
        json={"resource": "kb/*", "principal": "all-staff"},
        headers=headers,
    )
    client.put(
        "/api/entitlement/principals",
        json={"subject": "alice@acme.com", "groups": ["all-staff"]},
        headers=headers,
    )
    body = client.post(
        "/api/entitlement/filter",
        json={"subject": "alice@acme.com", "chunks": CHUNKS},
        headers=headers,
    ).json()
    assert [c["source"] for c in body["chunks"]] == ["kb/refund-policy", "kb/shipping"]
    assert body["withheld"] == 2


def test_filtering_for_an_unregistered_principal_is_refused(client):
    response = client.post(
        "/api/entitlement/filter",
        json={"subject": "nobody@acme.com", "chunks": CHUNKS},
        headers=as_user("marcus@example.com"),
    )
    assert response.status_code == 404
    assert "no idea who is asking" in response.json()["detail"]


def test_the_over_permission_endpoint_is_readable_before_any_setup(client):
    """Readable by an auditor: the diagnostic is the thing you show people to justify
    doing the work, so it must not require write access."""
    body = client.get(
        "/api/entitlement/over-permission", headers=as_user("aisha@example.com")
    ).json()
    assert body["requests"] == 0


def test_the_cli_explains_the_empty_state(isolated_db):
    result = runner.invoke(app, ["entitlement", "report"])
    assert "until the agent is told who's asking" in " ".join(result.output.split())


def test_the_cli_registers_principals_and_grants(isolated_db):
    assert runner.invoke(app, ["entitlement", "grant", "hr/*", "hr-team"]).exit_code == 0
    assert (
        runner.invoke(
            app, ["entitlement", "principal", "alice@acme.com", "--groups", "all-staff"]
        ).exit_code
        == 0
    )
