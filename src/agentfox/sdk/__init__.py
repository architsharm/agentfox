"""Python SDK (X-1b) — in-process enforcement.

The second integration surface. The gateway needs zero code change but only sees what
crosses the wire; the SDK sees *intent*, argument provenance, and the agent's own
structure — which is what makes taint tracking (P3-4) precise rather than inferred.

Two modes, both drop-in:

    # 1. Local — enforcement in-process, no server required
    from agentfox.sdk import AgentFox
    nom = AgentFox(agent="support-triage")

    @nom.tool("payments.transfer", impact="irreversible")
    def transfer(amount, currency, to): ...

    with nom.session(intent="refund a duplicate charge") as s:
        doc = s.retrieved(fetch_kb(query))       # tagged untrusted
        answer = s.complete(messages)            # guarded, traced, audited
        transfer(amount=250, currency="USD", to=doc.account)   # contained

    # 2. Remote — the same API against a gateway
    nom = AgentFox(agent="support-triage", base_url="http://localhost:8080",
                   api_key="nom_agt_...")

The remote mode exists because a customer's agent may not be Python, or may not be
allowed to hold a database connection. The local mode exists because an in-process
call has no network hop to spend against the latency budget (NFR-1).
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from agentfox.core.db import session_scope
from agentfox.detection import TaintTracker
from agentfox.integrations.correlation import refs_from_env
from agentfox.runtime.enforcement import EnforcementResult, Enforcer

log = logging.getLogger(__name__)


class PolicyViolation(Exception):
    """Raised when enforcement blocks. Carries the full decision, never just a message."""

    def __init__(self, result: EnforcementResult) -> None:
        super().__init__(result.reason or "blocked by policy")
        self.result = result
        self.trace_id = result.trace_id
        self.decision_id = result.decision_id
        self.rules_fired = result.rules_fired
        self.entities = result.entities


class ApprovalRequired(Exception):
    """Raised when a decision escalates to a human (P2-3)."""

    def __init__(self, result: EnforcementResult) -> None:
        super().__init__(result.reason or "human approval required")
        self.result = result
        self.approval_id = result.approval_id
        self.trace_id = result.trace_id


@dataclass
class TaggedContent:
    """Content carrying its provenance, so taint survives being passed around."""

    text: str
    source: str = "retrieved"
    path: str | None = None

    def __str__(self) -> str:  # so it drops into f-strings transparently
        return self.text


@dataclass
class AgentSession:
    """One execution path: prompts, retrievals, tool calls, decisions."""

    agent: str
    intent: str | None = None
    environment: str = "production"
    session_id: str | None = None
    trace_id: str | None = None
    tracker: TaintTracker = field(default_factory=TaintTracker)
    prior_tools: list[str] = field(default_factory=list)
    _client: AgentFox = field(repr=False, default=None)  # type: ignore[assignment]

    # -- provenance ------------------------------------------------------
    def retrieved(self, text: str, path: str | None = None) -> TaggedContent:
        """Tag content pulled from a document store as untrusted."""
        marker = path or f"$.retrieved[{len(self.tracker.marks)}]"
        self.tracker.mark(marker, "retrieved", text)
        return TaggedContent(text=text, source="retrieved", path=marker)

    def tool_result(
        self, text: str, path: str | None = None, tool: str | None = None
    ) -> TaggedContent:
        """Tag a tool's raw output as untrusted.

        ``tool`` names the *producing* tool (its registered `Tool.key`) so a later
        call whose argument matches this output can be checked for composed
        privilege escalation (F3.8, `guardrails/composition.py`) — an argument
        value traced back to a lower-impact tool's result, now feeding a
        higher-impact one. Omit it and the content is still tainted as before;
        it just can't be checked against that specific failure mode, since
        nothing then names which tool produced it.
        """
        if path:
            marker = path
        elif tool:
            marker = f"tool:{tool}#{len(self.tracker.marks)}"
        else:
            marker = f"$.tool_result[{len(self.tracker.marks)}]"
        self.tracker.mark(marker, "tool_result", text)
        return TaggedContent(text=text, source="tool_result", path=marker)

    def subagent_output(self, text: str, path: str | None = None) -> TaggedContent:
        marker = path or f"$.subagent[{len(self.tracker.marks)}]"
        self.tracker.mark(marker, "subagent", text)
        return TaggedContent(text=text, source="subagent", path=marker)

    # -- guarded operations ----------------------------------------------
    def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str = "default",
        provider: str | None = None,
        schema: dict[str, Any] | None = None,
        raise_on_block: bool = True,
        **kwargs: Any,
    ) -> Any:
        result, response = self._client._complete(
            agent=self.agent,
            messages=messages,
            model=model,
            provider=provider,
            environment=self.environment,
            session_id=self.session_id,
            intent=self.intent,
            trust_map=self._trust_map(messages),
            schema=schema,
            **kwargs,
        )
        self.trace_id = result.trace_id
        if raise_on_block:
            if result.blocked:
                raise PolicyViolation(result)
            if result.escalated:
                raise ApprovalRequired(result)
        return response

    def guard_tool(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        provenance: dict[str, str] | None = None,
        raise_on_block: bool = True,
    ) -> EnforcementResult:
        result = self._client._guard_tool(
            agent=self.agent,
            tool=tool,
            arguments=arguments,
            provenance=provenance or self._infer_provenance(arguments),
            intent=self.intent,
            tracker=self.tracker,
            prior_tools=list(self.prior_tools),
        )
        self.prior_tools.append(tool)
        if raise_on_block:
            if result.blocked:
                raise PolicyViolation(result)
            if result.escalated:
                raise ApprovalRequired(result)
        return result

    # -- helpers ----------------------------------------------------------
    def _trust_map(self, messages: list[dict[str, Any]]) -> dict[str, str]:
        """Map declared TaggedContent back onto message indices."""
        out: dict[str, str] = {}
        for i, message in enumerate(messages):
            content = message.get("content")
            if isinstance(content, TaggedContent):
                out[str(i)] = content.source
                message["content"] = content.text
        return out

    def _infer_provenance(self, arguments: dict[str, Any]) -> dict[str, str]:
        """Unwrap TaggedContent in arguments; leave the rest to taint inference."""
        out: dict[str, str] = {}

        def walk(node: Any, path: str) -> None:
            if isinstance(node, dict):
                for key, value in list(node.items()):
                    if isinstance(value, TaggedContent):
                        out[f"{path}.{key}".lstrip(".")] = value.source
                        node[key] = value.text
                    else:
                        walk(value, f"{path}.{key}".lstrip("."))
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    if isinstance(value, TaggedContent):
                        out[f"{path}[{i}]"] = value.source
                        node[i] = value.text
                    else:
                        walk(value, f"{path}[{i}]")

        walk(arguments, "")
        return out


class AgentFox:
    """SDK entry point. Local by default; remote when ``base_url`` is given."""

    def __init__(
        self,
        agent: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        environment: str = "production",
        timeout: float = 30.0,
        session: Session | None = None,
    ) -> None:
        """
        ``session`` — an existing SQLAlchemy session to enforce within.

        Pass this when the host application already holds a transaction. Without it
        the SDK opens and commits its own session per call, which is correct when
        AgentFox is the only writer but deadlocks against a caller's open write
        transaction (SQLite permits a single writer). Sharing the session also means
        enforcement decisions commit atomically with the work they authorised —
        usually what a host application actually wants.
        """
        self.agent = agent
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_key = api_key
        self.environment = environment
        self.timeout = timeout
        # Stored as `_session`: `session` is the context-manager method above.
        self._session = session

    @contextmanager
    def _db(self) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
        else:
            with session_scope() as owned:
                yield owned

    @property
    def remote(self) -> bool:
        return self.base_url is not None

    @contextmanager
    def session(
        self, intent: str | None = None, session_id: str | None = None
    ) -> Iterator[AgentSession]:
        agent_session = AgentSession(
            agent=self.agent,
            intent=intent,
            environment=self.environment,
            session_id=session_id,
            _client=self,
        )
        yield agent_session

    # -- decorators -------------------------------------------------------
    def tool(
        self,
        key: str,
        *,
        impact: str = "read",
        session: AgentSession | None = None,
    ) -> Callable:
        """Wrap a function so every call is authorised before it runs.

        The decorated function's *keyword arguments* become the policy input, which is
        why argument-level constraints and provenance work without the caller doing
        anything special.

        ``impact`` is a declaration, and is written to the tool registry: every
        impact-based containment rule reads `Tool.impact`, so an impact that lived
        only on this wrapper was one no policy ever saw.
        """

        def decorator(fn: Callable) -> Callable:
            description = (fn.__doc__ or "").strip().split("\n")[0]
            declared = self._declare_tool(key, impact, description)

            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                nonlocal declared
                if not declared:  # the database was not there at import time
                    declared = self._declare_tool(key, impact, description)
                target = session or getattr(wrapper, "_nometria_session", None)
                if target is None:
                    with self.session() as ad_hoc:
                        ad_hoc.guard_tool(key, dict(kwargs))
                else:
                    target.guard_tool(key, dict(kwargs))
                return fn(*args, **kwargs)

            wrapper._nometria_tool = key  # type: ignore[attr-defined]
            wrapper._nometria_impact = impact  # type: ignore[attr-defined]
            return wrapper

        return decorator

    def guard(self, surface: str = "input") -> Callable:
        """Guard a function's string return value (e.g. a retrieval helper)."""

        def decorator(fn: Callable) -> Callable:
            @functools.wraps(fn)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                value = fn(*args, **kwargs)
                if isinstance(value, str):
                    outcome = self.check(value, surface=surface)
                    if outcome.get("verdict") == "block":
                        raise PolicyViolation(
                            EnforcementResult(
                                verdict="block",
                                reason=outcome.get("reason", ""),
                                rules_fired=outcome.get("rules_fired", []),
                                entities=outcome.get("entities", []),
                                trace_id=outcome.get("trace_id"),
                            )
                        )
                return value

            return wrapper

        return decorator

    # -- direct calls ------------------------------------------------------
    def check(
        self, content: str, *, surface: str = "input", taint_source: str = "user"
    ) -> dict[str, Any]:
        if self.remote:
            return self._post(
                f"/v1/guard/{'output' if surface == 'output' else 'input'}",
                {
                    "agent": self.agent,
                    "content": content,
                    "surface": surface,
                    "taint_source": taint_source,
                },
            )
        with self._db() as session:
            return Enforcer(session).check_content(
                agent_slug=self.agent,
                content=content,
                surface=surface,
                taint_source=taint_source,
            )

    # -- internals ---------------------------------------------------------
    def _declare_tool(self, key: str, impact: str, description: str = "") -> bool:
        """Record a code-level tool declaration. Returns whether the row was written.

        Best effort, because a decorator runs at import time and must never be the
        reason an application fails to import: if the database is not reachable yet
        the declaration is kept in-process (`DECLARED_TOOL_IMPACTS`, which `auto()`
        consults) and the write is retried on the tool's first call. Remote mode
        writes nothing locally — the gateway's registry is that deployment's record.
        """
        from agentfox.registry.service import DECLARED_TOOL_IMPACTS, upsert_tool

        DECLARED_TOOL_IMPACTS[key] = impact
        if self.remote:
            return True
        try:
            with self._db() as session:
                upsert_tool(
                    session, key, impact=impact, description=description, impact_source="declared"
                )
            return True
        except Exception as exc:
            log.debug("agentfox: tool '%s' not yet written to the registry: %s", key, exc)
            return False

    def _complete(self, **kwargs: Any) -> tuple[EnforcementResult, Any]:
        if self.remote:
            return self._remote_complete(**kwargs)
        with self._db() as session:
            return Enforcer(session).run_completion(agent_slug=kwargs.pop("agent"), **kwargs)

    def _remote_complete(self, **kwargs: Any) -> tuple[EnforcementResult, Any]:
        headers = self._headers()
        headers["X-Nometria-Agent"] = kwargs["agent"]
        if kwargs.get("intent"):
            headers["X-Nometria-Intent"] = kwargs["intent"]
        if kwargs.get("session_id"):
            headers["X-Nometria-Session"] = kwargs["session_id"]
        if kwargs.get("trust_map"):
            import json

            headers["X-Nometria-Trust"] = json.dumps(kwargs["trust_map"])
        # I-4/I-6: in remote mode the correlation ids have to travel on the wire, or
        # the gateway records a governance decision that nothing can be joined to.
        for ref in refs_from_env():
            if ref.system == "langsmith":
                headers["langsmith-trace-id"] = ref.external_trace_id
                if ref.external_run_id:
                    headers["langsmith-run-id"] = ref.external_run_id
            elif ref.system == "langfuse":
                headers["langfuse-trace-id"] = ref.external_trace_id
                if ref.external_run_id:
                    headers["langfuse-observation-id"] = ref.external_run_id

        response = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json={"model": kwargs.get("model", "default"), "messages": kwargs.get("messages", [])},
            headers=headers,
            timeout=self.timeout,
        )
        result = EnforcementResult(
            verdict=response.headers.get("X-Nometria-Verdict", "allow"),
            effective_verdict=response.headers.get("X-Nometria-Effective-Verdict", "allow"),
            mode=response.headers.get("X-Nometria-Mode", "observe"),
            trace_id=response.headers.get("X-Nometria-Trace"),
            decision_id=response.headers.get("X-Nometria-Decision"),
        )
        if response.status_code == 403:
            error = response.json().get("error", {})
            result.verdict = "block"
            result.reason = error.get("message", "blocked")
            result.rules_fired = error.get("rules_fired", [])
            result.entities = error.get("entities", [])
            return result, None
        if response.status_code == 202:
            body = response.json()
            result.verdict = "escalate"
            result.approval_id = body.get("approval_id")
            result.reason = body.get("reason", "")
            return result, None
        response.raise_for_status()
        return result, response.json()

    def _guard_tool(self, **kwargs: Any) -> EnforcementResult:
        if self.remote:
            payload = self._post(
                "/v1/guard/tool_call",
                {
                    "agent": kwargs["agent"],
                    "tool": kwargs["tool"],
                    "arguments": kwargs["arguments"],
                    "provenance": kwargs.get("provenance") or {},
                    "intent": kwargs.get("intent"),
                    "prior_tools": kwargs.get("prior_tools") or [],
                },
            )
            return EnforcementResult(
                verdict=payload.get("verdict", "allow"),
                effective_verdict=payload.get("effective_verdict", "allow"),
                mode=payload.get("mode", "observe"),
                trace_id=payload.get("trace_id"),
                decision_id=payload.get("decision_id"),
                approval_id=payload.get("approval_id"),
                rules_fired=payload.get("rules_fired", []),
                entities=payload.get("entities", []),
                reason=payload.get("reason", ""),
            )
        with self._db() as session:
            from agentfox.prove.audit.trace import start_trace
            from agentfox.registry.service import slugify

            enforcer = Enforcer(session)
            agent, _identity, _shadow = enforcer.resolve(kwargs["agent"])
            trace = start_trace(
                session,
                agent_id=agent.id if agent else None,
                agent_slug=slugify(kwargs["agent"]),
                intent=kwargs.get("intent"),
            )
            return enforcer.guard_tool_call(
                agent_slug=kwargs["agent"],
                tool_key=kwargs["tool"],
                arguments=kwargs["arguments"],
                provenance=kwargs.get("provenance"),
                intent=kwargs.get("intent"),
                trace=trace,
                tracker=kwargs.get("tracker"),
                prior_tools=kwargs.get("prior_tools"),
            )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


__all__ = [
    "AgentSession",
    "ApprovalRequired",
    "AgentFox",
    "PolicyViolation",
    "TaggedContent",
]
