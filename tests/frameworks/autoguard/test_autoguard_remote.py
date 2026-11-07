"""`auto()` with an account key: every check goes to that account's gateway.

The Sentry model. A developer who connected a repository to their AgentFox account
(or exported AGENTFOX_URL and AGENTFOX_API_KEY) adds the same one line, and the calls
show up on the account's dashboard instead of in a database on their laptop. The
gateway here is the real one, in-process, sharing the test database, so each test
checks both what the caller saw and what the account recorded.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from agentfox.core.db import session_scope
from agentfox.core.models import Decision, User
from agentfox.frameworks.autoguard import Blocked, auto, remote

from .test_autoguard_tool_calls import (
    TOOLS,
    _bind_shipped_policies,
    _exfiltration_turn,
    _grant,
    _openai_response,
    _openai_tool_call,
)


@pytest.fixture
def account(client, monkeypatch):
    """A workspace API key, and the gateway every `Remote` talks to. Returns the paths
    the process called, so a test can tell the checks went over the wire."""
    from agentfox.platform.identity.operators import issue_token

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == "admin@example.com"))
        _token, raw = issue_token(session, user, name="laptop")
    paths: list[str] = []

    class Wire:
        def post(self, url, json, headers):
            paths.append(url.removeprefix("http://testserver"))
            return client.post(url, json=json, headers=headers)

    monkeypatch.setattr(
        remote.Remote, "__post_init__", lambda self: setattr(self, "_client", Wire())
    )
    monkeypatch.setenv("AGENTFOX_URL", "http://testserver")
    monkeypatch.setenv("AGENTFOX_API_KEY", raw)
    return paths


def _decisions() -> int:
    with session_scope() as session:
        return session.query(Decision).count()


def test_a_configured_key_sends_every_check_to_the_account(account, fake_openai, capsys):
    completions, script, _calls = fake_openai
    script.append(_openai_response(content="Your order shipped yesterday."))
    before = _decisions()
    governed = auto(agent="support-bot")

    completions().create(model="gpt-4o", messages=[{"role": "user", "content": "where is it?"}])

    assert governed.remote is not None
    assert "/v1/guard/input" in account and "/v1/guard/output" in account
    assert _decisions() > before  # recorded on the account
    assert "AgentFox account at http://testserver" in capsys.readouterr().err


def test_an_ungranted_agents_ordinary_tool_call_still_runs(account, fake_openai):
    """Adding the one line to an existing app must not refuse its tools: the gateway
    applies the same no-grants carve-out the local path does."""
    _bind_shipped_policies()
    completions, script, _calls = fake_openai
    reply = _openai_response(_openai_tool_call("c1", "fetch_url", {"url": "https://x.io"}))
    script.append(reply)
    auto(agent="support-bot", quiet=True)

    assert (
        completions().create(
            model="gpt-4o", messages=[{"role": "user", "content": "read x.io"}], tools=TOOLS
        )
        is reply
    )
    assert "/v1/guard/tool_call" in account


def test_default_deny_applies_once_the_agent_has_a_grant(account, fake_openai):
    _grant("support-bot", "read_customer_record")
    completions, script, _calls = fake_openai
    script.append(_openai_response(_openai_tool_call("c1", "issue_refund", {"order": "o-1"})))
    auto(agent="support-bot", quiet=True)

    with pytest.raises(Blocked, match="issue_refund"):
        completions().create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS
        )


def test_an_argument_copied_from_a_tool_result_is_tainted_on_the_gateway(account, fake_openai):
    """The conversation goes with the tool call, so the account sees the injection's
    send_email for what it is."""
    _bind_shipped_policies()
    _grant("support-bot", "send_email")
    completions, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    auto(agent="support-bot", quiet=True)

    with pytest.raises(Blocked) as excinfo:
        completions().create(model="gpt-4o", messages=messages, tools=TOOLS)
    assert excinfo.value.result.verdict in ("escalate", "block")
    assert "send_email" in str(excinfo.value)


def test_observe_mode_never_refuses(account, fake_openai):
    _grant("support-bot", "read_customer_record")
    completions, script, _calls = fake_openai
    reply = _openai_response(_openai_tool_call("c1", "issue_refund", {"order": "o-1"}))
    script.append(reply)
    governed = auto(agent="support-bot", mode="observe", quiet=True)

    assert (
        completions().create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS
        )
        is reply
    )
    assert governed.calls_blocked == 0


def test_the_env_file_init_writes_is_enough(account, fake_openai, monkeypatch, tmp_path):
    """`agentfox init` writes .agentfox/agentfox.env; the app needs nothing exported."""
    key = remote.configured().key
    monkeypatch.delenv("AGENTFOX_URL")
    monkeypatch.delenv("AGENTFOX_API_KEY")
    (tmp_path / ".agentfox").mkdir()
    (tmp_path / ".agentfox" / "agentfox.env").write_text(
        f"# written by agentfox init\nAGENTFOX_URL=http://testserver\nAGENTFOX_API_KEY={key}\n"
    )
    monkeypatch.chdir(tmp_path)
    completions, script, _calls = fake_openai
    script.append(_openai_response(content="ok"))
    governed = auto(agent="support-bot", quiet=True)

    completions().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert governed.remote is not None
    assert "/v1/guard/output" in account


def test_without_a_key_nothing_changes(fake_openai, monkeypatch):
    monkeypatch.delenv("AGENTFOX_URL", raising=False)
    monkeypatch.delenv("AGENTFOX_API_KEY", raising=False)
    completions, script, _calls = fake_openai
    script.append(_openai_response(content="ok"))
    governed = auto(agent="support-bot", quiet=True)

    completions().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert governed.remote is None


def test_inside_inits_attack_test_auto_stands_down(fake_openai, monkeypatch):
    """`agentfox init` runs the attack test by importing the app; the auto() line init
    added must not report every attack as the app's own traffic."""
    from agentfox.frameworks.autoguard import ATTACK_TEST_ENV

    monkeypatch.setenv(ATTACK_TEST_ENV, "1")
    governed = auto(agent="support-bot", quiet=True)
    assert not governed.active and governed.environment == "test"
