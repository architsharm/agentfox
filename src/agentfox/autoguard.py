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

Modes — who decides whether a call is refused in-process:

* ``"policy"`` (the default) — the policies decide. Each policy's own mode applies,
  plus the agent's kill switch, quarantine and hard budget caps: `Blocked` is raised
  exactly when the *enforced* verdict stops the call, i.e. when the gateway would have
  refused it. The shipped ``baseline`` pack is in observe mode, so adding the import
  blocks nothing; ``agentfox policy enforce baseline`` is the one step that starts
  blocking, with no second knob to find here.
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
  (``NOMETRIA_STREAMING_MODE=windowed``), not something a patched SDK can offer.

Frameworks (LangGraph, CrewAI, LlamaIndex, AutoGen, ...) are detected, not patched:
they reach the model through one of the client libraries above, and the summary says
which of those routes are actually governed.

Everything is import-guarded: a codebase with only `anthropic` installed never sees an
OpenAI import error, and `auto()` on a machine with neither still succeeds — it simply
reports that there was nothing to patch, which is information rather than failure.
"""

from __future__ import annotations

import atexit
import contextvars
import functools
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .audit.trace import ATTR_AGENT, ATTR_REQUEST_MODEL, add_span
from .config import get_settings
from .db import init_db, session_scope
from .enforcement import EnforcementResult, Enforcer
from .registry.service import register_agent

log = logging.getLogger(__name__)

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
        if self.policies_bound == 0:
            lines.append(
                "  No policy is bound, so the shipped baseline applies as a fallback, "
                "in observe: detections are recorded, nothing is blocked on their "
                "account. Tool-call containment enforces regardless. Run "
                "`agentfox init` for the full set and to choose what enforces."
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
        if self.mode == "policy":
            lines.append(
                "  Policy mode: each policy's own mode decides. Observe-mode policies "
                "(baseline ships in observe) record what they would have blocked; "
                "enforce-mode policies, the kill switch and budget caps raise "
                "agentfox.Blocked. `agentfox policy enforce baseline` is the one step "
                "that starts blocking."
            )
        elif self.mode == "observe":
            lines.append(
                "  Observe mode: decisions are recorded, nothing is blocked in-process — "
                "not even by an enforce-mode policy or the kill switch."
            )
        else:
            lines.append(
                "  Enforce mode (strict): any call a policy would block raises "
                "agentfox.Blocked, even when that policy is still in observe."
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Framework detection
# ---------------------------------------------------------------------------

#: Modules whose presence in `sys.modules` tells us what the app is built on. Reading
#: `sys.modules` rather than importing keeps detection free of side effects — we learn
#: what the app already loaded, not what it *could* load.
_FRAMEWORK_MODULES = {
    "langgraph": "langgraph",
    "langchain": "langchain",
    "llama_index": "llamaindex",
    "crewai": "crewai",
    "autogen": "autogen",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "mcp": "mcp",
    "ragas": "ragas",
    "litellm": "litellm",
}

#: Detected framework -> the client libraries (patch labels) it calls the model
#: through. Only frameworks that make model calls are listed; web frameworks and MCP
#: carry no model traffic of their own.
_FRAMEWORK_ROUTES: dict[str, tuple[str, ...]] = {
    "langgraph": ("langchain", "openai", "anthropic"),
    "langchain": ("langchain",),
    "crewai": ("litellm", "openai", "anthropic"),
    "llamaindex": ("openai", "anthropic"),
    "autogen": ("openai", "anthropic"),
    "ragas": ("langchain", "openai"),
}


def detect_frameworks() -> list[str]:
    return sorted({name for module, name in _FRAMEWORK_MODULES.items() if module in sys.modules})


def _framework_routes(
    frameworks: list[str], patches: list[PatchResult]
) -> dict[str, dict[str, str]]:
    by_label = {p.library: p for p in patches}
    routes: dict[str, dict[str, str]] = {}
    for framework in frameworks:
        clients = _FRAMEWORK_ROUTES.get(framework)
        if not clients:
            continue
        statuses: dict[str, str] = {}
        for client in clients:
            sync = by_label.get(client)
            async_ = by_label.get(f"{client}.async")
            sync_ok = bool(sync and sync.patched)
            async_ok = bool(async_ and async_.patched)
            if sync_ok and async_ok:
                statuses[client] = "governed"
            elif sync_ok:
                statuses[client] = "governed (sync only)"
            elif async_ok:
                statuses[client] = "governed (async only)"
            elif sync is not None and sync.detail != "not installed":
                # Installed but we could not patch it: say so, loudly.
                statuses[client] = f"NOT governed ({sync.detail})"
            # Not installed: the framework cannot be routing through it — omitted.
        routes[framework] = statuses
    return routes


def default_agent_slug() -> str:
    """Guess a sensible agent name so `auto()` needs no arguments at all.

    Order: explicit env var, then the service name conventions used by most
    deployments, then the entry-point script. A wrong-but-stable guess is far better
    than a required argument — the developer can rename the agent in the registry
    later, and until then their traffic is at least attributed to *something*.
    """
    for var in ("NOMETRIA_AGENT", "OTEL_SERVICE_NAME", "SERVICE_NAME", "APP_NAME", "K_SERVICE"):
        value = os.environ.get(var)
        if value:
            return value
    entry = os.path.basename(sys.argv[0] or "")
    if entry and entry not in ("python", "python3", "-c", "pytest"):
        return os.path.splitext(entry)[0]
    return "default-agent"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _messages_from(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise OpenAI and Anthropic shapes into our message list.

    Anthropic carries the system prompt outside `messages`; folding it back in means
    an injection in a system prompt is evaluated on the same surface either way.
    """
    messages = list(kwargs.get("messages") or [])
    system = kwargs.get("system")
    if system:
        text = (
            system
            if isinstance(system, str)
            else " ".join(str(b.get("text", "")) for b in system if isinstance(b, dict))
        )
        messages = [{"role": "system", "content": text}, *messages]
    return [
        {"role": str(m.get("role", "user")), "content": m.get("content")}
        for m in messages
        if isinstance(m, dict)
    ]


