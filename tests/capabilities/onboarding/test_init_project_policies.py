"""`agentfox init --server` says when it leaves `.agentfox/policies/*.yaml` behind.

The reference says policy files there are loaded by `init`; with a setup key they
were silently ignored, a policy that did nothing with no word about it.
"""

from __future__ import annotations

from rich.console import Console

from agentfox.capabilities.onboarding.client import _say_project_policies


def _said(root, server="https://gw.example") -> str:
    console = Console(record=True, width=200)
    _say_project_policies(console, root, server)
    return console.export_text()


def test_policy_files_in_the_repo_are_named_with_the_command_that_loads_them(tmp_path):
    (tmp_path / ".agentfox" / "policies").mkdir(parents=True)
    (tmp_path / ".agentfox" / "policies" / "payables-guard.yaml").write_text("key: x\n")
    out = _said(tmp_path)
    assert "1 policy file(s) in .agentfox/policies (payables-guard.yaml)" in out
    assert "were not loaded into your account" in out
    assert "https://gw.example/api/policies" in out


def test_nothing_is_said_without_policy_files(tmp_path):
    assert _said(tmp_path) == ""
