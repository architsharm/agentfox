"""Every `agentfox policy enforce …` the docs, `up` and `auto()` suggest works.

`policy enforce baseline` answered "unknown policy 'baseline'" on a workspace set up
from the dashboard (its libraries are per-agent copies, and `baseline` was never
loaded), and enforcing changed nothing for an app whose `auto()` line `up` had
written with `mode="observe"`, without a word about it.
"""

from __future__ import annotations

from sqlalchemy import select
from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.core.models import Policy
from agentfox.platform.policy import PolicyDocument, current_binding, save_policy

BASIC = (
    "key: {key}\nmode: observe\n"
    "rules:\n  - id: basic.x\n    when: {{surface: [input]}}\n    effect: block\n"
)


def _mode(session, key: str) -> str | None:
    policy = session.scalar(select(Policy).where(Policy.key == key))
    if policy is None:
        return None
    binding, _ = current_binding(session, policy.id)
    return binding.mode if binding else None


def test_enforce_baseline_loads_the_shipped_pack_when_it_was_never_loaded(session):
    result = CliRunner().invoke(app, ["policy", "enforce", "baseline"])
    assert result.exit_code == 0, result.output
    assert "unknown policy" not in result.output
    session.expire_all()
    assert _mode(session, "baseline") == "enforce"


def test_enforce_a_library_switches_every_agents_copy(session):
    for slug in ("payables", "support"):
        key = f"agent.{slug}.basic"
        save_policy(session, PolicyDocument.from_yaml(BASIC.format(key=key)), bind_mode="observe")
    session.commit()

    result = CliRunner().invoke(app, ["policy", "enforce", "basic"])
    assert result.exit_code == 0, result.output
    session.expire_all()
    assert _mode(session, "agent.payables.basic") == "enforce"
    assert _mode(session, "agent.support.basic") == "enforce"


def test_an_unknown_name_still_says_so(session):
    result = CliRunner().invoke(app, ["policy", "enforce", "no-such-thing"])
    assert result.exit_code == 1
    assert "unknown policy 'no-such-thing'" in result.output


def test_enforce_names_an_auto_line_that_never_blocks(session, tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text(
        "import agentfox\n\n"
        'agentfox.auto("support-bot", mode="observe")  # added by `agentfox up`\n'
    )
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["policy", "enforce", "baseline"])
    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert 'app.py:3 calls agentfox.auto with mode="observe"' in out
    assert 'agentfox.auto("support-bot") # added by `agentfox up`' in out
