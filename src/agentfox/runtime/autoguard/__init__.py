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
the response, so the caller's code never runs it. The OpenAI Responses API
(``client.responses.create``) is not patched, so its calls are not governed here.

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

Frameworks (LangGraph, CrewAI, LlamaIndex, AutoGen, ...) are detected, not patched:
they reach the model through one of the client libraries above, and the summary says
which of those routes are actually governed.

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
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentfox.core.config import get_settings
from agentfox.core.db import init_db, session_scope
from agentfox.core.models import utcnow
from agentfox.detection.taint import TaintTracker
from agentfox.detection.warmup import warm_in_background
from agentfox.errors import AgentFoxError
from agentfox.identity import ensure_identity
from agentfox.prove.audit.trace import (
    ATTR_AGENT,
    ATTR_REQUEST_MODEL,
    ATTR_TOOL_IMPACT,
    ATTR_TOOL_NAME,
    ATTR_VERDICT,
    add_span,
)
from agentfox.registry.service import register_agent
from agentfox.runtime.autoguard.environment import (
    _FRAMEWORK_ROUTES,
    _framework_routes,
    default_agent_slug,
    detect_frameworks,
)
from agentfox.runtime.autoguard.shapes import (
    _chunk_text,
    _chunk_tool_calls,
    _chunk_usage,
    _lc_messages_from,
    _messages_from,
    _text_of,
    _usage_of,
)
from agentfox.runtime.autoguard.tool_calls import (
    _arguments,
    _provenance_of,
    _tool_calls_of,
    _tool_specs,
    _ToolCall,
)
from agentfox.runtime.enforcement import _CAPABILITY_REFUSAL_RULE_IDS, EnforcementResult, Enforcer

log = logging.getLogger("agentfox.runtime.autoguard")


#: Guards against governing the model calls the platform makes for itself — an
#: LLM-as-judge call inside an eval would otherwise be traced as agent traffic and
#: charged against the agent's budget. It also stays set for the duration of a
#: governed call, so a LangChain `invoke` that calls the patched OpenAI client
#: underneath is governed once, not twice.
_IN_AGENTFOX: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agentfox_internal", default=False
)


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
        # Found by installing 0.3.1 from PyPI into a third-party project and
        # calling auto() without running `agentfox init` first, which is exactly
        # what adding one line to an existing app looks like: the banner said
        # "enforce mode", the canonical injection went straight to OpenAI, and
        # the 401 from an invalid key proved it had left the process.
        #
        # The enforcer now falls back to the shipped baseline in observe when
        # nothing is bound (see _fallback_policies), so this line says what is
        # actually running rather than warning that nothing is. Still said out
        # loud, because "a fallback is deciding for you" is a fact an operator
        # has to know before they trust a clean dashboard.
        #
        # It used to add "Tool-call containment enforces regardless", which was false
        # twice over: nothing on this path looked at a tool call at all, and the
        # containment pack is not part of the fallback. What is true now depends on
        # the mode, so the sentence does too.
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
                "calls in the response (OpenAI tool_calls, Anthropic tool_use) before "
                "your code can run them. Not the OpenAI Responses API."
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
        from agentfox.containment.escalation import record_turn
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


def _pop_evidence(kwargs: dict[str, Any]) -> dict[str, Any]:
    # P10 — the caller's end-user identity and retrieved context, if it supplied
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

    tracker, prior_tools = _provenance_of(kwargs)
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
    )
    return call, result, enforced, effective


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
) -> None:
    """Span, output evaluation, tool-call authorisation, budget charge, turn record.
    Shared by buffered, streamed, sync and async calls. Raises `Blocked` when the
    output or a tool call must be refused under the state's mode and ``may_raise``."""
    state = call.state
    tool_calls = tool_calls or []
    provider_ms = (time.perf_counter() - call.started) * 1000
    refusal: Blocked | None = None
    tool_failure: Exception | None = None
    try:
        if text or usage or tool_calls:
            token = _IN_AGENTFOX.set(True)
            try:
                with session_scope() as session:
                    enforcer = Enforcer(session)
                    agent, identity, _shadow = enforcer.resolve(state.agent)
                    if text:
                        outbound = _evaluate_output(
                            call, session, enforcer, agent, identity, text, usage, provider_ms
                        )
                        if outbound is not None:
                            refusal = Blocked(outbound)
                    if tool_calls:
                        tool_refusal = _govern_tool_calls(
                            call, session, enforcer, identity, tool_calls
                        )
                        refusal = refusal or tool_refusal
                    # P15: this call never goes through AgentFox's own provider
                    # abstraction — it's the caller's own SDK, patched in place — so
                    # nothing else on this path ever charges spend against the
                    # agent's budget. Charged even when the output is refused: the
                    # tokens were spent either way.
                    if agent is not None and usage:
                        from types import SimpleNamespace

                        from agentfox.providers.remote import estimate_cost

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

    # P11: capture the exchange as a conversation turn. Escalation governance was
    # complete and inert for anyone using the one-liner — the detector reads recorded
    # turns, and nothing was recording them. Session grouping falls back to the trace
    # when the caller has no session concept.
    try:
        _record_turn(state, call.messages, text, call.trace_id)
    except Exception as exc:  # pragma: no cover - defence in depth
        # Guarded here as well as inside, so that a future change to turn capture
        # cannot become a change to whether the caller's request succeeds.
        log.debug("agentfox: turn capture failed: %s", exc)

    if call.flagged:
        state.would_have_blocked += 1
        log.info("agentfox: would have blocked (%s mode) — %s", state.mode, call.flagged)


