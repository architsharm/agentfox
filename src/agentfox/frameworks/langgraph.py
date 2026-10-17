"""LangGraph integration — the primary adoption path.

**11 of 11 senior AI engineers surveyed use LangGraph.** A governance product that is
not a LangGraph primitive is a proxy teams route around, which is why this sits in
Tranche 0 alongside streaming and migrations rather than in a later integrations
milestone.

Design decisions:

* **Nothing here requires LangGraph to import.** The module loads without it, and the
  pieces that genuinely need it fail with a clear message at call time. That keeps
  `pip install agentfox` light and keeps the offline test path honest.
* **Trace identity lives in graph state**, so it survives checkpointing, resumption
  and time-travel. An execution path that loses its trace id on resume produces an
  audit record with a hole in it.
* **Escalation maps to `interrupt()`** where available — LangGraph already has the
  right primitive for "stop and ask a human", and inventing a second one would mean
  the graph has two ways to pause.
* **Enforcement failures are loud.** A blocked node raises; it does not return a
  sentinel the graph might ignore. It raises `agentfox.PolicyViolation` /
  `agentfox.ApprovalRequired` — the same classes the SDK raises.
* **A tool node authorises the call the model asked for.** In a real graph a node
  receives the state and nothing else, so the arguments come from the latest tool
  call for that tool in ``state["messages"]`` (or from ``arguments=``), not from the
  node's keyword arguments, which are empty there.
* **Provenance crosses nodes.** What a retrieval node read is kept in the governance
  state, so an argument a later tool node copies out of it is tainted ``retrieved``.

Usage::

    from agentfox.frameworks.langgraph import AgentFoxGuard

    guard = AgentFoxGuard(agent="support-triage")

    builder = StateGraph(MyState)
    builder.add_node("retrieve", guard.retrieval_node(retrieve))
    builder.add_node("model",    guard.model_node(call_model))
    builder.add_node("act",      guard.tool_node(do_transfer, tool="payments.transfer"))
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from typing import Any

from agentfox.capabilities.detection import TaintTracker
from agentfox.core.db import init_db, session_scope

# The SDK's classes, not look-alikes: `except agentfox.PolicyViolation` must catch
# what a guarded node raises. Re-exported here so existing imports work.
from agentfox.errors import AgentFoxError, ApprovalRequired, PolicyViolation
from agentfox.exporters.correlation import links_for
from agentfox.runtime.enforcement import EnforcementResult, Enforcer

log = logging.getLogger(__name__)

#: Key under which we stash governance state inside the graph's state dict.
STATE_KEY = "__agentfox__"

#: How much of each retrieval the governance state keeps for taint inference, and how
#: many retrievals. Graph state is checkpointed, so it is bounded.
_RETRIEVED_CHARS = 20_000
_RETRIEVED_KEEP = 20


def _langgraph_interrupt():
    """Return LangGraph's `interrupt` if importable, else None."""
    try:
        from langgraph.types import interrupt  # type: ignore

        return interrupt
    except Exception:
        return None


def langgraph_available() -> bool:
    try:
        import langgraph  # noqa: F401
    except Exception:
        return False
    return True


