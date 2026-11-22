"""#219 — `policy list --json` prints the rows the table prints, for CI.

A CI step could not ask "which policies are still in observe mode" without
scraping the Rich table. `--json` emits the same policies, versions and modes as
JSON, the same shape `permit list`, `scan` and `doctor` already take.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.platform.policy import PolicyDocument, save_policy

RULE = "rules:\n  - id: {id}\n    when: {{surface: [{surface}]}}\n    effect: block\n"
OBSERVED = "key: watched\nmode: observe\n" + RULE.format(id="w.rule", surface="input")
ENFORCED = "key: enforced\nmode: enforce\n" + RULE.format(id="e.rule", surface="output")


def test_policy_list_json_lists_the_same_rows_as_the_table(session):
    save_policy(session, PolicyDocument.from_yaml(OBSERVED), bind_mode="observe")
    save_policy(session, PolicyDocument.from_yaml(ENFORCED), bind_mode="enforce")
    session.commit()

    runner = CliRunner()
    table = runner.invoke(app, ["policy", "list"]).output
    listed = runner.invoke(app, ["policy", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    rows = {row["policy"]: row for row in json.loads(listed.output)}

    assert set(rows) == {"watched", "enforced"}
    assert rows["watched"]["mode"] == "observe"
    assert rows["enforced"]["mode"] == "enforce"
    # The same version and rules count the table printed for each policy.
    for key, row in rows.items():
        line = next(x for x in table.splitlines() if x.startswith(key))
        assert f"v{row['version']}" in line and row["mode"] in line
        assert row["rules"] == int(line.split()[-1])
