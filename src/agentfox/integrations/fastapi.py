"""I-3 — FastAPI middleware and dependencies. 10 of 11 engineers run FastAPI.

Second only to LangGraph in the practitioner evidence, and the surface with the
lowest adoption cost: a team that already serves its agent behind FastAPI gets
governance by adding one line to `main.py`, with no change to the agent code itself.

The design point is that this is **not** a proxy. A proxy sees the HTTP envelope and
has to guess at semantics; a dependency runs inside the handler, where the agent slug,
the end user, and the actual prompt are already resolved. That is the difference
between "the request contained an SSN somewhere" and "this agent, acting for this
user, was about to send an SSN to a tool it is not entitled to use".

Two surfaces, because teams want different things:

* ``AgentFoxMiddleware`` — request-scoped trace correlation and headers on every
  response, with **no enforcement**. Safe to mount globally on day one.
* ``guard`` / ``Governed`` — an explicit dependency that enforces. Opt-in per route,
  because a middleware that can 403 a route the author never thought about is how a
  governance layer gets removed.

Import-guarded throughout: FastAPI is not a core dependency, and a team using the SDK
without a web framework should never see an ImportError from this module.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agentfox.core.db import session_scope
from agentfox.integrations.correlation import link_trace, refs_from_headers
from agentfox.prove.audit.trace import end_trace, start_trace
from agentfox.runtime.enforcement import EnforcementResult, Enforcer

log = logging.getLogger(__name__)

try:  # pragma: no cover - exercised only where fastapi is installed
    from fastapi import HTTPException, Request
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse, Response

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    BaseHTTPMiddleware = object  # type: ignore[assignment,misc]
    Request = Any  # type: ignore[assignment,misc]
    Response = Any  # type: ignore[assignment,misc]


#: Headers the middleware reads, matching the gateway's so a team can move between
#: the proxy and in-process enforcement without changing their client.
AGENT_HEADER = "x-nometria-agent"
SESSION_HEADER = "x-nometria-session"
INTENT_HEADER = "x-nometria-intent"
USER_HEADER = "x-nometria-user-principal"


@dataclass
class GovernanceContext:
    """What the dependency hands the route handler."""

    agent: str | None
    session_id: str | None
    intent: str | None
    user_principal: str | None
    correlation: dict[str, str]

    def enforcer(self, session) -> Enforcer:
        return Enforcer(session)


class AgentFoxMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
    """Observe-only request correlation. Mount globally; it cannot refuse a request.

    Enforcement deliberately lives in the dependency instead. A middleware that can
    403 a route its author never considered is how a governance layer gets removed
    on the first false positive — so this one only ever *observes*.
    """

    def __init__(self, app: Any, *, service: str = "app", record_latency: bool = True) -> None:
        if not FASTAPI_AVAILABLE:  # pragma: no cover
            raise RuntimeError("AgentFoxMiddleware requires fastapi: pip install fastapi")
        super().__init__(app)
        self.service = service
        self.record_latency = record_latency

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        headers = dict(request.headers)
        request.state.agentfox = GovernanceContext(
            agent=headers.get(AGENT_HEADER),
            session_id=headers.get(SESSION_HEADER),
            intent=headers.get(INTENT_HEADER),
            user_principal=headers.get(USER_HEADER),
            correlation=headers,
        )
        refs = refs_from_headers(headers)

        response = await call_next(request)
        response.headers["X-Nometria-Service"] = self.service
        if refs:
            response.headers["X-Nometria-External-Trace"] = refs[0].external_trace_id
        trace_id = getattr(request.state, "agentfox_trace_id", None)
        if trace_id:
            response.headers["X-Nometria-Trace"] = trace_id
        if self.record_latency:
            response.headers["X-Nometria-Latency-Ms"] = (
                f"{(time.perf_counter() - started) * 1000:.2f}"
            )
        return response


def context(request: Request) -> GovernanceContext:
    """Dependency: the governance context the middleware attached.

    Falls back to reading headers directly, so a route works whether or not the app
    mounted the middleware — a dependency that silently no-ops because of a missing
    `add_middleware` call is a governance gap that looks like working code.
    """
    existing = getattr(request.state, "agentfox", None)
    if existing is not None:
        return existing
    headers = dict(request.headers)
    return GovernanceContext(
        agent=headers.get(AGENT_HEADER),
        session_id=headers.get(SESSION_HEADER),
        intent=headers.get(INTENT_HEADER),
        user_principal=headers.get(USER_HEADER),
        correlation=headers,
    )


def guard(
    *,
    agent: str | None = None,
    surface: str = "input",
    field: str = "prompt",
    raise_on_block: bool = True,
) -> Callable:
    """Dependency factory that enforces on one request field.

    ``agent`` pins the route to a declared agent. Leaving it None reads the header,
    which is right for a multi-tenant gateway and wrong for a single-purpose route —
    so pin it where you can.
    """
    if not FASTAPI_AVAILABLE:  # pragma: no cover
        raise RuntimeError("agentfox.integrations.fastapi requires fastapi")

    async def dependency(request: Request) -> EnforcementResult:
        ctx = context(request)
        slug = agent or ctx.agent
        payload: dict[str, Any] = {}
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        content = str(payload.get(field) or "")

        with session_scope() as session:
            enforcer = Enforcer(session)
            resolved, identity, _shadow = enforcer.resolve(slug)
            # A trace is started here rather than left implicit: without one the
            # decision has nothing to correlate to, and correlating governance to the
            # request that caused it is most of the value of running in-process.
            trace = start_trace(
                session,
                agent_id=resolved.id if resolved else None,
                agent_slug=resolved.slug if resolved else slug,
                session_id=ctx.session_id,
                intent=ctx.intent,
            )
            link_trace(session, trace.id, refs_from_headers(ctx.correlation))
            result = enforcer.evaluate(
                agent=resolved,
                identity=identity,
                content=content,
                surface=surface,
                trace=trace,
                intent=ctx.intent,
            )
            end_trace(
                session,
                trace,
                verdict=result.verdict,
                status="blocked" if result.blocked else "ok",
            )
            request.state.agentfox_trace_id = result.trace_id
            request.state.agentfox_result = result

        if raise_on_block and result.blocked:
            raise HTTPException(
                status_code=403,
                detail={
                    "type": "agentfox_policy_violation",
                    "message": result.reason,
                    "trace_id": result.trace_id,
                    "decision_id": result.decision_id,
                    # P3-12: the route for disputing it travels with the refusal.
                    "explanation": result.explanation,
                },
            )
        return result

    return dependency


def install(app: Any, *, service: str = "app") -> Any:
    """One-line install: `agentfox.integrations.fastapi.install(app)`.

    Adds observe-only middleware and a `/agentfox/health` probe. Enforcement stays
    opt-in per route, which is the whole adoption argument — a team can ship this to
    production on a Friday.
    """
    app.add_middleware(AgentFoxMiddleware, service=service)

    @app.get("/agentfox/health", tags=["agentfox"])
    def _health() -> dict[str, Any]:
        from agentfox import __version__

        return {"status": "ok", "version": __version__, "mode": "observe", "service": service}

    return app


def blocked_response(result: EnforcementResult) -> Any:  # pragma: no cover - convenience
    return JSONResponse(
        status_code=403,
        content={"error": {"type": "agentfox_policy_violation", **result.to_json()}},
    )
