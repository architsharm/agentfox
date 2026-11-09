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


def test_connect_finds_the_agents_file_itself_and_names_it_as_the_dashboard_does(
    client, tmp_path, monkeypatch
):
    """Through the real connect route: the server keeps no file paths, so `init` looks up
    the file of each agent the server registered, by name, in its own map. (It crashed
    on the missing path when the server's reply was trusted for it.)"""
    from sqlalchemy import select

    from agentfox.capabilities.onboarding import client as init_client
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent
    from tests.conftest import as_user

    class Api:
        def __init__(self, server, key):
            self.key = key

        def post(self, path, body):
            response = client.post(
                f"/api/onboarding{path}", json=body, headers={"Authorization": f"Bearer {self.key}"}
            )
            response.raise_for_status()
            return response.json()

    key = client.get("/api/onboarding/key", headers=as_user("admin@example.com")).json()["value"]
    root = _repo(tmp_path)
    console = Console(record=True, width=200)
    init_client.report(Api("http://testserver", key), console, root, "http://testserver", key)

    out = console.export_text()
    # No terminal in tests, so the line is shown rather than added, under the slug the
    # server registered for the agent init mapped.
    with session_scope() as session:
        slugs = list(session.scalars(select(Agent.slug).where(Agent.status == "draft")))
    assert any(f'agentfox.auto("{slug}")' in out for slug in slugs), out
    assert (root / ".agentfox" / "agentfox.env").is_file()


def test_with_two_agents_in_one_file_the_line_names_the_one_the_script_runs(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "main.py").write_text(
        "billing = make('billing')\nsupport = make('support')\n\n"
        "if __name__ == '__main__':\n    support.invoke({})\n"
    )
    registered = [
        {"slug": "billing", "name": "billing", "file": "main.py", "attr": "billing"},
        {"slug": "support-triage", "name": "support-triage", "file": "main.py", "attr": "support"},
    ]
    console = Console(record=True)
    connect_live_traffic(console, tmp_path, "https://gw", "nom_api_abc", registered, ask=False)
    assert 'agentfox.auto("support-triage")' in console.export_text()


def test_a_rejected_key_says_rejected_not_unreachable(tmp_path):
    """`init --key <wrong>` reached the server and was refused; it used to say
    "Couldn't reach AgentFox", which sent people to check their network."""
    import pytest

    from agentfox.capabilities.onboarding import client as init_client

    class Refusing:
        def post(self, path, body):
            raise init_client.ApiError(401, "That setup key isn't valid")

    console = Console(record=True, width=200)
    with pytest.raises(SystemExit):
        init_client.report(Refusing(), console, _repo(tmp_path), "https://gw.example", "k")
    out = console.export_text()
    assert "rejected this key (401)" in out
    assert "Get started → Create a key" in out
    assert "Couldn't reach" not in out


def test_the_env_file_names_the_command_that_wrote_it(tmp_path):
    root = _repo(tmp_path)
    connect_live_traffic(
        Console(record=True), root, "https://gw", "nom_api_abc", REGISTERED, ask=False
    )
    head = (root / ".agentfox" / "agentfox.env").read_text().splitlines()[0]
    assert head == "# Written by `agentfox init`. Holds credentials: never commit it."
