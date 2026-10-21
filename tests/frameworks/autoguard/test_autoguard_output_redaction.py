"""`agentfox.auto()` applies an output redaction, not only records it.

A policy that says "hide personal data in replies" (``effect: redact`` on the output
surface) used to be evaluated and written to the record under `auto()` and then
ignored: only ``block`` raised, and nothing rewrote the response, so the caller got
the personal data the policy promised to hide. The gateway proxy and the LangGraph
guard both substitute the enforcer's rewritten text; these tests hold `auto()` to the
same, in each patched client's own response shape, sync and async.

The fakes are the ones `test_autoguard_async` builds: the real SDKs are deliberately
not installed in the dev environment.
"""

from __future__ import annotations

import types

import pytest

from agentfox.frameworks.autoguard import Blocked, auto, off, state
from tests.frameworks.autoguard.test_autoguard_async import (
    _LEAK,
    _NS,
    _enforce_baseline,
    _install_anthropic,
    _install_langchain,
    _install_litellm,
    _install_openai,
    _llm_outputs,
    _swap_modules,
)

_PII = "Reach Jane at jane.doe@example.com today."
_REDACTED = "Reach Jane at [REDACTED:PII.EMAIL] today."
_HI = [{"role": "user", "content": "hi"}]


@pytest.fixture
def app_db(isolated_db):
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)
    yield


@pytest.fixture(autouse=True)
def _reset():
    yield
    off()


@pytest.fixture
def openai_pii():
    completions, _calls, restore = _install_openai(_PII)
    yield completions
    restore()


@pytest.fixture
def anthropic_pii():
    messages, _calls, restore = _install_anthropic(_PII)
    yield messages
    restore()


@pytest.fixture
def litellm_pii():
    module, _calls, restore = _install_litellm(_PII)
    yield module
    restore()


@pytest.fixture
def langchain_pii():
    model_cls, _calls, restore = _install_langchain(_PII)
    yield model_cls
    restore()


def _turn_texts() -> list[str]:
    from agentfox.core.db import session_scope
    from agentfox.core.models import ConversationTurn

    with session_scope() as session:
        return [t.agent_text for t in session.query(ConversationTurn).all()]


# ---------------------------------------------------------------------------
# An enforced redaction rewrites the response, in each client's own shape
# ---------------------------------------------------------------------------


