"""Control attestations, retention policy and the retention purge.

* A review is an outcome, a note, the evidence it was made on, an expiry, and an
  audit-chain entry, made only by roles that answer for compliance.
* Changing retention is an audited, role-gated operator action.
* The purge deletes or redacts only what is past its class's period, keeps what a
  legal hold covers, and never removes an audit entry.
* The kill switch is a control, evidenced by its own use.
"""

from __future__ import annotations

import datetime as dt

from agentfox_ee.compliance import reviews
from agentfox_ee.compliance.status import evaluate_control
from sqlalchemy import func, select

from agentfox.capabilities.compliance import sync_catalog
from agentfox.core.models import (
    Agent,
    Control,
    ControlReview,
    Decision,
    FrameworkMapping,
    utcnow,
)
from tests.conftest import as_user

DANA = as_user("dana@example.com")  # compliance
AISHA = as_user("aisha@example.com")  # auditor
PRIYA = as_user("priya@example.com")  # developer
MARCUS = as_user("marcus@example.com")  # security


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------


def test_a_review_records_outcome_evidence_expiry_and_an_audit_entry(client):
    r = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "eu-ai-act", "outcome": "meets"},
        headers=DANA,
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["reviewer"] == "dana@example.com"
    assert review["state"] == "current"
    reviewed = dt.datetime.fromisoformat(review["reviewed_at"])
    expires = dt.datetime.fromisoformat(review["expires_at"])
    assert (expires - reviewed).days == reviews.REVIEW_VALID_DAYS

    detail = client.get("/api/controls/NOM-AUD-02", headers=DANA).json()
    eu = next(f for f in detail["frameworks"] if f["framework"] == "eu-ai-act")
    assert eu["review"]["outcome"] == "meets"
    assert eu["review"]["reviewer"] == "dana@example.com"
    assert detail["history"][0]["id"] == review["id"]
    assert "status" in detail["evidence"] and "rules" in detail["evidence"]

    entries = client.get(
        "/api/audit/entries", params={"action": "compliance.control_reviewed"}, headers=DANA
    ).json()["entries"]
    assert entries and entries[0]["seq"] == review["audit_seq"]

    # The review confirms the mapping it was made against, so the package's DRAFT
    # chip comes off those rows.
    framework = client.get("/api/frameworks/eu-ai-act", headers=DANA).json()
    row = next(c for c in framework["controls"] if c["key"] == "NOM-AUD-02")
    assert row["review_status"] == "reviewed"
    assert row["review"]["state"] == "current"
    assert framework["attestations"]["current"] >= 1


def test_anything_short_of_meets_needs_a_note(client):
    for outcome in ("partially_meets", "does_not_meet", "not_applicable"):
        r = client.post(
            "/api/controls/NOM-AUD-02/reviews",
            json={"framework": "eu-ai-act", "outcome": outcome},
            headers=DANA,
        )
        assert r.status_code == 400, outcome
    r = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "eu-ai-act", "outcome": "partially_meets", "note": "no checkpoints"},
        headers=DANA,
    )
    assert r.status_code == 201
    assert r.json()["note"] == "no checkpoints"


def test_a_review_must_name_a_known_outcome_and_a_mapped_framework(client):
    bad_outcome = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "eu-ai-act", "outcome": "looks fine"},
        headers=DANA,
    )
    assert bad_outcome.status_code == 400
    unmapped = client.post(
        "/api/controls/NOM-AUD-02/reviews",
        json={"framework": "mitre-atlas", "outcome": "meets"},
        headers=DANA,
    )
    assert unmapped.status_code == 400
    unknown = client.post(
        "/api/controls/NOM-NOPE-01/reviews",
        json={"framework": "eu-ai-act", "outcome": "meets"},
        headers=DANA,
    )
    assert unknown.status_code == 400