def _register_tool(session: Any, name: str, descriptor: dict[str, Any] | None) -> None:
    """Put a tool the model called into the registry the first time it is seen.

    Containment reasons over `Tool.impact`, and an unregistered tool is reasoned
    about as ``read`` — the least dangerous value there is. So the impact is
    inferred from the tool's name and the description the request declared
    (`integrations.mcp.infer_impact`, the guess MCP governance already makes, read
    cautiously: a name that moves money or sends a message is irreversible, as the
    learned-permissions guess has it — an unconfirmed payment tool guessed `read`
    is containment switched off for the one tool that needed it) and recorded as
    ``impact_source="inferred"``, for a human to confirm with `agentfox declare tool`.
    A declaration made in code (`@fox.tool(impact=...)`)
    beats the guess. An existing row is never overwritten — except an inferred one
    that code has since declared.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from agentfox.core.models import Tool
    from agentfox.improvement.traffic import infer_declared_impact
    from agentfox.integrations.mcp import infer_impact
    from agentfox.registry.service import DECLARED_TOOL_IMPACTS, impact_source_of, upsert_tool

    declared = DECLARED_TOOL_IMPACTS.get(name)
    existing = session.scalar(select(Tool).where(Tool.key == name))
    if existing is not None:
        if declared and impact_source_of(existing) == "inferred":
            upsert_tool(session, name, impact=declared, impact_source="declared")
        return
    descriptor = descriptor or {}
    guess = infer_impact(name, descriptor)
    if infer_declared_impact(name) == "irreversible":
        guess = "irreversible"
    try:
        # A savepoint, because two processes meeting the same new tool at once is
        # ordinary, and losing that race must not roll back the decisions already
        # written in this session.
        with session.begin_nested():
            upsert_tool(
                session,
                name,
                name=name,
                impact=declared or guess,
                impact_source="declared" if declared else "inferred",
                schema=descriptor.get("inputSchema") or {},
                description=descriptor.get("description", ""),
            )
    except IntegrityError:
        pass  # registered by someone else a moment ago; theirs stands


def _agent_has_grants(session: Any, identity: Any) -> bool:
    """Whether anyone has configured least privilege for this agent at all."""
    if identity is None:
        return False
    from sqlalchemy import func, select

    from agentfox.core.models import Capability

    count = session.scalar(
        select(func.count()).select_from(Capability).where(Capability.identity_id == identity.id)
    )
    return bool(count)


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
    message names the rule that did, and mentions the exempt ones last (#83).
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
            },
        )
    return refusal


def _evaluate_output(
    call: _Call,
    session: Any,
    enforcer: Enforcer,
    agent: Any,
    identity: Any,
    text: str,
    usage: dict[str, int],
    provider_ms: float,
) -> EnforcementResult | None:
    """Write the llm span and evaluate the output surface. Returns the result when it
    must be refused under the state's mode."""
    from agentfox.core.models import Trace

    state = call.state
    # The only place on this path that writes a kind="llm" span with the raw
    # response text — the shape sample_production() (P4-2 online eval) scores.
    # Mirrors enforcement.py's _finish_completion(), the gateway path's equivalent.
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
        },
        duration_ms=provider_ms,
    )

    principal_ref = call.evidence.get("agentfox_principal")
    chunks = call.evidence.get("agentfox_chunks") or []
    # Either one is evidence. Chunks without a principal still carry the sources the
    # answer was built from, which is what source authority (F2) and numeric
    # integrity (F7) check; gating them on a principal skipped both (#5).
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
        return outbound
    if enforced or effective:
        call.flagged = call.flagged or outbound.reason or "output flagged by policy"
    return None


