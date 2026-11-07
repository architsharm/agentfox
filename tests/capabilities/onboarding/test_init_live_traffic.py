"""After `agentfox init --key` connects, the app's own calls reach the account: the
workspace key is saved where `agentfox.auto()` finds it, and with a yes the one line
is added to the file that runs the agent."""

from __future__ import annotations

from rich.console import Console

from agentfox.capabilities.onboarding.client import connect_live_traffic
from agentfox.frameworks.autoguard import remote

APP = (
    "from langgraph.prebuilt import create_react_agent\n\n"
    "support = create_react_agent(model='openai:gpt-4o', tools=[], name='support')\n\n"
    "if __name__ == '__main__':\n    support.invoke({})\n"
)
REGISTERED = [{"slug": "support", "name": "support", "file": "main.py"}]


def _repo(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "main.py").write_text(APP)
    return tmp_path


def test_a_yes_adds_the_line_and_auto_finds_the_key(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    console = Console(record=True)
    monkeypatch.setattr(console, "input", lambda prompt: "")  # Enter = yes
    changed = connect_live_traffic(
        console, root, "https://gw.example/", "nom_api_abc", REGISTERED, ask=True
    )

    assert changed == root / "main.py"
    text = changed.read_text()
    assert 'agentfox.auto("support")' in text
    assert text.index("agentfox.auto(") < text.index("from langgraph")
    assert ".agentfox/agentfox.env" in (root / ".gitignore").read_text()
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGENTFOX_URL", raising=False)
    monkeypatch.delenv("AGENTFOX_API_KEY", raising=False)
    found = remote.configured()
    assert found is not None and found.url == "https://gw.example" and found.key == "nom_api_abc"


def test_without_a_terminal_the_line_is_shown_not_added(tmp_path):
    root = _repo(tmp_path)
    console = Console(record=True)
    assert (
        connect_live_traffic(console, root, "https://gw", "nom_api_abc", REGISTERED, ask=False)
        is None
    )
    assert "agentfox.auto" not in (root / "main.py").read_text()
    assert 'agentfox.auto("support")' in console.export_text()
    assert (root / ".agentfox" / "agentfox.env").is_file()


def test_an_old_setup_key_changes_nothing(tmp_path):
    root = _repo(tmp_path)
    assert (
        connect_live_traffic(Console(), root, "https://gw", "afi_old", REGISTERED, ask=True) is None
    )
    assert not (root / ".agentfox").exists()
