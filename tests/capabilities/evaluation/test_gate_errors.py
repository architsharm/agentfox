"""Regressions: a CI gate that could not fail (#25, #26, X4).

- every case errored and the gate still printed GATE PASS (exit 0); JUnit hard-coded
  errors="0" and dropped which case broke;
- `test gate` always scored with the four defaults, whatever the baseline used;
- `test run --scorers bogus` produced an empty table and exited 0.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.capabilities.evaluation import gate, set_baseline
from agentfox.capabilities.evaluation.gating import INFORMATION_URI, to_junit, to_sarif
from agentfox.capabilities.evaluation.runner import NativeEvalRunner
from agentfox.core.models import EvalRun, EvalSuite
from agentfox.platform.providers import register_provider

runner = CliRunner()


class _BrokenProvider:
    key = "broken-test-provider"

    def available(self):
        return True

    def supports_native_streaming(self):
        return False

    def complete(self, request):
        raise RuntimeError("upstream said 401")

    def stream(self, request):
        raise RuntimeError("upstream said 401")

    def judge(self, output, rubric, model="default"):
        raise RuntimeError("upstream said 401")


def _suite(session) -> EvalSuite:
    return session.query(EvalSuite).filter_by(key="support-quality").one()


def test_a_gate_fails_when_cases_error(seeded):
    register_provider(_BrokenProvider())
    run = NativeEvalRunner().run(seeded, _suite(seeded), {"provider": "broken-test-provider"})
    assert run.summary_json["errors"] == 5
    assert run.summary_json["errored_cases"][0]["error"] == "RuntimeError: upstream said 401"

    result = gate(seeded, run)
    assert not result.passed
    assert result.exit_code == 1
    assert len(result.errors) == 5

    junit = ET.fromstring(to_junit(result, "support-quality"))
    assert junit.get("errors") == "5"
    errors = junit.findall("testcase/error")
    assert len(errors) == 5
    assert "upstream said 401" in errors[0].get("message")
    assert not junit.findall("testcase/skipped")

    sarif = json.loads(to_sarif(result))
    assert any(r["ruleId"] == "case_error" for r in sarif["runs"][0]["results"])


def test_a_clean_run_still_passes_and_reports_zero_errors(seeded):
    run = NativeEvalRunner().run(seeded, _suite(seeded), {"provider": "echo", "model": "echo-1"})
    result = gate(seeded, run)
    assert result.passed
    assert ET.fromstring(to_junit(result)).get("errors") == "0"


def test_sarif_names_the_real_tool_and_version(seeded):
    from agentfox import __version__

    run = NativeEvalRunner().run(seeded, _suite(seeded), {"provider": "echo", "model": "echo-1"})
    driver = json.loads(to_sarif(gate(seeded, run)))["runs"][0]["tool"]["driver"]
    assert driver["version"] == __version__
    assert driver["informationUri"] == INFORMATION_URI
    assert "example" not in driver["informationUri"]


def test_cli_gate_scores_with_the_baselines_scorers(seeded):
    seeded.commit()
    base = NativeEvalRunner().run(
        seeded, _suite(seeded), {"provider": "echo", "model": "echo-1"}, ["contains"]
    )
    set_baseline(seeded, base, "main")
    seeded.commit()

    result = runner.invoke(app, ["test", "gate", "support-quality"])
    assert result.exit_code == 0, result.output
    latest = (
        seeded.query(EvalRun)
        .filter(EvalRun.id != base.id)
        .order_by(EvalRun.started_at.desc())
        .first()
    )
    assert latest.scorer_keys == ["contains"]

    explicit = runner.invoke(app, ["test", "gate", "support-quality", "--scorers", "groundedness"])
    assert explicit.exit_code == 0, explicit.output
    seeded.expire_all()
    newest = seeded.query(EvalRun).order_by(EvalRun.started_at.desc()).first()
    assert newest.scorer_keys == ["groundedness"]


def test_cli_gate_exits_nonzero_when_every_case_errors(seeded):
    seeded.commit()
    register_provider(_BrokenProvider())
    result = runner.invoke(
        app, ["test", "gate", "support-quality", "--provider", "broken-test-provider"]
    )
    assert result.exit_code == 1, result.output
    assert "GATE FAIL" in result.output
    assert "upstream said 401" in result.output


def test_cli_run_refuses_an_unknown_scorer(seeded):
    seeded.commit()
    for command in ("run", "gate"):
        result = runner.invoke(app, ["test", command, "support-quality", "--scorers", "bogus"])
        assert result.exit_code == 1, result.output
        assert "unknown scorer" in result.output
        assert "groundedness" in result.output  # names the valid ones


def test_online_sampling_reports_traces_it_could_not_score(seeded):
    """`test online --rate 1.0` sampled every trace and scored only those with a
    recorded LLM output, saying nothing about the rest."""
    from agentfox.capabilities.evaluation import sample_production
    from agentfox.core.models import Span, Trace

    agent = "online-skip-agent"
    with_output = Trace(agent_slug=agent, intent="refund?")
    without_output = Trace(agent_slug=agent, intent="guard only")
    seeded.add_all([with_output, without_output])
    seeded.flush()
    seeded.add(
        Span(
            trace_id=with_output.id,
            kind="llm",
            attributes_json={"agentfox.output": "Refunds are issued within 30 days."},
        )
    )
    seeded.flush()

    run = sample_production(seeded, agent, rate=1.0)
    assert run.summary_json["population"] == 2
    assert run.summary_json["sampled"] == 1
    assert run.summary_json["skipped_no_output"] == 1
    assert run.summary_json["skipped_trace_ids"] == [without_output.id]

    seeded.commit()
    result = runner.invoke(app, ["test", "online", agent, "--rate", "1.0"])
    assert result.exit_code == 0, result.output
    assert "1 sampled trace(s) not scored" in " ".join(result.output.split())
