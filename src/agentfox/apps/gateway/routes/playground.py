"""Public playground — "attack our agent, see the real guardrail verdict."

Unauthenticated by design, the same way `inline.py`'s `/v1/guard/*` routes are: no
`current_user`, no role check, no account. What keeps this safe to expose publicly
is that every route here only ever touches one visitor's own sandbox tenant
(`playground_sessions.py`), and that nothing in a sandbox reaches the outside: no
real model provider, no real money or email (the seeded `payments.transfer` /
`email.send` tools have no backend; the `echo` provider never calls out).

A sandbox lives in the deployment database under its own `org_id`, so the tenant
filter in `tenancy.py` is what separates one visitor from another and from the
deployment's own data — the same mechanism that separates two paying customers.
The session id in the path is the only credential; see `playground_sessions.py`
for what that does and does not prove.

Every verdict returned here comes from the same `Enforcer`/`McpGovernor` code path
the rest of the product uses — this file adds session plumbing, not detection
logic.

Every verdict body carries both `verdict`/`applied_verdict` (what happened to this
request) and `effective_verdict`/`would_be_verdict` (what the bound policy says
should happen, which in observe mode is the one that did not take effect). See
`gateway/verdicts.py`.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from agentfox.apps.gateway.playground_sessions import (
    SESSION_TTL_SECONDS,
    PlaygroundSession,
    PlaygroundUnavailable,
    get_store,
    session_creation_limiter,
)
from agentfox.apps.gateway.routes.playground_deps import playground_session
from agentfox.apps.gateway.verdicts import with_verdict_aliases
from agentfox.core.models import Agent
from agentfox.fixtures import sandbox_agents
from agentfox.fixtures.seed import AGENTS, CAPABILITIES, POISONED_DOCUMENT, TOOLS

router = APIRouter(prefix="/api/playground", tags=["playground"])


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/sessions", status_code=201)
def create_session(request: Request, background: BackgroundTasks) -> dict[str, Any]:
    """Create a playground sandbox.

    A private tenant in the deployment database, seeded with the demo fixtures.
    `session_id` is the only credential. It survives this process, so a follow-up
    request served by a different instance finds the same sandbox; it expires
    `expires_in_seconds` after the last action on it, and its data is then deleted.
    """
    if not session_creation_limiter.check(_client_key(request)):
        raise HTTPException(
            429,
            "Too many playground sandboxes from this address recently — please try "
            "again in a while.",
        )
    try:
        record = get_store().create()
    except PlaygroundUnavailable as exc:
        # 503 rather than 500: the playground is unavailable, the rest of the API is
        # not, and the message names what an operator has to run.
        raise HTTPException(503, str(exc)) from exc
    # After the response: sweep, keep the cap, and build a spare for the next visitor.
    background.add_task(get_store().refill)
    return {
        "session_id": record.id,
        "expires_in_seconds": SESSION_TTL_SECONDS,
        # The agents modelled on live-tested apps first, each with its tools and the
        # prompts that show what its policy does; then the demo world's own agents.
        "agents": [
            *sandbox_agents.describe(),
            *({"slug": a["slug"], "name": a["name"], "purpose": a["purpose"]} for a in AGENTS),
        ],
        "tools": {
            **{t["key"]: {"name": t["name"], "impact": t["impact"]} for t in TOOLS},
            **sandbox_agents.tools(),
        },
        "capabilities": CAPABILITIES,
        "poisoned_document": POISONED_DOCUMENT,
        "mode": "observe",
    }


class PlaygroundChatRequest(BaseModel):
    agent: str = "support-triage"
    message: str
    #: A "retrieved document" the visitor is free to edit — attached as a `tool`
    #: message on this one call, so indirect injection (Tier B) is something the
    #: visitor drives, not a fixed scripted moment.
    document: str | None = None


@router.post("/sessions/{session_id}/chat")
def chat(
    session_id: str,
    payload: PlaygroundChatRequest,
    record: PlaygroundSession = Depends(playground_session),
) -> dict[str, Any]:
    from agentfox.capabilities.containment.escalation import record_turn
    from agentfox.runtime.enforcement import Enforcer

    if not payload.message.strip():
        raise HTTPException(400, "message must not be empty")

    with record.session_scope() as session:
        enforcer = Enforcer(session)

        # Tier A — the assembled-conversation-window check, run *in addition to*
        # the single-message evaluation below, so a payload split across several
        # short messages is caught even when no single message alone is.
        window_result = enforcer.check_conversation_window(
            agent_slug=payload.agent,
            session_id=session_id,
            new_user_text=payload.message,
        )

        messages: list[dict[str, Any]] = [{"role": "user", "content": payload.message}]
        if payload.document:
            messages.append({"role": "tool", "content": payload.document})

        result, response = enforcer.run_completion(
            agent_slug=payload.agent,
            messages=messages,
            model="echo-1",
            session_id=session_id,
            intent="playground chat",
            environment=sandbox_agents.ENVIRONMENT,
        )
        record.remember_trace(session, result.trace_id)

        answer = response.text if response is not None else None
        if answer:
            agent_row = session.scalar(select(Agent).where(Agent.slug == payload.agent))
            record_turn(
                session,
                session_id=session_id,
                agent_id=agent_row.id if agent_row else None,
                trace_id=result.trace_id,
                user_text=payload.message,
                agent_text=answer,
            )

        return {
            "reply": answer,
            "blocked": result.blocked,
            "escalated": result.escalated,
            "verdict": with_verdict_aliases(result.to_json()),
            "conversation_window_verdict": with_verdict_aliases(window_result.to_json()),
        }


class PlaygroundToolCallRequest(BaseModel):
    agent: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)
    intent: str | None = None


@router.post("/sessions/{session_id}/tool-call")
def tool_call(
    session_id: str,
    payload: PlaygroundToolCallRequest,
    record: PlaygroundSession = Depends(playground_session),
) -> dict[str, Any]:
    """Try a tool call directly, with no model in the loop.

    Tiers C (parameter exploitation) and D (excessive agency) don't need an LLM to
    decide to misbehave; the visitor decides.

    A sandbox agent's tools are simulated (`fixtures/sandbox_agents.py`): when the
    call is allowed its deterministic result is produced, then checked as a tool
    result. `result` is null when the result was withheld (`result_withheld`), and
    `result_verdict` is that check.

    `verdict`/`applied_verdict` is what happened to this call;
    `effective_verdict`/`would_be_verdict` is what the bound policy says should
    happen, which in observe mode is the one that did not take effect.
    """
    from agentfox.platform.ledger.trace import start_trace
    from agentfox.platform.registry.service import slugify
    from agentfox.runtime.enforcement import Enforcer

    with record.session_scope() as session:
        enforcer = Enforcer(session)
        agent, _identity, _shadow = enforcer.resolve(payload.agent)
        trace = start_trace(
            session,
            agent_id=agent.id if agent else None,
            agent_slug=slugify(payload.agent),
            session_id=session_id,
            intent=payload.intent,
            environment=sandbox_agents.ENVIRONMENT,
        )
        result = enforcer.guard_tool_call(
            agent_slug=payload.agent,
            tool_key=payload.tool,
            arguments=payload.arguments,
            provenance=payload.provenance or None,
            intent=payload.intent,
            trace=trace,
        )
        record.remember_trace(session, result.trace_id or trace.id)
        body = with_verdict_aliases(result.to_json())

        output = None
        if result.verdict == "allow":
            output = sandbox_agents.simulate(payload.agent, payload.tool, payload.arguments)
        if output is None:
            return body
        # Checked the way a tool result is before a model reads it.
        checked = enforcer.check_content(
            payload.agent,
            output if isinstance(output, str) else json.dumps(output),
            surface="tool_result",
            taint_source="tool_result",
            trace=trace,
        )
        withheld = checked["verdict"] not in ("allow", "redact", "mask", "tokenize")
        if checked.get("content") and not withheld:
            output = checked["content"]
        return {
            **body,
            "result": None if withheld else output,
            "result_withheld": withheld,
            "result_verdict": with_verdict_aliases(checked),
        }


class PlaygroundEnforceRequest(BaseModel):
    mode: str


@router.post("/sessions/{session_id}/enforce")
def set_enforce_mode(
    session_id: str,
    payload: PlaygroundEnforceRequest,
    record: PlaygroundSession = Depends(playground_session),
) -> dict[str, Any]:
    """Flip the baseline policy observe -> enforce (or back) for this sandbox only.

    Nothing about the visitor's earlier messages changes retroactively — the point
    is to re-send the same injection afterwards and watch the verdict actually
    change from "would have blocked" to "blocked", the same "aha" `agentfox demo`
    already walks through interactively (`cli/demo.py`, section 08).
    """
    from agentfox.platform.policy import set_mode

    if payload.mode not in ("observe", "enforce"):
        raise HTTPException(400, "mode must be 'observe' or 'enforce'")
    with record.session_scope() as session:
        set_mode(session, "baseline", payload.mode)
    return {"mode": payload.mode}


@router.get("/sessions/{session_id}/state")
def state(
    session_id: str,
    record: PlaygroundSession = Depends(playground_session),
) -> dict[str, Any]:
    """Everything the live sidebar needs: recent traces (decisions + detector runs
    + findings), the tamper-evident audit chain's own self-check, and compliance
    posture — all real, already-existing functions, just called and serialized.
    """
    from agentfox.capabilities.compliance.status import compute_all, posture
    from agentfox.capabilities.detection.tuning import explain_recorded
    from agentfox.platform.ledger import chain
    from agentfox.platform.ledger.trace import full_trace

    with record.session_scope() as session:
        compute_all(session)
        traces = [
            full_trace(session, tid, explain=explain_recorded)
            for tid in reversed(record.trace_ids(session))
        ]
        chain_info = chain.chain_stats(session)
        verification = chain.verify_range(session)
        posture_info = posture(session)

    return {
        "traces": [t for t in traces if t is not None],
        "chain": {
            **chain_info,
            "verified": verification.valid,
            "entries_checked": verification.entries_checked,
        },
        "compliance": posture_info,
    }
