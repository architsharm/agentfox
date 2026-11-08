"""The workflow that drives the hosted job runner, and with it the public /live page.

From the day it was added until 2026-11-08 every run printed "AGENTFOX_API_URL or
AGENTFOX_CRON_SECRET is not set; nothing to run." and passed: the cron secret was
configured, the URL secret was not, and a green no-op hid it while /live, which
promises hourly runs, fell days behind.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "monitors.yml"


def _step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text())
    return doc["jobs"]["run"]["steps"][0]


def test_the_upstream_repository_has_an_api_url_without_a_secret():
    api_url = _step()["env"]["API_URL"]
    assert "secrets.AGENTFOX_API_URL" in api_url
    assert "vars.AGENTFOX_API_URL" in api_url
    assert "github.repository == 'architsharm/agentfox'" in api_url
    assert "https://guardrails-api.vercel.app" in api_url


def test_a_cron_secret_without_a_url_fails_instead_of_passing():
    script = _step()["run"]
    no_secret = script.index('if [ -z "$CRON_SECRET" ]')
    no_url = script.index('if [ -z "$API_URL" ]')
    assert no_secret < no_url
    # A fork with nothing configured still passes quietly; half-configured fails.
    assert "exit 0" in script[no_secret:no_url]
    assert "exit 1" in script[no_url:]