def _resolve_principal(session: Any, principal_ref: Any) -> Any:
    """The end user a call was made for, registered or not.

    A subject nobody registered used to resolve to None, and the entitlement check
    then ran as though no principal had been named — recording nothing at all (#5).
    An unregistered subject is still a person: it is evaluated as itself, with no
    groups or clearances (only what is granted to the subject directly), and what it
    could not see is recorded against that subject. Never added to the session.
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

    if _is_stream(kwargs, response) and hasattr(response, "__iter__"):
        return _GovernedStream(response, governed)
    _postflight(
        governed, _text_of(response), _usage_of(response), tool_calls=_tool_calls_of(response)
    )
    return response


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

    if _is_stream(kwargs, response):
        if hasattr(response, "__aiter__"):
            return _AsyncGovernedStream(response, governed)
        if hasattr(response, "__iter__"):
            return _GovernedStream(response, governed)
    _postflight(
        governed, _text_of(response), _usage_of(response), tool_calls=_tool_calls_of(response)
    )
    return response


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
        except Exception as exc:  # pragma: no cover - never break the caller's stream
            log.debug("agentfox: stream chunk not read: %s", exc)

    def _nm_finish(self, *, may_raise: bool = True) -> None:
        if self._nm_done:
            return
        self._nm_done = True
        tool_calls = [
            _ToolCall(part["name"], _arguments("".join(part["args"])), part.get("id"))
            for _index, part in sorted(self._nm_tools.items())
            if part.get("name")
        ]
        _postflight(
            self._nm_call,
            "".join(self._nm_parts),
            dict(self._nm_usage),
            tool_calls=tool_calls,
            may_raise=may_raise,
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

                return await _agovern(_live(state), govern_kwargs, call)

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

            return _govern(_live(state), govern_kwargs, call)

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
    if getattr(current, "__nometria__", False):
        return PatchResult(label, True, "already patched", version)
    had_own = attr in getattr(owner, "__dict__", {})
    governed = build(current)
    governed.__nometria__ = True
    governed.__nometria_original__ = current
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


_PATCHERS = (_patch_openai, _patch_anthropic, _patch_litellm, _patch_langchain)


def auto(
    agent: str | None = None,
    *,
    mode: str = "policy",
    environment: str | None = None,
    session_id: str | None = None,
    intent: str | None = None,
    register: bool = True,
    quiet: bool = False,
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

    Returns the state, so a developer can assert on it in a test rather than trusting
    that it worked.
    """
    global _STATE
    if mode not in MODES:
        raise ValueError("mode must be 'policy' (default), 'observe' or 'enforce'")

    settings = get_settings()
    state = AutoState(
        agent=agent or default_agent_slug(),
        mode=mode,
        environment=environment or settings.environment,
        frameworks=detect_frameworks(),
        session_id=session_id,
        intent=intent,
    )

    try:
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
                # resolved identity for the caller" (#83). `permit grant` would
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
            from agentfox.policy import active_policies

            state.policies_bound = len(active_policies(session))
    except Exception as exc:
        # Registration is a convenience; failing it must not stop governance, and
        # hiding the failure would leave the developer wondering why the agent never
        # appeared in the registry. The policy count shares this guard: if it could
        # not be taken it stays -1, and the banner says nothing rather than
        # claiming an all-clear it did not verify.
        log.warning("agentfox: could not register agent '%s': %s", state.agent, exc)

    # An opted-in model detector loads its weights on first use; in the gateway that
    # happens at startup, and in-process it must too, or the first governed calls
    # time out while it loads (#48). Off this thread; a no-op for the default set.
    warm_in_background()

    state.patches = [result for patch in _PATCHERS for result in patch(state)]
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
            original = getattr(current, "__nometria_original__", None)
            if original is not None:
                if had_own:
                    setattr(owner, attr, original)
                else:
                    delattr(owner, attr)  # it was inherited; let inheritance resume
                restored.append(label)
        except Exception:  # pragma: no cover - a module torn down under us
            pass
    _PATCHED.clear()
    _STATE = None
    return restored
