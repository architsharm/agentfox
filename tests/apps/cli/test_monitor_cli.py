"""`agentfox scan monitors` and `agentfox admin jobs run-due` against the local database."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from agentfox.apps.cli.commands.monitors import parse_interval
from agentfox.apps.cli.main import app

runner = CliRunner()


def _invoke(*args: str):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_add_list_pause_resume_remove(isolated_db):
    out = _invoke(
        "scan",
        "monitors",
        "add",
        "hosted_api",
        "https://api.example.com/openapi.json",
        "--every",
        "2h",
    )
    assert "every 2h" in out
    listing = json.loads(_invoke("scan", "monitors", "list", "--json"))["monitors"]
    assert [(m["kind"], m["interval_seconds"]) for m in listing] == [("hosted_api", 7200)]

    _invoke("scan", "monitors", "pause", "https://api.example.com/openapi.json")
    assert (
        json.loads(_invoke("scan", "monitors", "list", "--json"))["monitors"][0]["enabled"] is False
    )
    _invoke("scan", "monitors", "resume", listing[0]["id"])
    assert (
        json.loads(_invoke("scan", "monitors", "list", "--json"))["monitors"][0]["enabled"] is True
    )

    again = runner.invoke(
        app, ["scan", "monitors", "add", "hosted_api", "https://api.example.com/openapi.json"]
    )
    assert again.exit_code == 1
    _invoke("scan", "monitors", "remove", listing[0]["id"])
    assert json.loads(_invoke("scan", "monitors", "list", "--json"))["monitors"] == []


def test_unknown_kind_is_refused(isolated_db):
    result = runner.invoke(app, ["scan", "monitors", "add", "ftp", "x"])
    assert result.exit_code == 2 and "unknown monitor kind" in result.output


def test_run_reports_a_failure_without_crashing(isolated_db):
    _invoke("scan", "monitors", "add", "github_repo", "acme/bot")
    results = json.loads(_invoke("scan", "monitors", "run", "--json"))["results"]
    assert results[0]["status"] == "failed" and "no GitHub account" in results[0]["error"]
    # Not due again until its interval passes.
    assert json.loads(_invoke("scan", "monitors", "run", "--json"))["results"] == []


def test_admin_jobs_run_due_is_the_cron_pass(isolated_db):
    # A deployment whose only data is a monitor still gets its schedules.
    _invoke("scan", "monitors", "add", "github_repo", "acme/bot")
    first = json.loads(_invoke("admin", "jobs", "run-due", "--json"))
    assert first["scheduled"] >= 1 and first["processed"] >= 1
    monitor = json.loads(_invoke("scan", "monitors", "list", "--json"))["monitors"][0]
    assert monitor["status"] == "failed", "the monitors.run job ran it"
    second = json.loads(_invoke("admin", "jobs", "run-due", "--json"))
    assert second["scheduled"] == 0, "nothing is due again inside its interval"


def test_parse_interval():
    assert parse_interval("90") == 90
    assert parse_interval("30m") == 1800
    assert parse_interval("6h") == 21600
    assert parse_interval("1d") == 86400
