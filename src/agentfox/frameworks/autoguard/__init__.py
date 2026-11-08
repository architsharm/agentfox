"""The one-liner. `import agentfox; agentfox.auto()` and an existing app is governed.

Every integration surface built so far asks the developer to change how they call the
model: use our SDK, decorate the node, point at the gateway. Each is a small ask, and
the sum of small asks is why governance tooling sits in a proof-of-concept for six
months. The measured version of this: eleven of eleven engineers use LangGraph, and
not one of them adopted a governance product — they hand-rolled a wrapper, because a
wrapper they wrote is cheaper than a migration they have to justify.

So this module patches the client libraries in place — sync *and* async entry points,
streamed and buffered responses. The developer adds one line at startup and every
existing `client.chat.completions.create(...)` in the codebase is governed, traced and
audited without any of them being touched.

What is governed on each call: the request messages (pre-flight), the response text
(post-flight), and every tool call the response asks for — OpenAI ``tool_calls``
(and LiteLLM's, which share the shape), Anthropic ``tool_use`` blocks, LangChain
``AIMessage.tool_calls``, buffered or streamed. Each tool call goes through
`Enforcer.guard_tool_call` with argument provenance from the request's own
conversation (a value copied out of a ``role="tool"`` message is ``tool_result``
taint), and a tool seen for the first time is registered with an *inferred* impact
for a human to confirm. A refused tool call raises `Blocked` instead of returning
the response, so the caller's code never runs it.

The OpenAI Responses API (``client.responses.create`` / ``.parse`` / ``.stream``,
sync and async, buffered, streamed, ``with_streaming_response`` and
``with_raw_response``) is governed the same way: ``instructions`` and ``input`` are
the request messages (a ``function_call_output`` item is a tool's result, so
``tool_result`` taint), the ``message`` items' text is the response text, and each
``function_call`` item is a tool call. This is what the OpenAI Agents SDK calls the
model through, so ``auto()`` alone governs an Agents SDK app: its model calls, the
tool calls the model asks for (before the SDK runs them) and the tool results fed
back. Tools OpenAI hosts (web search, file search, code interpreter, hosted MCP) have
already run when the response arrives; they are recorded, not authorised. A request
that continues a conversation held on OpenAI's servers (``previous_response_id``,
``conversation``) carries only the new turn, so provenance for the earlier turns is
recorded as unknown rather than guessed.

CrewAI tools are governed where they run, as LangChain's are: a CrewAI agent writes
its tool calls as text ("Action: ... / Action Input: ..."), which no model-level
patch can read as a tool call, so ``CrewStructuredTool.invoke`` and
``BaseTool.run`` (and their async twins) are patched. Each call is authorised with
the arguments' provenance taken from the tool results seen earlier in the run, and
its result is checked as ``tool_result`` before the agent reads it.

An output redaction (a ``redact`` / ``mask`` / ``tokenize`` rule on the output
surface) is applied, not only recorded: the enforcer's rewritten text replaces the
assistant text in the client's own response object (``choices[0].message.content``,
Anthropic's text blocks, ``AIMessage.content``), as the gateway proxy and the
LangGraph guard substitute it. It follows the same mode rule as a block — the
enforced verdict in ``"policy"`` mode, the effective one in ``"enforce"``, never in
``"observe"`` — and a response that cannot be rewritten (a frozen object) is refused
rather than returned unredacted. A *streamed* response cannot be rewritten after its
chunks were yielded, so an applied redaction refuses the stream at its end instead;
see below.

Modes — who decides whether a call is refused in-process:

* ``"policy"`` (the default) — the policies decide. Each policy's own mode applies,
  plus the agent's kill switch, quarantine and hard budget caps: `Blocked` is raised
  exactly when the *enforced* verdict stops the call, i.e. when the gateway would have
  refused it. The shipped ``baseline`` pack is in observe mode, so adding the import
  blocks nothing; ``agentfox policy enforce baseline`` is the one step that starts
  blocking, with no second knob to find here. Tool calls follow the same rule, with
  one carve-out: capability default-deny raises only once the agent holds at least
  one capability grant (see `_govern_tool_calls`), because before that it would
  refuse every tool an existing app has.
* ``"observe"`` — never raise. A library-level safety valve: every decision is still
  recorded, and what *would* have been blocked is logged and counted.
* ``"enforce"`` — strict: raise whenever the *effective* verdict (what the policies
  would do if they were all enforced) blocks, even for a policy still in observe.
  Meant for tests and CI, where a would-have-blocked should fail the build.

What is deliberately *not* done here:

* **No enforcement on import.** The default mode defers to the policies, and the
  shipped policies observe. A library that silently starts blocking production
  traffic because someone added an import is indefensible, however correct its policy.
* **No silent failure.** If patching fails — a version we do not recognise, an SDK
  that moved its internals — we say so and leave the client alone. A governance layer
  that quietly stops governing is the failure mode this product exists to prevent, so
  it must never be one we ship. If *pre-flight* fails at call time, the configured
  ``fail_mode`` decides: ``open`` (default) lets the call through with a warning;
  ``closed`` refuses it (except in observe mode, which never raises).
* **No re-entrancy.** Patching twice, or governing our own internal model calls, would
  double-count spend and recurse. Guarded explicitly.
* **No recall of streamed output.** A streamed response is passed through chunk by
  chunk and evaluated once it is exhausted; a block raises `Blocked` at the end of
  iteration, but chunks already yielded to the caller cannot be taken back. Windowed
  enforcement that can cut a stream mid-flight is the gateway's job
  (``AGENTFOX_STREAMING_MODE=windowed``), not something a patched SDK can offer.
  The same holds for redaction: an applied output redaction on a stream raises
  `Blocked` at its end, because the text was already handed over unredacted. To
  receive redacted text, call without ``stream=True`` or stream through the
  gateway's buffered mode, which holds the response until the rewrite is done.

Frameworks (LangGraph, CrewAI, LlamaIndex, AutoGen, the OpenAI Agents SDK, ...) are
detected, not patched: they reach the model through one of the client libraries
above, and the summary says which of those routes are actually governed. The
exception is where their tools run: LangChain's and CrewAI's tools are patched there
(see above), because that is the only place their tool calls can be seen. And a few
of their own objects are watched (``delegation``), to tell an agent's own parts — a
hand-off, an agent used as a tool, a structured-output tool — from its capabilities.

Everything is import-guarded: a codebase with only `anthropic` installed never sees an
OpenAI import error, and `auto()` on a machine with neither still succeeds — it simply
reports that there was nothing to patch, which is information rather than failure.

The package: this module holds what has to share one namespace — the live state,
the governed call, the streamed-response wrappers, the patchers and the public
API (`auto`, `state`, `off`). Reading the client libraries' shapes (``shapes``),
their tool calls (``tool_calls``) and the app's environment (``environment``) are
pure helpers beside it.
"""

from __future__ import annotations

import atexit
import contextvars
import functools
import inspect
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentfox.capabilities.detection.taint import TaintTracker
from agentfox.capabilities.detection.warmup import warm_in_background
from agentfox.core.config import get_settings
from agentfox.core.db import init_db, session_scope
from agentfox.core.models import utcnow
from agentfox.errors import AgentFoxError
from agentfox.frameworks.autoguard import delegation as _delegation
from agentfox.frameworks.autoguard.environment import (
    _FRAMEWORK_ROUTES,
    _framework_routes,
    default_agent_slug,
    detect_frameworks,
)
from agentfox.frameworks.autoguard.shapes import (
    _chunk_final_response,
    _chunk_text,
    _chunk_tool_calls,
    _chunk_usage,
    _lc_messages_from,
    _messages_from,
    _responses_messages,
    _rewrite_text,
    _text_of,
    _usage_of,
)
from agentfox.frameworks.autoguard.tool_calls import (
    _arguments,
    _hosted_calls_of,
    _HostedCall,
    _provenance_of,
    _tool_calls_of,
    _tool_specs,
    _ToolCall,
)
from agentfox.platform.identity import ensure_identity
from agentfox.platform.ledger.trace import (
    ATTR_AGENT,
    ATTR_REQUEST_MODEL,
    ATTR_TOOL_IMPACT,
    ATTR_TOOL_NAME,
    ATTR_VERDICT,
    add_span,
)
from agentfox.platform.registry.service import register_agent
from agentfox.runtime.enforcement import _CAPABILITY_REFUSAL_RULE_IDS, EnforcementResult, Enforcer
from agentfox.runtime.enforcement.result import REWRITE_VERDICTS

log = logging.getLogger("agentfox.runtime.autoguard")


#: Guards against governing the model calls the platform makes for itself — an
#: LLM-as-judge call inside an eval would otherwise be traced as agent traffic and
#: charged against the agent's budget. It also stays set for the duration of a
#: governed call, so a LangChain `invoke` that calls the patched OpenAI client
#: underneath is governed once, not twice.
_IN_AGENTFOX: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agentfox_internal", default=False
)


#: Set while a LangChain chat model call is being governed, so its reply's tool calls
#: can be left to the tool-level guard when that is on.
_FROM_LANGCHAIN: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agentfox_from_langchain", default=False
)

#: Set while a CrewAI agent runs a task, for the same reason: its tools are governed
#: where they run (see `_patch_crewai_tools`), so the native tool calls in its model's
#: replies are not decided a second time.
_FROM_CREWAI: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agentfox_from_crewai", default=False
)


def _tools_governed_where_they_run(state: AutoState) -> bool:
    """Whether the tool calls in the current model reply are left to the tool-level
    guard: the reply came from a framework whose tools are patched where they run."""
    return (state.lc_tools and _FROM_LANGCHAIN.get()) or (state.crew_tools and _FROM_CREWAI.get())


#: Key in a governed request saying part of the conversation is held by the provider
#: (the Responses API's `previous_response_id` / `conversation`), not in the request.
_HISTORY_NOTE = "_agentfox_history_note"

_STATE: AutoState | None = None


#: The accepted values of `auto(mode=...)`. See the module docstring.
MODES = ("policy", "observe", "enforce")


#: label -> (owner, attribute, owner-had-its-own-attribute). Everything we swapped,
#: so `off()` restores exactly that — including entry points that were inherited
#: rather than defined on the class we patched.
_PATCHED: dict[str, tuple[Any, str, bool]] = {}


@dataclass
class PatchResult:
    library: str
    patched: bool
    detail: str = ""
    version: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "patched": self.patched,
            "detail": self.detail,
            "version": self.version,
        }


