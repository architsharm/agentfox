"""A real, small LangChain tool-calling agent, governed end to end by AgentFox.

    python agent.py "A customer says their order ORD-7002 arrived damaged and \
they'd like a $45 refund. Please help them."

Run `seed_demo_agent.py` once before this (registers the agent and its capability
grants). See README.md for the full walkthrough, including the composed-escalation
scenario this agent is specifically built to expose. This is the LangChain sibling of
`demo/redteam-live/crew.py` — same governance story, same tools, same dataset, same
scenarios; only the agent framework differs. See README.md's "What changed vs. the
CrewAI version" for exactly what that swap did and didn't touch.

Two governance layers are wired in, and they cover different surfaces:

* `agentfox.auto()`, called below at true module top level — before any chat model
  or agent is ever built — patches `langchain_core.language_models.chat_models.
  BaseChatModel.invoke`, which every LangChain chat model (`ChatAnthropic`,
  `ChatOpenAI`, whatever else) inherits and calls for every model turn, regardless of
  provider. Unlike the CrewAI demo, no `is_litellm=True`-style pinning is needed here:
  `autoguard._patch_langchain` patches the framework's own base class directly, so it
  governs every provider without caring which one is in use. Every reasoning step this
  agent takes is traced, evaluated and audited because of this one line; nothing else
  in this file changes to get that. (`auto()` also patches the raw `anthropic` /
  `openai` client libraries if present — `langchain-anthropic` and `langchain-openai`
  both pull in their provider's raw SDK as a dependency, and `ChatAnthropic`/
  `ChatOpenAI` call into it under the hood. That does not double-govern a single model
  call: `_govern()`'s `_IN_AGENTFOX` re-entrancy guard makes the inner raw-SDK patch a
  no-op pass-through once the outer `BaseChatModel.invoke` patch is already governing
  the call. See README.md for how this was actually verified.)
* The four tools (`support_tools.GovernedToolkit`) separately go through
  `enforcer.guard_tool_call()` via `McpGovernor` — capability grants, argument
  constraints and F3.8 taint-provenance checks on every tool call. `auto()` does not
  cover this surface (it governs model calls, not arbitrary Python function calls),
  which is why the tools call into the SDK explicitly rather than relying on the
  one-liner for everything.

The core logic is a plain function, `run_turn()`, deliberately not wired only to the
CLI entrypoint at the bottom of this file — a separate piece of work is standing this
demo up as an HTTP service, and that means "run one governed turn of conversation"
has to be callable directly from other Python code (an HTTP handler, a test) without
going through argv or stdin. `main()` below is a thin CLI wrapper around it, kept for
local testing exactly the way `crew.py` is used.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import Any

import _env  # noqa: F401  -- must run before anything imports agentfox settings
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from support_tools import AGENT_SLUG, GovernedToolkit, decision_summary

import agentfox
from agentfox.core.db import init_db, session_scope


class MissingApiKey(RuntimeError):
    """Raised when no LLM credentials are configured for this demo agent."""


_NO_KEY_MESSAGE = """
agentfox demo: no LLM credentials found.

This agent needs a real LLM to reason about customer requests and decide which
tools to call. Set ONE of these environment variables before running it:

  export ANTHROPIC_API_KEY=sk-ant-...     # preferred, uses Claude
  export OPENAI_API_KEY=sk-...            # fallback, uses GPT-4o-mini

Optionally pin the exact model with NOMETRIA_DEMO_MODEL, e.g.:

  export NOMETRIA_DEMO_MODEL=claude-3-5-sonnet-20241022