def test_openai_reply_is_redacted(app_db, openai_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    response = openai_pii.Completions().create(model="gpt-4o", messages=_HI)
    assert response.choices[0].message.content == _REDACTED
    assert state().calls_blocked == 0


async def test_async_openai_reply_is_redacted(app_db, openai_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    response = await openai_pii.AsyncCompletions().create(model="gpt-4o", messages=_HI)
    assert response.choices[0].message.content == _REDACTED


def test_anthropic_reply_is_redacted(app_db, anthropic_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    response = anthropic_pii.Messages().create(
        model="claude-sonnet-4-5", max_tokens=64, messages=_HI
    )
    assert response.content[0].text == _REDACTED
    assert response.content[0].type == "text"


async def test_async_anthropic_reply_is_redacted(app_db, anthropic_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    response = await anthropic_pii.AsyncMessages().create(
        model="claude-sonnet-4-5", max_tokens=64, messages=_HI
    )
    assert response.content[0].text == _REDACTED


def test_an_anthropic_reply_split_across_text_blocks_is_redacted_whole(app_db):
    """The output is evaluated as one text; the rewrite lands in the first text block
    and the rest are emptied, so the concatenation the caller reads is the redaction.
    A non-text block between them is left alone."""
    messages, _calls, restore = _install_anthropic(_PII)
    thinking = _NS(type="thinking", thinking="look up Jane")
    reply = _NS(
        content=[
            _NS(type="text", text="Reach Jane at jane.doe"),
            thinking,
            _NS(type="text", text="@example.com today."),
        ],
        usage=None,
    )
    messages.Messages.create = lambda self, **kwargs: reply
    try:
        _enforce_baseline()
        auto(agent="support-triage", quiet=True)
        response = messages.Messages().create(model="claude-sonnet-4-5", messages=_HI)
        assert [b.type for b in response.content] == ["text", "thinking", "text"]
        assert "".join(b.text for b in response.content if b.type == "text") == _REDACTED
        assert response.content[1] is thinking and thinking.thinking == "look up Jane"
    finally:
        restore()


def test_litellm_reply_is_redacted(app_db, litellm_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    response = litellm_pii.completion(model="gpt-4o", messages=_HI)
    assert response.choices[0].message.content == _REDACTED


async def test_async_litellm_reply_is_redacted(app_db, litellm_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    response = await litellm_pii.acompletion(model="gpt-4o", messages=_HI)
    assert response.choices[0].message.content == _REDACTED


def test_langchain_reply_is_redacted(app_db, langchain_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    assert langchain_pii().invoke("hi").content == _REDACTED


async def test_async_langchain_reply_is_redacted(app_db, langchain_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    assert (await langchain_pii().ainvoke("hi")).content == _REDACTED


def test_strict_mode_applies_a_redaction_the_policy_only_observes(app_db, openai_pii):
    """``mode="enforce"`` acts on the effective verdict, for redaction as for block."""
    auto(agent="support-triage", mode="enforce", quiet=True)
    response = openai_pii.Completions().create(model="gpt-4o", messages=_HI)
    assert response.choices[0].message.content == _REDACTED


def test_the_recorded_turn_is_the_redacted_text(app_db, openai_pii):
    """What the caller got is what the conversation record holds."""
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    openai_pii.Completions().create(model="gpt-4o", messages=_HI)
    texts = _turn_texts()
    assert _REDACTED in texts
    assert _PII not in texts


def test_a_response_that_cannot_be_rewritten_is_refused(app_db):
    """A redaction that cannot be applied fails closed rather than handing the
    caller the text the policy said to hide."""

    class _ReadOnly:
        content = _PII

        def __setattr__(self, name, value):
            raise AttributeError("read-only")

    litellm = types.ModuleType("litellm")
    litellm.completion = lambda **kw: _NS(choices=[_NS(message=_ReadOnly())], usage=None)
    restore = _swap_modules("litellm", {"litellm": litellm})
    try:
        _enforce_baseline()
        auto(agent="support-triage", quiet=True)
        with pytest.raises(Blocked, match="could not be applied"):
            litellm.completion(model="gpt-4o", messages=_HI)
        assert state().calls_blocked == 1
    finally:
        restore()


# ---------------------------------------------------------------------------
# What does not change
# ---------------------------------------------------------------------------


def test_an_observe_mode_policy_redacts_nothing_under_the_default_mode(app_db, openai_pii):
    """The seeded baseline observes: the redaction is recorded, the reply untouched."""
    auto(agent="support-triage", quiet=True)
    response = openai_pii.Completions().create(model="gpt-4o", messages=_HI)
    assert response.choices[0].message.content == _PII


def test_observe_mode_records_but_never_rewrites(app_db, openai_pii, anthropic_pii):
    _enforce_baseline()
    auto(agent="support-triage", mode="observe", quiet=True)
    response = openai_pii.Completions().create(model="gpt-4o", messages=_HI)
    assert response.choices[0].message.content == _PII
    message = anthropic_pii.Messages().create(model="claude-sonnet-4-5", max_tokens=8, messages=_HI)
    assert message.content[0].text == _PII
    assert _llm_outputs() == [_PII, _PII], "both outputs are still on the record"
    assert state().calls_blocked == 0


def test_a_clean_reply_is_returned_unchanged(app_db):
    completions, _calls, restore = _install_openai("Your order ships Tuesday.")
    try:
        _enforce_baseline()
        auto(agent="support-triage", quiet=True)
        response = completions.Completions().create(model="gpt-4o", messages=_HI)
        assert response.choices[0].message.content == "Your order ships Tuesday."
    finally:
        restore()


def test_a_block_still_raises_rather_than_redacting(app_db):
    completions, _calls, restore = _install_openai(_LEAK)
    try:
        _enforce_baseline()
        auto(agent="support-triage", quiet=True)
        with pytest.raises(Blocked):
            completions.Completions().create(model="gpt-4o", messages=_HI)
        assert state().calls_blocked == 1
    finally:
        restore()


# ---------------------------------------------------------------------------
# Streams: chunks already yielded cannot be rewritten, so the stream is refused
# ---------------------------------------------------------------------------


def test_an_enforced_redaction_on_a_stream_raises_at_the_end(app_db, openai_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    stream = openai_pii.Completions().create(model="gpt-4o", messages=_HI, stream=True)
    with pytest.raises(Blocked, match="stream"):
        list(stream)
    assert state().calls_blocked == 1


async def test_an_enforced_redaction_on_an_async_stream_raises_at_the_end(app_db, anthropic_pii):
    _enforce_baseline()
    auto(agent="support-triage", quiet=True)
    stream = await anthropic_pii.AsyncMessages().create(
        model="claude-sonnet-4-5", max_tokens=64, messages=_HI, stream=True
    )
    with pytest.raises(Blocked, match="stream"):
        [e async for e in stream]


def test_observe_mode_streams_pass_through_untouched(app_db, openai_pii):
    _enforce_baseline()
    auto(agent="support-triage", mode="observe", quiet=True)
    chunks = list(openai_pii.Completions().create(model="gpt-4o", messages=_HI, stream=True))
    assert "".join(c.choices[0].delta.content for c in chunks if c.choices) == _PII
    assert state().calls_blocked == 0