@dataclass
class AutoState:
    """What `auto()` did, so a developer can see it rather than trust it."""

    agent: str
    mode: str
    environment: str
    patches: list[PatchResult] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    calls_governed: int = 0
    #: Calls refused in-process (`Blocked` raised) under this state's mode.
    calls_blocked: int = 0
    #: Calls a policy flagged but that were let through — because the flagging policy
    #: is in observe, or because this state's mode is ``"observe"``.
    would_have_blocked: int = 0
    started: bool = False
    #: How many policies are actually in force for this agent. -1 means the count
    #: could not be taken (no database yet, or the query failed) — distinct from
    #: 0, which is the dangerous case the banner warns about.
    policies_bound: int = -1
    #: Groups turns into a conversation. Without one every exchange looks like a
    #: separate single-turn conversation, and turn-depth and repeated-failure
    #: conditions can never fire.
    session_id: str | None = None
    #: The task this agent does, in a sentence. Policy judges an irreversible tool call
    #: against it; without one, `intent.undeclared_irreversible` escalates every one.
    intent: str | None = None
    #: LangChain tools are governed where they run (`BaseTool.invoke`), so the tool
    #: calls in a LangChain model's reply are not decided a second time.
    lc_tools: bool = False
    #: CrewAI tools are governed where they run (`CrewStructuredTool.invoke`,
    #: `BaseTool.run`), the same way.
    crew_tools: bool = False
    #: What a refused LangChain tool call does: "message" hands the agent the refusal
    #: as the tool's result and the run carries on; "raise" raises `Blocked`.
    tool_refusals: str = "message"
    #: The account this process reports to (`remote.Remote`), or None when it enforces
    #: against the local database. See `agentfox.frameworks.autoguard.remote`.
    remote: Any = None

    @property
    def active(self) -> bool:
        return any(p.patched for p in self.patches)

    def framework_routes(self) -> dict[str, dict[str, str]]:
        """Which client libraries each detected framework reaches the model through,
        and whether that route is governed. Frameworks are never patched directly."""
        return _framework_routes(self.frameworks, self.patches)

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "mode": self.mode,
            "environment": self.environment,
            "active": self.active,
            "patches": [p.to_json() for p in self.patches],
            "frameworks": self.frameworks,
            "framework_routes": self.framework_routes(),
            "calls_governed": self.calls_governed,
            "calls_blocked": self.calls_blocked,
            "would_have_blocked": self.would_have_blocked,
        }

    def summary(self) -> str:
        """One paragraph a developer reads once and never again."""
        # Whether anything is actually in force. See `policies_bound` — a banner
        # that says "governing in enforce mode" over an empty policy set is the
        # one sentence this product must never print.
        by_label = {p.library: p for p in self.patches}
        patched = [p.library for p in self.patches if p.patched]
        lines = [
            f"AgentFox is governing '{self.agent}' in {self.mode} mode ({self.environment}).",
        ]
        if self.remote is not None:
            lines.append(
                f"Every check goes to your AgentFox account at {self.remote.url}; "
                "the calls show up on its dashboard."
            )
        # Found by installing 0.3.1 from PyPI into a third-party project and
        # calling auto() without running `agentfox init` first, which is exactly
        # what adding one line to an existing app looks like: the banner said
        # "enforce mode", the canonical injection went straight to OpenAI, and
        # the 401 from an invalid key proved it had left the process.
        #
        # The enforcer falls back to the shipped baseline in observe when nothing
        # is bound (see _fallback_policies), so this line says what is actually
        # running rather than warning that nothing is. Still said out loud, because
        # "a fallback is deciding for you" is a fact an operator has to know before
        # they trust a clean dashboard.
        #
        # What is true about tool calls depends on the mode (the containment pack
        # is not part of the fallback), so the sentence does too.
        if self.policies_bound == 0:
            tools = {
                "enforce": "Tool calls are checked as well, and in strict enforce mode "
                "one outside this agent's capability grants raises agentfox.Blocked.",
                "observe": "Tool calls are checked and recorded as well; none is refused.",
            }.get(
                self.mode,
                "Tool calls are checked and recorded as well, but none is refused until "
                "this agent holds a capability grant or tool-containment is bound.",
            )
            lines.append(
                "  No policy is bound, so the shipped baseline applies as a fallback, "
                f"in observe: detections are recorded, nothing is blocked on their "
                f"account. {tools} Run `agentfox init` for the full set and to choose "
                "what enforces."
            )
        if patched:
            lines.append(f"  Patched: {', '.join(patched)}")
        else:
            lines.append(
                "  Nothing patched — no supported client library was importable. "
                "Install openai or anthropic, or use the SDK directly."
            )
        for result in self.patches:
            if result.patched:
                continue
            # "anthropic.async: not installed" under "anthropic: not installed" says
            # nothing new; every other skip is its own fact and is reported.
            base = by_label.get(result.library.removesuffix(".async"))
            if (
                result.library.endswith(".async")
                and base is not None
                and not base.patched
                and base.detail == result.detail
            ):
                continue
            lines.append(f"  Skipped {result.library}: {result.detail}")
        if self.frameworks:
            lines.append(f"  Detected: {', '.join(self.frameworks)}")
            for framework, routes in self.framework_routes().items():
                if routes:
                    parts = ", ".join(f"{client}: {status}" for client, status in routes.items())
                    lines.append(f"    {framework} → {parts}")
                else:
                    clients = "/".join(_FRAMEWORK_ROUTES[framework])
                    lines.append(
                        f"    {framework} → none of {clients} is installed or patched; "
                        "its model calls are NOT governed"
                    )
        if patched:
            lines.append(
                "  Governed per call: request messages, response text, and the tool "
                "calls in the response (OpenAI tool_calls and Responses API "
                "function_call items, Anthropic tool_use) before your code can run "
                "them."
            )
            if by_label.get("openai.responses") and by_label["openai.responses"].patched:
                lines.append(
                    "  OpenAI-hosted tools (web search, file search, code interpreter) "
                    "run at OpenAI, so they are recorded, not stopped."
                )
            if self.lc_tools or self.crew_tools:
                where = " and ".join(
                    name
                    for name, on in (("LangChain", self.lc_tools), ("CrewAI", self.crew_tools))
                    if on
                )
                lines.append(
                    f"  {where} tools are checked where they run, and what they return "
                    "is checked before the model reads it."
                )
        if self.mode == "policy":
            lines.append(
                "  Policy mode: each policy's own mode decides. Observe-mode policies "
                "(baseline ships in observe) record what they would have blocked; "
                "enforce-mode policies, the kill switch and budget caps raise "
                "agentfox.Blocked — for a tool call too. A tool outside the agent's "
                "capability grants raises once it has at least one grant. "
                "`agentfox policy enforce baseline` is the one step that starts "
                "blocking content."
            )
        elif self.mode == "observe":
            lines.append(
                "  Observe mode: decisions are recorded, nothing is blocked in-process — "
                "not even a tool call, an enforce-mode policy or the kill switch."
            )
        else:
            lines.append(
                "  Enforce mode (strict): any call or tool call a policy would block or "
                "escalate raises agentfox.Blocked, even when that policy is still in "
                "observe, and a tool with no capability grant always does."
            )
        return "\n".join(lines)


def _record_turn(
    state: AutoState, messages: list[dict[str, Any]], answer: str, trace_id: str
) -> None:
    """Record one exchange for missed-escalation detection. Never fails the request."""
    try:
        user_text = next(
            (
                str(m.get("content") or "")
                for m in reversed(messages)
                if str(m.get("role")) == "user"
            ),
            "",
        )
        if not user_text:
            return
        from agentfox.capabilities.containment.escalation import record_turn
        from agentfox.core.db import session_scope
        from agentfox.core.models import Agent

        token = _IN_AGENTFOX.set(True)
        try:
            with session_scope() as session:
                from sqlalchemy import select

                agent = session.scalar(select(Agent).where(Agent.slug == state.agent))
                record_turn(
                    session,
                    session_id=state.session_id or trace_id,
                    agent_id=agent.id if agent else None,
                    trace_id=trace_id,
                    user_text=user_text,
                    agent_text=answer,
                )
        finally:
            _IN_AGENTFOX.reset(token)
    except Exception as exc:  # pragma: no cover - observability must not break the call
        log.debug("agentfox: turn capture skipped: %s", exc)


from agentfox.core.vocab import ATTACK_TEST_ENV  # noqa: E402 - re-exported


class _SkipLocalSetup(Exception):
    """`auto()` reports to an account: no local database to create or register in."""


class Blocked(AgentFoxError, RuntimeError):
    """Raised when a governed call is refused in-process.

    An `agentfox.errors.AgentFoxError`, so one ``except`` covers it and the SDK's and
    LangGraph's exceptions; still a ``RuntimeError`` for code written before that.

    When it is raised depends on the `auto()` mode (see the module docstring);
    ``.result`` is the `EnforcementResult` that refused it. When what was refused is
    a tool call the model asked for, ``.tool_call`` names it (``name``,
    ``arguments``) and the message says which rule refused it and where its
    arguments came from — the response carrying the call is withheld, so the
    caller's own code never gets the chance to run it.
    """

    def __init__(self, result: Any, message: str | None = None, tool_call: Any = None) -> None:
        super().__init__(message or result.reason or "blocked by policy")
        self.result = result
        self.tool_call = tool_call


#: Reserved kwargs the caller may pass to any patched entry point. Popped before the
#: real provider sees them (it would reject them as unrecognised).
_EVIDENCE_KWARGS = ("agentfox_principal", "agentfox_chunks", "agentfox_purpose")


def _raises(mode: str, *, enforced: bool, effective: bool) -> bool:
    """Whether a flagged call is refused in-process under `mode`.

    ``enforced`` — the enforced verdict stops the call (what the gateway would do).
    ``effective`` — the counterfactual verdict blocks (what it would do were every
    policy enforced).
    """
    if mode == "observe":
        return False
    if mode == "enforce":
        return enforced or effective
    return enforced  # "policy"


def _fail_closed_result(exc: Exception, stage: str = "pre-flight") -> EnforcementResult:
    reason = f"{stage} failed and fail_mode=closed: {exc}"
    return EnforcementResult(
        verdict="block",
        effective_verdict="block",
        mode="enforce",
        reason=reason,
        degraded=["preflight"],
        rules_fired=[
            {
                "rule_id": "autoguard.fail_closed",
                "effect": "block",
                "reason": reason,
                "controls": ["NOM-RTG-06"],
            }
        ],
    )