def test_only_compliance_owners_and_auditors_may_attest(client):
    body = {"framework": "eu-ai-act", "outcome": "meets"}
    for headers in (PRIYA, MARCUS):
        r = client.post("/api/controls/NOM-AUD-02/reviews", json=body, headers=headers)
        assert r.status_code == 403
    assert (
        client.post("/api/controls/NOM-AUD-02/reviews", json=body, headers=AISHA).status_code == 201
    )


def test_a_review_expires_and_a_new_one_supersedes_it(seeded):
    sync_catalog(seeded)
    long_ago = utcnow() - dt.timedelta(days=reviews.REVIEW_VALID_DAYS + 5)
    old = reviews.record_review(
        seeded, "NOM-AUD-02", "soc2", "meets", reviewer="dana@example.com", now=long_ago
    )
    assert reviews.review_state(old) == "expired"
    latest = reviews.latest_reviews(seeded, "soc2")[("NOM-AUD-02", "soc2")]
    assert latest.id == old.id

    from agentfox_ee.compliance.frameworks import framework_coverage

    assert framework_coverage(seeded, "soc2")["attestations"]["expired"] >= 1

    new = reviews.record_review(
        seeded,
        "NOM-AUD-02",
        "soc2",
        "does_not_meet",
        reviewer="aisha@example.com",
        note="checkpoint key rotated without re-signing",
    )
    latest = reviews.latest_reviews(seeded, "soc2")[("NOM-AUD-02", "soc2")]
    assert latest.id == new.id and reviews.review_state(latest) == "current"
    # Both attestations are kept: history is the point.
    assert len(reviews.review_history(seeded, "NOM-AUD-02")) == 2
    assert seeded.scalar(select(func.count()).select_from(ControlReview)) == 2


def test_the_one_click_mapping_route_is_gone(client):
    r = client.post(
        "/api/frameworks/review",
        json={"control_key": "NOM-AUD-02", "framework": "eu-ai-act"},
        headers=DANA,
    )
    assert r.status_code in (404, 405)


def test_a_framework_lists_requirements_with_their_controls(client):
    detail = client.get("/api/frameworks/eu-ai-act", headers=DANA).json()
    requirements = detail["requirements_detail"]
    assert requirements
    art14 = [r for r in requirements if r["reference"].startswith("Art. 14")]
    assert art14 and any(c["key"] == "NOM-RTG-14" for c in art14[0]["controls"])
    assert client.get("/api/frameworks/not-a-framework", headers=DANA).status_code == 404


def test_the_kill_switch_control_is_evidenced_by_its_use(seeded):
    from agentfox.platform.registry.control import kill

    sync_catalog(seeded)
    control = seeded.scalar(select(Control).where(Control.key == "NOM-RTG-14"))
    assert evaluate_control(seeded, control).status == "not_implemented"

    agent = seeded.scalar(select(Agent).where(Agent.status == "active"))
    kill(seeded, agent.slug, reason="drill", actor="marcus@example.com")
    held = evaluate_control(seeded, control)
    assert held.status == "effective", held.rationale

    # An allowed call after the stop means the switch leaked.
    seeded.add(
        Decision(
            agent_id=agent.id,
            verdict="allow",
            created_at=utcnow() + dt.timedelta(seconds=5),
        )
    )
    seeded.flush()
    leaked = evaluate_control(seeded, control)
    assert leaked.status == "failing"


def test_a_control_added_by_an_upgrade_reaches_a_workspace_with_the_old_catalog(client, seeded):
    """The catalog was only loaded into an empty workspace, so a control a new build
    adds was 'No such control' wherever an older catalog was already stored."""
    from agentfox.core.models import Control

    seeded.query(FrameworkMapping).filter_by(control_key="NOM-RTG-14").delete()
    seeded.query(Control).filter_by(key="NOM-RTG-14").delete()
    seeded.commit()
    assert client.get("/api/controls/NOM-RTG-14").status_code == 200
    keys = {c["key"] for c in client.get("/api/controls").json()["controls"]}
    assert "NOM-RTG-14" in keys