class AgentFoxGuard:
    """Wraps LangGraph nodes so every step is governed, traced and audited.

    ``session`` may be supplied when the host application already holds one; the same
    reasoning as the SDK — sharing the transaction means enforcement decisions commit
    atomically with the work they authorised.
    """

    def __init__(
        self,
        agent: str,
        *,
        environment: str = "production",
        intent: str | None = None,
        session: Any = None,
        raise_on_escalate: bool = True,
    ) -> None:
        self.agent = agent
        self.environment = environment
        self.intent = intent
        self._session = session
        self.raise_on_escalate = raise_on_escalate
        self._schema_ready = session is not None
        # The detectors run in this process: warm the opted-in model ones now, in
        # the background, rather than inside the graph's first node.
        from agentfox.capabilities.detection.warmup import warm_in_background

        warm_in_background()

    # -- session plumbing -------------------------------------------------
    @contextmanager
    def _db(self):
        if self._session is not None:
            yield self._session
        else:
            if not self._schema_ready:
                # Like `auto()`: a graph run against a fresh state directory must
                # not fail with "no such table: agents". Idempotent, and done
                # on first use rather than at construction, because a guard is
                # usually built at import time when no database need be reachable.
                init_db()
                self._schema_ready = True
            with session_scope() as owned:
                yield owned

    # -- graph state ------------------------------------------------------
    @staticmethod
    def state_of(state: Any) -> dict[str, Any]:
        """Read our governance sub-state out of a graph state (dict or object)."""
        if isinstance(state, dict):
            return dict(state.get(STATE_KEY) or {})
        return dict(getattr(state, STATE_KEY, {}) or {})

    @staticmethod
    def _merge(governance: dict[str, Any]) -> dict[str, Any]:
        """A node return value that merges our sub-state without touching the rest."""
        return {STATE_KEY: governance}

    def _carry(self, state: Any, **changes: Any) -> dict[str, Any]:
        """The incoming governance state with ``changes`` applied, as a node update.

        Carried whole rather than written as a delta: a state schema without a
        merging reducer on ``__agentfox__`` replaces the value on every write, and a
        tool node writing only ``tools_called`` would erase the trace id and what
        was retrieved.
        """
        return self._merge({**self.state_of(state), **changes})

    def trace_id(self, state: Any) -> str | None:
        return self.state_of(state).get("trace_id")

    # -- node wrappers ----------------------------------------------------
    def model_node(
        self,
        fn: Callable | None = None,
        *,
        messages_key: str = "messages",
        schema: dict[str, Any] | None = None,
    ) -> Callable:
        """Guard a node that calls a model.

        Enforces on the inbound messages *before* the node runs and on whatever text
        the node returns. Trace identity is written back into graph state so later
        nodes join the same execution path across checkpoints.
        """

        def decorator(inner: Callable) -> Callable:
            @functools.wraps(inner)
            def wrapper(state: Any, *args: Any, **kwargs: Any) -> Any:
                messages = _read(state, messages_key) or []
                with self._db() as session:
                    enforcer = Enforcer(session)
                    pre = enforcer.preflight(
                        agent_slug=self.agent,
                        messages=_normalise(messages),
                        environment=self.environment,
                        intent=self.intent,
                        session_id=self.state_of(state).get("session_id"),
                    )
                    governance = {
                        **self.state_of(state),
                        "trace_id": pre.trace.id if pre.trace else None,
                        "last_verdict": pre.result.verdict,
                    }
                    # LangChain turns LangSmith tracing on by default, so the
                    # ambient run tree is usually already there — the link costs the
                    # user no configuration. Carried in graph state so it survives a
                    # checkpoint and a resumed run still points at the same run.
                    if pre.trace is not None:
                        external = links_for(session, pre.trace.id)
                        if external:
                            governance["observability"] = [
                                {"system": link.system, "trace": link.external_trace_id}
                                for link in external
                            ]
                    if pre.stopped:
                        self._stop(pre.result)
                        return self._merge({**governance, "blocked": True})

                    result = inner(state, *args, **kwargs)

                    text = _extract_text(result, messages_key)
                    if text:
                        outbound = enforcer.evaluate(
                            agent=pre.agent,
                            identity=pre.identity,
                            content=text,
                            surface="output",
                            trace=pre.trace,
                            taint_source="none",
                            intent=self.intent,
                            schema=schema,
                            tracker=pre.tracker,
                        )
                        governance["last_verdict"] = outbound.verdict
                        if outbound.blocked or outbound.escalated:
                            self._stop(outbound)
                        if outbound.content is not None:
                            result = _replace_text(result, messages_key, outbound.content)

                return _with_governance(result, self._merge(governance))

            return wrapper

        return decorator(fn) if fn else decorator

    def retrieval_node(self, fn: Callable | None = None, *, source: str = "retrieved") -> Callable:
        """Guard a retrieval node.

        Retrieved content is marked untrusted and scanned on the ``retrieved`` surface
        — the indirect-injection path, which is the highest-severity realistic attack
        on an agent and the one a model-era input filter never sees.
        """

        def decorator(inner: Callable) -> Callable:
            @functools.wraps(inner)
            def wrapper(state: Any, *args: Any, **kwargs: Any) -> Any:
                result = inner(state, *args, **kwargs)
                text = _stringify(_without_governance(result))
                if not text.strip():
                    return result
                with self._db() as session:
                    outcome = Enforcer(session).check_content(
                        agent_slug=self.agent,
                        content=text,
                        surface="retrieved",
                        taint_source=source,
                    )
                if outcome.get("verdict") == "block":
                    self._stop(_result_from(outcome))
                # Kept so a later tool node can tell that an argument was copied out
                # of this: taint that stops at the node boundary is no taint.
                prior = list(self.state_of(state).get("retrieved") or [])
                entry = {
                    "path": f"$.retrieved[{len(prior)}]",
                    "source": source,
                    "text": text[:_RETRIEVED_CHARS],
                }
                retrieved = [*prior, entry][-_RETRIEVED_KEEP:]
                return _with_governance(result, self._carry(state, retrieved=retrieved))

            return wrapper

        return decorator(fn) if fn else decorator

    def tool_node(
        self,
        fn: Callable | None = None,
        *,
        tool: str,
        provenance: dict[str, str] | None = None,
        arguments: Callable[[Any], dict[str, Any]] | Sequence[str] | None = None,
        messages_key: str = "messages",
    ) -> Callable:
        """Guard a node that performs a tool call.

        Authorises on the full execution path — tool, arguments, argument provenance —
        before the function body runs. A denied call never executes.

        Which arguments are authorised, first that applies:

        * ``arguments=`` — a function of the state returning the arguments, or a list
          of state keys to take them from;
        * keyword arguments the node was called with (a node called directly);
        * the latest tool call for ``tool`` in ``state[messages_key]`` — what the
          model asked for, which is the call this node is about to make.

        A graph node receives only the state, so authorising its keyword arguments
        alone authorised ``{}`` in every real graph: an argument limit refused every
        call and provenance had nothing to check.
        """

        def decorator(inner: Callable) -> Callable:
            @functools.wraps(inner)
            def wrapper(state: Any, *args: Any, **kwargs: Any) -> Any:
                call_arguments = self._arguments_for(state, tool, arguments, kwargs, messages_key)
                governance = self.state_of(state)
                prior_steps = governance.get("steps", [])
                with self._db() as session:
                    from agentfox.core.models import Trace

                    trace_id = governance.get("trace_id")
                    trace = session.get(Trace, trace_id) if trace_id else None
                    enforcer = Enforcer(session)
                    result = enforcer.guard_tool_call(
                        agent_slug=self.agent,
                        tool_key=tool,
                        arguments=call_arguments,
                        provenance=provenance,
                        intent=self.intent,
                        trace=trace,
                        tracker=_tracker_from(governance, trace_id),
                        prior_tools=governance.get("tools_called", []),
                        prior_steps=prior_steps,
                    )
                if result.blocked or result.escalated:
                    self._stop(result)

                out = inner(state, *args, **kwargs)
                called = [*governance.get("tools_called", []), tool]
                # The same step-history shape McpGovernor threads through
                # guard_tool_call, so LoopGovernor sees an alternating
                # A/B/A/B cycle or a stalled no-new-observation run here too, not just
                # a per-tool repeat count.
                steps = [
                    *prior_steps,
                    {"tool": tool, "arguments": call_arguments, "observation": out},
                ]
                return _with_governance(out, self._carry(state, tools_called=called, steps=steps))

            return wrapper

        return decorator(fn) if fn else decorator

    @staticmethod
    def _arguments_for(
        state: Any,
        tool: str,
        source: Callable[[Any], dict[str, Any]] | Sequence[str] | None,
        kwargs: dict[str, Any],
        messages_key: str,
    ) -> dict[str, Any]:
        if callable(source):
            return dict(source(state) or {})
        if source is not None:
            return {key: _read(state, key) for key in source}
        if kwargs:
            return dict(kwargs)
        found = _tool_call_arguments(_read(state, messages_key), tool)
        if found is not None:
            return found
        log.warning(
            "agentfox: tool node '%s' found no tool call for it in state['%s'] and was "
            "given no arguments; authorising it with none. Pass arguments= to say "
            "where its arguments are.",
            tool,
            messages_key,
        )
        return {}

    # -- escalation -------------------------------------------------------
    def _denial(self, answer: Any) -> str | None:
        """Why a resume value does not authorise the paused step, or None if it does.

        Fails closed: only ``True`` or ``{"approved": True}`` (the boolean, not a
        truthy string) approves. Anything else — ``{"approved": False}``, ``None``, an
        empty dict, ``"yes"`` — is a denial, because an answer we cannot read is not
        an approval.

        When the answer names an ``approval_id``, the stored approval must say
        ``approved`` too, so a resume cannot claim an approval the approver denied,
        that expired, or that does not exist.
        """
        if answer is True:
            return None
        if not isinstance(answer, dict) or answer.get("approved") is not True:
            return "approval denied: the resume value did not approve this step"
        approval_id = answer.get("approval_id")
        if approval_id is None:
            return None
        from agentfox.core.models import ApprovalRequest

        with self._db() as session:
            stored = session.get(ApprovalRequest, str(approval_id))
            status = stored.status if stored is not None else None
        if status == "approved":
            return None
        if status is None:
            return f"approval denied: no approval '{approval_id}' exists"
        return f"approval denied: approval '{approval_id}' is {status}, not approved"

    def _stop(self, result: EnforcementResult) -> None:
        if result.escalated and self.raise_on_escalate:
            interrupt = _langgraph_interrupt()
            if interrupt is not None:
                # LangGraph already models "pause and ask a human". Reusing it means
                # the graph has one pause mechanism, not two — and the approval
                # resumes through the checkpointer the team already configured.
                #
                # On resume LangGraph re-runs the node and `interrupt()` returns the
                # value given to `Command(resume=...)`. That value *is* the human's
                # answer, so it decides whether the node continues: only an explicit
                # approval does. Ignoring it — as this did — ran the tool after a
                # `{"approved": False}` resume.
                try:
                    answer = interrupt(
                        {
                            "agentfox": "approval_required",
                            "approval_id": result.approval_id,
                            "reason": result.reason,
                            "trace_id": result.trace_id,
                            "rules_fired": result.rules_fired,
                        }
                    )
                except RuntimeError as exc:
                    # A wrapped node called outside a running graph (a unit test, a
                    # direct call) has nothing to pause: hold it the way the guard
                    # does without LangGraph, rather than crash with LangGraph's
                    # "outside of a runnable context".
                    if "runnable context" not in str(exc):
                        raise
                    raise ApprovalRequired(result) from None
                denial = self._denial(answer)
                if denial is None:
                    return
                raise PolicyViolation(
                    dataclasses.replace(
                        result,
                        verdict="block",
                        reason=f"{denial} ({result.reason})" if result.reason else denial,
                    )
                )
            raise ApprovalRequired(result)
        if result.blocked:
            raise PolicyViolation(result)