@dataclass
class _Call:
    """What pre-flight established, carried to post-flight — which, for a streamed
    response, runs only once the caller has exhausted the stream."""

    state: AutoState
    model: str
    messages: list[dict[str, Any]]
    trace_id: str
    evidence: dict[str, Any]
    #: Reason a policy flagged this call but it was let through (see
    #: `AutoState.would_have_blocked`); None when nothing was flagged.
    flagged: str | None = None
    started: float = 0.0
    #: Provenance of everything in the request, for the tool calls in the response.
    tracker: TaintTracker = field(default_factory=TaintTracker)
    #: Tools already called earlier in this conversation, in order.
    prior_tools: list[str] = field(default_factory=list)
    #: The request's own tool declarations, by name.
    tool_specs: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Set when part of the conversation is not in the request (the Responses API's
    #: ``previous_response_id`` / ``conversation`` keep it on OpenAI's servers): the
    #: provenance of anything from those turns is unknown, and the record says so.
    provenance_note: str | None = None


def _pop_evidence(kwargs: dict[str, Any]) -> dict[str, Any]:
    # The caller's end-user identity and retrieved context, if it supplied
    # them. Popped before anything else so they never leak to the real provider
    # call, which sees these as unrecognised kwargs otherwise. A subject that
    # doesn't resolve to a registered principal still gets recorded correctly
    # downstream (as "declared but unregistered" — see entitlement.filter_retrieval),
    # so no lookup happens here.
    return {key: kwargs.pop(key, None) for key in _EVIDENCE_KWARGS}


def _run_preflight(
    state: AutoState, kwargs: dict[str, Any], evidence: dict[str, Any]
) -> tuple[_Call, EnforcementResult, bool, bool]:
    """The pre-flight itself. Returns (call, worst result, enforced, effective)."""
    messages = _messages_from(kwargs)
    _watch_framework_parts()  # cheap once done; a framework may load after auto()
    if state.remote is not None:
        return _remote_preflight(state, kwargs, evidence, messages)
    with session_scope() as session:
        enforcer = Enforcer(session)
        # The real pre-flight path — kill-switch/quarantine, hard budget caps, the
        # answerability gate, then per-message evaluation — the same one every other
        # call surface goes through.
        outcome = enforcer.preflight(
            agent_slug=state.agent,
            messages=messages,
            model=str(kwargs.get("model") or "default"),
            environment=state.environment,
            session_id=state.session_id,
            intent=state.intent,
            trust_map=_declared_for(state)(messages) or None,
        )
        trace = outcome.trace
        result = outcome.result
        # `stopped` is the enforced outcome: an enforce-mode policy blocked or
        # escalated, or the kill switch / budget / answerability gate refused. An
        # observe-mode policy's block shows only in `effective_verdict`.
        enforced = outcome.stopped
        effective = enforced or result.effective_verdict == "block"

        # Tier A — payload splitting / multi-turn jailbreaks: the check above only
        # ever sees THIS call's own messages array. An attacker who spreads a payload
        # across several separate calls in the same conversation (each individually
        # innocuous) defeats it completely. Only runs when the caller supplied a
        # stable session_id; skipped once pre-flight has already stopped the call.
        if not enforced and state.session_id:
            new_user_text = next(
                (
                    str(m.get("content") or "")
                    for m in reversed(messages)
                    if str(m.get("role")) == "user"
                ),
                "",
            )
            if new_user_text:
                window = enforcer.check_conversation_window(
                    agent_slug=state.agent,
                    session_id=state.session_id,
                    new_user_text=new_user_text,
                    trace=trace,
                )
                window_enforced = window.blocked
                window_effective = window_enforced or window.effective_verdict == "block"
                if window_effective:
                    window.reason = (
                        f"multi-turn: {window.reason}"
                        if window.reason
                        else "multi-turn conversation window flagged an injection"
                    )
                if window_enforced or (window_effective and not effective):
                    result = window
                enforced = enforced or window_enforced
                effective = effective or window_effective

    tracker, prior_tools = _provenance_of(kwargs, _declared_for(state))
    tracker.trace_id = trace.id
    call = _Call(
        state=state,
        model=str(kwargs.get("model") or ""),
        messages=messages,
        trace_id=trace.id,
        evidence=evidence,
        tracker=tracker,
        prior_tools=prior_tools,
        tool_specs=_tool_specs(kwargs),
        provenance_note=kwargs.get(_HISTORY_NOTE),
    )
    return call, result, enforced, effective


def _declared_for(state: AutoState) -> Callable[[list[Any]], dict[str, str]]:
    """Messages quoting a tool result this conversation's tools returned, declared
    ``tool_result`` for provenance marking (see `_ToolResults`); and a hand-off's own
    tool message, declared ``user``: a hand-off carries the conversation the person
    typed to the next agent, and its acknowledgement is no tool's output."""

    def declared(messages: list[Any]) -> dict[str, str]:
        return {
            **_TOOL_RESULTS.declared(state.session_id, messages),
            **_delegation.handoff_messages(messages),
        }

    return declared


def _preflight(state: AutoState, kwargs: dict[str, Any], evidence: dict[str, Any]) -> _Call | None:
    """Pre-flight, decided. Raises `Blocked` when the call must be refused under
    ``state.mode`` (or pre-flight failed with ``fail_mode=closed``); returns None when
    pre-flight failed open, in which case the call proceeds ungoverned."""
    try:
        call, result, enforced, effective = _run_preflight(state, kwargs, evidence)
    except Exception as exc:
        try:
            fail_mode = get_settings().fail_mode
        except Exception:  # pragma: no cover - settings themselves unreadable
            fail_mode = "open"
        if fail_mode == "closed" and state.mode != "observe":
            log.error("agentfox: pre-flight failed, refusing the call (fail_mode=closed): %s", exc)
            state.calls_blocked += 1
            raise Blocked(_fail_closed_result(exc)) from exc
        log.warning("agentfox: pre-flight failed, allowing the call (fail_mode=open): %s", exc)
        return None

    # Decided after the session has committed, so the refused call's trace and
    # decisions are on the record rather than rolled back with the exception.
    if _raises(state.mode, enforced=enforced, effective=effective):
        state.calls_governed += 1
        state.calls_blocked += 1
        raise Blocked(result)
    if enforced or effective:
        call.flagged = result.reason or "flagged by policy"
    return call


def _postflight(
    call: _Call,
    text: str,
    usage: dict[str, int],
    *,
    tool_calls: list[_ToolCall] | None = None,
    may_raise: bool = True,
    response: Any = None,
    hosted: list[_HostedCall] | None = None,
) -> None:
    """Span, output evaluation, tool-call authorisation, budget charge, turn record.
    Shared by buffered, streamed, sync and async calls. Raises `Blocked` when the
    output or a tool call must be refused under the state's mode and ``may_raise``.

    ``response`` is the buffered response object, rewritten in place when an output
    redaction applies; None for a stream, whose chunks are already with the caller
    and so cannot be — an applied redaction refuses the stream instead (see
    `_apply_redaction`).

    ``hosted`` are the tools OpenAI ran itself during a Responses API call (web
    search, file search, ...): already run, so recorded rather than authorised."""
    state = call.state
    tool_calls = tool_calls or []
    hosted = hosted or []
    provider_ms = (time.perf_counter() - call.started) * 1000
    refusal: Blocked | None = None
    tool_failure: Exception | None = None
    # A structured-output tool call (pydantic-ai's `final_result`) is the answer: with
    # no text beside it, what it carries is checked as the output. Its arguments
    # cannot be rewritten in place, so a redaction that applies refuses it instead.
    if not text and tool_calls:
        payload = _output_payload(tool_calls)
        if payload:
            text, response = payload, None
    try:
        if (text or usage or tool_calls) and state.remote is not None:
            refusal, text = _remote_postflight(call, text, usage, tool_calls, response)
        elif text or usage or tool_calls or hosted:
            token = _IN_AGENTFOX.set(True)
            try:
                with session_scope() as session:
                    enforcer = Enforcer(session)
                    agent, identity, _shadow = enforcer.resolve(state.agent)
                    if text:
                        outbound, refused, rewrite = _evaluate_output(
                            call, session, enforcer, agent, identity, text, usage, provider_ms
                        )
                        if refused:
                            refusal = Blocked(outbound)
                        elif rewrite is not None:
                            refusal = _apply_redaction(outbound, rewrite, response)
                            if refusal is None:
                                text = rewrite
                    if tool_calls and not _tools_governed_where_they_run(state):
                        tool_refusal = _govern_tool_calls(
                            call, session, enforcer, identity, tool_calls
                        )
                        refusal = refusal or tool_refusal
                    if hosted:
                        _record_hosted(call, session, hosted)
                    # This call never goes through AgentFox's own provider
                    # abstraction — it's the caller's own SDK, patched in place — so
                    # nothing else on this path ever charges spend against the
                    # agent's budget. Charged even when the output is refused: the
                    # tokens were spent either way.
                    if agent is not None and usage:
                        from types import SimpleNamespace

                        from agentfox.platform.providers.remote import estimate_cost

                        cost = estimate_cost(
                            call.model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
                        )
                        enforcer._charge_budget(agent, SimpleNamespace(usage=usage, cost_usd=cost))
            finally:
                _IN_AGENTFOX.reset(token)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("agentfox: post-flight failed: %s", exc)
        if tool_calls:
            tool_failure = exc

    # A tool call nobody could check is the one case where failing open hands an
    # unchecked action to the caller's code, so it follows `fail_mode` exactly as a
    # pre-flight failure does — and, like one, never raises in observe mode.
    if tool_failure is not None and refusal is None and state.mode != "observe":
        try:
            fail_mode = get_settings().fail_mode
        except Exception:  # pragma: no cover - settings themselves unreadable
            fail_mode = "open"
        if fail_mode == "closed":
            refusal = Blocked(_fail_closed_result(tool_failure, "tool-call authorisation"))

    if refusal is not None and not may_raise:
        # The caller abandoned the stream early; there is nobody left to raise to.
        log.warning(
            "agentfox: output of an abandoned stream would have been blocked — %s",
            refusal,
        )
        call.flagged = call.flagged or str(refusal)
        refusal = None

    state.calls_governed += 1
    if refusal is not None:
        state.calls_blocked += 1
        raise refusal

    # Capture the exchange as a conversation turn. Escalation governance was
    # complete and inert for anyone using the one-liner — the detector reads recorded
    # turns, and nothing was recording them. Session grouping falls back to the trace
    # when the caller has no session concept.
    try:
        if state.remote is None:
            _record_turn(state, call.messages, text, call.trace_id)
    except Exception as exc:  # pragma: no cover - defence in depth
        # Guarded here as well as inside, so that a future change to turn capture
        # cannot become a change to whether the caller's request succeeds.
        log.debug("agentfox: turn capture failed: %s", exc)

    if call.flagged:
        state.would_have_blocked += 1
        log.info("agentfox: would have blocked (%s mode) — %s", state.mode, call.flagged)


# -- An agent's own parts: hand-offs, agents used as tools, output tools ---------------
#
# See `delegation`: a hand-off or an agent used as a tool is recorded as a delegation
# (a `subagent` span and a `delegates_to` edge), never decided as a tool needing a
# grant; a framework's structured-output tool (pydantic-ai's `final_result`) is not
# decided at all, and what it carries is checked as the model's output.

_handoff_of = _delegation.handoff_of
_lc_handoff = _delegation.lc_handoff
_crew_handoff = _delegation.crew_handoff
#: Tool name -> (agent reached, relation); see `delegation.DELEGATION_TOOLS`.
_HANDOFF_TOOLS = _delegation.DELEGATION_TOOLS


def _watch_framework_parts() -> None:
    """Learn hand-off, agent-as-tool and output-tool names from the framework modules
    already imported (`delegation.watch`); cheap once done."""
    _delegation.watch(_PATCHED)


def _output_payload(tool_calls: list[_ToolCall]) -> str:
    """What the response's structured-output tool calls carry, as text: the answer a
    framework like pydantic-ai returns through a tool rather than as text."""
    parts = [
        json.dumps(t.arguments, default=str, ensure_ascii=False)
        for t in tool_calls
        if _delegation.is_output_tool(t.name)
    ]
    return "\n".join(parts)


def _record_handoff(
    session: Any, state: AutoState, trace_id: str, tool: str, target: str, relation: str
) -> None:
    """A `subagent` span and a `delegates_to` edge for one hand-off."""
    from agentfox.platform.registry.service import record_edge

    add_span(
        session,
        trace_id,
        kind="subagent",
        name=target,
        attributes={
            ATTR_AGENT: state.agent,
            "agentfox.child_agent": target,
            "agentfox.handoff.tool": tool,
            "agentfox.handoff.relation": relation,
        },
    )
    record_edge(session, "agent", state.agent, "agent", target, "delegates_to")


def _handoff_where_it_runs(state: AutoState, tool: str, target: str, relation: str) -> str | None:
    """Record a hand-off made by a tool governed where it runs (LangGraph, CrewAI).
    Returns its trace id. Never fails the hand-off."""
    if state.remote is not None:
        return None  # the account's gateway has no hand-off endpoint; nothing to refuse
    from agentfox.platform.ledger.trace import start_trace

    token = _IN_AGENTFOX.set(True)
    try:
        with session_scope() as session:
            agent = Enforcer(session).resolve(state.agent)[0]
            trace = start_trace(
                session,
                agent_id=agent.id if agent else None,
                agent_slug=state.agent,
                session_id=state.session_id,
                environment=state.environment,
                intent=state.intent,
            )
            _record_handoff(session, state, trace.id, tool, target, relation)
            return trace.id
    except Exception as exc:  # pragma: no cover - observability must not break the run
        log.debug("agentfox: hand-off not recorded: %s", exc)
        return None
    finally:
        _IN_AGENTFOX.reset(token)


def _register_tool(session: Any, name: str, descriptor: dict[str, Any] | None) -> None:
    """Register a tool the model called; see `register_called_tool`."""
    from agentfox.platform.registry.service import register_called_tool

    register_called_tool(session, name, descriptor)


def _agent_has_grants(session: Any, identity: Any) -> bool:
    """Whether anyone has configured least privilege for this agent at all."""
    from agentfox.platform.identity.service import holds_any_grant

    return holds_any_grant(session, identity)


def _stopping_rules(result: EnforcementResult) -> list[dict[str, Any]]:
    """The fired rules that refused (or would refuse) the call, applied ones first."""
    stopping = [r for r in result.rules_fired or [] if r.get("effect") in ("block", "escalate")]
    # Applied before recorded-only, and the rule that set the verdict before the rest.
    return sorted(
        stopping,
        key=lambda r: (r.get("mode") != "enforce", r.get("effect") != result.effective_verdict),
    )


def _capability_only(result: EnforcementResult) -> bool:
    """True when the only *applied* refusal is a capability one — the absence of a
    grant, rather than a policy, the kill switch or a destructive action."""
    applied = [r for r in _stopping_rules(result) if r.get("mode", "enforce") == "enforce"]
    return bool(applied) and all(r.get("rule_id") in _CAPABILITY_REFUSAL_RULE_IDS for r in applied)


def _describe_origin(path: str | None) -> str:
    if not path:
        return ""
    if path.startswith("tool:"):
        name, _, index = path[len("tool:") :].partition("#")
        return f" (the result of {name}, messages[{index}])" if index else f" ({name})"
    if path.startswith("$."):
        return f" ({path[2:].removesuffix('.content')})"
    return f" ({path})"


def _describe_tool_refusal(
    tool_call: _ToolCall,
    result: EnforcementResult,
    marks: list[Any],
    *,
    applied: bool,
    exempt: frozenset[str] = frozenset(),
) -> str:
    """One sentence an engineer can act on: which tool, which rule, and where the
    arguments that mattered came from.

    ``exempt`` are the rules this process let through (the no-grants carve-out in
    ``"policy"`` mode). They did not refuse anything, so they never lead: the
    message names the rule that did, and mentions the exempt ones last.
    """
    rules = sorted(_stopping_rules(result), key=lambda r: r.get("rule_id") in exempt)
    rule = rules[0] if rules else {}
    rule_id = rule.get("rule_id") or "policy"
    reason = (rule.get("reason") or result.reason or "").strip().rstrip(".")
    if result.effective_verdict == "escalate" or result.verdict == "escalate":
        outcome = "needs human approval"
        if result.approval_id:
            outcome += f" (approval {result.approval_id})"
    else:
        outcome = "was refused" if applied else "would have been refused"
    message = f"tool call {tool_call.name} {outcome} by {rule_id}"
    if reason:
        message += f": {reason}"
    others = [
        r.get("rule_id") for r in rules[1:] if r.get("rule_id") and r.get("rule_id") not in exempt
    ]
    if others:
        message += f" (also: {', '.join(dict.fromkeys(others))})"
    waived = [r.get("rule_id") for r in rules[1:] if r.get("rule_id") in exempt]
    if waived:
        message += (
            f"; {', '.join(dict.fromkeys(waived))} not applied: this agent has no "
            "capability grant yet"
        )
    untrusted = [m for m in marks if m.trust == "untrusted"]
    if untrusted:
        parts = [
            f"{m.path} from {m.source.replace('_', ' ')}{_describe_origin(m.propagated_from)}"
            for m in untrusted
        ]
        message += ". Argument provenance: " + "; ".join(parts)
    elif marks or tool_call.arguments:
        message += ". No argument came from untrusted content"
    return message + "."


def _govern_tool_calls(
    call: _Call,
    session: Any,
    enforcer: Enforcer,
    identity: Any,
    tool_calls: list[_ToolCall],
) -> Blocked | None:
    """Authorise every tool call in the response. Returns the refusal to raise under
    the state's mode, if any; every call is checked and recorded either way.

    Which verdicts raise follows the call's own rules (`_raises`), with escalation
    counted as a stop: an escalated tool call handed back to the caller is a tool
    call that runs without the approval it needed. One exception in ``"policy"``
    mode: an agent nobody has granted any capability to has not had least privilege
    configured, and capability default-deny would refuse every tool it has — so for
    that agent a refusal that is *only* a missing grant is recorded as
    would-have-blocked rather than raised. The first grant (`agentfox permit
    grant`) is what turns it on, the same way `agentfox policy enforce` turns on a
    policy. Strict ``"enforce"`` mode raises on it regardless.
    """
    from agentfox.core.models import Trace

    state = call.state
    trace = session.get(Trace, call.trace_id)
    tracker = call.tracker
    prior = list(call.prior_tools)
    has_grants: bool | None = None
    refusal: Blocked | None = None

    # What this process will do with a refusal, decided before the call so the
    # containment finding it raises says whether the call was actually stopped.
    if state.mode == "policy":
        has_grants = _agent_has_grants(session, identity)
    in_process = {"observe": "none", "enforce": "all"}.get(state.mode, "enforced")
    exempt = (
        frozenset(_CAPABILITY_REFUSAL_RULE_IDS)
        if state.mode == "policy" and not has_grants
        else frozenset()
    )

    for tool_call in tool_calls:
        handoff = _handoff_of(tool_call.name, call.tool_specs.get(tool_call.name))
        if handoff is not None:
            _record_handoff(session, state, call.trace_id, tool_call.name, *handoff)
            continue
        if _delegation.is_output_tool(tool_call.name):
            continue  # the answer, not a capability: checked as output (`_postflight`)
        _register_tool(session, tool_call.name, call.tool_specs.get(tool_call.name))
        seen = len(tracker.marks)
        result = enforcer.guard_tool_call(
            in_process=in_process,
            exempt_rules=exempt,
            agent_slug=state.agent,
            intent=state.intent,
            tool_key=tool_call.name,
            arguments=tool_call.arguments,
            trace=trace,
            tracker=tracker,
            prior_tools=list(prior),
        )
        marks = tracker.marks[seen:]  # this call's arguments, as taint_arguments saw them
        prior.append(tool_call.name)

        enforced = result.blocked or result.escalated
        effective = enforced or result.effective_verdict in ("block", "escalate")
        note = ""
        if enforced and state.mode == "policy" and _capability_only(result):
            if has_grants is None:
                has_grants = _agent_has_grants(session, identity)
            enforced = has_grants
            if not has_grants:
                note = "no capability grant exists for this agent; default-deny not applied"
        raised = _raises(state.mode, enforced=enforced, effective=effective)
        if raised:
            if refusal is None:
                refusal = Blocked(
                    result,
                    "agentfox: "
                    + _describe_tool_refusal(tool_call, result, marks, applied=True, exempt=exempt),
                    tool_call=tool_call,
                )
        elif effective:
            call.flagged = call.flagged or _describe_tool_refusal(
                tool_call, result, marks, applied=False, exempt=exempt
            )
            if not note and (result.blocked or result.escalated):
                note = f"auto() is in {state.mode} mode; recorded, not applied in-process"

        # One `tool` span per call, alongside the decision. The decision records what
        # the enforcer decided; this records what actually happened in this process,
        # which differs exactly when auto() let a refused call through (observe mode,
        # or the no-grants carve-out above) — a decision reading `block` on a call
        # that ran would otherwise be the record's only word on it.
        add_span(
            session,
            call.trace_id,
            kind="tool",
            name=tool_call.name,
            attributes={
                ATTR_AGENT: state.agent,
                ATTR_TOOL_NAME: tool_call.name,
                ATTR_TOOL_IMPACT: (result.taint or {}).get("tool_impact"),
                ATTR_VERDICT: result.verdict,
                "agentfox.decision_id": result.decision_id,
                "agentfox.runtime.autoguard.raised": raised,
                "agentfox.runtime.autoguard.note": note,
                **({"agentfox.provenance": call.provenance_note} if call.provenance_note else {}),
            },
        )
    return refusal


def _record_hosted(call: _Call, session: Any, hosted: list[_HostedCall]) -> None:
    """One `tool` span per hosted tool OpenAI ran during this call.

    They ran before the response came back, so there is nothing to authorise: the
    span is the record that the agent searched the web or read a file store, with
    what it searched for. The tool is registered so it appears in the agent's
    inventory like any other.
    """
    state = call.state
    for item in hosted:
        _register_tool(session, item.name, {"description": f"OpenAI hosted tool ({item.name})"})
        add_span(
            session,
            call.trace_id,
            kind="tool",
            name=item.name,
            attributes={
                ATTR_AGENT: state.agent,
                ATTR_TOOL_NAME: item.name,
                "agentfox.tool.hosted": True,
                "agentfox.tool.status": item.status,
                "agentfox.tool.detail": json.dumps(item.detail, default=str)[:2000],
                "agentfox.runtime.autoguard.raised": False,
                "agentfox.runtime.autoguard.note": (
                    "run by OpenAI before the response arrived; recorded, not authorised"
                ),
            },
        )


def _evaluate_output(
    call: _Call,
    session: Any,
    enforcer: Enforcer,
    agent: Any,
    identity: Any,
    text: str,
    usage: dict[str, int],
    provider_ms: float,
) -> tuple[EnforcementResult, bool, str | None]:
    """Write the llm span and evaluate the output surface.

    Returns ``(result, refused, rewrite)``: ``refused`` when the output must be refused
    under the state's mode, else ``rewrite`` is the redacted text the caller must get
    instead of the original (None when nothing is rewritten)."""
    from agentfox.core.models import Trace

    state = call.state
    # The only place on this path that writes a kind="llm" span with the raw
    # response text — the shape sample_production() (online eval) scores.
    # Mirrors enforcement/completion.py's _finish_completion(), the gateway path's equivalent.
    add_span(
        session,
        call.trace_id,
        kind="llm",
        name=f"{state.agent}.invoke",
        attributes={
            ATTR_AGENT: state.agent,
            ATTR_REQUEST_MODEL: call.model,
            "gen_ai.usage.input_tokens": usage.get("input_tokens", 0),
            "gen_ai.usage.output_tokens": usage.get("output_tokens", 0),
            "agentfox.output": text,
            **({"agentfox.provenance": call.provenance_note} if call.provenance_note else {}),
        },
        duration_ms=provider_ms,
    )

    principal_ref = call.evidence.get("agentfox_principal")
    chunks = call.evidence.get("agentfox_chunks") or []
    # Either one is evidence. Chunks without a principal still carry the sources the
    # answer was built from, which is what source authority and numeric
    # integrity check; gating them on a principal skipped both.
    if principal_ref is not None or chunks:
        enforcer.evidence = {
            "principal": _resolve_principal(session, principal_ref),
            "chunks": chunks,
            "purpose": call.evidence.get("agentfox_purpose"),
        }

    outbound = enforcer.evaluate(
        agent=agent,
        identity=identity,
        content=text,
        surface="output",
        trace=session.get(Trace, call.trace_id),
    )
    # The gateway withholds an output whose enforced verdict is block.
    enforced = outbound.blocked
    effective = enforced or outbound.effective_verdict == "block"
    if _raises(state.mode, enforced=enforced, effective=effective):
        return outbound, True, None
    if enforced or effective:
        call.flagged = call.flagged or outbound.reason or "output flagged by policy"
    rewrite = _applied_rewrite(state.mode, outbound)
    if rewrite is None and outbound.content is not None:
        log.info("agentfox: output would have been redacted (%s mode)", state.mode)
    return outbound, False, rewrite


def _applied_rewrite(mode: str, outbound: EnforcementResult) -> str | None:
    """The redacted text to hand the caller, under `mode`, or None.

    The enforcer computes the rewrite (``outbound.content``) whenever the *effective*
    verdict is a redaction — including for a policy still in observe — so which one
    applies is decided here, by the same rule `_raises` applies to a block: the
    enforced verdict in ``"policy"`` mode (what the gateway's guard endpoint returns
    as ``content``), the effective one in strict ``"enforce"`` mode, never in
    ``"observe"``.
    """
    if mode == "observe" or outbound.content is None:
        return None
    if outbound.verdict in REWRITE_VERDICTS:
        return outbound.content
    if mode == "enforce" and outbound.effective_verdict in REWRITE_VERDICTS:
        return outbound.content
    return None


def _apply_redaction(outbound: EnforcementResult, rewrite: str, response: Any) -> Blocked | None:
    """Write an applied redaction into the caller's response; a refusal if it can't be.

    Either way the caller never receives the text the policy said to hide. A stream
    (``response`` None) has already handed its chunks over, and no SDK stream lets
    them be rewritten after the fact, so the redaction becomes a refusal at the end of
    the stream, as a block would. The gateway's buffered streaming is the way to get
    redacted streamed text.
    """
    reason = outbound.reason or "output redaction required by policy"
    if response is None:
        return Blocked(
            outbound,
            f"{reason}: this output must be redacted, but it was streamed and the chunks "
            "already yielded cannot be rewritten, so the stream is refused. Call without "
            "stream=True to receive the redacted text, or stream through the gateway "
            "(AGENTFOX_STREAMING_MODE=buffered).",
        )
    if _rewrite_text(response, rewrite):
        return None
    return Blocked(
        outbound,
        f"{reason}: the redaction could not be applied to this "
        f"{type(response).__name__} response, so it is refused rather than returned "
        "unredacted.",
    )


def _resolve_principal(session: Any, principal_ref: Any) -> Any:
    """The end user a call was made for, registered or not.

    An unregistered subject still resolves, so the entitlement check does not run as
    though no principal had been named and record nothing. It is still a person: it is
    evaluated as itself, with no groups or clearances (only what is granted to the
    subject directly), and what it could not see is recorded against that subject. Never
    added to the session.
    """
    if principal_ref is None:
        return None
    from sqlalchemy import select

    from agentfox.core.models import EndUserPrincipal

    subject = principal_ref.get("subject") if isinstance(principal_ref, dict) else principal_ref
    subject = str(subject or "").strip()
    if not subject:
        return None
    registered = session.scalar(select(EndUserPrincipal).where(EndUserPrincipal.subject == subject))
    if registered is not None:
        return registered
    return EndUserPrincipal(subject=subject, groups=[], clearances=[], purposes=[])


def _is_stream(kwargs: dict[str, Any], response: Any) -> bool:
    return bool(kwargs.get("stream")) and getattr(response, "choices", None) is None


def _govern(state: AutoState, kwargs: dict[str, Any], call: Callable[[], Any]) -> Any:
    """Pre-flight, call, post-flight — for a synchronous entry point."""
    evidence = _pop_evidence(kwargs)
    if _IN_AGENTFOX.get():
        return call()

    token = _IN_AGENTFOX.set(True)
    try:
        governed = _preflight(state, kwargs, evidence)
        started = time.perf_counter()
        response = call()
    finally:
        _IN_AGENTFOX.reset(token)
    if governed is None:  # pre-flight failed open
        return response
    governed.started = started

    return _settle(governed, kwargs, response, is_async=False)


async def _agovern(state: AutoState, kwargs: dict[str, Any], call: Callable[[], Any]) -> Any:
    """`_govern` for an async entry point: the same pre- and post-flight (whose
    database work stays synchronous), with the provider call awaited."""
    evidence = _pop_evidence(kwargs)
    if _IN_AGENTFOX.get():
        return await call()

    token = _IN_AGENTFOX.set(True)
    try:
        governed = _preflight(state, kwargs, evidence)
        started = time.perf_counter()
        response = await call()
    finally:
        _IN_AGENTFOX.reset(token)
    if governed is None:  # pre-flight failed open
        return response
    governed.started = started

    return _settle(governed, kwargs, response, is_async=True)


def _is_raw(response: Any) -> bool:
    """An OpenAI SDK raw response (`with_raw_response` / `with_streaming_response`):
    the HTTP response, whose `.parse()` yields what a plain call returns."""
    return hasattr(response, "http_response") and callable(getattr(response, "parse", None))


def _settle(governed: _Call, kwargs: dict[str, Any], response: Any, *, is_async: bool) -> Any:
    """What the caller gets back: a stream wrapped so post-flight runs when it ends,
    a raw response whose `.parse()` is governed, or the buffered response, checked."""
    if _is_raw(response):
        return _govern_parse(governed, kwargs, response)
    if _is_stream(kwargs, response):
        if is_async and hasattr(response, "__aiter__"):
            return _AsyncGovernedStream(response, governed)
        if hasattr(response, "__iter__"):
            return _GovernedStream(response, governed)
    _postflight(
        governed,
        _text_of(response),
        _usage_of(response),
        tool_calls=_tool_calls_of(response),
        response=response,
        hosted=_hosted_calls_of(response),
    )
    return response


def _govern_parse(governed: _Call, kwargs: dict[str, Any], raw: Any) -> Any:
    """Govern what a raw response parses to, when the caller parses it.

    The OpenAI SDK's ``with_streaming_response.create`` — the path the Agents SDK
    streams through — and ``with_raw_response.create`` return the HTTP response, not
    the model's: its ``.parse()`` produces the stream or the response object. That
    is where post-flight has to sit. The first parse is governed (a buffered
    response checked, a stream wrapped) and the same object is handed back on every
    later call, as the SDK itself caches it. A raw response nobody parses was
    pre-flighted only: the caller read bytes AgentFox cannot interpret.
    """
    original = raw.parse
    done: dict[str, Any] = {}

    def settle(parsed: Any, is_async: bool) -> Any:
        if "parsed" not in done:
            done["parsed"] = _settle(governed, kwargs, parsed, is_async=is_async)
        return done["parsed"]

    if inspect.iscoroutinefunction(original):

        async def aparse(*args: Any, **kw: Any) -> Any:
            parsed = await original(*args, **kw)
            if args or kw:  # parse(to=...): the caller's own type, not the model's reply
                return parsed
            return settle(parsed, True)

        governed_parse: Any = aparse
    else:

        def parse(*args: Any, **kw: Any) -> Any:
            parsed = original(*args, **kw)
            if args or kw:  # parse(to=...): the caller's own type, not the model's reply
                return parsed
            # The async client's legacy raw response parses synchronously to an
            # async stream; `_settle` wraps whichever iteration the result has.
            return settle(parsed, True)

        governed_parse = parse
    try:
        raw.parse = governed_parse
    except Exception as exc:  # pragma: no cover - a frozen response object
        log.warning("agentfox: could not govern this raw response's parse(): %s", exc)
    return raw


class _StreamBase:
    """Shared by the sync and async stream wrappers: chunks pass through unchanged,
    their text and usage are accumulated, and post-flight runs once — when the stream
    is exhausted, or when the caller leaves its context manager / closes it early.

    Anything else (``.response``, ``.close()``, SDK helpers) is proxied to the
    original stream object. `isinstance` checks against the SDK's own stream class do
    not hold for the wrapper.
    """

    def __init__(self, stream: Any, call: _Call) -> None:
        self._nm_stream = stream
        self._nm_call = call
        self._nm_iter: Any = None
        self._nm_parts: list[str] = []
        self._nm_usage: dict[str, int] = {}
        #: Tool calls arrive in fragments: index -> {"name", "id", "args": [str]}.
        self._nm_tools: dict[int, dict[str, Any]] = {}
        #: The whole response a Responses API stream's final event carries.
        self._nm_final: Any = None
        self._nm_done = False

    def __getattr__(self, name: str) -> Any:
        stream = self.__dict__.get("_nm_stream")
        if stream is None:
            raise AttributeError(name)
        return getattr(stream, name)

    def _nm_observe(self, chunk: Any) -> None:
        try:
            text = _chunk_text(chunk)
            if text:
                self._nm_parts.append(text)
            for key, value in _chunk_usage(chunk).items():
                if value:
                    self._nm_usage[key] = max(self._nm_usage.get(key, 0), value)
            _chunk_tool_calls(chunk, self._nm_tools)
            final = _chunk_final_response(chunk)
            if final is not None:
                self._nm_final = final
        except Exception as exc:  # pragma: no cover - never break the caller's stream
            log.debug("agentfox: stream chunk not read: %s", exc)

    def _nm_finish(self, *, may_raise: bool = True) -> None:
        if self._nm_done:
            return
        self._nm_done = True
        text = "".join(self._nm_parts)
        tool_calls = [
            _ToolCall(part["name"], _arguments("".join(part["args"])), part.get("id"))
            for _index, part in sorted(self._nm_tools.items())
            if part.get("name")
        ]
        hosted: list[_HostedCall] = []
        final = self._nm_final
        if final is not None:
            # A Responses API stream ended with the whole response: read it as a
            # buffered call is read, deltas only where it is silent.
            text = _text_of(final) or text
            tool_calls = _tool_calls_of(final) or tool_calls
            hosted = _hosted_calls_of(final)
        _postflight(
            self._nm_call,
            text,
            dict(self._nm_usage),
            tool_calls=tool_calls,
            may_raise=may_raise,
            hosted=hosted,
        )


class _GovernedStream(_StreamBase):
    def __iter__(self) -> _GovernedStream:
        return self

    def __next__(self) -> Any:
        if self._nm_iter is None:
            self._nm_iter = iter(self._nm_stream)
        try:
            chunk = next(self._nm_iter)
        except StopIteration:
            self._nm_finish()
            raise
        self._nm_observe(chunk)
        return chunk

    def __enter__(self) -> _GovernedStream:
        enter = getattr(self._nm_stream, "__enter__", None)
        if enter is not None:
            enter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        exit_ = getattr(self._nm_stream, "__exit__", None)
        suppressed = exit_(exc_type, exc, tb) if exit_ is not None else None
        self._nm_finish(may_raise=exc_type is None)
        return suppressed

    def close(self) -> None:
        close = getattr(self._nm_stream, "close", None)
        if close is not None:
            close()
        self._nm_finish(may_raise=False)


class _AsyncGovernedStream(_StreamBase):
    def __aiter__(self) -> _AsyncGovernedStream:
        return self

    async def __anext__(self) -> Any:
        if self._nm_iter is None:
            self._nm_iter = self._nm_stream.__aiter__()
        try:
            chunk = await self._nm_iter.__anext__()
        except StopAsyncIteration:
            self._nm_finish()
            raise
        self._nm_observe(chunk)
        return chunk

    async def __aenter__(self) -> _AsyncGovernedStream:
        enter = getattr(self._nm_stream, "__aenter__", None)
        if enter is not None:
            await enter()
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        exit_ = getattr(self._nm_stream, "__aexit__", None)
        suppressed = await exit_(exc_type, exc, tb) if exit_ is not None else None
        self._nm_finish(may_raise=exc_type is None)
        return suppressed


def _live(state: AutoState) -> AutoState:
    """The state a patched entry point governs under. A second `auto()` finds the
    patches already in place; reading the current state (rather than the one captured
    when the patch went in) is what lets it change the mode or the agent."""
    return _STATE if _STATE is not None else state


def _sdk_method(state: AutoState, *, is_async: bool) -> Callable[[Any], Any]:
    """Wrapper factory for `Resource.create(self, **kwargs)` and module-level
    functions alike: whatever is called, its kwargs are the request."""

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(*args: Any, **kwargs: Any) -> Any:
                return await _agovern(_live(state), kwargs, lambda: original(*args, **kwargs))

            return agoverned

        @functools.wraps(original)
        def governed(*args: Any, **kwargs: Any) -> Any:
            return _govern(_live(state), kwargs, lambda: original(*args, **kwargs))

        return governed

    return build


def _responses_request(kwargs: dict[str, Any]) -> dict[str, Any]:
    """The governed view of an OpenAI Responses API request: its ``instructions`` and
    ``input`` as a chat message list (see `_responses_messages`), its model, tools
    and stream flag. The caller's own kwargs are what the provider receives,
    reserved evidence kwargs popped first.

    The SDK's own sentinels (``omit`` / ``NOT_GIVEN``) are truthy objects, so every
    value is type-checked rather than tested for truth.
    """
    model = kwargs.get("model")
    tools = kwargs.get("tools")
    governed: dict[str, Any] = {
        "messages": _responses_messages(kwargs),
        "model": model if isinstance(model, str) else "",
        "tools": list(tools) if isinstance(tools, (list, tuple)) else [],
        "stream": kwargs.get("stream") is True,
    }
    for key in _EVIDENCE_KWARGS:  # never forwarded to OpenAI
        if key in kwargs:
            governed[key] = kwargs.pop(key)
    previous = kwargs.get("previous_response_id")
    conversation = kwargs.get("conversation")
    held = (
        f"previous_response_id={previous}"
        if isinstance(previous, str) and previous
        else f"conversation={_get_id(conversation)}"
        if isinstance(conversation, (str, dict)) or hasattr(conversation, "id")
        else None
    )
    if held:
        # The earlier turns are on OpenAI's servers, not in this request: nothing
        # here can say where a value from them came from. Recorded as unknown rather
        # than guessed clean.
        governed[_HISTORY_NOTE] = (
            f"unknown for earlier turns: the conversation is held by OpenAI ({held}), "
            "so only this request's own input was read for provenance"
        )
    return governed


def _get_id(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return str(value.get("id") or "")
    return str(getattr(value, "id", "") or "")


def _responses_method(state: AutoState, *, is_async: bool) -> Callable[[Any], Any]:
    """Wrapper factory for `Responses.create` / `.parse` and their async twins."""

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(*args: Any, **kwargs: Any) -> Any:
                govern_kwargs = _responses_request(kwargs)
                return await _agovern(
                    _live(state), govern_kwargs, lambda: original(*args, **kwargs)
                )

            return agoverned

        @functools.wraps(original)
        def governed(*args: Any, **kwargs: Any) -> Any:
            govern_kwargs = _responses_request(kwargs)
            return _govern(_live(state), govern_kwargs, lambda: original(*args, **kwargs))

        return governed

    return build


def _lc_method(state: AutoState, *, is_async: bool) -> Callable[[Any], Any]:
    """Wrapper factory for `BaseChatModel.invoke` / `.ainvoke`."""

    def request(self: Any, chat_input: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        model_name = getattr(self, "model_name", None) or getattr(self, "model", None) or ""
        govern_kwargs: dict[str, Any] = {
            "messages": _lc_messages_from(chat_input),
            "model": str(model_name),
        }
        for key in _EVIDENCE_KWARGS:  # never forwarded to the chat model
            if key in kwargs:
                govern_kwargs[key] = kwargs.pop(key)
        if kwargs.get("tools"):  # `bind_tools` passes them here; read, not popped
            govern_kwargs["tools"] = kwargs["tools"]
        return govern_kwargs

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(
                self: Any, chat_input: Any, config: Any = None, *, stop: Any = None, **kwargs: Any
            ) -> Any:
                govern_kwargs = request(self, chat_input, kwargs)

                def call() -> Any:
                    if config is not None:
                        return original(self, chat_input, config, stop=stop, **kwargs)
                    return original(self, chat_input, stop=stop, **kwargs)

                token = _FROM_LANGCHAIN.set(True)
                try:
                    return await _agovern(_live(state), govern_kwargs, call)
                finally:
                    _FROM_LANGCHAIN.reset(token)

            return agoverned

        @functools.wraps(original)
        def governed(
            self: Any, chat_input: Any, config: Any = None, *, stop: Any = None, **kwargs: Any
        ) -> Any:
            govern_kwargs = request(self, chat_input, kwargs)

            def call() -> Any:
                if config is not None:
                    return original(self, chat_input, config, stop=stop, **kwargs)
                return original(self, chat_input, stop=stop, **kwargs)

            token = _FROM_LANGCHAIN.set(True)
            try:
                return _govern(_live(state), govern_kwargs, call)
            finally:
                _FROM_LANGCHAIN.reset(token)

        return governed

    return build


def _patch_attr(
    label: str,
    library: str,
    owner: Any,
    attr: str,
    build: Callable[[Any], Any],
    version: str | None,
    detail: str,
) -> PatchResult:
    """Swap `owner.attr` for its governed wrapper, idempotently, and remember it."""
    current = getattr(owner, attr, None) if owner is not None else None
    if current is None:  # SDK shape drift
        return PatchResult(
            label,
            False,
            f"this {library} version has no {detail}; leaving it alone rather than guessing",
            version,
        )
    if getattr(current, "__agentfox__", False):
        return PatchResult(label, True, "already patched", version)
    had_own = attr in getattr(owner, "__dict__", {})
    governed = build(current)
    governed.__agentfox__ = True
    governed.__agentfox_original__ = current
    setattr(owner, attr, governed)
    _PATCHED[label] = (owner, attr, had_own)
    return PatchResult(label, True, detail, version)


def _not_importable(library: str, exc: Exception) -> list[PatchResult]:
    detail = "not installed" if isinstance(exc, ImportError) else f"import failed: {exc}"
    return [PatchResult(library, False, detail), PatchResult(f"{library}.async", False, detail)]


def _patch_openai(state: AutoState) -> list[PatchResult]:
    try:
        import openai
        from openai.resources.chat import completions
    except Exception as exc:
        return _not_importable("openai", exc)

    version = getattr(openai, "__version__", None)
    return [
        _patch_attr(
            "openai",
            "openai",
            getattr(completions, "Completions", None),
            "create",
            _sdk_method(state, is_async=False),
            version,
            "chat.completions.create",
        ),
        _patch_attr(
            "openai.async",
            "openai",
            getattr(completions, "AsyncCompletions", None),
            "create",
            _sdk_method(state, is_async=True),
            version,
            "AsyncCompletions.create",
        ),
        *_patch_openai_responses(state, version),
    ]


#: label -> (class, method, async, what it is). `create` covers `responses.stream()`
#: and `with_streaming_response` / `with_raw_response` (all call it); `parse` posts
#: on its own and is patched separately.
_RESPONSES_ENTRY_POINTS = (
    ("openai.responses", "Responses", "create", False, "responses.create"),
    ("openai.responses.async", "AsyncResponses", "create", True, "AsyncResponses.create"),
    ("openai.responses.parse", "Responses", "parse", False, "responses.parse"),
    ("openai.responses.parse.async", "AsyncResponses", "parse", True, "AsyncResponses.parse"),
)


def _patch_openai_responses(state: AutoState, version: str | None) -> list[PatchResult]:
    """The Responses API: what the OpenAI Agents SDK calls the model through."""
    try:
        from openai.resources.responses import responses as module
    except Exception:
        return [
            PatchResult(
                label,
                False,
                "this openai version has no Responses API (openai>=1.66 has it)",
                version,
            )
            for label, *_rest in _RESPONSES_ENTRY_POINTS[:2]
        ]
    return [
        _patch_attr(
            label,
            "openai",
            getattr(module, owner, None),
            attr,
            _responses_method(state, is_async=is_async),
            version,
            detail,
        )
        for label, owner, attr, is_async, detail in _RESPONSES_ENTRY_POINTS
    ]


def _patch_anthropic(state: AutoState) -> list[PatchResult]:
    try:
        import anthropic
        from anthropic.resources import messages as messages_module
    except Exception as exc:
        return _not_importable("anthropic", exc)

    version = getattr(anthropic, "__version__", None)
    return [
        _patch_attr(
            "anthropic",
            "anthropic",
            getattr(messages_module, "Messages", None),
            "create",
            _sdk_method(state, is_async=False),
            version,
            "messages.create",
        ),
        _patch_attr(
            "anthropic.async",
            "anthropic",
            getattr(messages_module, "AsyncMessages", None),
            "create",
            _sdk_method(state, is_async=True),
            version,
            "AsyncMessages.create",
        ),
    ]


def _patch_litellm(state: AutoState) -> list[PatchResult]:
    try:
        import litellm
    except Exception as exc:
        return _not_importable("litellm", exc)

    version = getattr(litellm, "__version__", None)
    return [
        _patch_attr(
            "litellm",
            "litellm",
            litellm,
            "completion",
            _sdk_method(state, is_async=False),
            version,
            "litellm.completion",
        ),
        _patch_attr(
            "litellm.async",
            "litellm",
            litellm,
            "acompletion",
            _sdk_method(state, is_async=True),
            version,
            "litellm.acompletion",
        ),
    ]


def _patch_langchain(state: AutoState) -> list[PatchResult]:
    try:
        import langchain_core
        from langchain_core.language_models.chat_models import BaseChatModel
    except Exception as exc:
        return _not_importable("langchain", exc)

    version = getattr(langchain_core, "__version__", None)
    return [
        _patch_attr(
            "langchain",
            "langchain-core",
            BaseChatModel,
            "invoke",
            _lc_method(state, is_async=False),
            version,
            "BaseChatModel.invoke",
        ),
        _patch_attr(
            "langchain.async",
            "langchain-core",
            BaseChatModel,
            "ainvoke",
            _lc_method(state, is_async=True),
            version,
            "BaseChatModel.ainvoke",
        ),
    ]


# -- LangChain tools, governed where they run ---------------------------------------

_HELD_MESSAGE = (
    "This tool call is held for human approval (approval_id: {approval_id}). Tell the "
    "user it is waiting for a person to approve it. When the user says it has been "
    "approved, call this tool again with exactly the same arguments: it runs once if it "
    "was approved, and is held again if it was not."
)


class _LcHeld:
    """Approvals this process opened for LangChain tool calls, by tool and arguments,
    so the same call made again after a person approved it runs once."""

    def __init__(self) -> None:
        self._held: dict[tuple[str, str], str] = {}

    @staticmethod
    def _key(tool: str, arguments: dict[str, Any]) -> tuple[str, str]:
        return tool, json.dumps(arguments, sort_keys=True, default=str)

    def approved(self, session: Any, tool: str, arguments: dict[str, Any]) -> str | None:
        from agentfox.core.models import ApprovalRequest

        key = self._key(tool, arguments)
        approval_id = self._held.get(key)
        if approval_id is None:
            return None
        approval = session.get(ApprovalRequest, approval_id)
        status = approval.status if approval is not None else "gone"
        if status == "approved":
            self._held.pop(key, None)
            return approval_id
        if status != "pending":
            self._held.pop(key, None)
        return None

    def hold(self, tool: str, arguments: dict[str, Any], approval_id: str) -> None:
        self._held[self._key(tool, arguments)] = approval_id


_LC_HELD = _LcHeld()


def _lc_tool_input(tool: Any, tool_input: Any) -> tuple[str, dict[str, Any], str | None]:
    """The tool's name, its arguments, and the model's tool-call id when given one."""
    name = str(getattr(tool, "name", "") or type(tool).__name__)
    call_id = None
    args = tool_input
    if isinstance(tool_input, dict) and tool_input.get("type") == "tool_call":
        call_id = tool_input.get("id")
        args = tool_input.get("args", {})
    if isinstance(args, str):
        args = {"input": args}
    elif not isinstance(args, dict):
        args = {"_value": args}
    return name, dict(args), call_id


def _lc_tool_reply(text: str, name: str, call_id: str | None, *, error: bool) -> Any:
    """What the agent receives in the tool's place: a ToolMessage when the model asked
    for the call by id (so the conversation stays well formed), else the text."""
    if call_id is None:
        return text
    from langchain_core.messages import ToolMessage

    return ToolMessage(
        content=text, tool_call_id=call_id, name=name, status="error" if error else "success"
    )


class _ToolResults:
    """What the tools governed where they run (LangChain, CrewAI) returned, recently,
    per conversation: the provenance a tool-level guard has no request to read.

    A model-level guard rebuilds provenance from the request, which carries the whole
    conversation. A tool-level guard sees only the call; and a CrewAI agent hands a
    tool's result back to its model as text inside its own messages ("Observation:
    ..."), where marking by role reads it as something the user typed. So each
    result is kept here: a later tool call's arguments are matched against them
    (`tracker`), and a model request that quotes one has that message declared
    ``tool_result`` (`declared`). Bounded: the last `_PER_SESSION` results of the
    last `_SESSIONS` conversations. A result from another conversation in the same
    process (one with no ``session_id``) can only make a call stricter.
    """

    _PER_SESSION = 64
    _SESSIONS = 256
    #: A result shorter than this is too common a string to say where text came from.
    _MIN = 12
    #: Matching reads the start of a result: a framework may truncate a long one.
    _NEEDLE = 200

    def __init__(self) -> None:
        import collections
        import threading

        self._by_session: collections.OrderedDict[str, collections.deque[tuple[str, str]]] = (
            collections.OrderedDict()
        )
        self._deque = collections.deque
        self._lock = threading.Lock()

    def add(self, session_id: str | None, tool: str, text: str) -> None:
        if len(text.strip()) < self._MIN:
            return
        key = session_id or ""
        with self._lock:
            results = self._by_session.pop(key, None) or self._deque(maxlen=self._PER_SESSION)
            results.append((tool, text))
            self._by_session[key] = results
            while len(self._by_session) > self._SESSIONS:
                self._by_session.popitem(last=False)

    def _results(self, session_id: str | None) -> list[tuple[str, str]]:
        with self._lock:
            return list(self._by_session.get(session_id or "", ()))

    def tracker(self, session_id: str | None) -> tuple[TaintTracker, list[str]]:
        """A tracker holding this conversation's tool results, and their tools in order."""
        tracker = TaintTracker()
        results = self._results(session_id)
        for tool, text in results:
            tracker.mark(f"tool:{tool}", "tool_result", text)
        return tracker, [tool for tool, _text in results]

    def declared(self, session_id: str | None, messages: list[Any]) -> dict[str, str]:
        """Message index -> ``tool_result`` for each message that quotes a result."""
        from agentfox.capabilities.detection.taint import _flatten, _norm

        needles = [_norm(text)[: self._NEEDLE] for _tool, text in self._results(session_id)]
        if not needles:
            return {}
        declared: dict[str, str] = {}
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or message.get("role") in ("tool", "function"):
                continue
            content = message.get("content")
            text = _norm(content if isinstance(content, str) else _flatten(content))
            if text and any(needle in text for needle in needles):
                declared[str(index)] = "tool_result"
        return declared

    def clear(self) -> None:
        with self._lock:
            self._by_session.clear()


_TOOL_RESULTS = _ToolResults()


def _lc_tool_decide(
    state: AutoState,
    name: str,
    arguments: dict[str, Any],
    handoff: tuple[str, str] | None = None,
) -> tuple[bool, EnforcementResult, str | None]:
    """Authorise one tool call where it runs (LangChain, CrewAI). Returns (may run,
    decision, trace id). Argument provenance comes from the results of the tools
    this conversation already ran (`_ToolResults`). A hand-off (``handoff``: target,
    relation) is recorded, not decided (see `_handoff_of`)."""
    if handoff is not None:
        if handoff[1] == "handoff":
            _delegation.learn_handoff(name, handoff[0])
        return True, EnforcementResult(), _handoff_where_it_runs(state, name, *handoff)
    if state.remote is not None:
        return _remote_tool_decide(state, name, arguments)
    from agentfox.platform.ledger.trace import start_trace

    token = _IN_AGENTFOX.set(True)
    try:
        with session_scope() as session:
            enforcer = Enforcer(session)
            agent, identity, _shadow = enforcer.resolve(state.agent)
            _register_tool(session, name, None)
            trace = start_trace(
                session,
                agent_id=agent.id if agent else None,
                agent_slug=state.agent,
                session_id=state.session_id,
                environment=state.environment,
                intent=state.intent,
            )
            tracker, prior_tools = _TOOL_RESULTS.tracker(state.session_id)
            tracker.trace_id = trace.id
            has_grants = _agent_has_grants(session, identity)
            exempt = (
                frozenset(_CAPABILITY_REFUSAL_RULE_IDS)
                if state.mode == "policy" and not has_grants
                else frozenset()
            )
            result = enforcer.guard_tool_call(
                in_process={"observe": "none", "enforce": "all"}.get(state.mode, "enforced"),
                exempt_rules=exempt,
                agent_slug=state.agent,
                intent=state.intent,
                tool_key=name,
                arguments=arguments,
                trace=trace,
                tracker=tracker,
                prior_tools=prior_tools,
                approval_id=_LC_HELD.approved(session, name, arguments),
            )
            enforced = result.blocked or result.escalated
            effective = enforced or result.effective_verdict in ("block", "escalate")
            if enforced and state.mode == "policy" and _capability_only(result):
                enforced = has_grants
            raised = _raises(state.mode, enforced=enforced, effective=effective)
            if result.escalated and result.approval_id:
                _LC_HELD.hold(name, arguments, result.approval_id)
            state.calls_governed += 1
            if raised:
                state.calls_blocked += 1
            elif effective:
                state.would_have_blocked += 1
            return not raised, result, trace.id
    finally:
        _IN_AGENTFOX.reset(token)


def _lc_tool_result(state: AutoState, trace_id: str | None, text: str) -> EnforcementResult | None:
    """Check what the tool returned before the model reads it. Returns the decision
    when it withholds the result, else None."""
    if not text:
        return None
    if state.remote is not None:
        return _remote_tool_result(state, trace_id, text)
    from agentfox.core.models import Trace

    token = _IN_AGENTFOX.set(True)
    try:
        with session_scope() as session:
            enforcer = Enforcer(session)
            trace = session.get(Trace, trace_id) if trace_id else None
            decision = enforcer.check_content(
                agent_slug=state.agent,
                content=text,
                surface="tool_result",
                taint_source="tool_result",
                trace=trace,
            )
            verdict = decision.get("verdict", "allow")
            effective = decision.get("effective_verdict", verdict)
            enforced = verdict in ("block", "escalate")
            stop = _raises(
                state.mode, enforced=enforced, effective=enforced or effective in ("block",)
            )
            if not stop:
                return None
            return EnforcementResult(
                verdict=verdict,
                effective_verdict=effective,
                reason=decision.get("reason", ""),
                user_message=decision.get("user_message") or "",
                trace_id=decision.get("trace_id"),
                rules_fired=decision.get("rules_fired") or [],
            )
    finally:
        _IN_AGENTFOX.reset(token)


# ---------------------------------------------------------------------------
# Reporting to an account (`remote.Remote`): the same decisions, made by its gateway
# ---------------------------------------------------------------------------

_IN_PROCESS = {"observe": "none", "enforce": "all"}


def _stops(body: dict[str, Any]) -> bool:
    return body.get("verdict") in ("block", "escalate")


def _remote_preflight(
    state: AutoState,
    kwargs: dict[str, Any],
    evidence: dict[str, Any],
    messages: list[dict[str, Any]],
) -> tuple[_Call, EnforcementResult, bool, bool]:
    """Pre-flight on the account's gateway: what is new in this request (the user's
    turn and any tool results since the model last spoke), each checked as an input."""
    last_reply = max(
        (i for i, m in enumerate(messages) if str(m.get("role")) == "assistant"), default=-1
    )
    fresh = [
        m
        for m in messages[last_reply + 1 :]
        if str(m.get("role")) in ("user", "tool") and str(m.get("content") or "")
    ]
    trace_id: str | None = None
    worst: dict[str, Any] = {"verdict": "allow"}
    quoted = _TOOL_RESULTS.declared(state.session_id, fresh)
    # A hand-off's acknowledgement carries the person's conversation, not a tool's.
    handed = {id(messages[int(i)]) for i in _delegation.handoff_messages(messages)}
    for index, message in enumerate(fresh):
        body = state.remote.post(
            "/v1/guard/input",
            {
                "agent": state.agent,
                "content": str(message.get("content")),
                "taint_source": (
                    "tool_result"
                    if (message.get("role") == "tool" and id(message) not in handed)
                    or str(index) in quoted
                    else "user"
                ),
                "environment": state.environment,
                **{
                    k: v
                    for k, v in (
                        ("session_id", state.session_id),
                        ("intent", state.intent),
                        ("trace_id", trace_id),
                    )
                    if v
                },
            },
        )
        trace_id = trace_id or body.get("trace_id")
        # The worst decision leads: an applied stop, else a would-be block.
        if _stops(body) and not _stops(worst):
            worst = body
        elif not _stops(worst) and worst.get("effective_verdict") != "block":
            worst = body
    result = _remote_module().result(worst)
    enforced = _stops(worst)
    effective = enforced or worst.get("effective_verdict") == "block"
    tracker, prior_tools = _provenance_of(kwargs, _declared_for(state))
    tracker.trace_id = trace_id
    call = _Call(
        state=state,
        model=str(kwargs.get("model") or ""),
        messages=messages,
        trace_id=trace_id or "",
        evidence=evidence,
        tracker=tracker,
        prior_tools=prior_tools,
        tool_specs=_tool_specs(kwargs),
        provenance_note=kwargs.get(_HISTORY_NOTE),
    )
    return call, result, enforced, effective


def _remote_module() -> Any:
    from agentfox.frameworks.autoguard import remote

    return remote


def _remote_tool_body(
    state: AutoState, name: str, arguments: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    body = state.remote.post(
        "/v1/guard/tool_call",
        {
            "agent": state.agent,
            "tool": name,
            "arguments": arguments,
            "environment": state.environment,
            # A retry of a call a person approved goes through once; the process has
            # no approval id to send back.
            "redeem_approved": True,
            "in_process": _IN_PROCESS.get(state.mode, "enforced"),
            "waive_ungranted": state.mode == "policy",
            **{k: v for k, v in (("session_id", state.session_id), ("intent", state.intent)) if v},
            **extra,
        },
    )
    return body


def _remote_tool_verdict(
    state: AutoState, body: dict[str, Any]
) -> tuple[EnforcementResult, bool, bool]:
    """(result, raised, effective) under the same rules as a local tool decision."""
    result = _remote_module().result(body)
    enforced = _stops(body)
    effective = enforced or body.get("effective_verdict") in ("block", "escalate")
    if enforced and body.get("waived_rules") and _capability_only(result):
        enforced = False  # the no-grants carve-out, applied by the gateway
    return result, _raises(state.mode, enforced=enforced, effective=effective), effective


def _remote_postflight(
    call: _Call,
    text: str,
    usage: dict[str, int],
    tool_calls: list[_ToolCall],
    response: Any,
) -> tuple[Blocked | None, str]:
    """Post-flight on the account's gateway. Returns (refusal, text to hand on)."""
    state = call.state
    refusal: Blocked | None = None
    trace = {"trace_id": call.trace_id} if call.trace_id else {}
    session = {"session_id": state.session_id} if state.session_id else {}
    if text:
        body = state.remote.post(
            "/v1/guard/output",
            {
                "agent": state.agent,
                "content": text,
                "surface": "output",
                "environment": state.environment,
                **trace,
                **session,
                **({"usage": {"model": call.model, **usage}} if usage else {}),
            },
        )
        outbound = _remote_module().result(body)
        enforced = _stops(body)
        effective = enforced or body.get("effective_verdict") == "block"
        if _raises(state.mode, enforced=enforced, effective=effective):
            refusal = Blocked(outbound)
        else:
            rewrite = _applied_rewrite(state.mode, outbound)
            if rewrite is not None:
                refusal = _apply_redaction(outbound, rewrite, response)
                if refusal is None:
                    text = rewrite
            elif effective:
                call.flagged = call.flagged or outbound.reason or "flagged by policy"
    if tool_calls and not _tools_governed_where_they_run(state):
        prior = list(call.prior_tools)
        for tool_call in tool_calls:
            if _handoff_of(
                tool_call.name, call.tool_specs.get(tool_call.name)
            ) or _delegation.is_output_tool(tool_call.name):
                continue  # an agent's own part, not a tool: nothing for the gateway to grant
            body = _remote_tool_body(
                state,
                tool_call.name,
                tool_call.arguments,
                # The conversation, so the gateway infers which arguments came from
                # a tool result.
                messages=call.messages,
                prior_tools=list(prior),
                declare=call.tool_specs.get(tool_call.name) or {},
            )
            prior.append(tool_call.name)
            result, raised, effective = _remote_tool_verdict(state, body)
            if raised and refusal is None:
                refusal = Blocked(
                    result,
                    "agentfox: " + _describe_tool_refusal(tool_call, result, [], applied=True),
                    tool_call=tool_call,
                )
            elif effective and not raised:
                call.flagged = call.flagged or _describe_tool_refusal(
                    tool_call, result, [], applied=False
                )
    return refusal, text


def _remote_tool_decide(
    state: AutoState, name: str, arguments: dict[str, Any]
) -> tuple[bool, EnforcementResult, str | None]:
    """`_lc_tool_decide` on the account's gateway."""
    results = _TOOL_RESULTS._results(state.session_id)
    provenance: dict[str, Any] = {}
    if results:
        provenance = {
            "messages": [{"role": "tool", "name": tool, "content": text} for tool, text in results],
            "prior_tools": [tool for tool, _text in results],
        }
    body = _remote_tool_body(state, name, arguments, declare={}, **provenance)
    result, raised, effective = _remote_tool_verdict(state, body)
    state.calls_governed += 1
    if raised:
        state.calls_blocked += 1
    elif effective:
        state.would_have_blocked += 1
    return not raised, result, body.get("trace_id")


def _remote_tool_result(
    state: AutoState, trace_id: str | None, text: str
) -> EnforcementResult | None:
    """`_lc_tool_result` on the account's gateway."""
    body = state.remote.post(
        "/v1/guard/input",
        {
            "agent": state.agent,
            "content": text,
            "surface": "tool_result",
            "taint_source": "tool_result",
            "environment": state.environment,
            **({"trace_id": trace_id} if trace_id else {}),
            **({"session_id": state.session_id} if state.session_id else {}),
        },
    )
    enforced = _stops(body)
    effective = enforced or body.get("effective_verdict") == "block"
    if not _raises(state.mode, enforced=enforced, effective=effective):
        return None
    return _remote_module().result(body)


def _lc_tool_method(state: AutoState, *, is_async: bool) -> Callable[[Any], Any]:
    """Wrapper factory for `BaseTool.invoke` / `.ainvoke`."""

    def before(tool: Any, tool_input: Any) -> tuple[Any, str, dict[str, Any], str | None, Any]:
        st = _live(state)
        name, arguments, call_id = _lc_tool_input(tool, tool_input)
        allowed, result, trace_id = _lc_tool_decide(st, name, arguments, _lc_handoff(tool))
        if allowed:
            return None, name, arguments, call_id, trace_id
        if st.tool_refusals == "raise":
            raise Blocked(result, f"agentfox: tool call '{name}' refused: {result.reason}")
        if result.escalated and result.approval_id:
            text = _HELD_MESSAGE.format(approval_id=result.approval_id)
        else:
            text = "This tool call was blocked by policy: " + (
                result.user_message or result.reason or "not allowed"
            )
        return _lc_tool_reply(text, name, call_id, error=True), name, arguments, call_id, trace_id

    def after(output: Any, name: str, call_id: str | None, trace_id: str | None) -> Any:
        if _delegation.is_handoff_message(name):
            # A hand-off returns the framework's routing (LangGraph: a `Command` that
            # carries the whole conversation on to the next agent), not content from
            # outside the system: nothing to check, and no tool result for the next
            # agent's arguments to be copied from.
            return output
        text = getattr(output, "content", output)
        st = _live(state)
        text = text if isinstance(text, str) else str(text)
        withheld = _lc_tool_result(st, trace_id, text)
        if withheld is None:
            _TOOL_RESULTS.add(st.session_id, name, text)
            return output
        message = withheld.user_message or withheld.reason or "it failed a policy check"
        return _lc_tool_reply(
            f"This tool's result was withheld by policy: {message}",
            name,
            call_id or getattr(output, "tool_call_id", None),
            error=True,
        )

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(self: Any, tool_input: Any, *args: Any, **kwargs: Any) -> Any:
                if _IN_AGENTFOX.get():
                    return await original(self, tool_input, *args, **kwargs)
                refusal, name, _arguments, call_id, trace_id = before(self, tool_input)
                if refusal is not None:
                    return refusal
                output = await original(self, tool_input, *args, **kwargs)
                return after(output, name, call_id, trace_id)

            return agoverned

        @functools.wraps(original)
        def governed(self: Any, tool_input: Any, *args: Any, **kwargs: Any) -> Any:
            if _IN_AGENTFOX.get():
                return original(self, tool_input, *args, **kwargs)
            refusal, name, _arguments, call_id, trace_id = before(self, tool_input)
            if refusal is not None:
                return refusal
            output = original(self, tool_input, *args, **kwargs)
            return after(output, name, call_id, trace_id)

        return governed

    return build


def _patch_langchain_tools(state: AutoState) -> list[PatchResult]:
    try:
        import langchain_core
        from langchain_core.tools import BaseTool
    except Exception as exc:
        return _not_importable("langchain tools", exc)

    version = getattr(langchain_core, "__version__", None)
    results = [
        _patch_attr(
            "langchain.tools",
            "langchain-core",
            BaseTool,
            "invoke",
            _lc_tool_method(state, is_async=False),
            version,
            "BaseTool.invoke",
        ),
        _patch_attr(
            "langchain.tools.async",
            "langchain-core",
            BaseTool,
            "ainvoke",
            _lc_tool_method(state, is_async=True),
            version,
            "BaseTool.ainvoke",
        ),
    ]
    state.lc_tools = all(r.patched for r in results)
    return results


# -- CrewAI tools, governed where they run -------------------------------------------


def _crew_tool_name(tool: Any) -> str:
    """The tool's name as CrewAI hands it to the model (``sanitize_tool_name``), so a
    tool keeps one key whether it was called by text or natively."""
    name = str(getattr(tool, "name", "") or type(tool).__name__)
    try:
        from crewai.utilities.string_utils import sanitize_tool_name

        return sanitize_tool_name(name) or name
    except Exception:  # older crewai: no sanitiser, the name as given
        return name


def _crew_invoke_input(tool: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """`CrewStructuredTool.invoke(input, config=None, **kwargs)`: the arguments the
    agent wrote after "Action Input:", already parsed by CrewAI into a dict, or a
    string it could not parse."""
    raw = args[0] if args else kwargs.get("input", {})
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {"input": raw}
    if isinstance(raw, dict):
        return dict(raw)
    return {"_value": raw}


def _crew_run_input(tool: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """`BaseTool.run(*args, **kwargs)`: what a native tool call or the app passed."""
    arguments = dict(kwargs)
    if len(args) == 1 and not arguments:
        return _crew_invoke_input(tool, args, {})
    if args:
        arguments["_args"] = list(args)
    return arguments


def _crew_tool_method(
    state: AutoState, *, is_async: bool, read: Callable[..., dict[str, Any]]
) -> Callable[[Any], Any]:
    """Wrapper factory for CrewAI's tool entry points. The same decision as a
    LangChain tool (`_lc_tool_decide`): a refused call hands the agent the refusal as
    the tool's result and the crew carries on (``tool_refusals="raise"`` raises
    `Blocked`); what the tool returns is checked as ``tool_result`` before the agent
    reads it, and kept as provenance for the calls that follow."""

    def before(tool: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, str, Any]:
        st = _live(state)
        name = _crew_tool_name(tool)
        arguments = read(tool, args, kwargs)
        handoff = _crew_handoff(tool, arguments)
        allowed, result, trace_id = _lc_tool_decide(st, name, arguments, handoff)
        if allowed:
            return None, name, trace_id
        if st.tool_refusals == "raise":
            raise Blocked(result, f"agentfox: tool call '{name}' refused: {result.reason}")
        if result.escalated and result.approval_id:
            return _HELD_MESSAGE.format(approval_id=result.approval_id), name, trace_id
        reason = result.user_message or result.reason or "not allowed"
        return f"This tool call was blocked by policy: {reason}", name, trace_id

    def after(output: Any, name: str, trace_id: str | None) -> Any:
        if inspect.isawaitable(output):
            # CrewAI's sync path over an `async def` tool hands back the coroutine
            # unawaited; it has no text yet, and awaiting it is CrewAI's business.
            return output
        st = _live(state)
        text = output if isinstance(output, str) else str(output)
        withheld = _lc_tool_result(st, trace_id, text)
        if withheld is None:
            _TOOL_RESULTS.add(st.session_id, name, text)
            return output
        message = withheld.user_message or withheld.reason or "it failed a policy check"
        return f"This tool's result was withheld by policy: {message}"

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def agoverned(self: Any, *args: Any, **kwargs: Any) -> Any:
                if _IN_AGENTFOX.get():
                    return await original(self, *args, **kwargs)
                refusal, name, trace_id = before(self, args, kwargs)
                if refusal is not None:
                    return refusal
                output = await original(self, *args, **kwargs)
                return after(output, name, trace_id)

            return agoverned

        @functools.wraps(original)
        def governed(self: Any, *args: Any, **kwargs: Any) -> Any:
            if _IN_AGENTFOX.get():
                return original(self, *args, **kwargs)
            refusal, name, trace_id = before(self, args, kwargs)
            if refusal is not None:
                return refusal
            output = original(self, *args, **kwargs)
            return after(output, name, trace_id)

        return governed

    return build


def _crew_scope(*, is_async: bool) -> Callable[[Any], Any]:
    """Wrapper factory for a CrewAI agent running a task: marks the model calls made
    inside it as CrewAI's, whose tool calls are decided where the tools run."""

    def build(original: Any) -> Any:
        if is_async:

            @functools.wraps(original)
            async def ascoped(*args: Any, **kwargs: Any) -> Any:
                token = _FROM_CREWAI.set(True)
                try:
                    return await original(*args, **kwargs)
                finally:
                    _FROM_CREWAI.reset(token)

            return ascoped

        @functools.wraps(original)
        def scoped(*args: Any, **kwargs: Any) -> Any:
            token = _FROM_CREWAI.set(True)
            try:
                return original(*args, **kwargs)
            finally:
                _FROM_CREWAI.reset(token)

        return scoped

    return build


#: CrewAI's tool entry points: label, owner (in `crewai.tools.*`), method, async,
#: how its arguments are read. `CrewStructuredTool.invoke` is an agent's text tool
#: call ("Action: ... / Action Input: ...", via `ToolUsage`); `BaseTool.run` and the
#: `@tool` decorator's `Tool.run` are a native tool call, or the app calling the tool.
#: None calls another, so each call is decided once.
_CREW_ENTRY_POINTS = (
    ("crewai.tools", "structured_tool.CrewStructuredTool", "invoke", False, _crew_invoke_input),
    (
        "crewai.tools.async",
        "structured_tool.CrewStructuredTool",
        "ainvoke",
        True,
        _crew_invoke_input,
    ),
    ("crewai.tools.run", "base_tool.BaseTool", "run", False, _crew_run_input),
    ("crewai.tools.run.async", "base_tool.BaseTool", "arun", True, _crew_run_input),
    ("crewai.tools.function", "base_tool.Tool", "run", False, _crew_run_input),
    ("crewai.tools.function.async", "base_tool.Tool", "arun", True, _crew_run_input),
)

#: Where a CrewAI agent runs: the model calls inside are CrewAI's (`_FROM_CREWAI`).
_CREW_AGENT_SCOPES = (
    ("crewai.agent", "execute_task", False),
    ("crewai.agent.async", "aexecute_task", True),
    ("crewai.agent.kickoff", "kickoff", False),
    ("crewai.agent.kickoff.async", "kickoff_async", True),
)


def _patch_crewai_tools(state: AutoState) -> list[PatchResult]:
    """CrewAI tools, governed where they run (see `_CREW_ENTRY_POINTS`).

    Reported as two results, ``crewai.tools`` and ``crewai.tools.async``, each
    patched when every entry point of its kind is. CrewAI is imported only when it is
    installed; that import takes a second or two the first time.
    """
    import importlib.util

    try:
        if importlib.util.find_spec("crewai") is None:
            return _not_importable("crewai tools", ImportError("crewai"))
        import crewai
        from crewai.tools import base_tool, structured_tool
    except Exception as exc:
        return _not_importable("crewai tools", exc)

    modules = {"base_tool": base_tool, "structured_tool": structured_tool}
    version = getattr(crewai, "__version__", None)
    parts: dict[bool, list[PatchResult]] = {False: [], True: []}
    for label, where, attr, is_async, read in _CREW_ENTRY_POINTS:
        module, _, cls = where.partition(".")
        owner = getattr(modules[module], cls, None)
        if cls == "Tool" and attr not in getattr(owner, "__dict__", {}):
            continue  # `Tool` inherits BaseTool's, patched already
        parts[is_async].append(
            _patch_attr(
                label,
                "crewai",
                owner,
                attr,
                _crew_tool_method(state, is_async=is_async, read=read),
                version,
                f"{cls}.{attr}",
            )
        )
    try:
        from crewai import Agent

        for label, attr, is_async in _CREW_AGENT_SCOPES:
            if getattr(Agent, attr, None) is not None:
                _patch_attr(
                    label, "crewai", Agent, attr, _crew_scope(is_async=is_async), version, attr
                )
    except Exception as exc:  # pragma: no cover - the tools are still governed
        log.debug("agentfox: CrewAI agent scope not patched: %s", exc)

    results = []
    for label, is_async in (("crewai.tools", False), ("crewai.tools.async", True)):
        failed = [p for p in parts[is_async] if not p.patched]
        details = [p.detail for p in parts[is_async] if p.detail != "already patched"]
        detail = failed[0].detail if failed else ", ".join(details) or "already patched"
        results.append(PatchResult(label, not failed and bool(parts[is_async]), detail, version))
    state.crew_tools = results[0].patched
    return results


_PATCHERS = (
    _patch_openai,
    _patch_anthropic,
    _patch_litellm,
    _patch_langchain,
    _patch_langchain_tools,
    _patch_crewai_tools,
)


def auto(
    agent: str | None = None,
    *,
    mode: str = "policy",
    environment: str | None = None,
    session_id: str | None = None,
    intent: str | None = None,
    register: bool = True,
    quiet: bool = False,
    tool_refusals: str = "message",
    server: str | None = None,
    key: str | None = None,
) -> AutoState:
    """Govern this process. One line, no code changes anywhere else.

        import agentfox
        agentfox.auto()

    Every call is traced, evaluated and audited. Whether a call is ever refused is
    decided by ``mode``:

    * ``"policy"`` (default) — the policies decide: `Blocked` is raised exactly when
      the enforced verdict stops the call (an enforce-mode policy, the kill switch,
      quarantine or a hard budget cap) — what the gateway would refuse. The shipped
      detector packs observe, so model traffic is not refused until
      ``agentfox policy enforce baseline``; tool containment enforces from
      ``agentfox init``, so a tool call it stops is refused. Start with
      ``mode="observe"`` to see what that would be first.
    * ``"observe"`` — never raise; would-have-blocked is logged and counted.
    * ``"enforce"`` — strict: raise whenever the effective verdict blocks, even for a
      policy still in observe. For tests and CI.

    Tool calls in a response are authorised under the same mode before the response
    is returned (see the module docstring); a refused one raises `Blocked`.

    ``intent`` is the agent's task in a sentence ("answer a customer's support
    request"). An irreversible tool call with no declared task is escalated by
    tool containment, since it cannot be judged against one.

    LangChain tools are also governed where they run (``BaseTool.invoke``), whoever
    called them. A refused call hands the agent the refusal as the tool's result and
    the run carries on (``tool_refusals="raise"`` raises `Blocked` instead); a call
    held for a person runs once when made again after they approve; what a tool
    returns is checked before the model reads it.

    With an account key configured (``server=``/``key=``, ``AGENTFOX_URL`` and
    ``AGENTFOX_API_KEY``, or the ``.agentfox/agentfox.env`` that ``agentfox init``
    writes), every check goes to that account's gateway and the calls show up on its
    dashboard; see `agentfox.frameworks.autoguard.remote`.

    Returns the state, so a developer can assert on it in a test rather than trusting
    that it worked.
    """
    global _STATE
    if mode not in MODES:
        raise ValueError("mode must be 'policy' (default), 'observe' or 'enforce'")
    if os.environ.get(ATTACK_TEST_ENV):
        # Loaded by `agentfox init`'s attack test, which checks each call itself with
        # every tool faked: governing it here too would record the attacks as the
        # app's own traffic.
        return AutoState(agent=agent or default_agent_slug(), mode=mode, environment="test")
    if tool_refusals not in ("message", "raise"):
        raise ValueError("tool_refusals must be 'message' (default) or 'raise'")

    settings = get_settings()
    state = AutoState(
        agent=agent or default_agent_slug(),
        mode=mode,
        environment=environment or settings.environment,
        frameworks=detect_frameworks(),
        session_id=session_id,
        intent=intent,
        tool_refusals=tool_refusals,
    )
    from agentfox.frameworks.autoguard import remote as _remote

    state.remote = _remote.configured(server, key)

    try:
        if state.remote is not None:
            # The account registers the agent on its first call; nothing local to set up.
            raise _SkipLocalSetup
        init_db()
        if register:
            with session_scope() as session:
                agent = register_agent(
                    session,
                    state.agent,
                    name=state.agent,
                    environment=state.environment,
                    framework=state.frameworks[0] if state.frameworks else None,
                    purpose="auto-registered by agentfox.auto()",
                )
                # An agent with no identity holds no grants and cannot be given any
                # by name until something creates one; its refusals said "no
                # resolved identity for the caller". `permit grant` would
                # create it anyway; creating it here makes the first refusal name
                # the agent and the grant to make.
                identity = ensure_identity(session, agent)
                # In process there is no credential to be verified, so nothing else
                # marks the identity as in use; without this a running agent's
                # identity is posture-flagged stale.
                identity.last_used_at = utcnow()
        # How many policies actually reach this agent. Taken here because the
        # banner below claims a mode, and a mode claim with nothing behind it is
        # the failure this count exists to surface.
        with session_scope() as session:
            from agentfox.platform.policy import active_policies

            state.policies_bound = len(active_policies(session))
    except _SkipLocalSetup:
        pass
    except Exception as exc:
        # Registration is a convenience; failing it must not stop governance, and
        # hiding the failure would leave the developer wondering why the agent never
        # appeared in the registry. The policy count shares this guard: if it could
        # not be taken it stays -1, and the banner says nothing rather than
        # claiming an all-clear it did not verify.
        log.warning("agentfox: could not register agent '%s': %s", state.agent, exc)

    # An opted-in model detector loads its weights on first use; in the gateway that
    # happens at startup, and in-process it must too, or the first governed calls
    # time out while it loads. Off this thread; a no-op for the default set.
    warm_in_background()

    state.patches = [result for patch in _PATCHERS for result in patch(state)]
    # Hand-offs, agents used as tools and output tools, learned from the frameworks'
    # own objects: those imported already, and those imported after this line.
    _delegation.start(_PATCHED)
    state.started = True
    _STATE = state

    if not quiet:
        print(state.summary(), file=sys.stderr)  # noqa: T201 - the point is to be seen
    atexit.register(_report_at_exit)
    return state


def _report_at_exit() -> None:  # pragma: no cover - process teardown
    if _STATE and _STATE.calls_governed:
        print(
            f"agentfox: governed {_STATE.calls_governed} model call(s). "
            f"Run `agentfox findings` to see what it found.",
            file=sys.stderr,
        )


def state() -> AutoState | None:
    """What `auto()` did, or None if it was never called."""
    return _STATE


def off() -> list[str]:
    """Undo the patches. Mostly for tests, and for a developer proving it is reversible.

    Returns the labels restored (``"openai"``, ``"openai.async"``, ...).
    """
    global _STATE
    restored: list[str] = []
    for label, (owner, attr, had_own) in list(_PATCHED.items()):
        try:
            current = getattr(owner, attr, None)
            original = getattr(current, "__agentfox_original__", None)
            if original is not None:
                if had_own:
                    setattr(owner, attr, original)
                else:
                    delattr(owner, attr)  # it was inherited; let inheritance resume
                restored.append(label)
        except Exception:  # pragma: no cover - a module torn down under us
            pass
    _PATCHED.clear()
    _TOOL_RESULTS.clear()
    _delegation.stop()
    _STATE = None
    return restored
