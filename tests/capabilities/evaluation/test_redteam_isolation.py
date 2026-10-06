"""Regressions for the red-team CLI and its side effects (#34, #35, #36).

- probe tool calls wrote `redteam.sim.*` Decisions and containment findings into the
  production tables, where they showed in findings and were replayed by simulate;
- `test redteam` exited 0 when attacks got through;
- `--deployment-probes` silently did nothing without `--adaptive`;
- adaptive output printed raw stats dicts.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import func, select
from typer.testing import CliRunner

from agentfox.capabilities.evaluation import run_campaign
from agentfox.cli.main import app
from agentfox.core.models import Decision, Finding

runner = CliRunner()


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_probe_tool_calls_do_not_write_production_decisions_or_findings(seeded):
    before_findings = seeded.scalar(select(func.count()).select_from(Finding))
    campaign = run_campaign(seeded, "support-triage")
    # Tool-call and scenario probes ran and were scored...
    kinds = {p["kind"] for p in campaign.summary_json["probes"]}
    assert {"tool_call", "scenario"} <= kinds
    # ...without leaving a decision a replay would pick up,
    assert not seeded.scalar(
        select(func.count()).select_from(Decision).where(Decision.tool_key.like("redteam.sim%"))
    )
    # or a containment finding about a simulated tool in the findings queue.
    leaked = [
        f.title
        for f in seeded.scalars(select(Finding))
        if "redteam.sim" in (f.title or "") or f.type == "containment"
    ]
    assert leaked == []
    # Only the campaign's own verdict may become a finding.
    new = seeded.scalar(select(func.count()).select_from(Finding)) - before_findings
    assert new <= 2


def _fake_campaign(succeeded: int, adaptive: dict | None = None):
    summary = {
        "probes_run": 3,
        "attacks_run": 3,
        "attacks_blocked": 3 - succeeded,
        "attacks_succeeded": succeeded,
        "benign_probes_run": 0,
        "benign_false_positives": 0,
        "recall": (3 - succeeded) / 3,
        "posture_score": (3 - succeeded) / 3,
    }
    if adaptive:
        summary["adaptive"] = adaptive
    return SimpleNamespace(id="rtc_fake", summary_json=summary)


def test_redteam_exits_nonzero_when_an_attack_gets_through(seeded, monkeypatch):
    import agentfox.capabilities.evaluation as evaluation

    seeded.commit()
    monkeypatch.setattr(evaluation, "run_campaign", lambda *a, **k: _fake_campaign(1))
    result = runner.invoke(app, ["test", "redteam", "support-triage"])
    assert result.exit_code == 1, result.output
    assert "1 attack(s) got through" in _flat(result.output)

    allowed = runner.invoke(app, ["test", "redteam", "support-triage", "--allow-escapes"])
    assert allowed.exit_code == 0, allowed.output

    monkeypatch.setattr(evaluation, "run_campaign", lambda *a, **k: _fake_campaign(0))
    clean = runner.invoke(app, ["test", "redteam", "support-triage"])
    assert clean.exit_code == 0, clean.output


def test_deployment_probes_without_adaptive_says_it_has_no_effect(seeded, monkeypatch):
    import agentfox.capabilities.evaluation as evaluation

    seeded.commit()
    seen = {}

    def fake(*args, **kwargs):
        seen.update(kwargs)
        return _fake_campaign(0)

    monkeypatch.setattr(evaluation, "run_campaign", fake)
    result = runner.invoke(app, ["test", "redteam", "support-triage", "--deployment-probes"])
    assert result.exit_code == 0, result.output
    assert "no effect without --adaptive" in _flat(result.output)

    quiet = runner.invoke(app, ["test", "redteam", "support-triage", "--adaptive"])
    assert "no effect" not in quiet.output
    assert seen["include_deployment_probes"] is True


def test_adaptive_output_prints_counts_not_dicts(seeded, monkeypatch):
    import agentfox.capabilities.evaluation as evaluation

    seeded.commit()
    adaptive = {
        "escape_rate_by_semantics": {
            "readable": {"attempts": 8, "escapes": 0, "escape_rate": 0.0},
            "requires_decode": {"attempts": 3, "escapes": 2, "escape_rate": 0.6667},
        }
    }
    monkeypatch.setattr(
        evaluation, "run_campaign", lambda *a, **k: _fake_campaign(0, adaptive=adaptive)
    )
    result = runner.invoke(app, ["test", "redteam", "support-triage", "--adaptive"])
    out = _flat(result.output)
    assert "{" not in out
    assert "readable 0/8" in out
    assert "requires_decode 2/3 (67%)" in out
