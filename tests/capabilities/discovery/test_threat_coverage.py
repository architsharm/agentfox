"""Coverage by threat — the axis a security engineer works along.

The product sliced its data five ways and not this one. Every ingredient was already
tagged for it and nothing performed the join, which is how the inconsistencies
survived long enough to be evidence: detectors emit a bare `LLM01` while the control
catalogue writes `LLM01 Prompt Injection`, `LLM04` was spelled two ways in one file,
and `LLM07` appeared nowhere at all despite a shipped detector that stamps it.

The tests below are mostly about the ways this view could lie, because a coverage
page that overstates coverage is worse than no coverage page: it is the screen
somebody is looking at, reassured, while the thing it claims to cover is happening.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.capabilities.discovery.threats import coverage, load_threats, threat_id
from agentfox.core.models import RedTeamFinding
from tests.conftest import as_user


@pytest.fixture
def cov(seeded):
    return coverage(seeded)


def _row(cov, ident: str) -> dict:
    return next(t for t in cov["threats"] if t["id"] == ident)


# ---------------------------------------------------------------------------
# Normalising three spellings of the same thing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written,expected",
    [
        ("LLM01", "LLM01"),
        ("LLM01 Prompt Injection", "LLM01"),
        ("llm01 prompt injection", "LLM01"),
        ("LLM04 Data & Model Poisoning", "LLM04"),
        ("LLM04 Data and Model Poisoning", "LLM04"),
        ("AML.T0051 LLM Prompt Injection", "AML.T0051"),
        ("T13 Rogue Agents", "T13"),
    ],
)
def test_the_same_threat_written_three_ways_is_one_threat(written, expected):
    """`LLM04` really was spelled two ways in `controls.yaml`. Nothing noticed for as
    long as nothing grouped by the column."""
    assert threat_id(written) == expected


def test_a_control_mapped_twice_under_two_spellings_is_counted_once(cov):
    keys = [c["key"] for c in _row(cov, "LLM04")["controls"]]
    assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# The ways this page could lie
# ---------------------------------------------------------------------------


def test_observe_mode_is_not_counted_as_covered(seeded, cov):
    """The most expensive wrong number this product could publish.

    Everything ships in observe by default, so if observing counted as covered a
    fresh install would report full coverage while blocking nothing.
    """
    observing = [t for t in cov["threats"] if t["status"] == "observing"]
    assert observing, "the seeded deployment is in observe; this test proves nothing otherwise"
    for threat in observing:
        assert "Nothing is being stopped" in threat["detail"]
    assert cov["enforcing"] <= cov["scored"] - len(observing)


def test_a_threat_nobody_wrote_a_control_for_still_appears(cov):
    """Why the catalogue is declared rather than derived from the mappings.

    Nothing in `controls.yaml` mentions LLM07. Derived from the mappings it would not
    exist, and the one view whose job is to show gaps would be structurally unable to
    show the largest kind of gap there is.
    """
    llm07 = _row(cov, "LLM07")
    assert llm07["controls"] == []
    assert llm07["status"] != "enforcing"


def test_the_detector_that_already_covered_llm07_is_credited(cov):
    """It shipped stamping `LLM07` on system-prompt-leak detections and no control,
    rule or page ever mentioned it. Real coverage, entirely uncredited."""
    assert any(d["key"] == "injection.heuristic" for d in _row(cov, "LLM07")["detectors"])


def test_an_unbound_policy_does_not_count_as_protection(seeded):
    """A policy version sitting in the store is not protecting anything.

    Counting it would be the error that gets somebody breached while reading a green
    screen, so the rules come from the bound layers only.
    """
    from agentfox.core.models import PolicyBinding

    before = coverage(seeded)["enforcing"]
    for binding in seeded.scalars(select(PolicyBinding)):
        seeded.delete(binding)
    seeded.flush()
    assert coverage(seeded)["enforcing"] == 0 <= before


def test_a_red_team_breach_outranks_everything_above_it(seeded):
    """A payload that got through is a measured fact; no amount of configuration
    above it changes that, so it must not be hidden by a green status."""
    campaign_findings = seeded.scalars(select(RedTeamFinding)).all()
    assert not campaign_findings, "fixture assumption: no red-team findings yet"

    seeded.add(RedTeamFinding(campaign_id="rtc_test", probe="p", succeeded=True, owasp_id="LLM01"))
    seeded.flush()
    llm01 = _row(coverage(seeded), "LLM01")
    assert llm01["status"] == "breached"
    assert llm01["redteam_breaches"] == 1


def test_a_blocked_red_team_payload_is_not_a_breach(seeded):
    """`succeeded` is from the attacker's point of view. Reading it the other way
    round turns the most alarming number on the page into the most reassuring."""
    seeded.add(RedTeamFinding(campaign_id="rtc_test", probe="p", succeeded=False, owasp_id="LLM02"))
    seeded.flush()
    llm02 = _row(coverage(seeded), "LLM02")
    assert llm02["redteam_breaches"] == 0
    assert llm02["redteam_attempts"] == 1
    assert llm02["status"] != "breached"


def test_out_of_scope_threats_are_excluded_rather_than_failed(cov):
    """Training-data poisoning is not something a runtime control plane is in the
    path of. Scoring it would drag the number down with something nobody can act on,
    which teaches readers to ignore the number."""
    out = [t for t in cov["threats"] if t["status"] == "out_of_scope"]
    assert out
    assert all(t["id"] not in {g["id"] for g in cov["gaps"]} for t in out)
    assert cov["scored"] == len(cov["threats"]) - len(out)


# ---------------------------------------------------------------------------
# The catalogue itself
# ---------------------------------------------------------------------------


def test_the_owasp_llm_top_ten_has_ten_entries():
    """A "Top 10" page showing nine is a coverage view with a coverage gap."""
    entries = load_threats()["catalogues"]["owasp-llm"]["entries"]
    assert len(entries) == 10
    assert {e["id"] for e in entries} == {f"LLM{n:02d}" for n in range(1, 11)}


def test_every_declared_threat_states_whether_this_product_addresses_it():
    """So an uncovered threat reads as a decision or a gap, never an oversight."""
    for catalogue in load_threats()["catalogues"].values():
        for entry in catalogue["entries"]:
            assert entry.get("coverage_intent") in {"runtime", "partial", "out_of_scope"}


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


def test_every_role_including_the_auditor_can_read_it(client):
    """ "Are we covered against prompt injection" is not a privileged question, and a
    posture only its owner can see is a posture nobody checks."""
    for who in ("admin@example.com", "priya@example.com", "aisha@example.com"):
        response = client.get("/api/coverage/threats", headers=as_user(who))
        assert response.status_code == 200, who
        assert response.json()["scored"] > 0