def _text_of(response: Any) -> str:
    """Pull the assistant text out of whichever client shape came back."""
    try:
        choices = getattr(response, "choices", None)
        if choices:
            return getattr(choices[0].message, "content", "") or ""
        content = getattr(response, "content", None)
        if isinstance(content, list):
            return "".join(getattr(block, "text", "") or "" for block in content)
        if isinstance(content, str):  # LangChain's AIMessage.content is a plain string
            return content
    except Exception:  # pragma: no cover - defensive against SDK shape drift
        pass
    return ""


def _usage_of(response: Any) -> dict[str, int]:
    """Pull input/output token counts out of whichever client shape came back —
    same normalise-across-providers pattern as `_text_of`, needed because this path
    governs the caller's own raw SDK response, never AgentFox's own
    `CompletionResponse` (the shape `Enforcer._charge_budget` was written against).
    OpenAI's `usage.prompt_tokens`/`completion_tokens` and Anthropic's
    `usage.input_tokens`/`output_tokens` are both covered; an unrecognised shape
    returns an empty dict rather than guessing, which is a silent no-charge, not a
    wrong one.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    try:
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        if input_tokens is None:
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        if output_tokens is None:
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
        return {"input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0)}
    except Exception:  # pragma: no cover - defensive against SDK shape drift
        return {}


def _chunk_text(chunk: Any) -> str:
    """The text a single streamed chunk carries.

    OpenAI and LiteLLM: ``chunk.choices[0].delta.content``. Anthropic: the
    ``content_block_delta`` event's ``delta.text`` (other event types carry none).
    """
    try:
        choices = getattr(chunk, "choices", None)
        if choices:
            content = getattr(getattr(choices[0], "delta", None), "content", None)
            return content if isinstance(content, str) else ""
        if getattr(chunk, "type", None) == "content_block_delta":
            text = getattr(getattr(chunk, "delta", None), "text", None)
            return text if isinstance(text, str) else ""
    except Exception:  # pragma: no cover - defensive against SDK shape drift
        pass
    return ""


def _chunk_usage(chunk: Any) -> dict[str, int]:
    """Token counts a streamed chunk carries: OpenAI's final ``include_usage`` chunk,
    Anthropic's ``message_start`` (input) and ``message_delta`` (output) events."""
    if getattr(chunk, "type", None) == "message_start":
        return _usage_of(getattr(chunk, "message", None))
    return _usage_of(chunk)