# ---------------------------------------------------------------------------
# State helpers — tolerant of dict states, dataclasses and pydantic models
# ---------------------------------------------------------------------------


def _tool_call_arguments(messages: Any, tool: str) -> dict[str, Any] | None:
    """The arguments of the latest call to ``tool`` the model made, or None.

    Reads LangChain messages (``AIMessage.tool_calls``: ``name`` and ``args``) and
    OpenAI-shaped dicts (``tool_calls[].function``: ``name`` and JSON ``arguments``).
    Only the latest message that carries tool calls is read: an older call to the
    same tool is not the one this node is about to make.
    """
    for message in reversed(list(messages or [])):
        if isinstance(message, dict):
            calls = message.get("tool_calls")
        else:
            calls = getattr(message, "tool_calls", None)
        if not calls:
            continue
        for call in calls:
            if not isinstance(call, dict):
                call = {"name": getattr(call, "name", None), "args": getattr(call, "args", {})}
            function = call.get("function") or {}
            name = call.get("name") or function.get("name")
            if name != tool:
                continue
            raw = call["args"] if "args" in call else function.get("arguments")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw or "{}")
                except ValueError:
                    raw = {"_raw": raw}
            return dict(raw or {})
        return None
    return None


def _tracker_from(governance: dict[str, Any], trace_id: str | None) -> TaintTracker:
    """A taint tracker that knows what earlier retrieval nodes read."""
    tracker = TaintTracker(trace_id=trace_id)
    for entry in governance.get("retrieved") or []:
        if isinstance(entry, dict) and entry.get("text"):
            tracker.mark(
                str(entry.get("path") or "$.retrieved"),
                str(entry.get("source") or "retrieved"),
                str(entry["text"]),
            )
    return tracker


