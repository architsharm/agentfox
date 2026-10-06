"""#49 — `policy effective` shows each layer's mode, not one mode for all of them.

The header said "mode enforce" whenever any layer enforced, which read as though
every rule listed was enforcing.
"""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.cli.main import app
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