#: LangChain message `.type` -> our role vocabulary.
_LC_ROLES = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}


def _lc_messages_from(chat_input: Any) -> list[dict[str, Any]]:
    """Normalise whatever `BaseChatModel.invoke` was given into our message list.

    LangChain accepts a bare string, a `PromptValue`, or a sequence of `BaseMessage`
    (or plain dicts). Whichever shape arrives, the point is the same as
    `_messages_from`: evaluate on the same surface regardless of how the caller built
    the input.
    """
    if isinstance(chat_input, str):
        return [{"role": "user", "content": chat_input}]

    if hasattr(chat_input, "to_messages"):  # a PromptValue
        chat_input = chat_input.to_messages()

    sequence = chat_input if isinstance(chat_input, (list, tuple)) else [chat_input]
    messages: list[dict[str, Any]] = []
    for item in sequence:
        if isinstance(item, dict):
            messages.append({"role": str(item.get("role", "user")), "content": item.get("content")})
            continue
        content = getattr(item, "content", None)
        msg_type = getattr(item, "type", None)
        if content is None and msg_type is None:
            continue
        role = _LC_ROLES.get(str(msg_type), str(msg_type or "user"))
        messages.append({"role": role, "content": content if isinstance(content, str) else str(content)})
    return messages


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
        from .db import session_scope
        from .escalation import record_turn
        from .models import Agent

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


class Blocked(RuntimeError):
    """Raised when a governed call is refused in-process.

    When it is raised depends on the `auto()` mode (see the module docstring);
    ``.result`` is the `EnforcementResult` that refused it.
    """

    def __init__(self, result: Any) -> None:
        super().__init__(result.reason or "blocked by policy")
        self.result = result


# ---------------------------------------------------------------------------
# The governed call
# ---------------------------------------------------------------------------

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


def _fail_closed_result(exc: Exception) -> EnforcementResult:
    reason = f"pre-flight failed and fail_mode=closed: {exc}"
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

    call = _Call(
        state=state,
        model=str(kwargs.get("model") or ""),
        messages=messages,
        trace_id=trace.id,
        evidence=evidence,
    )
    return call, result, enforced, effective


def _preflight(
    state: AutoState, kwargs: dict[str, Any], evidence: dict[str, Any]
) -> _Call | None:
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


