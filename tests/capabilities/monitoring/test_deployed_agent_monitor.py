"""A probe target that opts in is watched as a ``deployed_agent`` monitor.

The monitor runs the live probe library (`evaluation.live_probes.run_target`) and hands
the findings a run opened or closed to the shared alerting, so a probe that gets
through reaches Slack like any other monitored change. The `probes.run` job stays as a
fallback; the two share the target's ``next_due_at``, so a target is probed at most
once per window whichever runs first.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from agentfox.capabilities.evaluation import live_probes
from agentfox.capabilities.monitoring import alerts
from agentfox.capabilities.monitoring import service as monitoring
from agentfox.core.config import get_settings
from agentfox.core.models import RedTeamCampaign
from tests.capabilities.evaluation.test_live_probes import NOW, _opted_in, _target
from tests.capabilities.evaluation.test_live_probes import agent as agent  # noqa: F401 - fixture


@pytest.fixture
def alerting(monkeypatch, slack):
    monkeypatch.setattr(get_settings(), "allow_egress", True)
    monkeypatch.setattr(
        get_settings(), "slack_webhook_url", "https://hooks.slack.com/services/T/B/X"
    )
    monkeypatch.setattr(get_settings(), "slack_min_severity", "low")
    monkeypatch.setattr(monitoring, "_probe_sleep", lambda seconds: None)
    return slack


def _campaigns(session) -> int:
    return len(list(session.scalars(select(RedTeamCampaign))))


def test_opting_in_creates_the_monitor_and_registering_alone_does_not(seeded):
    registered = _target(seeded, name="registered only")
    assert monitoring.get_monitor(seeded, "deployed_agent", registered.id) is None

    target = _opted_in(seeded)
    monitor = monitoring.get_monitor(seeded, "deployed_agent", target.id)
    assert monitor is not None and monitor.enabled
    assert monitor.config_json["probe_target_id"] == target.id
    assert monitor.interval_seconds >= live_probes.MIN_INTERVAL_SECONDS
    assert "deployed_agent" in monitoring.kinds()


def test_probe_findings_reach_slack_and_a_target_is_probed_once_per_window(seeded, agent, alerting):
    target = _opted_in(seeded)
    monitor = monitoring.get_monitor(seeded, "deployed_agent", target.id)
    window = dt.timedelta(seconds=target.interval_seconds + 1)

    first = monitoring.run_monitor(seeded, monitor, now=NOW)
    assert first["summary"]["escaped"] == 0 and first["summary"]["campaign_id"]
    assert first["status"] == monitoring.BASELINE
    seeded.commit()
    assert alerts.wait_for_delivery(5)
    assert alerting == []

    # Same window: neither the monitor nor the probes.run fallback sends anything.
    sent = len(agent.requests)
    soon = NOW + dt.timedelta(minutes=5)
    skipped = monitoring.run_monitor(seeded, monitor, now=soon)
    assert "not due" in skipped["summary"]["skipped"]
    assert live_probes.run_due(seeded, {}, now=soon)["campaigns"] == []
    assert len(agent.requests) == sent and _campaigns(seeded) == 1
    # The monitor waits for the target's clock rather than its own interval.
    assert monitoring._aware(monitor.next_run_at) == monitoring._aware(target.next_due_at)

    # Next window: the agent now follows injected instructions. Findings open and alert.
    agent.vulnerable = True
    later = NOW + window
    escaped = monitoring.run_monitor(seeded, monitor, now=later)
    opened = escaped["summary"]["findings"]["opened"]
    assert escaped["summary"]["escaped"] > 0 and opened
    assert escaped["status"] == monitoring.CHANGED
    seeded.commit()
    assert alerts.wait_for_delivery(5)
    texts = [body["text"] for _url, body in alerting]
    assert texts and all("Live probe" in t for t in texts), texts

    # The fallback job running first in a window makes the monitor skip it too.
    alerting.clear()
    agent.vulnerable = False
    next_window = later + window
    ran = live_probes.run_due(seeded, {}, now=next_window)["campaigns"]
    assert [c["target_id"] for c in ran] == [target.id]
    before = _campaigns(seeded)
    again = monitoring.run_monitor(seeded, monitor, now=next_window + dt.timedelta(minutes=1))
    assert "not due" in again["summary"]["skipped"]
    assert _campaigns(seeded) == before


def test_contained_again_closes_the_findings_and_says_so(seeded, agent, alerting):
    target = _opted_in(seeded)
    monitor = monitoring.get_monitor(seeded, "deployed_agent", target.id)
    window = dt.timedelta(seconds=target.interval_seconds + 1)
    monitoring.run_monitor(seeded, monitor, now=NOW)
    agent.vulnerable = True
    opened = monitoring.run_monitor(seeded, monitor, now=NOW + window)["summary"]["findings"]
    seeded.commit()
    assert alerts.wait_for_delivery(5)
    alerting.clear()

    agent.vulnerable = False
    closed = monitoring.run_monitor(seeded, monitor, now=NOW + 2 * window)["summary"]["findings"]
    assert sorted(closed["closed"]) == sorted(opened["opened"])
    seeded.commit()
    assert alerts.wait_for_delivery(5)
    assert alerting and all("Cleared" in body["text"] for _url, body in alerting)


def test_a_target_that_opted_out_is_not_probed_and_is_not_a_failure(seeded, agent, alerting):
    target = _opted_in(seeded)
    monitor = monitoring.get_monitor(seeded, "deployed_agent", target.id)
    live_probes.opt_out(seeded, target, actor="marcus@example.com")
    result = monitoring.run_monitor(seeded, monitor, now=NOW)
    assert result["status"] == monitoring.INCONCLUSIVE
    assert monitor.consecutive_failures == 0
    assert agent.requests == []
