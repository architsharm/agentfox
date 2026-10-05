"""LangGraph integration (I-1) — the primary adoption path.

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
  sentinel the graph might ignore.

Usage::

    from agentfox.integrations.langgraph import AgentFoxGuard

    guard = AgentFoxGuard(agent="support-triage")

    builder = StateGraph(MyState)
    builder.add_node("retrieve", guard.retrieval_node(retrieve))
    builder.add_node("model",    guard.model_node(call_model))
    builder.add_node("act",      guard.tool_node(do_transfer, tool="payments.transfer"))
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from agentfox.core.db import session_scope
from agentfox.integrations.correlation import links_for
from agentfox.runtime.enforcement import EnforcementResult, Enforcer

#: Key under which we stash governance state inside the graph's state dict.
STATE_KEY = "__nometria__"


class PolicyViolation(Exception):
    """Raised inside a graph when enforcement blocks a node."""

    def __init__(self, result: EnforcementResult) -> None:
        super().__init__(result.reason or "blocked by policy")
        self.result = result
        self.trace_id = result.trace_id
        self.decision_id = result.decision_id
        self.rules_fired = result.rules_fired
        self.entities = result.entities


class ApprovalRequired(Exception):
    """Raised when a node escalates and `interrupt()` is unavailable."""

    def __init__(self, result: EnforcementResult) -> None:
        super().__init__(result.reason or "human approval required")
        self.result = result
        self.approval_id = result.approval_id
        self.trace_id = result.trace_id


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

    # -- session plumbing -------------------------------------------------
    @contextmanager
    def _db(self):
        if self._session is not None:
            yield self._session
        else:
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
                        "trace_id": pre.trace.id if pre.trace else None,
                        "last_verdict": pre.result.verdict,
                    }
                    # I-4/I-6: LangChain turns LangSmith tracing on by default, so the
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
                text = _stringify(result)
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
                return result

            return wrapper

        return decorator(fn) if fn else decorator

    def tool_node(
        self,
        fn: Callable | None = None,
        *,
        tool: str,
        provenance: dict[str, str] | None = None,
    ) -> Callable:
        """Guard a node that performs a tool call.

        Authorises on the full execution path — tool, arguments, argument provenance —
        before the function body runs. A denied call never executes.
        """

        def decorator(inner: Callable) -> Callable:
            @functools.wraps(inner)
            def wrapper(state: Any, *args: Any, **kwargs: Any) -> Any:
                arguments = dict(kwargs)
                prior_steps = self.state_of(state).get("steps", [])
                with self._db() as session:
                    enforcer = Enforcer(session)
                    result = enforcer.guard_tool_call(
                        agent_slug=self.agent,
                        tool_key=tool,
                        arguments=arguments,
                        provenance=provenance,
                        intent=self.intent,
                        prior_tools=self.state_of(state).get("tools_called", []),
                        prior_steps=prior_steps,
                    )
                if result.blocked or result.escalated:
                    self._stop(result)

                out = inner(state, *args, **kwargs)
                called = [*self.state_of(state).get("tools_called", []), tool]
                # PL-4 fast-follow: the same step-history shape McpGovernor already
                # threads through guard_tool_call, so LoopGovernor sees an alternating
                # A/B/A/B cycle or a stalled no-new-observation run here too, not just
                # a per-tool repeat count.
                steps = [*prior_steps, {"tool": tool, "arguments": arguments, "observation": out}]
                return _with_governance(out, self._merge({"tools_called": called, "steps": steps}))

            return wrapper

        return decorator(fn) if fn else decorator

    # -- escalation -------------------------------------------------------
    def _stop(self, result: EnforcementResult) -> None:
        if result.escalated and self.raise_on_escalate:
            interrupt = _langgraph_interrupt()
            if interrupt is not None:
                # LangGraph already models "pause and ask a human". Reusing it means
                # the graph has one pause mechanism, not two — and the approval
                # resumes through the checkpointer the team already configured.
                interrupt(
                    {
                        "agentfox": "approval_required",
                        "approval_id": result.approval_id,
                        "reason": result.reason,
                        "trace_id": result.trace_id,
                        "rules_fired": result.rules_fired,
                    }
                )
                return
            raise ApprovalRequired(result)
        if result.blocked:
            raise PolicyViolation(result)


# ---------------------------------------------------------------------------
# State helpers — tolerant of dict states, dataclasses and pydantic models
# ---------------------------------------------------------------------------


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
    "ApprovalRequired",
    "AgentFoxGuard",
    "PolicyViolation",
    "langgraph_available",
]