def _postflight(call: _Call, text: str, usage: dict[str, int], *, may_raise: bool = True) -> None:
    """Span, output evaluation, budget charge, turn record. Shared by buffered,
    streamed, sync and async calls. Raises `Blocked` when the output must be refused
    under the state's mode and ``may_raise``."""
    state = call.state
    provider_ms = (time.perf_counter() - call.started) * 1000
    refusal: EnforcementResult | None = None
    try:
        if text or usage:
            token = _IN_AGENTFOX.set(True)
            try:
                with session_scope() as session:
                    enforcer = Enforcer(session)
                    agent, identity, _shadow = enforcer.resolve(state.agent)
                    if text:
                        refusal = _evaluate_output(
                            call, session, enforcer, agent, identity, text, usage, provider_ms
                        )
                    # P15: this call never goes through AgentFox's own provider
                    # abstraction — it's the caller's own SDK, patched in place — so
                    # nothing else on this path ever charges spend against the
                    # agent's budget. Charged even when the output is refused: the
                    # tokens were spent either way.
                    if agent is not None and usage:
                        from types import SimpleNamespace

                        from .providers.remote import estimate_cost

                        cost = estimate_cost(
                            call.model, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
                        )
                        enforcer._charge_budget(agent, SimpleNamespace(usage=usage, cost_usd=cost))
            finally:
                _IN_AGENTFOX.reset(token)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("agentfox: post-flight failed: %s", exc)

    if refusal is not None and not may_raise:
        # The caller abandoned the stream early; there is nobody left to raise to.
        log.warning(
            "agentfox: output of an abandoned stream would have been blocked — %s",
            refusal.reason,
        )
        call.flagged = call.flagged or refusal.reason
        refusal = None

    state.calls_governed += 1
    if refusal is not None:
        state.calls_blocked += 1
        raise Blocked(refusal)

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
    from .models import Trace

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
    if principal_ref is not None:
        from sqlalchemy import select

        from .models import EndUserPrincipal

        subject = (
            principal_ref.get("subject") if isinstance(principal_ref, dict) else str(principal_ref)
        )
        principal_obj = session.scalar(
            select(EndUserPrincipal).where(EndUserPrincipal.subject == subject)
        )
        enforcer.evidence = {
            "principal": principal_obj,
            "chunks": call.evidence.get("agentfox_chunks") or [],
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
    _postflight(governed, _text_of(response), _usage_of(response))
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
    _postflight(governed, _text_of(response), _usage_of(response))
    return response


# ---------------------------------------------------------------------------
# Streamed responses
# ---------------------------------------------------------------------------


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
        except Exception as exc:  # pragma: no cover - never break the caller's stream
            log.debug("agentfox: stream chunk not read: %s", exc)

    def _nm_finish(self, *, may_raise: bool = True) -> None:
        if self._nm_done:
            return
        self._nm_done = True
        _postflight(
            self._nm_call, "".join(self._nm_parts), dict(self._nm_usage), may_raise=may_raise
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


# ---------------------------------------------------------------------------
# Patchers
# ---------------------------------------------------------------------------


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
            "openai", "openai", getattr(completions, "Completions", None), "create",
            _sdk_method(state, is_async=False), version, "chat.completions.create",
        ),
        _patch_attr(
            "openai.async", "openai", getattr(completions, "AsyncCompletions", None), "create",
            _sdk_method(state, is_async=True), version, "AsyncCompletions.create",
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
            "anthropic", "anthropic", getattr(messages_module, "Messages", None), "create",
            _sdk_method(state, is_async=False), version, "messages.create",
        ),
        _patch_attr(
            "anthropic.async", "anthropic", getattr(messages_module, "AsyncMessages", None),
            "create", _sdk_method(state, is_async=True), version, "AsyncMessages.create",
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
            "litellm", "litellm", litellm, "completion",
            _sdk_method(state, is_async=False), version, "litellm.completion",
        ),
        _patch_attr(
            "litellm.async", "litellm", litellm, "acompletion",
            _sdk_method(state, is_async=True), version, "litellm.acompletion",
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
            "langchain", "langchain-core", BaseChatModel, "invoke",
            _lc_method(state, is_async=False), version, "BaseChatModel.invoke",
        ),
        _patch_attr(
            "langchain.async", "langchain-core", BaseChatModel, "ainvoke",
            _lc_method(state, is_async=True), version, "BaseChatModel.ainvoke",
        ),
    ]


_PATCHERS = (_patch_openai, _patch_anthropic, _patch_litellm, _patch_langchain)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def auto(
    agent: str | None = None,
    *,
    mode: str = "policy",
    environment: str | None = None,
    session_id: str | None = None,
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
      baseline observes, so this blocks nothing until
      ``agentfox policy enforce baseline``.
    * ``"observe"`` — never raise; would-have-blocked is logged and counted.
    * ``"enforce"`` — strict: raise whenever the effective verdict blocks, even for a
      policy still in observe. For tests and CI.

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
    )

    try:
        init_db()
        if register:
            with session_scope() as session:
                register_agent(
                    session,
                    state.agent,
                    name=state.agent,
                    environment=state.environment,
                    framework=state.frameworks[0] if state.frameworks else None,
                    purpose="auto-registered by agentfox.auto()",
                )
        # How many policies actually reach this agent. Taken here because the
        # banner below claims a mode, and a mode claim with nothing behind it is
        # the failure this count exists to surface.
        with session_scope() as session:
            from .policy import active_policies

            state.policies_bound = len(active_policies(session))
    except Exception as exc:
        # Registration is a convenience; failing it must not stop governance, and
        # hiding the failure would leave the developer wondering why the agent never
        # appeared in the registry. The policy count shares this guard: if it could
        # not be taken it stays -1, and the banner says nothing rather than
        # claiming an all-clear it did not verify.
        log.warning("agentfox: could not register agent '%s': %s", state.agent, exc)

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
