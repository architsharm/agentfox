"""#49 — `policy effective` shows each layer's mode, not one mode for all of them.

The header said "mode enforce" whenever any layer enforced, which read as though
every rule listed was enforcing.
"""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.platform.policy import PolicyDocument, save_policy

RULE = "rules:\n  - id: {id}\n    when: {{surface: [{surface}]}}\n    effect: block\n"
OBSERVED = "key: watched\nmode: observe\n" + RULE.format(id="w.rule", surface="input")
ENFORCED = "key: enforced\nmode: enforce\n" + RULE.format(id="e.rule", surface="output")


def test_effective_reports_per_layer_and_per_rule_modes(session):
    save_policy(session, PolicyDocument.from_yaml(OBSERVED), bind_mode="observe")
    save_policy(session, PolicyDocument.from_yaml(ENFORCED), bind_mode="enforce")
    session.commit()

    out = CliRunner().invoke(app, ["policy", "effective", "--environment", "production"]).output
    header = out.splitlines()[0]
    assert "mode enforce" not in header
    lines = {line.split()[0]: line for line in out.splitlines() if line.strip()}
    assert "watched" in out and "enforced" in out
    assert "observe" in lines["w.rule"] and "enforce" in lines["e.rule"]
    layer_lines = [line for line in out.splitlines() if "org:*(extend)" in line]
    assert any("watched" in line and "observe" in line for line in layer_lines)
    assert any("enforced" in line and "enforce" in line for line in layer_lines)


def test_business_rules_are_listed_and_counted_like_other_rules(session, monkeypatch):
    """An approval limit is in force too: `policy effective` lists it with a title, and
    `policy list` counts it, so the CLI agrees with Your rules in the dashboard."""
    from agentfox.apps.cli.commands import _shared
    from agentfox.capabilities.business import Ladder, save_ladder

    # The console is made once per process; give it a wide terminal whatever ran first.
    monkeypatch.setattr(_shared.console, "width", 160)
    save_policy(session, PolicyDocument.from_yaml(OBSERVED), bind_mode="observe")
    save_ladder(
        session,
        Ladder.model_validate(
            {
                "key": "custom-payments-transfer",
                "tool": "payments.transfer",
                "field": "arguments.amount",
                "unit": "USD",
                "bands": [
                    {"upto": 100, "outcome": "allow"},
                    {"outcome": "escalate", "reason": "Transfers over $100 need finance."},
                ],
            }
        ),
        actor="t@example.com",
    )
    session.commit()

    out = CliRunner().invoke(app, ["policy", "effective"]).output
    assert out.splitlines()[0].startswith("effective policy in production")
    line = next(x for x in out.splitlines() if x.startswith("business.custom-payments-transfer"))
    assert "Transfers over $100 need finance." in line
    assert "escalate" in line and "observe" in line
    assert (
        "title"
        in out.splitlines()[
            next(i for i, x in enumerate(out.splitlines()) if x.startswith("rule "))
        ]
    )

    listed = CliRunner().invoke(app, ["policy", "list"]).output
    row = next(x for x in listed.splitlines() if x.startswith("business rules"))
    assert row.split()[-1] == "1" and "observe" in row
