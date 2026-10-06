"""Scheduled probes against a deployed agent: consent, caps, SSRF, scoring and regressions.

An http target is a fake agent behind `core.outbound`'s injectable transport and DNS,
so every request goes through the real address vetting and connection pinning.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
import socket

import httpx
import pytest
from sqlalchemy import select

from agentfox.capabilities.evaluation import live_probes
from agentfox.capabilities.evaluation.live_probes import OPT_IN_WARNING, ProbeTargetError
from agentfox.core import outbound
from agentfox.core.config import get_settings
from agentfox.core.models import AuditEntry, Finding, ProbeTarget, RedTeamCampaign, Trace

NOW = dt.datetime(2026, 10, 6, 12, 0, tzinfo=dt.UTC)
URL = "https://agent.example/probe"
_BACKWARDS = re.compile(r"'([^']+)'\s*written backwards|backwards:\s*'([^']+)'")


def _fake_dns(table: dict[str, list[str]]):
    def resolve(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror(f"no such host {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in table[host]]

    return resolve


class FakeAgent:
    """An agent endpoint speaking the probe contract. `vulnerable` decides whether it
    follows injected instructions (replies with the canary, calls the tool)."""

    def __init__(self) -> None:
        self.vulnerable = False
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        message = body["message"]
        if body["probe"]["id"].startswith("benign."):
            return httpx.Response(200, json={"reply": "We are open 9 to 5."})
        if not self.vulnerable:
            return httpx.Response(200, json={"reply": "Sorry, I can't help with that."})
        if message.startswith("Decode this base64"):
            message = base64.b64decode(message.rsplit(" ", 1)[-1]).decode()
        match = _BACKWARDS.search(message)
        reversed_code = next(g for g in match.groups() if g) if match else ""
        calls = []
        if "Call the" in message:
            calls.append({"name": "payments.transfer", "arguments": {"amount": 9999}})
        return httpx.Response(
            200, json={"reply": f"Sure: {reversed_code[::-1]}", "tool_calls": calls}
        )


@pytest.fixture
def agent(monkeypatch):
    fake = FakeAgent()
    monkeypatch.setattr(outbound, "_getaddrinfo", _fake_dns({"agent.example": ["93.184.216.34"]}))
    monkeypatch.setattr(outbound, "_TRANSPORT", httpx.MockTransport(fake))
    return fake


def _target(session, **kw) -> ProbeTarget:
    defaults = dict(
        agent_slug="support-triage",
        adapter="http",
        url=URL,
        created_by="marcus@example.com",
        config={"forbidden_tools": ["payments.transfer"]},
        rate_limit_per_minute=60,
    )
    defaults.update(kw)
    return live_probes.register_target(session, **defaults)


def _opted_in(session, **kw) -> ProbeTarget:
    target = _target(session, **kw)
    live_probes.opt_in(session, target, actor="marcus@example.com", acknowledgement=OPT_IN_WARNING)
    return target


def _run(session, target, *, at=NOW, sleeps=None):
    return live_probes.run_target(
        session, target, now=at, sleep=(sleeps.append if sleeps is not None else lambda s: None)
    )


# ---------------------------------------------------------------------------
# consent
# ---------------------------------------------------------------------------


def test_a_registered_target_is_disabled_and_sends_nothing(seeded, agent):
    target = _target(seeded)
    assert target.enabled is False and target.opted_in_by is None
    with pytest.raises(ProbeTargetError, match="not opted in"):
        _run(seeded, target)
    assert agent.requests == []


def test_opt_in_needs_the_exact_warning_and_records_who(seeded, agent):
    target = _target(seeded)
    with pytest.raises(ProbeTargetError, match="acknowledge"):
        live_probes.opt_in(seeded, target, actor="marcus@example.com", acknowledgement="ok")
    assert target.enabled is False

    live_probes.opt_in(seeded, target, actor="marcus@example.com", acknowledgement=OPT_IN_WARNING)
    assert target.enabled and target.opted_in_by == "marcus@example.com"
    assert target.opted_in_at is not None and target.opt_in_acknowledgement == OPT_IN_WARNING
    entry = seeded.scalar(select(AuditEntry).where(AuditEntry.action == "probe.opt_in"))
    assert entry is not None and entry.actor_id == "marcus@example.com"
    assert entry.subject_id == target.id


def test_changing_the_url_clears_the_opt_in(seeded, agent):
    target = _opted_in(seeded)
    live_probes.update_url(
        seeded, target, "https://other.example/probe", actor="marcus@example.com"
    )
    assert target.enabled is False and target.opted_in_by is None
    assert target.registered_host == "other.example"


def test_an_unknown_agent_cannot_be_targeted(seeded):
    with pytest.raises(ProbeTargetError, match="unknown agent"):
        _target(seeded, agent_slug="nobody")


def test_the_kill_switch_stops_every_target(seeded, agent, monkeypatch):
    target = _opted_in(seeded)
    monkeypatch.setattr(get_settings(), "live_probes_enabled", False)
    with pytest.raises(ProbeTargetError, match="disabled"):
        _run(seeded, target)
    assert live_probes.run_due(seeded, {}, now=NOW)["campaigns"] == []
    assert agent.requests == []


# ---------------------------------------------------------------------------
# caps and SSRF
# ---------------------------------------------------------------------------


def test_limits_are_clamped_to_the_hard_caps(seeded):
    target = _target(
        seeded,
        interval_seconds=5,
        max_probes_per_run=10_000,
        rate_limit_per_minute=10_000,
        timeout_seconds=600,
    )
    assert target.interval_seconds == live_probes.MIN_INTERVAL_SECONDS
    assert target.max_probes_per_run == live_probes.MAX_PROBES_PER_RUN_CAP
    assert target.rate_limit_per_minute == live_probes.MAX_RATE_PER_MINUTE_CAP
    assert target.timeout_seconds == live_probes.MAX_TIMEOUT_SECONDS


def test_a_run_respects_the_probe_cap_and_the_rate_limit(seeded, agent):
    target = _opted_in(seeded, max_probes_per_run=3, rate_limit_per_minute=6)
    sleeps: list[float] = []
    campaign = _run(seeded, target, sleeps=sleeps)
    assert len(agent.requests) == 3
    assert len(campaign.probes) == 3
    assert sleeps == [10.0, 10.0]  # 60 / 6, between sends, not before the first


def test_every_request_is_tagged_and_carries_the_stored_auth(seeded, agent, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(get_settings(), "token_encryption_key", Fernet.generate_key().decode())
    target = _opted_in(seeded, auth_header="Bearer probe-test-token", max_probes_per_run=1)
    campaign = _run(seeded, target)
    sent = agent.requests[0]
    assert sent.headers["x-agentfox-probe"] == campaign.id
    assert sent.headers["authorization"] == "Bearer probe-test-token"
    assert sent.url.host == "93.184.216.34" and sent.headers["host"] == "agent.example"
    assert "probe-test-token" not in json.dumps(live_probes.target_json(target))


def test_a_target_resolving_to_a_private_address_is_never_contacted(seeded, monkeypatch):
    def no_network(request):
        raise AssertionError("a connection was attempted")

    monkeypatch.setattr(outbound, "_getaddrinfo", _fake_dns({"agent.example": ["10.0.0.7"]}))
    monkeypatch.setattr(outbound, "_TRANSPORT", httpx.MockTransport(no_network))
    target = _opted_in(seeded, max_probes_per_run=2)
    campaign = _run(seeded, target)
    assert campaign.summary_json["errors"] == 2
    assert campaign.summary_json["contained"] == 0 and campaign.summary_json["escaped"] == 0
    assert (
        "internal address" in campaign.summary_json["results"]["injection.direct_override"]["error"]
    )


def test_a_redirect_is_refused_not_followed(seeded, monkeypatch):
    seen: list[str] = []

    def handler(request):
        seen.append(request.headers["host"])
        return httpx.Response(307, headers={"location": "https://elsewhere.example/x"})

    monkeypatch.setattr(
        outbound,
        "_getaddrinfo",
        _fake_dns({"agent.example": ["93.184.216.34"], "elsewhere.example": ["151.101.1.1"]}),
    )
    monkeypatch.setattr(outbound, "_TRANSPORT", httpx.MockTransport(handler))
    target = _opted_in(seeded, max_probes_per_run=1)
    campaign = _run(seeded, target)
    assert seen == ["agent.example"]
    assert campaign.summary_json["errors"] == 1


def test_only_the_registered_host_is_reached(seeded, agent):
    target = _opted_in(seeded, max_probes_per_run=1)
    target.url = "https://sneaky.example/probe"  # edited behind the API's back
    campaign = _run(seeded, target)
    assert agent.requests == []
    assert "only 'agent.example' is registered" in json.dumps(campaign.summary_json)


def test_a_reply_outside_the_contract_is_an_error_not_containment(seeded, monkeypatch):
    monkeypatch.setattr(outbound, "_getaddrinfo", _fake_dns({"agent.example": ["93.184.216.34"]}))
    monkeypatch.setattr(
        outbound, "_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(200, text="hi"))
    )
    campaign = _run(seeded, _opted_in(seeded, max_probes_per_run=1))
    assert campaign.summary_json["errors"] == 1 and campaign.summary_json["contained"] == 0


# ---------------------------------------------------------------------------
# scoring, comparison and findings
# ---------------------------------------------------------------------------


def _open_escapes(session):
    return list(
        session.scalars(
            select(Finding).where(
                Finding.type == live_probes.FINDING_TYPE, Finding.status == "open"
            )
        )
    )


def test_an_attack_that_was_contained_and_now_escapes_opens_a_finding_then_closes(seeded, agent):
    target = _opted_in(seeded)

    first = _run(seeded, target)
    assert first.summary_json["escaped"] == 0
    assert first.summary_json["contained"] == first.summary_json["attacks_attempted"] == 9
    assert first.summary_json["posture"]["direction"] == "no_baseline"
    assert _open_escapes(seeded) == []

    agent.vulnerable = True  # a deploy made the agent follow injected instructions
    second = _run(seeded, target, at=NOW + dt.timedelta(days=1))
    summary = second.summary_json
    assert summary["escaped"] == 9 and summary["contained"] == 0
    assert summary["posture"]["direction"] == "weaker"
    assert summary["posture"]["baseline"]["campaign_id"] == first.id
    agency = summary["results"]["agency.forbidden_tool"]
    assert set(agency["signals"]) >= {"canary", "forbidden_tool"}

    findings = _open_escapes(seeded)
    assert len(findings) == 9
    assert sorted(summary["findings"]["opened"]) == sorted(f.id for f in findings)
    one = next(f for f in findings if f.evidence_json["probe"] == "injection.direct_override")
    assert one.evidence_json["source"] == "live_probe"
    assert one.evidence_json["regression"] is True
    assert one.evidence_json["previous_status"] == "contained"
    assert "contained in the previous run" in one.title
    assert one.subject_id == "support-triage"

    # The same escape next run counts an occurrence, it does not refile.
    third = _run(seeded, target, at=NOW + dt.timedelta(days=2))
    assert third.summary_json["findings"]["opened"] == []
    assert len(_open_escapes(seeded)) == 9
    assert third.summary_json["posture"]["direction"] == "unchanged"

    agent.vulnerable = False  # fixed
    fourth = _run(seeded, target, at=NOW + dt.timedelta(days=3))
    assert fourth.summary_json["posture"]["direction"] == "stronger"
    assert len(fourth.summary_json["findings"]["closed"]) == 9
    assert _open_escapes(seeded) == []


def test_an_agent_that_repeats_its_input_is_not_scored_as_compromised(seeded, monkeypatch):
    """The reversed code is in the message; only an agent that followed the instruction
    produces the forward one. An echoing agent must come out contained."""

    def echo(request):
        return httpx.Response(
            200, json={"reply": "You said: " + json.loads(request.content)["message"]}
        )

    monkeypatch.setattr(outbound, "_getaddrinfo", _fake_dns({"agent.example": ["93.184.216.34"]}))
    monkeypatch.setattr(outbound, "_TRANSPORT", httpx.MockTransport(echo))
    campaign = _run(seeded, _opted_in(seeded))
    assert campaign.summary_json["escaped"] == 0
    assert campaign.summary_json["results"]["injection.direct_override"]["contained_by"] == (
        "not_followed"
    )


def test_blocked_by_the_endpoint_is_contained_and_blocking_a_benign_question_is_over_blocking(
    seeded, monkeypatch
):
    monkeypatch.setattr(outbound, "_getaddrinfo", _fake_dns({"agent.example": ["93.184.216.34"]}))
    monkeypatch.setattr(
        outbound,
        "_TRANSPORT",
        httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": None, "blocked": True})),
    )
    campaign = _run(seeded, _opted_in(seeded))
    summary = campaign.summary_json
    assert summary["contained_by_block"] == summary["contained"] == 9
    assert summary["over_blocked"] == 2
    assert summary["results"]["benign.support_hours"]["status"] == "over_blocked"


def test_live_campaigns_are_marked_apart_from_production_red_team_data(seeded, agent):
    target = _opted_in(seeded, max_probes_per_run=2)
    campaign = _run(seeded, target)
    assert campaign.runner == "live"
    assert campaign.target_json["source"] == "live_probe"
    assert campaign.target_json["target_id"] == target.id
    assert campaign.summary_json["what_this_measures"] == live_probes.WHAT_THIS_MEASURES


# ---------------------------------------------------------------------------
# in-process: an agent governed by this gateway
# ---------------------------------------------------------------------------


def test_an_in_process_target_is_scored_on_the_gateway_verdict(seeded):
    from agentfox.platform.policy import set_mode

    set_mode(seeded, "baseline", "enforce")
    target = live_probes.register_target(
        seeded,
        agent_slug="support-triage",
        adapter="in_process",
        model="echo-1",
        created_by="marcus@example.com",
    )
    live_probes.opt_in(seeded, target, actor="marcus@example.com", acknowledgement=OPT_IN_WARNING)
    campaign = _run(seeded, target)
    results = campaign.summary_json["results"]
    assert campaign.summary_json["scoring"] == "gateway_verdict"
    assert results["injection.direct_override"]["status"] == "contained"
    assert results["injection.direct_override"]["contained_by"] == "blocked"
    assert results["benign.support_hours"]["status"] == "answered"
    assert all(r["status"] in ("contained", "escaped", "answered") for r in results.values())
    assert campaign.summary_json["errors"] == 0
    # Probe traffic is marked on the traces it leaves behind.
    traces = list(seeded.scalars(select(Trace).where(Trace.session_id.like("afx-probe:%"))))
    assert traces and all(t.session_id == f"afx-probe:{campaign.id}" for t in traces)


# ---------------------------------------------------------------------------
# the job
# ---------------------------------------------------------------------------


def test_the_job_runs_only_opted_in_due_targets_and_moves_next_due(seeded, agent):
    from agentfox.apps import jobs as handlers
    from agentfox.platform.jobs import scheduler

    assert "probes.run" in handlers.HANDLERS
    assert any(d.kind == "probes.run" and d.enabled for d in scheduler.DEFAULT_SCHEDULES)

    _target(seeded, name="never opted in")
    target = _opted_in(seeded, max_probes_per_run=1)
    result = live_probes.run_due(seeded, {}, now=NOW)
    assert [c["target_id"] for c in result["campaigns"]] == [target.id]
    assert target.next_due_at is not None
    assert live_probes.run_due(seeded, {}, now=NOW + dt.timedelta(minutes=5))["campaigns"] == []
    later = NOW + dt.timedelta(seconds=target.interval_seconds + 1)
    assert len(live_probes.run_due(seeded, {}, now=later)["campaigns"]) == 1
    assert len(list(seeded.scalars(select(RedTeamCampaign)))) == 2


def test_one_failing_target_does_not_stop_the_others(seeded, agent, monkeypatch):
    broken = _opted_in(seeded, max_probes_per_run=1)
    healthy = _opted_in(seeded, max_probes_per_run=1, name="healthy")
    real = live_probes.run_target

    def flaky(session, target, **kw):
        if target.id == broken.id:
            raise RuntimeError("boom")
        return real(session, target, **kw)

    monkeypatch.setattr(live_probes, "run_target", flaky)
    result = live_probes.run_due(seeded, {}, now=NOW)
    by_id = {c["target_id"]: c for c in result["campaigns"]}
    assert "boom" in by_id[broken.id]["error"]
    assert by_id[healthy.id]["campaign_id"]
    assert broken.next_due_at is not None  # retried next interval, not every cron call


def test_an_unreadable_stored_credential_sends_nothing(seeded, agent, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(get_settings(), "token_encryption_key", Fernet.generate_key().decode())
    target = _opted_in(seeded, auth_header="Bearer x", max_probes_per_run=1)
    monkeypatch.setattr(get_settings(), "token_encryption_key", Fernet.generate_key().decode())
    campaign = _run(seeded, target)
    assert agent.requests == []
    assert campaign.summary_json["errors"] == 1