def _without_governance(result: Any) -> Any:
    if isinstance(result, dict) and STATE_KEY in result:
        return {k: v for k, v in result.items() if k != STATE_KEY}
    return result


def _read(state: Any, key: str) -> Any:
    if isinstance(state, dict):
        return state.get(key)
    return getattr(state, key, None)


def _normalise(messages: Any) -> list[dict[str, Any]]:
    """Convert LangChain message objects to the plain dicts enforcement expects."""
    out: list[dict[str, Any]] = []
    for message in messages or []:
        if isinstance(message, dict):
            out.append(message)
            continue
        role = getattr(message, "type", None) or getattr(message, "role", "user")
        role = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}.get(
            str(role), str(role)
        )
        out.append({"role": role, "content": getattr(message, "content", str(message))})
    return out


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_stringify(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_stringify(v) for v in value)
    return getattr(value, "content", None) or str(value)


def _extract_text(result: Any, messages_key: str) -> str:
    if isinstance(result, dict) and messages_key in result:
        return _stringify(result[messages_key])
    return _stringify(result)


def _replace_text(result: Any, messages_key: str, text: str) -> Any:
    """Substitute redacted content back into a node's return value."""
    if isinstance(result, dict) and messages_key in result:
        messages = result[messages_key]
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                return {**result, messages_key: [*messages[:-1], {**last, "content": text}]}
        return {**result, messages_key: text}
    if isinstance(result, str):
        return text
    return result


def _with_governance(result: Any, governance: dict[str, Any]) -> Any:
    if isinstance(result, dict):
        merged = dict(result)
        merged[STATE_KEY] = {**(merged.get(STATE_KEY) or {}), **governance[STATE_KEY]}
        return merged
    return result


def _result_from(payload: dict[str, Any]) -> EnforcementResult:
    return EnforcementResult(
        verdict=payload.get("verdict", "allow"),
        effective_verdict=payload.get("effective_verdict", "allow"),
        reason=payload.get("reason", ""),
        rules_fired=payload.get("rules_fired", []),
        entities=payload.get("entities", []),
        trace_id=payload.get("trace_id"),
        decision_id=payload.get("decision_id"),
    )


__all__ = [
    "STATE_KEY",
    "AgentFoxError",
    "ApprovalRequired",
    "AgentFoxGuard",
    "PolicyViolation",
    "langgraph_available",
]