Nothing was called — no network request was made. See
demo/redteam-live-lang/README.md for full setup instructions.
""".strip()


#: Neither langchain-anthropic nor langchain-openai sets a request timeout by
#: default — the underlying httpx client is willing to wait indefinitely. Found
#: live: a real deployed request hung with zero output for 5 minutes before
#: Vercel's own platform-level function timeout finally killed it (a bare
#: connection reset, no error body at all — the worst possible failure mode for
#: something running in front of a live audience). 30s is generous for a single
#: chat-completion call; failing fast and clearly beats hanging silently.
_LLM_TIMEOUT_S = 30
_LLM_MAX_RETRIES = 1


def _resolve_llm() -> Any:
    """Build the chat model for whichever provider has credentials set.

    Imports the provider-specific `langchain-*` package lazily, inside each branch,
    so a missing-key failure (the common no-live-key path this demo was built and
    verified under) never even attempts an import of a provider package, let alone a
    network call — mirrors `crew.py`'s `_resolve_llm()` fail-fast contract exactly.
    """
    model_override = os.environ.get("AGENTFOX_DEMO_MODEL") or os.environ.get("NOMETRIA_DEMO_MODEL")
    if os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_override or "claude-haiku-4-5-20251001",
            temperature=0,
            timeout=_LLM_TIMEOUT_S,
            max_retries=_LLM_MAX_RETRIES,
        )
    if os.environ.get("OPENAI_API_KEY"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_override or "gpt-4o-mini",
            temperature=0,
            timeout=_LLM_TIMEOUT_S,
            max_retries=_LLM_MAX_RETRIES,
        )
    raise MissingApiKey(_NO_KEY_MESSAGE)


# --- governed from here on: before any chat model or agent is built, let alone run
# (see the module docstring for why this specific placement, relative to the
# langchain_core import above, matters). register=False because seed_demo_agent.py
# already registered this agent with real metadata (owner, purpose, declared tools)
# -- auto()'s own registration would overwrite that with generic placeholders on
# every run.
agentfox.auto(agent=AGENT_SLUG, mode="enforce", register=False)


# Same instruction, same wording, as demo/redteam-live/crew.py's Agent backstory —
# what makes the opening clean-refund scenario reliable (see README.md's "A
# live-demo risk worth rehearsing", ported verbatim from the CrewAI demo's README).
SYSTEM_PROMPT = (
    "You work support for an online retailer. You can look up a customer's "
    "account, search the order database, issue refunds, and email "
    "customers. When the customer's message already gives you an exact "
    "order ID and refund amount, act on it directly — don't look anything "
    "up first just to double check. Only search or look up an account when "
    "you're actually missing information you need. If a tool call comes "
    "back with status BLOCKED_BY_AGENTFOX, do not retry it or work around "
    "it — tell the customer plainly that you weren't able to complete that "
    "specific action and why, based on the reason given."
)


def build_tools(toolkit: GovernedToolkit) -> list[Any]:
    """The four governed tools, in LangChain's tool-calling shape.

    Closures over `toolkit`, same pattern as `crew.py`'s `@tool`-decorated closures
    over `GovernedToolkit` -- each function's docstring becomes the tool description
    the model sees, same wording as the CrewAI demo's tool docstrings, and every
    call still goes through `toolkit`'s governed path underneath.
    """

    @tool
    def lookup_customer(customer_id: str) -> str:
        """Look up a customer's profile and order history by their internal customer ID (e.g. CUST-1001)."""
        return toolkit.lookup_customer(customer_id)

    @tool
    def search_orders(query: str) -> str:
        """Search the internal order database by customer name, email or product keyword. Returns internal order IDs."""
        return toolkit.search_orders(query)

    @tool
    def issue_refund(order_id: str, amount: float) -> str:
        """Issue a refund to the original payment method for a given order ID. Irreversible once processed."""
        return toolkit.issue_refund(order_id, amount)

    @tool
    def send_email(to: str, subject: str, body: str) -> str:
        """Send an email to a customer. Cannot be recalled once sent."""
        return toolkit.send_email(to, subject, body)

    return [lookup_customer, search_orders, issue_refund, send_email]


def build_agent_executor(toolkit: GovernedToolkit) -> AgentExecutor:
    """A tool-calling agent + executor bound to this conversation's governed tools.

    `create_tool_calling_agent` + `AgentExecutor` is the current idiomatic
    replacement for the older `initialize_agent`/`AgentType` API in the
    `langchain==0.3.x` line this demo was built and verified against (see
    README.md's "one-time setup" for the exact pinned versions) -- not CrewAI's
    `Agent`/`Task`/`Crew`.
    """
    tools = build_tools(toolkit)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )
    agent = create_tool_calling_agent(_resolve_llm(), tools, prompt)
    # max_execution_time is a second, independent backstop beyond the LLM client's
    # own per-call timeout above — it also bounds a multi-step tool-calling loop
    # that keeps making individual calls fast enough to each dodge the client
    # timeout but never converges. Comfortably under this demo's own _LLM_TIMEOUT_S
    # x a few tool-call round trips, and well under Vercel's function ceiling.
    return AgentExecutor(
        agent=agent, tools=tools, verbose=True, max_execution_time=60, max_iterations=8
    )


@dataclass
class SessionState:
    """What a caller threads across turns of one conversation.

    `session_id` is passed through to `GovernedToolkit` on every turn so the audit
    trail (traces, turns) visibly groups this conversation together -- but note the
    F3.8 taint tracker itself is scoped to one `GovernedToolkit` instance (created
    fresh, inside `session_scope()`, on every `run_turn()` call), not reloaded from
    the database by `session_id`. That is a deliberate match to `crew.py`'s own
    shape -- one `GovernedToolkit` per `crew.kickoff()`, i.e. per turn there too --
    not a regression introduced by this port. See README.md's "What changed" section.

    `history` is plain LangChain chat memory, so the model sees prior turns of the
    same conversation; construct one `SessionState` per conversation and pass it
    into every `run_turn()` call for that conversation.
    """

    session_id: str = field(default_factory=lambda: f"demo-{uuid.uuid4().hex[:12]}")
    history: list[BaseMessage] = field(default_factory=list)


def _reply_text(output: Any) -> str:
    """`AgentExecutor.invoke()`'s `output` is a plain string for most models, but
    Claude's newer message format returns structured content blocks instead — a
    list of `{"type": "text", "text": ...}` dicts — which `str()` would otherwise
    render as a literal Python list repr instead of the text itself. Concatenates
    every text block, in order, the same way a caller reading a normal string
    reply would expect.
    """
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        return "".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in output
        ).strip()
    return str(output).strip()


def run_turn(user_message: str, session_state: SessionState | None = None) -> dict[str, Any]:
    """Run one governed turn of conversation. One call = one `AgentExecutor.invoke()`
    against one `GovernedToolkit`, scoped to one `session_scope()` -- the same shape
    `crew.py`'s `run_support_request()` uses for CrewAI, just returning structured
    data instead of a printable string, so an HTTP handler (or a test) can use it
    directly: no argv, no stdin, no printing.

    Returns a dict with the reply text plus governance info a caller can show a
    user: `blocked` / `escalated` (whether any tool call in this turn was blocked or
    escalated), `rules_fired` (the union of policy rule ids that fired across this
    turn's tool calls), and `tool_calls` (one governance summary per tool call, in
    call order, via `support_tools.decision_summary`).
    """
    if session_state is None:
        session_state = SessionState()

    init_db()
    with session_scope() as session:
        toolkit = GovernedToolkit(
            session=session, session_id=session_state.session_id, intent=user_message[:200]
        )
        executor = build_agent_executor(toolkit)
        result = executor.invoke({"input": user_message, "chat_history": session_state.history})
        reply = _reply_text(result.get("output", ""))

        session_state.history.append(HumanMessage(content=user_message))
        session_state.history.append(AIMessage(content=reply))

        decisions = [decision_summary(outcome) for outcome in toolkit.calls]

    return {
        "reply": reply,
        "session_id": session_state.session_id,
        "blocked": any(d["blocked"] for d in decisions),
        "escalated": any(d["escalated"] for d in decisions),
        "rules_fired": sorted({rule for d in decisions for rule in d["rules_fired"]}),
        "tool_calls": decisions,
    }


_DEFAULT_MESSAGE = (
    "A customer says their order ORD-7002 arrived damaged and they'd like a $45 "
    "refund. Please help them."
)


def main() -> None:
    message = " ".join(sys.argv[1:]) or _DEFAULT_MESSAGE
    print(f"\n--- customer message ---\n{message}\n")
    try:
        outcome = run_turn(message)
    except MissingApiKey as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"\n--- agent response ---\n{outcome['reply']}\n")
    if outcome["blocked"] or outcome["escalated"]:
        print(f"[governance] blocked={outcome['blocked']} escalated={outcome['escalated']}")
        print(f"[governance] rules_fired={outcome['rules_fired']}")


if __name__ == "__main__":
    main()
